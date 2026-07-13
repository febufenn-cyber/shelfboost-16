import csv
import json
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase2.db import connect, initialize as initialize_phase2
from shelfboost_phase3.db import initialize as initialize_phase3
from shelfboost_phase3.planning import plan_publish

SHOP = "fixture-store.myshopify.com"
GID = "gid://shopify/Product/101"


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        initialize_phase2(self.root)
        with connect(self.root) as connection:
            connection.execute(
                "INSERT INTO shops(domain, api_version, token_reference, active) VALUES (?, ?, ?, 1)",
                (SHOP, "2026-07", "TOKEN"),
            )
            shop_id = connection.execute("SELECT id FROM shops").fetchone()["id"]
            run_id = connection.execute(
                """
                INSERT INTO sync_runs(
                    shop_id, mode, status, requested_api_version,
                    observed_api_version, completed_at
                ) VALUES (?, 'full', 'completed', '2026-07', '2026-07', CURRENT_TIMESTAMP)
                """,
                (shop_id,),
            ).lastrowid
            payload = {
                "id": GID,
                "handle": "linen-shirt",
                "title": "Linen Shirt",
                "descriptionHtml": "<p>Old body</p>",
                "updatedAt": "2026-07-10T10:00:00Z",
                "seo": {"title": "Old SEO", "description": "Old meta"},
            }
            connection.execute(
                """
                INSERT INTO shopify_products(
                    shop_id, shopify_gid, legacy_id, handle, title, description_html,
                    vendor, product_type, status, tags_json, seo_title, seo_description,
                    created_at_shopify, updated_at_shopify, metafields_json, payload_json,
                    variants_complete, last_seen_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shop_id,
                    GID,
                    "101",
                    "linen-shirt",
                    "Linen Shirt",
                    "<p>Old body</p>",
                    "North",
                    "Shirts",
                    "ACTIVE",
                    "[]",
                    "Old SEO",
                    "Old meta",
                    "2026-01-01T00:00:00Z",
                    "2026-07-10T10:00:00Z",
                    "[]",
                    json.dumps(payload),
                    1,
                    run_id,
                ),
            )
        initialize_phase3(self.root)
        self.approved = self.root / "approved.csv"
        self.changes = self.root / "approved.changes.json"
        self.manifest = self.root / "bridge.manifest.json"
        self.write_inputs()

    def tearDown(self):
        self.tmp.cleanup()

    def write_inputs(
        self,
        *,
        original="Old SEO",
        final="New SEO",
        csv_final=None,
        provenance_updated="2026-07-10T10:00:00Z",
        field="SEO Title",
    ):
        csv_final = final if csv_final is None else csv_final
        with self.approved.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["Handle", "Body (HTML)", "SEO Title", "SEO Description"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Handle": "linen-shirt",
                    "Body (HTML)": "<p>Old body</p>",
                    "SEO Title": csv_final if field == "SEO Title" else "Old SEO",
                    "SEO Description": csv_final if field == "SEO Description" else "Old meta",
                }
            )
        self.changes.write_text(
            json.dumps(
                [
                    {
                        "handle": "linen-shirt",
                        "field": field,
                        "decision": "approved",
                        "original": original,
                        "final": final,
                        "reviewer_note": "ok",
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.manifest.write_text(
            json.dumps(
                {
                    "format": "shelfboost-phase1-bridge-v1",
                    "shop": SHOP,
                    "products": [
                        {
                            "handle": "linen-shirt",
                            "shopify_gid": GID,
                            "updated_at_shopify": provenance_updated,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_plans_ready_item_and_snapshot(self):
        result = plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["conflicts"], 0)
        with connect(self.root) as connection:
            item = connection.execute("SELECT * FROM publish_items").fetchone()
            self.assertEqual(item["status"], "ready")
            self.assertEqual(json.loads(item["proposed_fields_json"])["SEO Title"], "New SEO")
            snapshot = connection.execute("SELECT * FROM publish_snapshots").fetchone()
            self.assertEqual(snapshot["kind"], "planned_before")

    def test_same_sources_reuse_idempotent_plan(self):
        first = plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)
        second = plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)
        self.assertTrue(second["reused"])
        self.assertEqual(first["batch_id"], second["batch_id"])

    def test_original_mismatch_blocks_whole_batch(self):
        self.write_inputs(original="Wrong old")
        result = plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)
        self.assertEqual(result["status"], "blocked")
        with connect(self.root) as connection:
            item = connection.execute("SELECT * FROM publish_items").fetchone()
            self.assertIn("original_mismatch:SEO Title", item["conflict_reason"])

    def test_approved_csv_mismatch_blocks(self):
        self.write_inputs(csv_final="Different")
        result = plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)
        self.assertEqual(result["status"], "blocked")

    def test_dirty_refresh_queue_prevents_plan(self):
        with connect(self.root) as connection:
            shop_id = connection.execute("SELECT id FROM shops").fetchone()["id"]
            connection.execute(
                """
                INSERT INTO refresh_queue(
                    shop_id, product_gid, reason, source_webhook_id, status
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (shop_id, GID, "update", "w1"),
            )
        with self.assertRaisesRegex(RuntimeError, "Refresh queue"):
            plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)

    def test_stale_bridge_provenance_blocks(self):
        self.write_inputs(provenance_updated="2026-07-01T00:00:00Z")
        result = plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)
        self.assertEqual(result["status"], "blocked")

    def test_unsupported_field_is_rejected(self):
        self.write_inputs(field="Title")
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            plan_publish(self.root, SHOP, self.approved, self.changes, self.manifest)


if __name__ == "__main__":
    unittest.main()
