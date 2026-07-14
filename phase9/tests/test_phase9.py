from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shelfboost_phase4.core import Database
from shelfboost_phase9.core import BackupService, CircuitBreaker, FeatureFlagService, IncidentService, LaunchService, RateLimiter, SLOService, SecretScanner, initialize_operations, redact, security_headers


class Clock:
    def __init__(self,value=1000): self.value=float(value)
    def __call__(self): return self.value
    def advance(self,seconds): self.value+=seconds


class Phase9Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.db=Database(self.root/"ops.db"); initialize_operations(self.db); self.clock=Clock()
    def tearDown(self): self.temp.cleanup()

    def test_secret_scanner_redaction_and_security_headers(self):
        text="token shpat_ABCDEFGHIJKLMNOP and whsec_ABCDEFGHIJKLMNOP"
        findings=SecretScanner().scan_text(text,"fixture.txt"); self.assertEqual(len(findings),2)
        redacted=redact({"access_token":"shpat_ABCDEFGHIJKLMNOP","message":text}); self.assertEqual(redacted["access_token"],"[REDACTED]"); self.assertNotIn("shpat_",redacted["message"])
        headers=security_headers(); self.assertIn("Content-Security-Policy",headers); self.assertIn("frame-ancestors",headers["Content-Security-Policy"]); self.assertEqual(headers["X-Content-Type-Options"],"nosniff")

    def test_rate_limiter_resets_and_circuit_breaker_recovers(self):
        limiter=RateLimiter(2,60,self.clock); self.assertTrue(limiter.allow("shop:1")["allowed"]); self.assertTrue(limiter.allow("shop:1")["allowed"]); self.assertFalse(limiter.allow("shop:1")["allowed"])
        self.clock.advance(60); self.assertTrue(limiter.allow("shop:1")["allowed"])
        breaker=CircuitBreaker(2,30,self.clock); breaker.failure(); self.assertTrue(breaker.permit()); breaker.failure(); self.assertFalse(breaker.permit()); self.clock.advance(31); self.assertTrue(breaker.permit()); self.assertEqual(breaker.state,"half_open"); breaker.success(); self.assertEqual(breaker.state,"closed")

    def test_feature_canary_is_stable_and_kill_switch_is_immediate(self):
        flags=FeatureFlagService(self.db); flags.set("shopify_writes","Controlled publishing",enabled=True,rollout_percent=100,environments=["staging","production"])
        self.assertTrue(flags.enabled("shopify_writes","shop-1","production")); self.assertFalse(flags.enabled("shopify_writes","shop-1","local"))
        flags.kill("shopify_writes"); self.assertFalse(flags.enabled("shopify_writes","shop-1","production"))

    def test_slo_reports_error_budget_burn(self):
        slo=SLOService(self.db,self.clock); slo.define("webhook_ack",0.99,300,"operations","Webhook acknowledgements")
        for index in range(100): slo.observe("webhook_ack",index<98,20,"c"+str(index))
        report=slo.report("webhook_ack"); self.assertEqual(report["samples"],100); self.assertAlmostEqual(report["availability"],0.98); self.assertFalse(report["within_slo"]); self.assertGreater(report["error_budget_burn"],1)

    def test_backup_verify_restore_and_tamper_detection(self):
        source=self.root/"source"; source.mkdir(); (source/"db.sqlite").write_bytes(b"database"); (source/"snapshots").mkdir(); (source/"snapshots"/"one.json").write_text('{"ok":true}')
        backup=BackupService(self.db,self.clock); created=backup.create(source,self.root/"backups","backup-1"); path=Path(created["path"]); self.assertTrue(backup.verify(path)["verified"])
        restored=self.root/"restored"; self.assertTrue(backup.restore(path,restored)["restored"]); self.assertEqual((restored/"db.sqlite").read_bytes(),b"database")
        (path/"db.sqlite").write_bytes(b"tampered")
        with self.assertRaises(RuntimeError): backup.verify(path)

    def test_incident_timeline_requires_valid_transitions(self):
        incidents=IncidentService(self.db,self.clock); incident=incidents.declare("inc-1","sev2","Shopify write latency","on-call","monitor")
        with self.assertRaises(ValueError): incidents.transition(incident,"closed","owner","skip")
        incidents.transition(incident,"investigating","on-call","Investigating provider latency"); incidents.transition(incident,"mitigated","on-call","Writes disabled by kill switch"); incidents.transition(incident,"resolved","owner","Provider recovered"); incidents.transition(incident,"closed","owner","Review complete")
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM incidents WHERE id=?",(incident,)).fetchone()["status"],"closed"); self.assertEqual(c.execute("SELECT COUNT(*) FROM incident_events WHERE incident_id=?",(incident,)).fetchone()[0],5)

    def test_launch_report_separates_code_complete_from_production_ready(self):
        launch=LaunchService(self.db,self.clock); required=["regression","dev_store","kms","ai_provider","billing_sandbox","restore_drill","security_review","legal","shopify_review"]
        launch.set_gate("regression","code","Phase 0-9 tests","passed",evidence="CI run")
        for key,category in [("dev_store","staging"),("kms","provider"),("ai_provider","provider"),("billing_sandbox","provider"),("restore_drill","operations"),("security_review","security"),("legal","legal"),("shopify_review","shopify")]: launch.set_gate(key,category,key,"pending",owner="owner")
        report=launch.final_report(required,[f"phase-{number}" for number in range(10)])
        self.assertTrue(report["code_complete"]); self.assertFalse(report["production_ready"]); self.assertTrue(any("dev_store" in blocker for blocker in report["blockers"]))
        for key in required[1:]: launch.set_gate(key,"staging" if key=="dev_store" else "provider",key,"passed",evidence="external evidence",owner="owner")
        self.assertTrue(launch.final_report(required,[f"phase-{number}" for number in range(10)])["production_ready"])


if __name__ == "__main__": unittest.main()
