from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shelfboost_phase4.core import Database, TenantService
from shelfboost_phase8.core import MeasurementService, OptimizationService, initialize_measurement
from shelfboost_phase8.experiments import ControlledExperimentService


class Phase8Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Database(Path(self.temp.name)/"metrics.db"); initialize_measurement(self.db)
        self.tenants=TenantService(self.db); self.org,self.owner=self.tenants.create_organization("north-studio","North Studio","owner@example.com"); self.viewer=self.tenants.add_member(self.org,"viewer@example.com","viewer")
        with self.db.connect() as c: self.shop=int(c.execute("INSERT INTO app_shops(organization_id,domain) VALUES (?,'north-studio.myshopify.com')",(self.org,)).lastrowid)
        self.measure=MeasurementService(self.db,self.tenants,clock=lambda:2000); self.experiments=ControlledExperimentService(self.db,self.tenants,clock=lambda:1100); self.optimize=OptimizationService(self.db,self.tenants,clock=lambda:3000)
    def tearDown(self): self.temp.cleanup()

    def test_observations_require_source_window_and_are_idempotent(self):
        with self.assertRaises(ValueError): self.measure.observe(self.shop,self.owner,subject_key="p1",metric="clicks",value=1,unit="count",source="",window_start=1,window_end=2,source_reference="r",idempotency_key="k")
        first=self.measure.observe(self.shop,self.owner,subject_key="p1",metric="clicks",value=10,unit="count",source="search_console",window_start=100,window_end=200,source_reference="sc:1",idempotency_key="obs-1")
        second=self.measure.observe(self.shop,self.owner,subject_key="p1",metric="clicks",value=999,unit="count",source="search_console",window_start=100,window_end=200,source_reference="sc:1",idempotency_key="obs-1")
        self.assertFalse(first["reused"]); self.assertTrue(second["reused"]); self.assertEqual(first["observation_id"],second["observation_id"])
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT value FROM metric_observations WHERE id=?",(first["observation_id"],)).fetchone()["value"],10)

    def test_before_after_is_explicitly_observational(self):
        before=self.measure.observe(self.shop,self.owner,subject_key="p1",metric="impressions",value=100,unit="count",source="search_console",window_start=100,window_end=200,source_reference="before",idempotency_key="before")
        after=self.measure.observe(self.shop,self.owner,subject_key="p1",metric="impressions",value=125,unit="count",source="search_console",window_start=300,window_end=400,source_reference="after",idempotency_key="after")
        report=self.measure.before_after(self.shop,self.viewer,"p1","impressions",before["observation_id"],after["observation_id"])
        self.assertEqual(report["claim_type"],"observational"); self.assertEqual(report["absolute_change"],25); self.assertIn("no causal claim",report["limitations"])

    def test_assignment_is_stable_and_active_objective_is_immutable(self):
        experiment=self.experiments.create(self.shop,self.owner,"Title test","ctr","ratio","Approved title increases CTR",50,4,1000,2000)
        self.experiments.amend_draft(experiment,self.owner,hypothesis="A clearer approved title increases CTR")
        self.experiments.activate(experiment,self.owner)
        first=self.experiments.assign(experiment,"p1"); second=self.experiments.assign(experiment,"p1")
        self.assertEqual(first,second)
        with self.assertRaises(RuntimeError): self.experiments.amend_draft(experiment,self.owner,hypothesis="Changed after results")

    def test_experiment_requires_control_treatment_minimum_sample_and_window(self):
        experiment=self.experiments.create(self.shop,self.owner,"Meta test","ctr","ratio","Meta changes affect CTR",50,4,1000,2000); self.experiments.activate(experiment,self.owner)
        groups={"control":[],"treatment":[]}
        for index in range(100):
            subject=f"p{index}"; arm=self.experiments.assign(experiment,subject)
            if len(groups[arm])<2: groups[arm].append(subject)
            if all(len(items)>=2 for items in groups.values()): break
        self.assertTrue(all(len(items)>=2 for items in groups.values()))
        with self.assertRaises(RuntimeError): self.experiments.analyze(experiment,self.viewer)
        with self.assertRaises(ValueError): self.experiments.record_outcome(experiment,groups["control"][0],0.1,"ratio",999)
        for arm,subjects in groups.items():
            for offset,subject in enumerate(subjects): self.experiments.record_outcome(experiment,subject,0.10+offset*0.01+(0.03 if arm=="treatment" else 0),"ratio",1500)
        report=self.experiments.analyze(experiment,self.viewer)
        self.assertEqual(report["claim_type"],"controlled_estimate"); self.assertEqual(report["sample"],{"control":2,"treatment":2}); self.assertIn("statistical significance is not inferred",report["limitations"])

    def test_optimization_cycle_is_deduplicated_and_never_acts_automatically(self):
        signals=[{"subject_key":"p1","reason":"new_product","priority":70,"evidence":{"created_at":2900}},{"subject_key":"p2","reason":"performance_decline","priority":90,"evidence":{"metric":"clicks","change":-0.2}},{"subject_key":"p2","reason":"performance_decline","priority":90,"evidence":{"metric":"clicks","change":-0.2}}]
        result=self.optimize.create_cycle(self.shop,self.owner,"weekly:2026-07-14",signals)
        self.assertEqual(result["items"],2); self.assertEqual(result["automatic_actions"],0)
        self.assertTrue(self.optimize.create_cycle(self.shop,self.owner,"weekly:2026-07-14",signals)["reused"])
        alerts=self.optimize.alerts(self.shop,self.viewer); self.assertEqual(len(alerts),1); self.assertEqual(alerts[0]["subject_key"],"p2")

    def test_cross_tenant_observations_are_not_readable(self):
        observation=self.measure.observe(self.shop,self.owner,subject_key="p1",metric="clicks",value=1,unit="count",source="shopify",window_start=1,window_end=2,source_reference="r",idempotency_key="private")
        other_org,other_user=self.tenants.create_organization("other-org","Other","other@example.com")
        with self.assertRaises(PermissionError): self.measure.before_after(self.shop,other_user,"p1","clicks",observation["observation_id"],observation["observation_id"])
        self.assertNotEqual(other_org,self.org)


if __name__ == "__main__": unittest.main()
