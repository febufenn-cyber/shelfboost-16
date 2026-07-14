from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shelfboost_phase2.common import canonical_shop_domain, json_dumps, sha256_bytes, write_json
from shelfboost_phase2.db import connect

from .db import initialize
from .execution import _fields_from_live, _record_attempt, _snapshot_from_live, _update_mirror
from .planning import _insert_snapshot
from .writer import MutationRejected, MutationUncertain, SafeShopifyProductWriter

SECRET_KEYS = {"access_token", "authorization", "client_secret", "secret", "token"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SECRET_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _loads(value: str) -> Any:
    return json.loads(value or "{}")


def _snapshot(connection, item_id: int, kind: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT payload_json, payload_sha256 FROM publish_snapshots WHERE publish_item_id=? AND kind=?",
        (item_id, kind),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Missing {kind} snapshot for publish item {item_id}")
    payload = _loads(row["payload_json"])
    if sha256_bytes(json_dumps(payload).encode("utf-8")) != row["payload_sha256"]:
        raise RuntimeError(f"Snapshot digest mismatch for item {item_id} / {kind}")
    return payload


def _eligible(connection, item: dict[str, Any]) -> bool:
    if item["status"] == "succeeded":
        return True
    if item["status"] != "already_applied":
        return False
    evidence = connection.execute(
        """
        SELECT 1 FROM publish_attempts
        WHERE publish_item_id=? AND operation='publish'
          AND status IN ('succeeded','uncertain')
        LIMIT 1
        """,
        (item["id"],),
    ).fetchone()
    return evidence is not None


def _validate_shop(connection, batch: dict[str, Any]) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM shops WHERE id=?", (batch["shop_id"],)).fetchone()
    if not row:
        raise LookupError("Publish batch shop no longer exists")
    shop = dict(row)
    if int(shop["active"]) != 1:
        raise PermissionError("Cannot roll back an inactive or uninstalled shop")
    unresolved = connection.execute(
        """
        SELECT status, COUNT(*) AS count FROM refresh_queue
        WHERE shop_id=? AND status IN ('pending','processing','failed')
        GROUP BY status
        """,
        (shop["id"],),
    ).fetchall()
    if unresolved:
        detail = ", ".join(f"{row['status']}={row['count']}" for row in unresolved)
        raise RuntimeError(f"Refresh queue is not clean: {detail}")
    return shop


def plan_rollback(workspace: Path, batch_id: int) -> dict[str, Any]:
    initialize(workspace)
    with connect(workspace) as connection:
        row = connection.execute("SELECT * FROM publish_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown publish batch: {batch_id}")
        batch = dict(row)
        if batch["status"] not in {"completed", "partial", "failed", "rollback_partial", "rolled_back"}:
            raise RuntimeError(f"Publish batch is not rollback-eligible: {batch['status']}")
        shop = _validate_shop(connection, batch)
        items = [dict(row) for row in connection.execute(
            "SELECT * FROM publish_items WHERE batch_id=? ORDER BY id", (batch_id,)
        )]
        planned: list[dict[str, Any]] = []
        for item in items:
            if not _eligible(connection, item) and item["status"] != "rolled_back":
                continue
            before = _snapshot(connection, item["id"], "planned_before")
            after = _snapshot(connection, item["id"], "published_after")
            changed = list(_loads(item["changed_fields_json"]))
            planned.append({
                "item_id": int(item["id"]),
                "shopify_gid": item["shopify_gid"],
                "handle": item["handle"],
                "changed_fields": sorted(changed),
                "before_sha256": sha256_bytes(json_dumps(before).encode("utf-8")),
                "published_sha256": sha256_bytes(json_dumps(after).encode("utf-8")),
            })
        if not planned:
            raise RuntimeError("No verified Shelfboost-published items are eligible for rollback")
        identity = {
            "batch_id": batch_id,
            "shop": shop["domain"],
            "items": planned,
            "source_changes_sha256": batch["source_changes_sha256"],
            "source_approved_csv_sha256": batch["source_approved_csv_sha256"],
            "source_bridge_manifest_sha256": batch["source_bridge_manifest_sha256"],
        }
        key = sha256_bytes(json_dumps(identity).encode("utf-8"))
        existing = connection.execute(
            "SELECT * FROM rollback_runs WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing:
            return {
                "rollback_run_id": int(existing["id"]),
                "batch_id": batch_id,
                "status": existing["status"],
                "idempotency_key": key,
                "items": len(planned),
                "reused": True,
            }
        cursor = connection.execute(
            """
            INSERT INTO rollback_runs(batch_id, idempotency_key, status, plan_json)
            VALUES (?, ?, 'planned', ?)
            """,
            (batch_id, key, json_dumps(identity)),
        )
        run_id = int(cursor.lastrowid)
    report = {
        "format": "shelfboost-rollback-plan-v1",
        "rollback_run_id": run_id,
        "batch_id": batch_id,
        "shop": shop["domain"],
        "idempotency_key": key,
        "items": planned,
    }
    path = workspace.resolve() / "publish" / "plans" / f"rollback-{run_id}.json"
    write_json(path, report)
    return {**report, "plan_path": str(path), "reused": False}


def _classify(live: dict[str, str], original: dict[str, str], proposed: dict[str, str], changed: list[str]) -> str:
    if all(live[field] == original[field] for field in changed):
        return "already_rolled_back"
    if all(live[field] == proposed[field] for field in changed):
        return "safe_to_rollback"
    return "external_conflict"


def execute_rollback(
    workspace: Path,
    writer: SafeShopifyProductWriter,
    rollback_run_id: int,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    initialize(workspace)
    with connect(workspace) as connection:
        run_row = connection.execute("SELECT * FROM rollback_runs WHERE id=?", (rollback_run_id,)).fetchone()
        if not run_row:
            raise ValueError(f"Unknown rollback run: {rollback_run_id}")
        run = dict(run_row)
        batch = dict(connection.execute(
            "SELECT * FROM publish_batches WHERE id=?", (run["batch_id"],)
        ).fetchone())
        shop = _validate_shop(connection, batch)
        if canonical_shop_domain(writer.shop_domain) != shop["domain"]:
            raise ValueError("Writer is authenticated for a different shop")
        plan = _loads(run["plan_json"])
        item_ids = [int(item["item_id"]) for item in plan["items"]]
        connection.execute(
            "UPDATE rollback_runs SET status='running', started_at=COALESCE(started_at,CURRENT_TIMESTAMP), error_text='' WHERE id=?",
            (rollback_run_id,),
        )
        placeholders = ",".join("?" for _ in item_ids)
        rows = [dict(row) for row in connection.execute(
            f"SELECT * FROM publish_items WHERE id IN ({placeholders}) AND status IN ('succeeded','already_applied','rollback_failed') ORDER BY id LIMIT ?",
            (*item_ids, limit),
        )]

    processed = 0
    for item in rows:
        processed += 1
        original = dict(_loads(item["original_fields_json"]))
        proposed = dict(_loads(item["proposed_fields_json"]))
        changed = list(_loads(item["changed_fields_json"]))
        try:
            live_product = writer.fetch(item["shopify_gid"])
        except Exception as exc:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_failed', error_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (f"rollback_preflight_read_failed:{exc}", item["id"]),
                )
                _record_attempt(connection, item["id"], "rollback", "uncertain", error_text=str(exc))
            continue
        if live_product is None:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_conflict', conflict_reason='live_product_missing', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
            continue
        live_fields = _fields_from_live(live_product)
        with connect(workspace) as connection:
            _insert_snapshot(connection, item["id"], "rollback_before", _snapshot_from_live(live_product, live_fields))
        classification = _classify(live_fields, original, proposed, changed)
        if classification == "already_rolled_back":
            with connect(workspace) as connection:
                _insert_snapshot(connection, item["id"], "rollback_after", _snapshot_from_live(live_product, live_fields))
                _record_attempt(connection, item["id"], "rollback", "already_rolled_back", response=live_product)
                _update_mirror(connection, item, live_product)
                connection.execute(
                    "UPDATE publish_items SET status='rolled_back', error_text='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
            continue
        if classification == "external_conflict":
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_conflict', conflict_reason='live_fields_changed_after_publish', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
                _record_attempt(connection, item["id"], "rollback", "conflict", response=live_product)
            continue
        try:
            result = writer.update_once(item["shopify_gid"], original, changed)
        except MutationUncertain as exc:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_failed', error_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (f"uncertain:{exc}", item["id"]),
                )
                _record_attempt(connection, item["id"], "rollback", "uncertain", error_text=str(exc))
            continue
        except MutationRejected as exc:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_failed', error_text=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc), item["id"]),
                )
                _record_attempt(connection, item["id"], "rollback", "failed", error_text=str(exc))
            continue
        if result.user_errors:
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_failed', error_text='shopify_user_errors', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
                _record_attempt(
                    connection, item["id"], "rollback", "failed",
                    request=result.request_payload, response=result.raw_payload,
                    user_errors=result.user_errors, error_text="shopify_user_errors",
                )
            continue
        after_fields = _fields_from_live(result.product)
        if not all(after_fields[field] == original[field] for field in changed):
            with connect(workspace) as connection:
                connection.execute(
                    "UPDATE publish_items SET status='rollback_failed', error_text='rollback_response_did_not_verify', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (item["id"],),
                )
                _record_attempt(
                    connection, item["id"], "rollback", "uncertain",
                    request=result.request_payload, response=result.raw_payload,
                    error_text="rollback_response_did_not_verify",
                )
            continue
        with connect(workspace) as connection:
            _insert_snapshot(connection, item["id"], "rollback_after", _snapshot_from_live(result.product, after_fields))
            _record_attempt(
                connection, item["id"], "rollback", "succeeded",
                request=result.request_payload, response=result.raw_payload,
            )
            _update_mirror(connection, item, result.product)
            connection.execute(
                "UPDATE publish_items SET status='rolled_back', error_text='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item["id"],),
            )

    with connect(workspace) as connection:
        plan = _loads(connection.execute(
            "SELECT plan_json FROM rollback_runs WHERE id=?", (rollback_run_id,)
        ).fetchone()["plan_json"])
        ids = [int(item["item_id"]) for item in plan["items"]]
        placeholders = ",".join("?" for _ in ids)
        statuses = {
            row["status"]: int(row["count"])
            for row in connection.execute(
                f"SELECT status, COUNT(*) AS count FROM publish_items WHERE id IN ({placeholders}) GROUP BY status",
                ids,
            )
        }
        total = sum(statuses.values())
        rolled = statuses.get("rolled_back", 0)
        if total and rolled == total:
            status = "completed"
            batch_status = "rolled_back"
        elif rolled:
            status = "partial"
            batch_status = "rollback_partial"
        else:
            status = "failed"
            batch_status = "rollback_partial"
        connection.execute(
            "UPDATE rollback_runs SET status=?, completed_at=CASE WHEN ?='completed' THEN CURRENT_TIMESTAMP ELSE completed_at END WHERE id=?",
            (status, status, rollback_run_id),
        )
        connection.execute(
            "UPDATE publish_batches SET status=? WHERE id=?",
            (batch_status, run["batch_id"]),
        )
    return {
        "rollback_run_id": rollback_run_id,
        "batch_id": run["batch_id"],
        "status": status,
        "processed": processed,
        "item_statuses": statuses,
    }


def build_audit_bundle(workspace: Path, batch_id: int) -> dict[str, Any]:
    initialize(workspace)
    root = workspace.resolve() / "publish" / "reports" / f"batch-{batch_id}-audit"
    root.mkdir(parents=True, exist_ok=True)
    with connect(workspace) as connection:
        batch_row = connection.execute("SELECT * FROM publish_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch_row:
            raise ValueError(f"Unknown publish batch: {batch_id}")
        batch = dict(batch_row)
        shop = dict(connection.execute("SELECT * FROM shops WHERE id=?", (batch["shop_id"],)).fetchone())
        items = [dict(row) for row in connection.execute(
            "SELECT * FROM publish_items WHERE batch_id=? ORDER BY id", (batch_id,)
        )]
        snapshots = [dict(row) for row in connection.execute(
            """
            SELECT ps.* FROM publish_snapshots ps
            JOIN publish_items pi ON pi.id=ps.publish_item_id
            WHERE pi.batch_id=? ORDER BY ps.publish_item_id, ps.kind
            """,
            (batch_id,),
        )]
        attempts = [dict(row) for row in connection.execute(
            """
            SELECT pa.* FROM publish_attempts pa
            JOIN publish_items pi ON pi.id=pa.publish_item_id
            WHERE pi.batch_id=? ORDER BY pa.id
            """,
            (batch_id,),
        )]
        rollbacks = [dict(row) for row in connection.execute(
            "SELECT * FROM rollback_runs WHERE batch_id=? ORDER BY id", (batch_id,)
        )]
    files = {
        "batch.json": _redact(batch),
        "shop.json": _redact({key: shop[key] for key in shop if key not in {"token_reference"}}),
        "items.json": _redact(items),
        "snapshots.json": _redact(snapshots),
        "attempts.json": _redact(attempts),
        "rollback-runs.json": _redact(rollbacks),
        "source-digests.json": {
            "changes": {"name": batch["source_changes_name"], "sha256": batch["source_changes_sha256"]},
            "approved_csv": {"name": batch["source_approved_csv_name"], "sha256": batch["source_approved_csv_sha256"]},
            "bridge_manifest": {"name": batch["source_bridge_manifest_name"], "sha256": batch["source_bridge_manifest_sha256"]},
        },
    }
    manifest_files: list[dict[str, str]] = []
    for name, payload in files.items():
        path = root / name
        write_json(path, payload)
        manifest_files.append({"path": name, "sha256": sha256_bytes(path.read_bytes())})
    manifest = {
        "format": "shelfboost-publish-audit-v1",
        "batch_id": batch_id,
        "shop": shop["domain"],
        "files": sorted(manifest_files, key=lambda item: item["path"]),
    }
    manifest_path = root / "manifest.json"
    write_json(manifest_path, manifest)
    digest = sha256_bytes(manifest_path.read_bytes())
    with connect(workspace) as connection:
        connection.execute(
            "UPDATE rollback_runs SET audit_path=?, audit_manifest_sha256=? WHERE batch_id=?",
            (str(root), digest, batch_id),
        )
    return {"batch_id": batch_id, "audit_dir": str(root), "manifest": str(manifest_path), "manifest_sha256": digest, "files": len(manifest_files)}
