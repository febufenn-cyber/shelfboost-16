from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shelfboost_phase2.common import canonical_shop_domain, json_dumps, write_json
from shelfboost_phase2.db import connect

from .db import initialize
from .planning import _insert_snapshot
from .writer import MutationRejected, MutationUncertain, SafeShopifyProductWriter, payload_digest

SUCCESS_STATES = {"succeeded", "already_applied"}


def _fields_from_live(product: dict[str, Any]) -> dict[str, str]:
    seo = product.get("seo") or {}
    return {
        "Body (HTML)": str(product.get("descriptionHtml") or ""),
        "SEO Title": str(seo.get("title") or ""),
        "SEO Description": str(seo.get("description") or ""),
    }


def _snapshot_from_live(
    product: dict[str, Any], fields: dict[str, str]
) -> dict[str, Any]:
    return {
        "shopify_gid": str(product.get("id") or ""),
        "handle": str(product.get("handle") or ""),
        "updated_at_shopify": str(product.get("updatedAt") or ""),
        "fields": fields,
        "source_payload": product,
    }


def _record_attempt(
    connection,
    item_id: int,
    operation: str,
    status: str,
    *,
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    user_errors: list[dict[str, Any]] | None = None,
    error_text: str = "",
) -> None:
    request = request or {}
    response = response or {}
    connection.execute(
        """
        INSERT INTO publish_attempts(
            publish_item_id, operation, request_sha256, request_json,
            response_sha256, response_json, status, user_errors_json, error_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            operation,
            payload_digest(request) if request else "",
            json_dumps(request),
            payload_digest(response) if response else "",
            json_dumps(response),
            status,
            json_dumps(user_errors or []),
            error_text,
        ),
    )


def _update_mirror(
    connection, item: dict[str, Any], live_product: dict[str, Any]
) -> None:
    fields = _fields_from_live(live_product)
    payload_row = connection.execute(
        "SELECT payload_json FROM shopify_products WHERE id=?",
        (item["product_id"],),
    ).fetchone()
    try:
        payload = json.loads(payload_row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    payload.update(
        {
            "id": live_product.get("id") or item["shopify_gid"],
            "handle": live_product.get("handle") or item["handle"],
            "descriptionHtml": fields["Body (HTML)"],
            "updatedAt": live_product.get("updatedAt") or "",
            "seo": {
                "title": fields["SEO Title"],
                "description": fields["SEO Description"],
            },
        }
    )
    connection.execute(
        """
        UPDATE shopify_products
        SET description_html=?, seo_title=?, seo_description=?,
            updated_at_shopify=?, payload_json=?
        WHERE id=?
        """,
        (
            fields["Body (HTML)"],
            fields["SEO Title"],
            fields["SEO Description"],
            str(live_product.get("updatedAt") or ""),
            json_dumps(payload),
            item["product_id"],
        ),
    )


def _batch_shop(
    connection, batch_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    batch_row = connection.execute(
        "SELECT * FROM publish_batches WHERE id=?", (batch_id,)
    ).fetchone()
    if not batch_row:
        raise ValueError(f"Unknown publish batch: {batch_id}")
    batch = dict(batch_row)
    if batch["status"] == "blocked":
        raise RuntimeError("Blocked publish batches cannot execute")
    if batch["status"] in {"completed", "rolled_back"}:
        return batch, {}
    shop_row = connection.execute(
        "SELECT * FROM shops WHERE id=?", (batch["shop_id"],)
    ).fetchone()
    shop = dict(shop_row)
    if int(shop["active"]) != 1:
        raise PermissionError("Cannot publish to an inactive or uninstalled shop")
    unresolved = connection.execute(
        """
        SELECT status, COUNT(*) AS count FROM refresh_queue
        WHERE shop_id=? AND status IN ('pending','processing','failed')
        GROUP BY status
        """,
        (shop["id"],),
    ).fetchall()
    if unresolved:
        detail = ", ".join(
            f"{row['status']}={row['count']}" for row in unresolved
        )
        raise RuntimeError(f"Refresh queue is not clean: {detail}")
    return batch, shop


def _classify_live(
    live_fields: dict[str, str],
    original_fields: dict[str, str],
    proposed_fields: dict[str, str],
    changed_fields: list[str],
) -> str:
    if all(
        live_fields[field] == proposed_fields[field] for field in changed_fields
    ):
        if all(
            live_fields[field] == original_fields[field]
            for field in original_fields
            if field not in changed_fields
        ):
            return "already_applied"
    if all(
        live_fields[field] == original_fields[field] for field in original_fields
    ):
        return "safe_to_write"
    return "external_conflict"


def _verify_changed_fields(
    live_fields: dict[str, str],
    proposed_fields: dict[str, str],
    changed_fields: list[str],
) -> bool:
    return all(
        live_fields[field] == proposed_fields[field] for field in changed_fields
    )


def execute_publish(
    workspace: Path,
    writer: SafeShopifyProductWriter,
    batch_id: int,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    initialize(workspace)
    with connect(workspace) as connection:
        batch, shop = _batch_shop(connection, batch_id)
        if not shop:
            return {
                "batch_id": batch_id,
                "status": batch["status"],
                "processed": 0,
            }
        if canonical_shop_domain(writer.shop_domain) != shop["domain"]:
            raise ValueError("Writer is authenticated for a different shop")
        connection.execute(
            "UPDATE publish_batches SET status='running', started_at=COALESCE(started_at,CURRENT_TIMESTAMP), error_text='' WHERE id=?",
            (batch_id,),
        )
        rows = connection.execute(
            """
            SELECT * FROM publish_items
            WHERE batch_id=? AND status IN ('ready','uncertain')
            ORDER BY id LIMIT ?
            """,
            (batch_id, limit),
        ).fetchall()

    processed = 0
    for raw in rows:
        item = dict(raw)
        processed += 1
        original_fields = json.loads(item["original_fields_json"])
        proposed_fields = json.loads(item["proposed_fields_json"])
        changed_fields = json.loads(item["changed_fields_json"])
        try:
            live = writer.fetch(item["shopify_gid"])
        except Exception as exc:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='uncertain', error_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (f"preflight_read_failed:{exc}", item["id"]),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "reconcile",
                    "uncertain",
                    error_text=str(exc),
                )
            continue
        if live is None:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='conflict', conflict_reason='live_product_missing', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
            continue
        live_fields = _fields_from_live(live)
        classification = _classify_live(
            live_fields, original_fields, proposed_fields, changed_fields
        )
        with connect(workspace) as connection:
            _insert_snapshot(
                connection,
                item["id"],
                "live_before",
                _snapshot_from_live(live, live_fields),
            )
        if classification == "already_applied":
            with connect(workspace) as connection:
                _insert_snapshot(
                    connection,
                    item["id"],
                    "published_after",
                    _snapshot_from_live(live, live_fields),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "reconcile",
                    "already_applied",
                    response=live,
                )
                _update_mirror(connection, item, live)
                connection.execute(
                    "UPDATE publish_items SET status='already_applied', error_text='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
            continue
        if classification == "external_conflict":
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='conflict', conflict_reason='live_fields_changed_since_approval', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "reconcile",
                    "conflict",
                    response=live,
                )
            continue

        with connect(workspace) as connection:
            connection.execute(
                "UPDATE publish_items SET status='publishing', attempt_count=attempt_count+1, error_text='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item["id"],),
            )
        try:
            result = writer.update_once(
                item["shopify_gid"], proposed_fields, changed_fields
            )
        except MutationUncertain as exc:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='uncertain', error_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc), item["id"]),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "publish",
                    "uncertain",
                    error_text=str(exc),
                )
            continue
        except MutationRejected as exc:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='failed', error_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc), item["id"]),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "publish",
                    "failed",
                    error_text=str(exc),
                )
            continue

        if result.user_errors:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='failed', error_text='shopify_user_errors', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "publish",
                    "failed",
                    request=result.request_payload,
                    response=result.raw_payload,
                    user_errors=result.user_errors,
                    error_text="shopify_user_errors",
                )
            continue

        after_fields = _fields_from_live(result.product)
        if not _verify_changed_fields(
            after_fields, proposed_fields, changed_fields
        ):
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='uncertain', error_text='mutation_response_did_not_verify', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
                _record_attempt(
                    connection,
                    item["id"],
                    "publish",
                    "uncertain",
                    request=result.request_payload,
                    response=result.raw_payload,
                    error_text="mutation_response_did_not_verify",
                )
            continue
        with connect(workspace) as connection:
            _insert_snapshot(
                connection,
                item["id"],
                "published_after",
                _snapshot_from_live(result.product, after_fields),
            )
            _record_attempt(
                connection,
                item["id"],
                "publish",
                "succeeded",
                request=result.request_payload,
                response=result.raw_payload,
            )
            _update_mirror(connection, item, result.product)
            connection.execute(
                "UPDATE publish_items SET status='succeeded', error_text='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item["id"],),
            )

    with connect(workspace) as connection:
        statuses = {
            row["status"]: int(row["count"])
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM publish_items WHERE batch_id=? GROUP BY status",
                (batch_id,),
            )
        }
        total = sum(statuses.values())
        success = sum(statuses.get(state, 0) for state in SUCCESS_STATES)
        pending = sum(
            statuses.get(state, 0) for state in ("ready", "publishing")
        )
        if total and success == total:
            batch_status = "completed"
        elif pending:
            batch_status = "running"
        elif success:
            batch_status = "partial"
        else:
            batch_status = "failed"
        connection.execute(
            """
            UPDATE publish_batches
            SET status=?, completed_at=CASE
                WHEN ? IN ('completed','partial','failed') THEN CURRENT_TIMESTAMP
                ELSE completed_at END
            WHERE id=?
            """,
            (batch_status, batch_status, batch_id),
        )
    report = {
        "batch_id": batch_id,
        "status": batch_status,
        "processed": processed,
        "item_statuses": statuses,
    }
    write_json(
        workspace.resolve()
        / "publish"
        / "reports"
        / f"batch-{batch_id}-execution.json",
        report,
    )
    return report
