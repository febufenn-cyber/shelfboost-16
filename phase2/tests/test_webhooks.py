from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase2.db import connect, initialize
from shelfboost_phase2.fixture import FixtureItem, FixtureTransport
from shelfboost_phase2.shopify import ShopifyGraphQLClient
from shelfboost_phase2.sync import sync_catalog
from shelfboost_phase2.webhooks import ingest_webhook, refresh_queued_products

API_VERSION = "2026-07"
SECRET = "test-secret"
SHOP = "example-store.myshopify.com"


def variant_node(variant_id: int, sku: str) -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{variant_id}",
        "legacyResourceId": str(variant_id),
        "title": "Default Title",
        "sku": sku,
        "barcode": "",
        "price": "10.00",
        "selectedOptions": [{"name": "Title", "value": "Default Title"}],
    }


def product_node(product_id: int, handle: str, title: str | None = None) -> dict:
    return {
        "id": f"gid://shopify/Product/{product_id}",
        "legacyResourceId": str(product_id),
        "handle": handle,
        "title": title or handle.title(),
        "descriptionHtml": "<p>Copy</p>",
        "vendor": "Vendor",
        "productType": "General",
        "status": "ACTIVE",
        "tags": [],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-07-13T00:00:00Z",
        "seo": {"title": title or handle.title(), "description": "Description"},
        "metafields": {"nodes": [{"namespace": "facts", "key": "material", "type": "single_line_text_field", "value": "Cotton"}], "pageInfo": {"hasNextPage": False}},
        "variants": {"nodes": [variant_node(product_id * 10, f"SKU-{product_id}")], "pageInfo": {"hasNextPage": False, "endCursor": "end"}},
    }


def products_payload(nodes: list[dict]) -> dict:
    return {"data": {"products": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": "end"}}}}


def product_payload(node: dict | None) -> dict:
    return {"data": {"product": node}}


def client(payloads: list[dict]) -> ShopifyGraphQLClient:
    items = [
        FixtureItem(
            status=200,
            headers={"x-shopify-api-version": API_VERSION},
            payload=payload,
        )
        for payload in payloads
    ]
    return ShopifyGraphQLClient(
        SHOP,
        "token",
        API_VERSION,
        transport=FixtureTransport(items),
        sleep=lambda _: None,
    )


def signed_headers(body: bytes, topic: str, webhook_id: str, event_id: str = "event-1") -> dict[str, str]:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    return {
        "X-Shopify-Hmac-Sha256": base64.b64encode(digest).decode(),
        "X-Shopify-Shop-Domain": SHOP,
        "X-Shopify-Topic": topic,
        "X-Shopify-Webhook-Id": webhook_id,
        "X-Shopify-Event-Id": event_id,
        "X-Shopify-Api-Version": API_VERSION,
    }


class WebhookTests(unittest.TestCase):
    def test_initialize_migrates_phase2a_shop_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            db_path = workspace / "sync.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE shops (id INTEGER PRIMARY KEY, domain TEXT NOT NULL UNIQUE, api_version TEXT NOT NULL, token_reference TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                connection.commit()
            finally:
                connection.close()
            initialize(workspace)
            with connect(workspace) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(shops)")}
            self.assertIn("active", columns)
            self.assertIn("uninstalled_at", columns)

    def seed(self, workspace: Path) -> None:
        sync_catalog(workspace, client([products_payload([product_node(1, "one")])]))

    def test_valid_update_is_queued_and_duplicate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            body = json.dumps({"id": 1, "admin_graphql_api_id": "gid://shopify/Product/1"}, separators=(",", ":")).encode()
            first = ingest_webhook(workspace, signed_headers(body, "products/update", "webhook-1"), body, SECRET)
            duplicate = ingest_webhook(workspace, signed_headers(body, "products/update", "webhook-1"), body, SECRET)
            self.assertEqual(first["status"], "processed")
            self.assertEqual(duplicate["status"], "duplicate")
            with connect(workspace) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM refresh_queue").fetchone()[0], 1)

    def test_invalid_hmac_is_rejected_before_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            body = b'{"id":1}'
            headers = signed_headers(body, "products/update", "webhook-bad")
            headers["X-Shopify-Hmac-Sha256"] = "invalid"
            with self.assertRaises(PermissionError):
                ingest_webhook(workspace, headers, body, SECRET)
            with connect(workspace) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0], 0)

    def test_delete_soft_deletes_product_and_cancels_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            update_body = b'{"id":1,"admin_graphql_api_id":"gid://shopify/Product/1"}'
            ingest_webhook(workspace, signed_headers(update_body, "products/update", "update-1"), update_body, SECRET)
            delete_body = b'{"id":1}'
            ingest_webhook(workspace, signed_headers(delete_body, "products/delete", "delete-1"), delete_body, SECRET)
            with connect(workspace) as connection:
                self.assertEqual(connection.execute("SELECT is_deleted FROM shopify_products WHERE legacy_id='1'").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT status FROM refresh_queue").fetchone()[0], "ignored")

    def test_uninstall_disables_shop_and_ignores_pending_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            update_body = b'{"id":1,"admin_graphql_api_id":"gid://shopify/Product/1"}'
            ingest_webhook(workspace, signed_headers(update_body, "products/update", "update-1"), update_body, SECRET)
            uninstall_body = b'{"id":999}'
            ingest_webhook(workspace, signed_headers(uninstall_body, "app/uninstalled", "uninstall-1"), uninstall_body, SECRET)
            with connect(workspace) as connection:
                shop = connection.execute("SELECT active, token_reference FROM shops").fetchone()
                queue = connection.execute("SELECT status FROM refresh_queue").fetchone()[0]
            self.assertEqual(shop["active"], 0)
            self.assertEqual(shop["token_reference"], "")
            self.assertEqual(queue, "ignored")

    def test_refresh_queue_coalesces_product_events_and_updates_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            body = b'{"id":1,"admin_graphql_api_id":"gid://shopify/Product/1"}'
            ingest_webhook(workspace, signed_headers(body, "products/update", "update-1"), body, SECRET)
            ingest_webhook(workspace, signed_headers(body, "products/update", "update-2", "event-2"), body, SECRET)
            updated = product_node(1, "one", title="Updated One")
            result = refresh_queued_products(workspace, client([product_payload(updated)]))
            self.assertEqual(result["processed_products"], 1)
            self.assertEqual(result["requests"], 1)
            with connect(workspace) as connection:
                title = connection.execute("SELECT title FROM shopify_products WHERE legacy_id='1'").fetchone()[0]
                statuses = [row[0] for row in connection.execute("SELECT status FROM refresh_queue ORDER BY id")]
            self.assertEqual(title, "Updated One")
            self.assertEqual(statuses, ["processed", "processed"])


if __name__ == "__main__":
    unittest.main()
