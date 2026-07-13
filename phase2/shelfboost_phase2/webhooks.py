from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Mapping

from .common import canonical_shop_domain, json_dumps, sha256_bytes
from .db import connect, initialize
from .shopify import ShopifyGraphQLClient
from .sync import _replace_variants, _store_page, _upsert_product

REQUIRED_HEADERS = (
    "x-shopify-hmac-sha256",
    "x-shopify-shop-domain",
    "x-shopify-topic",
    "x-shopify-webhook-id",
)


def normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def verify_webhook_hmac(raw_body: bytes, supplied_hmac: str, client_secret: str) -> bool:
    if not supplied_hmac or not client_secret:
        return False
    digest = hmac.new(client_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, supplied_hmac.strip())


def _product_gid(payload: dict[str, Any]) -> str:
    gid = str(payload.get("admin_graphql_api_id") or "").strip()
    if gid.startswith("gid://shopify/Product/"):
        return gid
    legacy = payload.get("id")
    if legacy is None or str(legacy).strip() == "":
        return ""
    return f"gid://shopify/Product/{legacy}"


def ingest_webhook(
    workspace: Path,
    headers: Mapping[str, str],
    raw_body: bytes,
    client_secret: str,
) -> dict[str, Any]:
    """Verify and persist one Shopify HTTPS webhook delivery.

    HMAC is checked against the exact raw body before JSON or shop data is trusted.
    """
    normalized = normalized_headers(headers)
    missing = [name for name in REQUIRED_HEADERS if not normalized.get(name)]
    if missing:
        raise ValueError("Missing Shopify webhook headers: " + ", ".join(missing))
    if not verify_webhook_hmac(raw_body, normalized["x-shopify-hmac-sha256"], client_secret):
        raise PermissionError("Invalid Shopify webhook HMAC")

    shop_domain = canonical_shop_domain(normalized["x-shopify-shop-domain"])
    topic = normalized["x-shopify-topic"].lower()
    webhook_id = normalized["x-shopify-webhook-id"]
    event_id = normalized.get("x-shopify-event-id", "")
    api_version = normalized.get("x-shopify-api-version", "")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Webhook body is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Webhook payload must be a JSON object")

    initialize(workspace)
    with connect(workspace) as connection:
        shop = connection.execute(
            "SELECT id, active FROM shops WHERE domain=?", (shop_domain,)
        ).fetchone()
        if not shop:
            raise LookupError(f"Webhook shop is not registered in this workspace: {shop_domain}")

        existing = connection.execute(
            "SELECT status FROM webhook_deliveries WHERE webhook_id=?", (webhook_id,)
        ).fetchone()
        if existing:
            return {
                "status": "duplicate",
                "webhook_id": webhook_id,
                "topic": topic,
                "shop": shop_domain,
                "original_status": existing["status"],
            }

        digest = sha256_bytes(raw_body)
        connection.execute(
            """
            INSERT INTO webhook_deliveries(
                shop_id, webhook_id, event_id, topic, api_version, status,
                payload_sha256, payload_json
            ) VALUES (?, ?, ?, ?, ?, 'received', ?, ?)
            """,
            (
                int(shop["id"]),
                webhook_id,
                event_id,
                topic,
                api_version,
                digest,
                json_dumps(payload),
            ),
        )

        outcome = "ignored"
        product_gid = ""
        if topic in {"products/create", "products/update"}:
            product_gid = _product_gid(payload)
            if not product_gid:
                connection.execute(
                    "UPDATE webhook_deliveries SET status='failed', processed_at=CURRENT_TIMESTAMP, error_text='missing_product_id' WHERE webhook_id=?",
                    (webhook_id,),
                )
                raise ValueError("Product webhook does not contain a Shopify product ID")
            if int(shop["active"]) != 1:
                outcome = "ignored"
            else:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO refresh_queue(
                        shop_id, product_gid, reason, source_webhook_id, status
                    ) VALUES (?, ?, ?, ?, 'pending')
                    """,
                    (int(shop["id"]), product_gid, topic, webhook_id),
                )
                outcome = "processed"
        elif topic == "products/delete":
            product_gid = _product_gid(payload)
            if not product_gid:
                raise ValueError("Product deletion webhook does not contain a product ID")
            connection.execute(
                """
                UPDATE shopify_products
                SET is_deleted=1, deleted_at=CURRENT_TIMESTAMP
                WHERE shop_id=? AND shopify_gid=?
                """,
                (int(shop["id"]), product_gid),
            )
            connection.execute(
                "UPDATE refresh_queue SET status='ignored', processed_at=CURRENT_TIMESTAMP WHERE shop_id=? AND product_gid=? AND status IN ('pending','processing')",
                (int(shop["id"]), product_gid),
            )
            outcome = "processed"
        elif topic == "app/uninstalled":
            connection.execute(
                "UPDATE shops SET active=0, uninstalled_at=CURRENT_TIMESTAMP, token_reference='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(shop["id"]),),
            )
            connection.execute(
                "UPDATE refresh_queue SET status='ignored', processed_at=CURRENT_TIMESTAMP WHERE shop_id=? AND status IN ('pending','processing')",
                (int(shop["id"]),),
            )
            outcome = "processed"

        connection.execute(
            "UPDATE webhook_deliveries SET status=?, processed_at=CURRENT_TIMESTAMP WHERE webhook_id=?",
            (outcome, webhook_id),
        )

    return {
        "status": outcome,
        "webhook_id": webhook_id,
        "event_id": event_id,
        "topic": topic,
        "shop": shop_domain,
        "product_gid": product_gid,
        "payload_sha256": digest,
    }


def refresh_queued_products(
    workspace: Path,
    client: ShopifyGraphQLClient,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """Refresh distinct pending products after verified create/update webhooks."""
    initialize(workspace)
    with connect(workspace) as connection:
        shop = connection.execute(
            "SELECT id, active FROM shops WHERE domain=?", (client.shop_domain,)
        ).fetchone()
        if not shop:
            raise LookupError(f"Shop is not registered: {client.shop_domain}")
        if int(shop["active"]) != 1:
            raise PermissionError("Shop is inactive or uninstalled")
        product_rows = connection.execute(
            """
            SELECT product_gid, MIN(id) AS first_id
            FROM refresh_queue
            WHERE shop_id=? AND status='pending'
            GROUP BY product_gid
            ORDER BY first_id
            LIMIT ?
            """,
            (int(shop["id"]), limit),
        ).fetchall()
        if not product_rows:
            return {"processed_products": 0, "requests": 0, "run_id": None}
        run_cursor = connection.execute(
            """
            INSERT INTO sync_runs(shop_id, mode, requested_since, status, requested_api_version)
            VALUES (?, 'incremental', 'webhook_queue', 'running', ?)
            """,
            (int(shop["id"]), client.api_version),
        )
        run_id = int(run_cursor.lastrowid)
        gids = [row["product_gid"] for row in product_rows]
        connection.executemany(
            "UPDATE refresh_queue SET status='processing' WHERE shop_id=? AND product_gid=? AND status='pending'",
            [(int(shop["id"]), gid) for gid in gids],
        )

    request_start = client.request_count
    processed = 0
    variant_count = 0
    page_number = 0
    observed_version = ""
    try:
        for gid in gids:
            result = client.fetch_product(gid)
            observed_version = result.api_version
            page_number += 1
            node = result.data.get("product")
            with connect(workspace) as connection:
                _store_page(connection, workspace, run_id, page_number, f"webhook-product-{gid.rsplit('/', 1)[-1]}", "", "", result.raw_payload)
                if node is None:
                    connection.execute(
                        "UPDATE shopify_products SET is_deleted=1, deleted_at=CURRENT_TIMESTAMP WHERE shop_id=? AND shopify_gid=?",
                        (int(shop["id"]), gid),
                    )
                else:
                    metafields = node.get("metafields") or {"pageInfo": {"hasNextPage": False}}
                    if (metafields.get("pageInfo") or {}).get("hasNextPage"):
                        raise RuntimeError(f"facts metafields exceed the Phase 2B limit for {gid}")
                    variants_connection = node.get("variants") or {"nodes": [], "pageInfo": {"hasNextPage": False}}
                    variants = list(variants_connection.get("nodes") or [])
                    info = variants_connection.get("pageInfo") or {}
                    if info.get("hasNextPage"):
                        cursor = info.get("endCursor") or ""
                        for variant_page, cursor_in, variant_result, variant_connection in client.fetch_remaining_variants(gid, cursor):
                            variants.extend(variant_connection.get("nodes") or [])
                            _store_page(
                                connection,
                                workspace,
                                run_id,
                                variant_page,
                                f"webhook-variants-{gid.rsplit('/', 1)[-1]}",
                                cursor_in,
                                (variant_connection.get("pageInfo") or {}).get("endCursor") or "",
                                variant_result.raw_payload,
                            )
                    product_id = _upsert_product(connection, int(shop["id"]), run_id, node, True)
                    _replace_variants(connection, product_id, run_id, variants)
                    variant_count += len(variants)
                connection.execute(
                    "UPDATE refresh_queue SET status='processed', processed_at=CURRENT_TIMESTAMP, error_text='' WHERE shop_id=? AND product_gid=? AND status='processing'",
                    (int(shop["id"]), gid),
                )
            processed += 1

        with connect(workspace) as connection:
            connection.execute(
                """
                UPDATE sync_runs SET status='completed', completed_at=CURRENT_TIMESTAMP,
                    page_count=?, request_count=?, product_count=?, variant_count=?,
                    observed_api_version=? WHERE id=?
                """,
                (
                    page_number,
                    client.request_count - request_start,
                    processed,
                    variant_count,
                    observed_version,
                    run_id,
                ),
            )
        return {
            "run_id": run_id,
            "processed_products": processed,
            "variants": variant_count,
            "requests": client.request_count - request_start,
            "api_version": observed_version or client.api_version,
        }
    except Exception as exc:
        with connect(workspace) as connection:
            connection.execute(
                "UPDATE sync_runs SET status='failed', completed_at=CURRENT_TIMESTAMP, request_count=?, product_count=?, variant_count=?, observed_api_version=?, error_text=? WHERE id=?",
                (
                    client.request_count - request_start,
                    processed,
                    variant_count,
                    observed_version,
                    str(exc),
                    run_id,
                ),
            )
            connection.execute(
                "UPDATE refresh_queue SET status='failed', processed_at=CURRENT_TIMESTAMP, error_text=? WHERE shop_id=? AND status='processing'",
                (str(exc), int(shop["id"])),
            )
        raise


def webhook_status(workspace: Path) -> dict[str, Any]:
    with connect(workspace) as connection:
        deliveries = [dict(row) for row in connection.execute(
            "SELECT topic, status, COUNT(*) AS count FROM webhook_deliveries GROUP BY topic, status ORDER BY topic, status"
        )]
        queue = [dict(row) for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM refresh_queue GROUP BY status ORDER BY status"
        )]
    return {"deliveries": deliveries, "refresh_queue": queue}
