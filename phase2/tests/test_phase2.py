from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shelfboost_phase2.common import canonical_shop_domain
from shelfboost_phase2.db import connect
from shelfboost_phase2.fixture import FixtureItem, FixtureTransport
from shelfboost_phase2.shopify import ShopifyGraphQLClient, VersionMismatch
from shelfboost_phase2.sync import sync_catalog

API_VERSION = "2026-07"


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


def product_node(product_id: int, handle: str, *, variants: list[dict] | None = None, variants_more: bool = False, updated: str = "2026-07-10T00:00:00Z") -> dict:
    return {
        "id": f"gid://shopify/Product/{product_id}",
        "legacyResourceId": str(product_id),
        "handle": handle,
        "title": handle.replace("-", " ").title(),
        "descriptionHtml": "<p>Existing copy.</p>",
        "vendor": "Vendor",
        "productType": "General",
        "status": "ACTIVE",
        "tags": ["tag"],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": updated,
        "seo": {"title": handle, "description": "Description"},
        "metafields": {"nodes": [{"namespace": "facts", "key": "material", "type": "single_line_text_field", "value": "Cotton"}], "pageInfo": {"hasNextPage": False}},
        "variants": {
            "nodes": variants or [variant_node(product_id * 10 + 1, "SKU-1")],
            "pageInfo": {"hasNextPage": variants_more, "endCursor": "variant-next" if variants_more else "variant-end"},
        },
    }


def products_payload(nodes: list[dict], *, has_next: bool = False, cursor: str = "end") -> dict:
    return {"data": {"products": {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}}}


def variants_payload(nodes: list[dict], *, has_next: bool = False, cursor: str = "end") -> dict:
    return {"data": {"product": {"variants": {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}}}}


def item(payload: dict, *, status: int = 200, version: str = API_VERSION, headers: dict[str, str] | None = None) -> FixtureItem:
    merged = {"x-shopify-api-version": version}
    if headers:
        merged.update(headers)
    return FixtureItem(status=status, headers=merged, payload=payload)


class Phase2Tests(unittest.TestCase):
    def client(self, items: list[FixtureItem], *, version: str = API_VERSION, max_attempts: int = 4) -> ShopifyGraphQLClient:
        return ShopifyGraphQLClient(
            "example-store.myshopify.com",
            "token",
            version,
            transport=FixtureTransport(items),
            max_attempts=max_attempts,
            sleep=lambda _: None,
        )

    def test_canonical_shop_domain_rejects_non_shopify_hosts(self):
        self.assertEqual(canonical_shop_domain("https://Example-Store.myshopify.com/"), "example-store.myshopify.com")
        with self.assertRaises(ValueError):
            canonical_shop_domain("example.com")

    def test_sync_paginates_products_and_variants_and_writes_snapshots(self):
        first = product_node(1, "first", variants=[variant_node(11, "A")], variants_more=True)
        second = product_node(2, "second")
        fixtures = [
            item(products_payload([first], has_next=True, cursor="products-next")),
            item(variants_payload([variant_node(12, "B")])),
            item(products_payload([second])),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = sync_catalog(workspace, self.client(fixtures), page_size=1)
            self.assertEqual(result["products"], 2)
            self.assertEqual(result["variants"], 3)
            self.assertEqual(result["requests"], 3)
            with connect(workspace) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM shopify_products WHERE is_deleted=0").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM shopify_variants").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sync_pages").fetchone()[0], 3)
            self.assertEqual(len(list((workspace / "snapshots").rglob("*.json"))), 3)

    def test_full_sync_marks_products_missing_from_later_full_sync_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            sync_catalog(workspace, self.client([item(products_payload([product_node(1, "one"), product_node(2, "two")]))]))
            result = sync_catalog(workspace, self.client([item(products_payload([product_node(1, "one")]))]))
            self.assertEqual(result["deleted"], 1)
            with connect(workspace) as connection:
                deleted = connection.execute("SELECT handle FROM shopify_products WHERE is_deleted=1").fetchone()[0]
            self.assertEqual(deleted, "two")

    def test_incremental_sync_updates_seen_product_without_deleting_unseen(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            sync_catalog(workspace, self.client([item(products_payload([product_node(1, "one"), product_node(2, "two")]))]))
            updated = product_node(1, "one", updated="2026-07-12T00:00:00Z")
            result = sync_catalog(
                workspace,
                self.client([item(products_payload([updated]))]),
                mode="incremental",
                since="2026-07-11T00:00:00Z",
            )
            self.assertEqual(result["deleted"], 0)
            with connect(workspace) as connection:
                active = connection.execute("SELECT COUNT(*) FROM shopify_products WHERE is_deleted=0").fetchone()[0]
                updated_at = connection.execute("SELECT updated_at_shopify FROM shopify_products WHERE handle='one'").fetchone()[0]
            self.assertEqual(active, 2)
            self.assertEqual(updated_at, "2026-07-12T00:00:00Z")

    def test_version_fallback_is_rejected(self):
        fixture = item(products_payload([]), version="2026-04")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(VersionMismatch):
                sync_catalog(Path(tmp), self.client([fixture]))

    def test_retryable_http_response_is_retried(self):
        retry = FixtureItem(status=429, headers={"retry-after": "0", "x-shopify-api-version": API_VERSION}, payload={"error": "slow down"})
        success = item(products_payload([]))
        with tempfile.TemporaryDirectory() as tmp:
            result = sync_catalog(Path(tmp), self.client([retry, success]))
            self.assertEqual(result["requests"], 2)

    def test_metafield_truncation_fails_closed(self):
        node = product_node(1, "one")
        node["metafields"]["pageInfo"]["hasNextPage"] = True
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                sync_catalog(Path(tmp), self.client([item(products_payload([node]))]))
            with connect(Path(tmp)) as connection:
                status = connection.execute("SELECT status FROM sync_runs").fetchone()[0]
            self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
