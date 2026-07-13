from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import canonical_shop_domain, json_dumps, sha256_bytes, write_json
from .db import connect, initialize
from .shopify import ShopifyGraphQLClient


def register_shop(workspace: Path, domain: str, api_version: str, token_reference: str = "") -> int:
    initialize(workspace)
    domain = canonical_shop_domain(domain)
    with connect(workspace) as connection:
        connection.execute(
            """
            INSERT INTO shops(domain, api_version, token_reference)
            VALUES (?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                api_version=excluded.api_version,
                token_reference=excluded.token_reference,
                updated_at=CURRENT_TIMESTAMP
            """,
            (domain, api_version, token_reference),
        )
        row = connection.execute("SELECT id FROM shops WHERE domain=?", (domain,)).fetchone()
    return int(row["id"])


def _store_page(connection, workspace: Path, run_id: int, page_number: int, operation: str, cursor_in: str, cursor_out: str, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = sha256_bytes(encoded)
    connection.execute(
        """
        INSERT INTO sync_pages(run_id, page_number, operation, cursor_in, cursor_out, payload_sha256, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, page_number, operation, cursor_in, cursor_out, digest, encoded.decode("utf-8")),
    )
    write_json(
        workspace / "snapshots" / f"run-{run_id}" / f"{operation}-{page_number:04d}-{digest[:12]}.json",
        payload,
    )


def _upsert_product(connection, shop_id: int, run_id: int, node: dict[str, Any], variants_complete: bool) -> int:
    seo = node.get("seo") or {}
    metafields = (node.get("metafields") or {}).get("nodes") or []
    payload = json_dumps(node)
    connection.execute(
        """
        INSERT INTO shopify_products(
            shop_id, shopify_gid, legacy_id, handle, title, description_html, vendor,
            product_type, status, tags_json, seo_title, seo_description, created_at_shopify,
            updated_at_shopify, metafields_json, payload_json, variants_complete,
            last_seen_run_id, is_deleted, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
        ON CONFLICT(shop_id, shopify_gid) DO UPDATE SET
            legacy_id=excluded.legacy_id,
            handle=excluded.handle,
            title=excluded.title,
            description_html=excluded.description_html,
            vendor=excluded.vendor,
            product_type=excluded.product_type,
            status=excluded.status,
            tags_json=excluded.tags_json,
            seo_title=excluded.seo_title,
            seo_description=excluded.seo_description,
            created_at_shopify=excluded.created_at_shopify,
            updated_at_shopify=excluded.updated_at_shopify,
            metafields_json=excluded.metafields_json,
            payload_json=excluded.payload_json,
            variants_complete=excluded.variants_complete,
            last_seen_run_id=excluded.last_seen_run_id,
            is_deleted=0,
            deleted_at=NULL
        """,
        (
            shop_id,
            node["id"],
            str(node.get("legacyResourceId") or ""),
            node.get("handle") or "",
            node.get("title") or "",
            node.get("descriptionHtml") or "",
            node.get("vendor") or "",
            node.get("productType") or "",
            node.get("status") or "",
            json_dumps(node.get("tags") or []),
            seo.get("title") or "",
            seo.get("description") or "",
            node.get("createdAt") or "",
            node.get("updatedAt") or "",
            json_dumps(metafields),
            payload,
            int(variants_complete),
            run_id,
        ),
    )
    row = connection.execute(
        "SELECT id FROM shopify_products WHERE shop_id=? AND shopify_gid=?",
        (shop_id, node["id"]),
    ).fetchone()
    return int(row["id"])


def _replace_variants(connection, product_id: int, run_id: int, variants: list[dict[str, Any]]) -> None:
    connection.execute("DELETE FROM shopify_variants WHERE product_id=?", (product_id,))
    for variant in variants:
        connection.execute(
            """
            INSERT INTO shopify_variants(
                product_id, shopify_gid, legacy_id, title, sku, barcode, price,
                options_json, payload_json, last_seen_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                variant["id"],
                str(variant.get("legacyResourceId") or ""),
                variant.get("title") or "",
                variant.get("sku") or "",
                variant.get("barcode") or "",
                str(variant.get("price") or ""),
                json_dumps(variant.get("selectedOptions") or []),
                json_dumps(variant),
                run_id,
            ),
        )


def sync_catalog(
    workspace: Path,
    client: ShopifyGraphQLClient,
    *,
    mode: str = "full",
    since: str = "",
    page_size: int = 50,
    token_reference: str = "SHOPIFY_ACCESS_TOKEN",
) -> dict[str, Any]:
    if mode not in {"full", "incremental"}:
        raise ValueError("mode must be full or incremental")
    if mode == "incremental" and not since:
        raise ValueError("incremental sync requires --since")

    workspace = workspace.resolve()
    shop_id = register_shop(workspace, client.shop_domain, client.api_version, token_reference)
    with connect(workspace) as connection:
        cursor = connection.execute(
            """
            INSERT INTO sync_runs(shop_id, mode, requested_since, status, requested_api_version)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (shop_id, mode, since, client.api_version),
        )
        run_id = int(cursor.lastrowid)

    request_count_start = client.request_count
    product_count = 0
    variant_count = 0
    page_count = 0
    observed_version = ""
    last_cursor = ""
    try:
        for page_number, cursor_in, result, product_connection in client.iter_products(page_size=page_size, since=since):
            page_count += 1
            observed_version = result.api_version
            info = product_connection["pageInfo"]
            cursor_out = info.get("endCursor") or ""
            last_cursor = cursor_out
            with connect(workspace) as connection:
                _store_page(connection, workspace, run_id, page_number, "products", cursor_in, cursor_out, result.raw_payload)

                for node in product_connection.get("nodes") or []:
                    metafields_connection = node.get("metafields") or {"nodes": [], "pageInfo": {"hasNextPage": False}}
                    if (metafields_connection.get("pageInfo") or {}).get("hasNextPage"):
                        raise RuntimeError(f"facts metafields exceed the Phase 2A limit for {node['id']}")
                    variants_connection = node.get("variants") or {"nodes": [], "pageInfo": {"hasNextPage": False}}
                    variants = list(variants_connection.get("nodes") or [])
                    variants_info = variants_connection.get("pageInfo") or {}
                    complete = not bool(variants_info.get("hasNextPage"))
                    if not complete:
                        follow_cursor = variants_info.get("endCursor") or ""
                        for variant_page, variant_cursor, variant_result, variant_connection in client.fetch_remaining_variants(node["id"], follow_cursor):
                            variants.extend(variant_connection.get("nodes") or [])
                            _store_page(
                                connection,
                                workspace,
                                run_id,
                                variant_page,
                                f"variants-{node['legacyResourceId'] or node['id'].split('/')[-1]}",
                                variant_cursor,
                                (variant_connection.get("pageInfo") or {}).get("endCursor") or "",
                                variant_result.raw_payload,
                            )
                        complete = True
                    product_id = _upsert_product(connection, shop_id, run_id, node, complete)
                    _replace_variants(connection, product_id, run_id, variants)
                    product_count += 1
                    variant_count += len(variants)

        deleted_count = 0
        with connect(workspace) as connection:
            if mode == "full":
                deleted_count = connection.execute(
                    """
                    UPDATE shopify_products
                    SET is_deleted=1, deleted_at=CURRENT_TIMESTAMP
                    WHERE shop_id=? AND last_seen_run_id<>? AND is_deleted=0
                    """,
                    (shop_id, run_id),
                ).rowcount
            connection.execute(
                """
                UPDATE sync_runs
                SET status='completed', completed_at=CURRENT_TIMESTAMP, page_count=?, request_count=?,
                    product_count=?, variant_count=?, deleted_count=?, observed_api_version=?, last_cursor=?
                WHERE id=?
                """,
                (
                    page_count,
                    client.request_count - request_count_start,
                    product_count,
                    variant_count,
                    deleted_count,
                    observed_version,
                    last_cursor,
                    run_id,
                ),
            )
        return {
            "run_id": run_id,
            "shop": client.shop_domain,
            "mode": mode,
            "pages": page_count,
            "requests": client.request_count - request_count_start,
            "products": product_count,
            "variants": variant_count,
            "deleted": deleted_count,
            "api_version": observed_version or client.api_version,
        }
    except Exception as exc:
        with connect(workspace) as connection:
            connection.execute(
                """
                UPDATE sync_runs SET status='failed', completed_at=CURRENT_TIMESTAMP,
                    page_count=?, request_count=?, product_count=?, variant_count=?,
                    observed_api_version=?, last_cursor=?, error_text=? WHERE id=?
                """,
                (
                    page_count,
                    client.request_count - request_count_start,
                    product_count,
                    variant_count,
                    observed_version,
                    last_cursor,
                    str(exc),
                    run_id,
                ),
            )
        raise


def sync_status(workspace: Path) -> dict[str, Any]:
    with connect(workspace) as connection:
        shops = [dict(row) for row in connection.execute(
            "SELECT id, domain, api_version, token_reference, created_at, updated_at FROM shops ORDER BY id"
        )]
        latest_runs = [dict(row) for row in connection.execute(
            """
            SELECT sr.* FROM sync_runs sr
            JOIN (SELECT shop_id, MAX(id) AS max_id FROM sync_runs GROUP BY shop_id) latest
              ON latest.max_id=sr.id
            ORDER BY sr.shop_id
            """
        )]
        counts = [dict(row) for row in connection.execute(
            """
            SELECT shop_id,
                   SUM(CASE WHEN is_deleted=0 THEN 1 ELSE 0 END) AS active_products,
                   SUM(CASE WHEN is_deleted=1 THEN 1 ELSE 0 END) AS deleted_products
            FROM shopify_products GROUP BY shop_id
            """
        )]
    return {"shops": shops, "latest_runs": latest_runs, "product_counts": counts}
