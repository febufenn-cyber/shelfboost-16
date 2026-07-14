from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shelfboost_phase4.core import Database, TenantService
from shelfboost_phase5.experience import MerchantExperience, initialize_experience, render_dashboard, render_review


class Phase5Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Database(Path(self.temp.name)/"app.db"); initialize_experience(self.db)
        self.tenants=TenantService(self.db); self.org,self.owner=self.tenants.create_organization("north-studio","North Studio","owner@example.com")
        self.editor=self.tenants.add_member(self.org,"editor@example.com","editor"); self.viewer=self.tenants.add_member(self.org,"viewer@example.com","viewer")
        with self.db.connect() as c: self.shop=int(c.execute("INSERT INTO app_shops(organization_id,domain) VALUES (?,'north-studio.myshopify.com')",(self.org,)).lastrowid)
        self.experience=MerchantExperience(self.db,self.tenants)
    def tearDown(self): self.temp.cleanup()

    def product(self, handle="linen-shirt", priority=90, health=45):
        return self.experience.upsert_product(self.shop,self.editor,{"handle":handle,"title":handle.replace('-',' ').title(),"priority_score":priority,"health_score":health,"facts":{"material":"linen"}},[{"code":"thin","severity":"high","label":"Thin description","evidence":"32 words","source_type":"deterministic"},{"code":"tone","severity":"low","label":"Voice mismatch","evidence":"model review","source_type":"model"}])

    def test_onboarding_progression_and_recoverable_error(self):
        self.assertEqual(self.experience.set_onboarding(self.shop,self.owner,"installed")["state"],"installed")
        self.experience.set_onboarding(self.shop,self.owner,"syncing"); self.experience.set_onboarding(self.shop,self.owner,"error","temporary API failure")
        self.assertEqual(self.experience.set_onboarding(self.shop,self.owner,"syncing")["state"],"syncing")
        with self.assertRaises(PermissionError): self.experience.set_onboarding(self.shop,self.viewer,"audit_ready")

    def test_dashboard_is_scoped_filterable_paginated_and_accessible(self):
        self.product(); self.product("brass-lamp",60,70)
        view=self.experience.dashboard(self.shop,self.viewer,severity="high",source_type="deterministic",page_size=1)
        self.assertEqual(view["total"],2); self.assertEqual(len(view["products"]),1); self.assertEqual(view["pages"],2)
        markup=render_dashboard(view)
        self.assertIn("<h1>Catalog health</h1>",markup); self.assertIn("<caption>",markup); self.assertIn("deterministic",markup)

    def test_brand_versions_expose_governed_profile(self):
        profile={"tone":["warm"],"audience":["design-conscious buyers"],"prohibited_terms":["perfect"],"claims_policy":{"health":"prohibited"}}
        first=self.experience.create_brand_version(self.shop,self.editor,profile)
        second=self.experience.create_brand_version(self.shop,self.owner,{**profile,"tone":["warm","specific"]})
        active=self.experience.active_brand(self.shop,self.viewer)
        self.assertNotEqual(first,second); self.assertEqual(active["version"],2); self.assertIn("specific",active["profile"]["tone"])

    def test_warning_acknowledgement_role_and_approved_only_payload(self):
        product=self.product()
        batch=self.experience.create_review_batch(self.shop,self.editor,"Pilot",[{"product_id":product,"field_name":"SEO Title","original":"Old","proposed":"New","warnings":["keyword source unverified"]},{"product_id":product,"field_name":"SEO Description","original":"Old meta","proposed":"New meta","warnings":[]}])
        with self.db.connect() as c: fields=[dict(r) for r in c.execute("SELECT * FROM merchant_review_fields WHERE batch_id=? ORDER BY id",(batch,))]
        with self.assertRaises(RuntimeError): self.experience.decide_field(fields[0]["id"],self.editor,"approved")
        self.experience.decide_field(fields[0]["id"],self.editor,"approved",acknowledge_warnings=True,note="Checked source")
        self.experience.decide_field(fields[1]["id"],self.editor,"rejected",note="Keep current")
        with self.assertRaises(PermissionError): self.experience.request_publish(batch,self.viewer)
        payload=self.experience.request_publish(batch,self.owner)
        self.assertEqual(len(payload["fields"]),1); self.assertEqual(payload["fields"][0]["field"],"SEO Title")

    def test_high_risk_batch_requires_different_reviewer(self):
        product=self.product(); batch=self.experience.create_review_batch(self.shop,self.owner,"Claims",[{"product_id":product,"field_name":"Body (HTML)","original":"Old","proposed":"New","warnings":[]}],risk="high")
        with self.db.connect() as c: field=int(c.execute("SELECT id FROM merchant_review_fields WHERE batch_id=?",(batch,)).fetchone()["id"])
        self.experience.decide_field(field,self.owner,"approved")
        with self.assertRaises(PermissionError): self.experience.request_publish(batch,self.owner)
        with self.db.connect() as c: c.execute("UPDATE merchant_review_fields SET reviewed_by=? WHERE id=?",(self.editor,field))
        self.assertEqual(self.experience.request_publish(batch,self.owner)["batch_id"],batch)

    def test_viewer_cannot_mutate_and_cross_tenant_records_are_rejected(self):
        with self.assertRaises(PermissionError): self.experience.upsert_product(self.shop,self.viewer,{"handle":"x","title":"X"},[])
        other_org,other_user=self.tenants.create_organization("other-org","Other","other@example.com")
        with self.assertRaises(PermissionError): self.experience.dashboard(self.shop,other_user)
        self.assertNotEqual(other_org,self.org)

    def test_review_html_has_explicit_status_text_and_labels(self):
        markup=render_review([{"id":1,"field_name":"SEO Title","original_value":"Old","proposed_value":"New","warnings_json":"[\"Needs review\"]"}])
        self.assertIn("<label for='decision-1'>Decision</label>",markup); self.assertIn("Warnings:",markup); self.assertIn("<h3>Original</h3>",markup)


if __name__ == "__main__": unittest.main()
