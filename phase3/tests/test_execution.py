import json
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase2.db import connect, initialize as initialize_phase2
from shelfboost_phase3.db import initialize as initialize_phase3
from shelfboost_phase3.execution import execute_publish
from shelfboost_phase3.writer import MutationUncertain, UpdateResult

SHOP = "fixture-store.myshopify.com"
GID = "gid://shopify/Product/101"


def live(
    title="Old SEO",
    description="Old meta",
    body="<p>Old body</p>",
    updated="2026-07-10T10:00:00Z",
):
    return {
        "id": GID,
        "handle": "linen-shirt",
        "descriptionHtml": body,
        "updatedAt": updated,
        "seo": {"title": title, "description": description},
    }


class FakeWriter:
    def __init__(self, states, outcome="success"):
        self.shop_domain = SHOP
        self.states = list(states)
        self.outcome = outcome
        self.update_calls = 0

    def fetch(self, gid):
        if not self.states:
            return None
        return self.states.pop(0)

    def update_once(self, gid, proposed, changed):
        self.update_calls += 1
        if self.outcome == "uncertain":
            raise MutationUncertain("connection_reset")
        if self.outcome == "user_error":
            return UpdateResult(
                {},
                [{"field": ["product", "seo"], "message": "bad"}],
                {
                    "data": {
                        "productUpdate": {
                            "userErrors": [{"message": "bad"}]
                        }
                    }
                },
                {"variables": {}},
            )
        product = live(
            title=proposed["SEO Title"],
            description=proposed["SEO Description"],
            body=proposed["Body (HTML)"],
            updated="2026-07-13T12:00:00Z",
        )
        return UpdateResult(
            product,
            [],
            {
                "data": {
                    "productUpdate": {"product": product, "userErrors": []}
                }
            },
            {"variables": {"product": {"id": gid}}},
        )


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        initialize_phase2(self.root)
        initialize_phase3(self.root)
        with connect(self.root) as connection:
            connection.execute(
                "INSERT INTO shops(domain,api_version,token_reference,active) VALUES (?,?,?,1)",
                (SHOP, "2026-07", "TOKEN"),
            )
            shop = connection.execute("SELECT id FROM shops").fetchone()["id"]
            run = connection.execute(
                """
                INSERT INTO sync_runs(
                    shop_id,mode,status,requested_api_version,
                    observed_api_version,completed_at
                ) VALUES (?,'full','completed','2026-07','2026-07',CURRENT_TIMESTAMP)
                """,
                (shop,),
            ).lastrowid
            payload = live()
            product = connection.execute(
                """
                INSERT INTO shopify_products(
                    shop_id,shopify_gid,legacy_id,handle,title,description_html,
                    vendor,product_type,status,tags_json,seo_title,seo_description,
                    created_at_shopify,updated_at_shopify,metafields_json,payload_json,
                    variants_complete,last_seen_run_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    shop,
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
                    run,
                ),
            ).lastrowid
            batch = connection.execute(
                """
                INSERT INTO publish_batches(
                    shop_id,idempotency_key,source_changes_name,source_changes_sha256,
                    source_approved_csv_name,source_approved_csv_sha256,
                    source_bridge_manifest_name,source_bridge_manifest_sha256,status
                ) VALUES (?,?,?,?,?,?,?,?, 'planned')
                """,
                (shop, "key", "c", "1", "a", "2", "m", "3"),
            ).lastrowid
            original = {
                "Body (HTML)": "<p>Old body</p>",
                "SEO Title": "Old SEO",
                "SEO Description": "Old meta",
            }
            proposed = dict(original)
            proposed["SEO Title"] = "New SEO"
            self.item = connection.execute(
                """
                INSERT INTO publish_items(
                    batch_id,product_id,shopify_gid,handle,original_updated_at,
                    original_fields_json,proposed_fields_json,changed_fields_json,status
                ) VALUES (?,?,?,?,?,?,?,?, 'ready')
                """,
                (
                    batch,
                    product,
                    GID,
                    "linen-shirt",
                    "2026-07-10T10:00:00Z",
                    json.dumps(original),
                    json.dumps(proposed),
                    json.dumps(["SEO Title"]),
                ),
            ).lastrowid
            self.batch = batch

    def tearDown(self):
        self.tmp.cleanup()

    def item_status(self):
        with connect(self.root) as connection:
            return connection.execute(
                "SELECT status,error_text,conflict_reason,attempt_count FROM publish_items WHERE id=?",
                (self.item,),
            ).fetchone()

    def test_successful_write_is_verified_and_mirror_updated(self):
        writer = FakeWriter([live()])
        result = execute_publish(self.root, writer, self.batch)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(writer.update_calls, 1)
        self.assertEqual(self.item_status()["status"], "succeeded")
        with connect(self.root) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT seo_title FROM shopify_products"
                ).fetchone()["seo_title"],
                "New SEO",
            )
            self.assertIsNotNone(
                connection.execute(
                    "SELECT id FROM publish_snapshots WHERE kind='published_after'"
                ).fetchone()
            )

    def test_already_applied_skips_mutation(self):
        writer = FakeWriter([live(title="New SEO")])
        result = execute_publish(self.root, writer, self.batch)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(writer.update_calls, 0)
        self.assertEqual(self.item_status()["status"], "already_applied")

    def test_external_change_becomes_conflict(self):
        writer = FakeWriter([live(title="Merchant edit")])
        result = execute_publish(self.root, writer, self.batch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(writer.update_calls, 0)
        self.assertEqual(self.item_status()["status"], "conflict")

    def test_uncertain_result_is_not_blindly_retried(self):
        writer = FakeWriter([live()], outcome="uncertain")
        first = execute_publish(self.root, writer, self.batch)
        self.assertEqual(first["status"], "failed")
        self.assertEqual(self.item_status()["status"], "uncertain")
        self.assertEqual(writer.update_calls, 1)

        writer2 = FakeWriter([live(title="New SEO")])
        second = execute_publish(self.root, writer2, self.batch)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(writer2.update_calls, 0)
        self.assertEqual(self.item_status()["status"], "already_applied")

    def test_user_errors_are_terminal_failure(self):
        writer = FakeWriter([live()], outcome="user_error")
        result = execute_publish(self.root, writer, self.batch)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.item_status()["status"], "failed")
        with connect(self.root) as connection:
            errors = json.loads(
                connection.execute(
                    "SELECT user_errors_json FROM publish_attempts"
                ).fetchone()["user_errors_json"]
            )
            self.assertEqual(errors[0]["message"], "bad")

    def test_dirty_queue_blocks_execution(self):
        with connect(self.root) as connection:
            shop = connection.execute("SELECT id FROM shops").fetchone()["id"]
            connection.execute(
                """
                INSERT INTO refresh_queue(
                    shop_id,product_gid,reason,source_webhook_id,status
                ) VALUES (?,?,?,?, 'pending')
                """,
                (shop, GID, "update", "w1"),
            )
        with self.assertRaisesRegex(RuntimeError, "Refresh queue"):
            execute_publish(self.root, FakeWriter([live()]), self.batch)


if __name__ == "__main__":
    unittest.main()
