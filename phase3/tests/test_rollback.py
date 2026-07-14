from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase2.common import json_dumps, sha256_bytes
from shelfboost_phase2.db import connect
from shelfboost_phase3.db import initialize
from shelfboost_phase3.planning import _insert_snapshot
from shelfboost_phase3.rollback import build_audit_bundle, execute_rollback, plan_rollback
from shelfboost_phase3.writer import UpdateResult

DOMAIN = "rollback-fixture.myshopify.com"
GID = "gid://shopify/Product/7001"
ORIGINAL = {
    "Body (HTML)": "<p>Original copy</p>",
    "SEO Title": "Original title",
    "SEO Description": "Original description",
}
PROPOSED = {
    "Body (HTML)": "<p>Approved Shelfboost copy</p>",
    "SEO Title": "Original title",
    "SEO Description": "Original description",
}


def live_product(fields: dict[str, str], updated: str = "2026-07-14T00:01:00Z") -> dict:
    return {
        "id": GID,
        "handle": "rollback-product",
        "descriptionHtml": fields["Body (HTML)"],
        "updatedAt": updated,
        "seo": {
            "title": fields["SEO Title"],
            "description": fields["SEO Description"],
        },
    }


class FakeWriter:
    shop_domain = DOMAIN

    def __init__(self, fields: dict[str, str]):
        self.fields = dict(fields)
        self.calls = 0

    def fetch(self, product_gid: str):
        self.assert_gid(product_gid)
        return live_product(self.fields)

    def assert_gid(self, product_gid: str):
        if product_gid != GID:
            raise AssertionError(product_gid)

    def update_once(self, product_gid: str, values: dict[str, str], changed: list[str]):
        self.assert_gid(product_gid)
        self.calls += 1
        for field in changed:
            self.fields[field] = values[field]
        product = live_product(self.fields, "2026-07-14T00:02:00Z")
        request = {"variables": {"product": {"id": product_gid}}}
        return UpdateResult(product, [], {"data": {"productUpdate": {"product": product}}}, request)


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        initialize(self.workspace)
        with connect(self.workspace) as connection:
            shop_id = connection.execute(
                "INSERT INTO shops(domain, api_version, token_reference) VALUES (?, '2026-07', 'TEST_TOKEN')",
                (DOMAIN,),
            ).lastrowid
            run_id = connection.execute(
                """
                INSERT INTO sync_runs(shop_id, mode, status, requested_api_version, observed_api_version, completed_at)
                VALUES (?, 'full', 'completed', '2026-07', '2026-07', CURRENT_TIMESTAMP)
                """,
                (shop_id,),
            ).lastrowid
            payload = live_product(PROPOSED)
            product_id = connection.execute(
                """
                INSERT INTO shopify_products(
                    shop_id, shopify_gid, legacy_id, handle, title, description_html,
                    vendor, product_type, status, tags_json, seo_title, seo_description,
                    created_at_shopify, updated_at_shopify, metafields_json, payload_json,
                    variants_complete, last_seen_run_id
                ) VALUES (?, ?, '7001', 'rollback-product', 'Rollback Product', ?, '', '', 'ACTIVE',
                          '[]', ?, ?, '2026-07-01T00:00:00Z', '2026-07-14T00:01:00Z', '[]', ?, 1, ?)
                """,
                (
                    shop_id, GID, PROPOSED["Body (HTML)"], PROPOSED["SEO Title"],
                    PROPOSED["SEO Description"], json_dumps(payload), run_id,
                ),
            ).lastrowid
            batch_id = connection.execute(
                """
                INSERT INTO publish_batches(
                    shop_id, idempotency_key, source_changes_name, source_changes_sha256,
                    source_approved_csv_name, source_approved_csv_sha256,
                    source_bridge_manifest_name, source_bridge_manifest_sha256, status
                ) VALUES (?, 'publish-key', 'changes.json', 'c1', 'approved.csv', 'c2', 'bridge.json', 'c3', 'completed')
                """,
                (shop_id,),
            ).lastrowid
            item_id = connection.execute(
                """
                INSERT INTO publish_items(
                    batch_id, product_id, shopify_gid, handle, original_updated_at,
                    original_fields_json, proposed_fields_json, changed_fields_json, status
                ) VALUES (?, ?, ?, 'rollback-product', '2026-07-14T00:00:00Z', ?, ?, ?, 'succeeded')
                """,
                (batch_id, product_id, GID, json_dumps(ORIGINAL), json_dumps(PROPOSED), json_dumps(["Body (HTML)"])),
            ).lastrowid
            _insert_snapshot(connection, item_id, "planned_before", {
                "shopify_gid": GID, "handle": "rollback-product",
                "updated_at_shopify": "2026-07-14T00:00:00Z", "fields": ORIGINAL,
                "source_payload": live_product(ORIGINAL),
            })
            _insert_snapshot(connection, item_id, "published_after", {
                "shopify_gid": GID, "handle": "rollback-product",
                "updated_at_shopify": "2026-07-14T00:01:00Z", "fields": PROPOSED,
                "source_payload": payload,
            })
            connection.execute(
                "INSERT INTO publish_attempts(publish_item_id, operation, status, request_json) VALUES (?, 'publish', 'succeeded', ?)",
                (item_id, json_dumps({"access_token": "must-not-leak"})),
            )
        self.batch_id = int(batch_id)
        self.item_id = int(item_id)

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_is_deterministic_and_reused(self):
        first = plan_rollback(self.workspace, self.batch_id)
        second = plan_rollback(self.workspace, self.batch_id)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])

    def test_successful_selected_field_rollback_updates_mirror(self):
        plan = plan_rollback(self.workspace, self.batch_id)
        writer = FakeWriter(PROPOSED)
        result = execute_rollback(self.workspace, writer, plan["rollback_run_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(writer.calls, 1)
        self.assertEqual(writer.fields["Body (HTML)"], ORIGINAL["Body (HTML)"])
        with connect(self.workspace) as connection:
            item = connection.execute("SELECT status FROM publish_items WHERE id=?", (self.item_id,)).fetchone()
            product = connection.execute("SELECT description_html FROM shopify_products WHERE shopify_gid=?", (GID,)).fetchone()
        self.assertEqual(item["status"], "rolled_back")
        self.assertEqual(product["description_html"], ORIGINAL["Body (HTML)"])

    def test_external_edit_blocks_rollback_without_mutation(self):
        plan = plan_rollback(self.workspace, self.batch_id)
        external = dict(PROPOSED)
        external["Body (HTML)"] = "<p>Merchant changed this later</p>"
        writer = FakeWriter(external)
        result = execute_rollback(self.workspace, writer, plan["rollback_run_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(writer.calls, 0)
        with connect(self.workspace) as connection:
            status = connection.execute("SELECT status FROM publish_items WHERE id=?", (self.item_id,)).fetchone()["status"]
        self.assertEqual(status, "rollback_conflict")

    def test_already_restored_reconciles_without_mutation(self):
        plan = plan_rollback(self.workspace, self.batch_id)
        writer = FakeWriter(ORIGINAL)
        result = execute_rollback(self.workspace, writer, plan["rollback_run_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(writer.calls, 0)

    def test_audit_bundle_digests_and_redacts_secret_keys(self):
        plan = plan_rollback(self.workspace, self.batch_id)
        execute_rollback(self.workspace, FakeWriter(ORIGINAL), plan["rollback_run_id"])
        bundle = build_audit_bundle(self.workspace, self.batch_id)
        manifest = json.loads(Path(bundle["manifest"]).read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = Path(bundle["audit_dir"]) / item["path"]
            self.assertEqual(sha256_bytes(path.read_bytes()), item["sha256"])
        attempts = (Path(bundle["audit_dir"]) / "attempts.json").read_text(encoding="utf-8")
        self.assertNotIn("must-not-leak", attempts)
        self.assertIn("[REDACTED]", attempts)


if __name__ == "__main__":
    unittest.main()
