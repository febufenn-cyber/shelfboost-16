from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "phase1"))

from shelfboost_phase1.catalog import import_catalog  # noqa: E402
from shelfboost_phase1.db import connect as phase1_connect  # noqa: E402
from shelfboost_phase1.db import initialize as phase1_initialize  # noqa: E402
from shelfboost_phase2.bridge import export_phase1_catalog  # noqa: E402
from shelfboost_phase2.db import connect  # noqa: E402
from shelfboost_phase2.fixture import FixtureItem, FixtureTransport  # noqa: E402
from shelfboost_phase2.shopify import ShopifyGraphQLClient  # noqa: E402
from shelfboost_phase2.sync import sync_catalog  # noqa: E402

API_VERSION = "2026-07"
SHOP = "bridge-store.myshopify.com"


def variant_node(variant_id: int, sku: str, size: str) -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{variant_id}",
        "legacyResourceId": str(variant_id),
        "title": size,
        "sku": sku,
        "barcode": "",
        "price": "49.00",
        "selectedOptions": [{"name": "Size", "value": size}],
    }


def product_node(product_id: int, handle: str, product_type: str, facts: list[dict], variants: list[dict]) -> dict:
    return {
        "id": f"gid://shopify/Product/{product_id}",
        "legacyResourceId": str(product_id),
        "handle": handle,
        "title": handle.replace("-", " ").title(),
        "descriptionHtml": "<p>Existing copy.</p>",
        "vendor": "North Studio",
        "productType": product_type,
        "status": "ACTIVE",
        "tags": ["summer", "new"],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-07-13T00:00:00Z",
        "seo": {"title": handle, "description": "Existing meta description."},
        "metafields": {"nodes": facts, "pageInfo": {"hasNextPage": False}},
        "variants": {"nodes": variants, "pageInfo": {"hasNextPage": False, "endCursor": "end"}},
    }


def fact(key: str, value: str, field_type: str = "single_line_text_field") -> dict:
    return {"namespace": "facts", "key": key, "type": field_type, "value": value}


def client(nodes: list[dict]) -> ShopifyGraphQLClient:
    payload = {"data": {"products": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": "end"}}}}
    transport = FixtureTransport([
        FixtureItem(status=200, headers={"x-shopify-api-version": API_VERSION}, payload=payload)
    ])
    return ShopifyGraphQLClient(SHOP, "token", API_VERSION, transport=transport, sleep=lambda _: None)


class BridgeTests(unittest.TestCase):
    def seed(self, workspace: Path) -> None:
        sync_catalog(
            workspace,
            client(
                [
                    product_node(
                        1,
                        "linen-shirt",
                        "Shirts",
                        [fact("material", "Linen"), fact("fit", "Relaxed")],
                        [variant_node(11, "LS-S", "S"), variant_node(12, "LS-M", "M")],
                    ),
                    product_node(
                        2,
                        "brass-lamp",
                        "Lamps",
                        [fact("material", "Brass")],
                        [variant_node(21, "BL-1", "Default Title")],
                    ),
                ]
            ),
        )

    def test_export_round_trips_into_phase1_fact_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync_workspace = root / "sync"
            phase1_workspace = root / "pilot"
            self.seed(sync_workspace)
            output = root / "catalog.csv"
            result = export_phase1_catalog(sync_workspace, SHOP, output)
            self.assertEqual(result["products"], 2)
            self.assertEqual(result["rows"], 3)
            self.assertIn("Metafield: facts.material", result["fact_headers"])

            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["Handle"] for row in rows], ["brass-lamp", "linen-shirt", "linen-shirt"])
            self.assertEqual(rows[2]["Title"], "")
            self.assertEqual(rows[2]["Variant SKU"], "LS-M")

            phase1_initialize(phase1_workspace)
            imported = import_catalog(phase1_workspace, output)
            self.assertEqual(imported["products"], 2)
            self.assertEqual(imported["eligible"], 2)
            with phase1_connect(phase1_workspace) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM variants").fetchone()[0], 3)
                facts = {
                    (row["name"], row["value"])
                    for row in connection.execute("SELECT name, value FROM product_facts WHERE source_kind='merchant_fact'")
                }
            self.assertIn(("material", "Linen"), facts)
            self.assertIn(("material", "Brass"), facts)

            manifest = json.loads((root / "catalog.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["csv_sha256"], result["csv_sha256"])
            self.assertEqual(manifest["product_count"], 2)

    def test_deleted_products_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            with connect(workspace) as connection:
                connection.execute("UPDATE shopify_products SET is_deleted=1 WHERE handle='brass-lamp'")
            result = export_phase1_catalog(workspace, SHOP, workspace / "catalog.csv")
            self.assertEqual(result["products"], 1)

    def test_export_requires_completed_full_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            sync_catalog(
                workspace,
                client([product_node(1, "one", "General", [fact("material", "Cotton")], [variant_node(11, "ONE", "Default")])]),
                mode="incremental",
                since="2026-07-01T00:00:00Z",
            )
            with self.assertRaisesRegex(RuntimeError, "completed full sync"):
                export_phase1_catalog(workspace, SHOP, workspace / "catalog.csv")

    def test_export_blocks_incomplete_variants_and_dirty_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            with connect(workspace) as connection:
                connection.execute("UPDATE shopify_products SET variants_complete=0 WHERE handle='linen-shirt'")
            with self.assertRaisesRegex(RuntimeError, "Variant data is incomplete"):
                export_phase1_catalog(workspace, SHOP, workspace / "catalog.csv")

            with connect(workspace) as connection:
                connection.execute("UPDATE shopify_products SET variants_complete=1")
                shop_id = connection.execute("SELECT id FROM shops WHERE domain=?", (SHOP,)).fetchone()[0]
                connection.execute(
                    "INSERT INTO refresh_queue(shop_id, product_gid, reason, source_webhook_id, status) VALUES (?, ?, 'products/update', 'bridge-test', 'pending')",
                    (shop_id, "gid://shopify/Product/1"),
                )
            with self.assertRaisesRegex(RuntimeError, "Refresh queue is not clean"):
                export_phase1_catalog(workspace, SHOP, workspace / "catalog.csv")

    def test_export_blocks_inactive_shop(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.seed(workspace)
            with connect(workspace) as connection:
                connection.execute("UPDATE shops SET active=0")
            with self.assertRaises(PermissionError):
                export_phase1_catalog(workspace, SHOP, workspace / "catalog.csv")

    def test_unsupported_fact_type_is_omitted_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            sync_catalog(
                workspace,
                client([
                    product_node(
                        1,
                        "one",
                        "General",
                        [fact("material", "Cotton"), fact("related", '["gid://shopify/Product/2"]', "list.product_reference")],
                        [variant_node(11, "ONE", "Default")],
                    )
                ]),
            )
            result = export_phase1_catalog(workspace, SHOP, workspace / "catalog.csv")
            self.assertEqual(result["warnings"], 1)
            self.assertNotIn("Metafield: facts.related", result["fact_headers"])


if __name__ == "__main__":
    unittest.main()
