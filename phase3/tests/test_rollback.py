from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase2.common import json_dumps, sha256_bytes
from shelfboost_phase2.db import connect
from shelfboost_phase3.audit import build_audit_bundle
from shelfboost_phase3.db import initialize
from shelfboost_phase3.planning import _insert_snapshot
from shelfboost_phase3.rollback import execute_rollback, plan_rollback
from shelfboost_phase3.writer import UpdateResult

DOMAIN = "rollback-fixture.myshopify.com"
GID = "gid://shopify/Product/7001"
ORIGINAL = {"Body (HTML)": "<p>Original</p>", "SEO Title": "Title", "SEO Description": "Description"}
PROPOSED = {"Body (HTML)": "<p>Published</p>", "SEO Title": "Title", "SEO Description": "Description"}


def live(fields, updated="2026-07-14T00:01:00Z"):
    return {"id": GID, "handle": "rollback-product", "descriptionHtml": fields["Body (HTML)"], "updatedAt": updated, "seo": {"title": fields["SEO Title"], "description": fields["SEO Description"]}}


class Writer:
    shop_domain = DOMAIN
    def __init__(self, fields): self.fields, self.calls = dict(fields), 0
    def fetch(self, gid):
        assert gid == GID
        return live(self.fields)
    def update_once(self, gid, values, changed):
        assert gid == GID
        self.calls += 1
        for field in changed: self.fields[field] = values[field]
        product = live(self.fields, "2026-07-14T00:02:00Z")
        return UpdateResult(product, [], {"data": {"productUpdate": {"product": product}}}, {"variables": {"product": {"id": gid}}})


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.workspace = Path(self.temp.name); initialize(self.workspace)
        with connect(self.workspace) as c:
            shop = c.execute("INSERT INTO shops(domain,api_version,token_reference) VALUES (?,'2026-07','TEST')", (DOMAIN,)).lastrowid
            run = c.execute("INSERT INTO sync_runs(shop_id,mode,status,requested_api_version,observed_api_version,completed_at) VALUES (?,'full','completed','2026-07','2026-07',CURRENT_TIMESTAMP)", (shop,)).lastrowid
            product = c.execute("""INSERT INTO shopify_products(shop_id,shopify_gid,legacy_id,handle,title,description_html,vendor,product_type,status,tags_json,seo_title,seo_description,created_at_shopify,updated_at_shopify,metafields_json,payload_json,variants_complete,last_seen_run_id) VALUES (?,?,'7001','rollback-product','Product',?,'','','ACTIVE','[]',?,?,'2026-07-01T00:00:00Z','2026-07-14T00:01:00Z','[]',?,1,?)""", (shop,GID,PROPOSED["Body (HTML)"],PROPOSED["SEO Title"],PROPOSED["SEO Description"],json_dumps(live(PROPOSED)),run)).lastrowid
            self.batch = c.execute("""INSERT INTO publish_batches(shop_id,idempotency_key,source_changes_name,source_changes_sha256,source_approved_csv_name,source_approved_csv_sha256,source_bridge_manifest_name,source_bridge_manifest_sha256,status) VALUES (?,'key','changes.json','c1','approved.csv','c2','bridge.json','c3','completed')""", (shop,)).lastrowid
            self.item = c.execute("""INSERT INTO publish_items(batch_id,product_id,shopify_gid,handle,original_updated_at,original_fields_json,proposed_fields_json,changed_fields_json,status) VALUES (?,?,?,'rollback-product','2026-07-14T00:00:00Z',?,?,?,'succeeded')""", (self.batch,product,GID,json_dumps(ORIGINAL),json_dumps(PROPOSED),json_dumps(["Body (HTML)"]))).lastrowid
            _insert_snapshot(c,self.item,"planned_before",{"shopify_gid":GID,"handle":"rollback-product","updated_at_shopify":"2026-07-14T00:00:00Z","fields":ORIGINAL,"source_payload":live(ORIGINAL)})
            _insert_snapshot(c,self.item,"published_after",{"shopify_gid":GID,"handle":"rollback-product","updated_at_shopify":"2026-07-14T00:01:00Z","fields":PROPOSED,"source_payload":live(PROPOSED)})
            c.execute("INSERT INTO publish_attempts(publish_item_id,operation,status,request_json) VALUES (?,'publish','succeeded',?)", (self.item,json_dumps({"access_token":"must-not-leak"})))
    def tearDown(self): self.temp.cleanup()

    def test_plan_reuses_deterministic_key(self):
        one=plan_rollback(self.workspace,self.batch); two=plan_rollback(self.workspace,self.batch)
        self.assertFalse(one["reused"]); self.assertTrue(two["reused"]); self.assertEqual(one["idempotency_key"],two["idempotency_key"])

    def test_success_and_external_conflict(self):
        plan=plan_rollback(self.workspace,self.batch); writer=Writer(PROPOSED)
        result=execute_rollback(self.workspace,writer,plan["rollback_run_id"])
        self.assertEqual(result["status"],"completed"); self.assertEqual(writer.calls,1); self.assertEqual(writer.fields["Body (HTML)"],ORIGINAL["Body (HTML)"])

    def test_external_edit_blocks_mutation(self):
        plan=plan_rollback(self.workspace,self.batch); changed=dict(PROPOSED); changed["Body (HTML)"]="<p>Merchant edit</p>"; writer=Writer(changed)
        result=execute_rollback(self.workspace,writer,plan["rollback_run_id"])
        self.assertEqual(result["status"],"failed"); self.assertEqual(writer.calls,0)

    def test_audit_manifest_and_recursive_redaction(self):
        plan=plan_rollback(self.workspace,self.batch); execute_rollback(self.workspace,Writer(ORIGINAL),plan["rollback_run_id"])
        bundle=build_audit_bundle(self.workspace,self.batch); manifest=json.loads(Path(bundle["manifest"]).read_text())
        for item in manifest["files"]:
            path=Path(bundle["audit_dir"])/item["path"]; self.assertEqual(sha256_bytes(path.read_bytes()),item["sha256"])
        text=(Path(bundle["audit_dir"])/"attempts.json").read_text(); self.assertNotIn("must-not-leak",text); self.assertIn("[REDACTED]",text)


if __name__ == "__main__": unittest.main()
