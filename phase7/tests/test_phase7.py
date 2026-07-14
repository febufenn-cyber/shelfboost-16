from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase4.core import Database, TenantService
from shelfboost_phase7.core import BillingService, ComplianceService, EntitlementService, initialize_commercial


class FixtureBillingProvider:
    name="fixture"
    def __init__(self, secret="whsec_fixture"): self.secret=secret.encode()
    def sign(self, raw: bytes) -> str: return hmac.new(self.secret,raw,hashlib.sha256).hexdigest()
    def verify_and_decode(self, raw_body: bytes, signature: str):
        expected=hmac.new(self.secret,raw_body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature): raise PermissionError("Invalid billing signature")
        return json.loads(raw_body)


def event(event_id, created, shop, org, status="active", plan="growth", period_start=100, period_end=1000, grace=0):
    return {"id":event_id,"type":"subscription.updated","created":created,"data":{"object":{"id":"sub_1","customer":"cus_1","status":status,"current_period_start":period_start,"current_period_end":period_end,"metadata":{"shop_id":str(shop),"organization_id":str(org),"plan_code":plan,"grace_until":str(grace)}}}}


class Phase7Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/"billing.db"; self.db=Database(self.path); initialize_commercial(self.db)
        self.tenants=TenantService(self.db); self.org,self.owner=self.tenants.create_organization("north-studio","North Studio","owner@example.com")
        with self.db.connect() as c: self.shop=int(c.execute("INSERT INTO app_shops(organization_id,domain) VALUES (?,'north-studio.myshopify.com')",(self.org,)).lastrowid)
        self.provider=FixtureBillingProvider(); self.billing=BillingService(self.db,self.provider)
        self.billing.seed_plan("growth","Growth",{"generations":3,"publishes":2,"team_members":2,"catalog_products":1000},["generate","publish","add_team_member","add_catalog_product"])
    def tearDown(self): self.temp.cleanup()

    def send(self,payload,signature=None):
        raw=json.dumps(payload,separators=(",",":")).encode(); return self.billing.ingest(raw,signature or self.provider.sign(raw))

    def test_signature_dedupe_and_no_provider_secret_persisted(self):
        payload=event("evt_1",200,self.shop,self.org)
        raw=json.dumps(payload,separators=(",",":")).encode()
        with self.assertRaises(PermissionError): self.billing.ingest(raw,"bad")
        self.assertTrue(self.send(payload)["applied"]); self.assertTrue(self.send(payload)["duplicate"])
        self.assertNotIn(b"whsec_fixture",self.path.read_bytes())

    def test_out_of_order_event_cannot_overwrite_newer_state(self):
        self.send(event("evt_new",300,self.shop,self.org,status="active"))
        stale=self.send(event("evt_old",200,self.shop,self.org,status="cancelled"))
        self.assertTrue(stale["stale"])
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT status FROM subscriptions WHERE shop_id=?",(self.shop,)).fetchone()["status"],"active")

    def test_entitlement_metering_idempotency_limits_and_cancellation_degrade(self):
        self.send(event("evt_active",200,self.shop,self.org,status="active"))
        ent=EntitlementService(self.db,self.tenants,clock=lambda:500)
        first=ent.reserve(self.shop,"generate",2,"job-1",user_id=self.owner); second=ent.reserve(self.shop,"generate",2,"job-1",user_id=self.owner)
        self.assertTrue(first["reserved"]); self.assertTrue(second["reused"]); ent.settle(first["usage_id"])
        with self.assertRaises(PermissionError): ent.reserve(self.shop,"generate",2,"job-2",user_id=self.owner)
        self.send(event("evt_cancel",400,self.shop,self.org,status="cancelled"))
        self.assertFalse(ent.allowed(self.shop,"publish",self.owner)["allowed"])
        self.assertTrue(ent.allowed(self.shop,"read",self.owner)["allowed"]); self.assertTrue(ent.allowed(self.shop,"export",self.owner)["allowed"])

    def test_past_due_grace_window(self):
        self.send(event("evt_due",200,self.shop,self.org,status="past_due",grace=600))
        self.assertTrue(EntitlementService(self.db,self.tenants,clock=lambda:500).allowed(self.shop,"generate",self.owner)["allowed"])
        self.assertFalse(EntitlementService(self.db,self.tenants,clock=lambda:700).allowed(self.shop,"generate",self.owner)["allowed"])

    def test_consent_export_retention_and_tenant_scoped_request(self):
        compliance=ComplianceService(self.db,self.tenants,clock=lambda:1000)
        compliance.record_consent(self.org,self.owner,"analytics","2026-07",True,"settings")
        compliance.inventory("catalog_snapshot","merchant_content","catalog reconciliation",30,"purge_after_window")
        request=compliance.request(self.org,"export","owner@example.com",self.shop); payload=compliance.export(request)
        self.assertEqual(payload["organization_id"],self.org); self.assertEqual(payload["shops"][0]["domain"],"north-studio.myshopify.com")
        compliance.mark_retention(self.org,"snapshot","s1",500); compliance.mark_retention(self.org,"audit","a1",400,legal_hold=True)
        eligible=compliance.purge_eligible(600); self.assertEqual([row["resource_id"] for row in eligible],["s1"])
        other_org,_=self.tenants.create_organization("other-org","Other","other@example.com")
        with self.assertRaises(PermissionError): compliance.request(other_org,"delete","other@example.com",self.shop)

    def test_app_review_readiness_truthfully_reports_owner_and_provider_gates(self):
        compliance=ComplianceService(self.db,self.tenants)
        compliance.justify_scope("read_products","catalog sync","Required to audit product content",approved=True)
        compliance.justify_scope("write_products","approved publishing","Required only for selected reviewed fields",approved=True)
        compliance.set_review_check("privacy_webhooks","code","Privacy webhook handlers","passed","fixture tests")
        compliance.set_review_check("legal_policy","legal","Published privacy policy","pending","")
        report=compliance.readiness(["read_products","write_products"],["privacy_webhooks","legal_policy"])
        self.assertFalse(report["ready"]); self.assertIn("check_incomplete:legal_policy",report["blockers"])
        compliance.set_review_check("legal_policy","legal","Published privacy policy","passed","owner-provided URL")
        self.assertTrue(compliance.readiness(["read_products","write_products"],["privacy_webhooks","legal_policy"])["ready"])


if __name__ == "__main__": unittest.main()
