from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shelfboost_phase4.core import Database, TenantService
from shelfboost_phase6.core import AIService, EvaluationSuite, ModelRouter, ModelSpec, ProviderResult, initialize_ai, validate_output


class FixtureProvider:
    def __init__(self, outputs): self.outputs=list(outputs); self.calls=[]
    def generate(self, model, prompt, payload):
        self.calls.append(model); value=self.outputs.pop(0)
        if isinstance(value,Exception): raise value
        return ProviderResult(value,1000,500,{"fixture":True})


def safe_output(text="A linen shirt for warm days"):
    return {"fields":{"description_html":{"value":text,"facts_used":["material"]},"seo_title":{"value":"Linen Shirt | North Studio","facts_used":["material"]},"seo_description":{"value":"Shop a linen shirt with verified material details.","facts_used":["material"]}},"abstentions":[]}


class Phase6Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Database(Path(self.temp.name)/"ai.db"); initialize_ai(self.db)
        self.tenants=TenantService(self.db); self.org,self.owner=self.tenants.create_organization("north-studio","North Studio","owner@example.com"); self.editor=self.tenants.add_member(self.org,"editor@example.com","editor")
        with self.db.connect() as c: self.shop=int(c.execute("INSERT INTO app_shops(organization_id,domain) VALUES (?,'north-studio.myshopify.com')",(self.org,)).lastrowid)
        self.router=ModelRouter(ModelSpec("volume",1_000_000,1_000_000),ModelSpec("reasoning",4_000_000,8_000_000))
        self.base_request={"approved_facts":{"material":"linen"},"required_facts":["material"],"prohibited_terms":["perfect"],"risk":"normal","complexity":1,"estimated_input_tokens":1000,"estimated_output_tokens":500}
    def tearDown(self): self.temp.cleanup()

    def service(self, outputs):
        provider=FixtureProvider(outputs); service=AIService(self.db,self.tenants,self.router,provider)
        prompt=service.create_prompt(self.shop,self.editor,"product-copy","Use {{approved_facts}} and {{brand_profile}} only")
        job=service.create_job(self.shop,self.editor,prompt,100_000)
        return service,provider,prompt,job

    def test_safe_output_passes_and_is_prompt_traceable(self):
        service,provider,prompt,job=self.service([safe_output()]); result=service.generate(job,"p1",self.base_request)
        self.assertEqual(result["status"],"passed"); self.assertEqual(result["model"],"volume"); self.assertEqual(result["prompt_version"],1); self.assertEqual(len(result["prompt_sha256"]),64)

    def test_unapproved_facts_risky_claims_and_prohibited_terms_block(self):
        output=safe_output("The perfect clinically proven organic linen cure")
        output["fields"]["description_html"]["facts_used"]=["material","certification"]
        validation=validate_output(self.base_request,output)
        self.assertEqual(validation["status"],"blocked"); self.assertTrue(any("unapproved_fact" in error for error in validation["errors"])); self.assertTrue(any("risky_claim" in error for error in validation["errors"])); self.assertTrue(any("prohibited_term" in error for error in validation["errors"]))

    def test_required_missing_fact_requires_abstention(self):
        request={**self.base_request,"approved_facts":{},"required_facts":["material"]}
        output={"fields":{"seo_title":{"value":"Simple Shirt","facts_used":[]}},"abstentions":[]}
        self.assertEqual(validate_output(request,output)["status"],"blocked")
        output["abstentions"]=["material"]
        self.assertEqual(validate_output(request,output)["status"],"pass")

    def test_routing_budget_and_bounded_retry(self):
        service,provider,prompt,job=self.service([ValueError("malformed"),safe_output()]); request={**self.base_request,"risk":"high"}
        result=service.generate(job,"p1",request,max_attempts=2)
        self.assertEqual(result["model"],"reasoning"); self.assertEqual(provider.calls,["reasoning","reasoning"])
        tiny=service.create_job(self.shop,self.editor,prompt,1)
        with self.assertRaises(RuntimeError): service.generate(tiny,"p2",self.base_request)

    def test_duplicate_output_is_not_presented_as_unique(self):
        service,provider,prompt,job=self.service([safe_output(),safe_output()])
        self.assertEqual(service.generate(job,"p1",self.base_request)["status"],"passed")
        self.assertEqual(service.generate(job,"p2",self.base_request)["status"],"duplicate")

    def test_feedback_stays_proposed_until_admin_confirmation(self):
        service,provider,prompt,job=self.service([safe_output()]); rule=service.propose_feedback_rule(self.shop,self.editor,"brand","avoid superlatives")
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT status FROM ai_feedback_rules WHERE id=?",(rule,)).fetchone()["status"],"proposed")
        with self.assertRaises(PermissionError): service.confirm_feedback_rule(rule,self.editor)
        service.confirm_feedback_rule(rule,self.owner)
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT status FROM ai_feedback_rules WHERE id=?",(rule,)).fetchone()["status"],"confirmed")

    def test_evaluation_gate_records_regression_result(self):
        service,provider,prompt,job=self.service([safe_output()]); suite=EvaluationSuite(self.db); case=suite.add_case("safe apparel",self.base_request,{"required_fields":["description_html","seo_title"],"minimum_score":1.0})
        self.assertTrue(suite.record(prompt,case,safe_output())["passed"])
        bad={"fields":{"seo_title":{"value":"Perfect cure","facts_used":[]}},"abstentions":[]}
        self.assertFalse(suite.record(prompt,case,bad)["passed"])


if __name__ == "__main__": unittest.main()
