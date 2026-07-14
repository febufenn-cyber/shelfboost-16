from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass
from typing import Any

from shelfboost_phase4.core import Database, TenantService, stable_json

MEASUREMENT_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS publication_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, subject_key TEXT NOT NULL, batch_reference TEXT NOT NULL, changed_fields_json TEXT NOT NULL, published_at INTEGER NOT NULL, rollback_at INTEGER, idempotency_key TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS metric_observations(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, subject_key TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, source TEXT NOT NULL, window_start INTEGER NOT NULL, window_end INTEGER NOT NULL, source_reference TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(window_end>window_start));
CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, name TEXT NOT NULL, primary_metric TEXT NOT NULL, unit TEXT NOT NULL, hypothesis TEXT NOT NULL, treatment_percent INTEGER NOT NULL CHECK(treatment_percent BETWEEN 1 AND 99), minimum_sample INTEGER NOT NULL CHECK(minimum_sample>=2), window_start INTEGER NOT NULL, window_end INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','active','completed','cancelled')), created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK(window_end>window_start));
CREATE TABLE IF NOT EXISTS experiment_assignments(id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE, subject_key TEXT NOT NULL, arm TEXT NOT NULL CHECK(arm IN ('control','treatment')), assigned_at INTEGER NOT NULL, UNIQUE(experiment_id,subject_key));
CREATE TABLE IF NOT EXISTS experiment_outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE, subject_key TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, observed_at INTEGER NOT NULL, source_observation_id INTEGER REFERENCES metric_observations(id), UNIQUE(experiment_id,subject_key,metric));
CREATE TABLE IF NOT EXISTS optimization_cycles(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, cycle_key TEXT NOT NULL UNIQUE, reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('planned','reviewing','completed','cancelled')), created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS optimization_cycle_items(id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id INTEGER NOT NULL REFERENCES optimization_cycles(id) ON DELETE CASCADE, subject_key TEXT NOT NULL, reason TEXT NOT NULL, priority INTEGER NOT NULL, evidence_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','reviewing','accepted','dismissed','completed')), UNIQUE(cycle_id,subject_key,reason));
CREATE TABLE IF NOT EXISTS measurement_alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, alert_key TEXT NOT NULL UNIQUE, severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')), subject_key TEXT NOT NULL, message TEXT NOT NULL, evidence_json TEXT NOT NULL, acknowledged_at INTEGER, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS measurement_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, report_type TEXT NOT NULL, subject_reference TEXT NOT NULL, claim_type TEXT NOT NULL CHECK(claim_type IN ('observational','controlled_estimate')), payload_json TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_observation_lookup ON metric_observations(shop_id,subject_key,metric,window_start,window_end);
CREATE INDEX IF NOT EXISTS idx_cycle_items ON optimization_cycle_items(cycle_id,status,priority DESC,id);
"""


def initialize_measurement(db: Database) -> None:
    db.migrate()
    with db.connect() as c:
        c.executescript(MEASUREMENT_SCHEMA); c.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (8)")


@dataclass
class MeasurementService:
    db: Database
    tenants: TenantService
    clock: Any=time.time

    def record_change(self, shop_id: int, user_id: int, subject_key: str, batch_reference: str, fields: list[str], published_at: int, idempotency_key: str) -> int:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin"})
        if not subject_key or not fields or not idempotency_key: raise ValueError("Change evidence is incomplete")
        with self.db.connect() as c:
            try: return int(c.execute("INSERT INTO publication_changes(organization_id,shop_id,subject_key,batch_reference,changed_fields_json,published_at,idempotency_key) VALUES (?,?,?,?,?,?,?)",(org,shop_id,subject_key,batch_reference,stable_json(sorted(set(fields))),published_at,idempotency_key)).lastrowid)
            except Exception:
                row=c.execute("SELECT id FROM publication_changes WHERE idempotency_key=?",(idempotency_key,)).fetchone()
                if row: return int(row["id"])
                raise

    def observe(self, shop_id: int, user_id: int, *, subject_key: str, metric: str, value: float, unit: str, source: str, window_start: int, window_end: int, source_reference: str, idempotency_key: str, metadata: dict[str,Any]|None=None) -> dict[str,Any]:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"])
        if not all([subject_key,metric,unit,source,source_reference,idempotency_key]): raise ValueError("Observation source, subject, metric, unit, and key are required")
        if window_end<=window_start: raise ValueError("Observation window is invalid")
        with self.db.connect() as c:
            existing=c.execute("SELECT * FROM metric_observations WHERE idempotency_key=?",(idempotency_key,)).fetchone()
            if existing: return {"observation_id":int(existing["id"]),"reused":True}
            cursor=c.execute("INSERT INTO metric_observations(organization_id,shop_id,subject_key,metric,value,unit,source,window_start,window_end,source_reference,idempotency_key,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(org,shop_id,subject_key,metric,float(value),unit,source,window_start,window_end,source_reference,idempotency_key,stable_json(metadata or {})))
        return {"observation_id":int(cursor.lastrowid),"reused":False}

    def before_after(self, shop_id: int, user_id: int, subject_key: str, metric: str, before_id: int, after_id: int) -> dict[str,Any]:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"])
        with self.db.connect() as c:
            rows=[c.execute("SELECT * FROM metric_observations WHERE id=? AND organization_id=? AND shop_id=? AND subject_key=? AND metric=?",(item,org,shop_id,subject_key,metric)).fetchone() for item in (before_id,after_id)]
            if any(row is None for row in rows): raise PermissionError("Observation outside tenant or metric context")
            before,after=map(dict,rows)
            if before["unit"]!=after["unit"]: raise ValueError("Observation units differ")
            absolute=float(after["value"])-float(before["value"]); relative=None if float(before["value"])==0 else absolute/float(before["value"])
            payload={"subject_key":subject_key,"metric":metric,"unit":before["unit"],"before":{"value":before["value"],"window":[before["window_start"],before["window_end"]],"source":before["source"]},"after":{"value":after["value"],"window":[after["window_start"],after["window_end"]],"source":after["source"]},"absolute_change":absolute,"relative_change":relative,"limitations":["observational comparison","other changes may confound the result","no causal claim"]}
            report=int(c.execute("INSERT INTO measurement_reports(organization_id,shop_id,report_type,subject_reference,claim_type,payload_json,created_at) VALUES (?,?, 'before_after',?,'observational',?,?)",(org,shop_id,subject_key,stable_json(payload),int(self.clock()))).lastrowid)
        return {"report_id":report,"claim_type":"observational",**payload}


@dataclass
class ExperimentService:
    db: Database
    tenants: TenantService
    clock: Any=time.time

    def create(self, shop_id: int, user_id: int, name: str, metric: str, unit: str, hypothesis: str, treatment_percent: int, minimum_sample: int, window_start: int, window_end: int) -> int:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin"})
        if not all([name,metric,unit,hypothesis]) or window_end<=window_start: raise ValueError("Experiment declaration is incomplete")
        with self.db.connect() as c: return int(c.execute("INSERT INTO experiments(organization_id,shop_id,name,primary_metric,unit,hypothesis,treatment_percent,minimum_sample,window_start,window_end,status,created_by) VALUES (?,?,?,?,?,?,?,?,?,'draft',?)",(org,shop_id,name,metric,unit,hypothesis,treatment_percent,minimum_sample,window_start,window_end,user_id)).lastrowid)

    def activate(self, experiment_id: int, user_id: int) -> None:
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM experiments WHERE id=?",(experiment_id,)).fetchone()
            if not row: raise LookupError(experiment_id)
            self.tenants.require_role(int(row["organization_id"]),user_id,{"owner","admin"})
            if row["status"]!="draft": raise RuntimeError("Only draft experiments can activate")
            c.execute("UPDATE experiments SET status='active' WHERE id=?",(experiment_id,))

    def assign(self, experiment_id: int, subject_key: str) -> str:
        with self.db.connect() as c:
            experiment=c.execute("SELECT * FROM experiments WHERE id=? AND status='active'",(experiment_id,)).fetchone()
            if not experiment: raise RuntimeError("Experiment is not active")
            existing=c.execute("SELECT arm FROM experiment_assignments WHERE experiment_id=? AND subject_key=?",(experiment_id,subject_key)).fetchone()
            if existing: return str(existing["arm"])
            bucket=int(hashlib.sha256(f"{experiment_id}:{subject_key}".encode()).hexdigest()[:8],16)%100
            arm="treatment" if bucket<int(experiment["treatment_percent"]) else "control"
            c.execute("INSERT INTO experiment_assignments(experiment_id,subject_key,arm,assigned_at) VALUES (?,?,?,?)",(experiment_id,subject_key,arm,int(self.clock())))
        return arm

    def record_outcome(self, experiment_id: int, subject_key: str, value: float, unit: str, observed_at: int, source_observation_id: int|None=None) -> None:
        with self.db.connect() as c:
            experiment=c.execute("SELECT * FROM experiments WHERE id=? AND status='active'",(experiment_id,)).fetchone()
            if not experiment: raise RuntimeError("Experiment is not active")
            assignment=c.execute("SELECT 1 FROM experiment_assignments WHERE experiment_id=? AND subject_key=?",(experiment_id,subject_key)).fetchone()
            if not assignment: raise RuntimeError("Subject is not assigned")
            if unit!=experiment["unit"] or not (int(experiment["window_start"])<=observed_at<=int(experiment["window_end"])): raise ValueError("Outcome unit or window mismatch")
            c.execute("INSERT INTO experiment_outcomes(experiment_id,subject_key,metric,value,unit,observed_at,source_observation_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT(experiment_id,subject_key,metric) DO UPDATE SET value=excluded.value,unit=excluded.unit,observed_at=excluded.observed_at,source_observation_id=excluded.source_observation_id",(experiment_id,subject_key,experiment["primary_metric"],float(value),unit,observed_at,source_observation_id))

    def analyze(self, experiment_id: int, user_id: int) -> dict[str,Any]:
        with self.db.connect() as c:
            experiment=c.execute("SELECT * FROM experiments WHERE id=?",(experiment_id,)).fetchone()
            if not experiment: raise LookupError(experiment_id)
            self.tenants.require_role(int(experiment["organization_id"]),user_id,{"owner","admin","editor","viewer"})
            rows=[dict(row) for row in c.execute("SELECT a.arm,o.value FROM experiment_assignments a JOIN experiment_outcomes o ON o.experiment_id=a.experiment_id AND o.subject_key=a.subject_key WHERE a.experiment_id=? AND o.metric=?",(experiment_id,experiment["primary_metric"]))]
            groups={"control":[row["value"] for row in rows if row["arm"]=="control"],"treatment":[row["value"] for row in rows if row["arm"]=="treatment"]}
            if len(rows)<int(experiment["minimum_sample"]): raise RuntimeError("Minimum completed sample not reached")
            if not groups["control"] or not groups["treatment"]: raise RuntimeError("Both control and treatment outcomes are required")
            control=statistics.fmean(groups["control"]); treatment=statistics.fmean(groups["treatment"]); delta=treatment-control; relative=None if control==0 else delta/control
            payload={"experiment_id":experiment_id,"primary_metric":experiment["primary_metric"],"unit":experiment["unit"],"sample":{"control":len(groups["control"]),"treatment":len(groups["treatment"])},"mean":{"control":control,"treatment":treatment},"difference":delta,"relative_difference":relative,"claim_type":"controlled_estimate","limitations":["estimate applies to declared sample and window","no universal performance guarantee","statistical significance is not inferred"]}
            c.execute("INSERT INTO measurement_reports(organization_id,shop_id,report_type,subject_reference,claim_type,payload_json,created_at) VALUES (?,?, 'experiment',?,'controlled_estimate',?,?)",(experiment["organization_id"],experiment["shop_id"],str(experiment_id),stable_json(payload),int(self.clock())))
        return payload


@dataclass
class OptimizationService:
    db: Database
    tenants: TenantService
    clock: Any=time.time

    def create_cycle(self, shop_id: int, user_id: int, cycle_key: str, signals: list[dict[str,Any]]) -> dict[str,Any]:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin","editor"})
        if not cycle_key or not signals: raise ValueError("Cycle key and signals required")
        with self.db.connect() as c:
            existing=c.execute("SELECT id FROM optimization_cycles WHERE cycle_key=?",(cycle_key,)).fetchone()
            if existing: return {"cycle_id":int(existing["id"]),"reused":True}
            cycle=int(c.execute("INSERT INTO optimization_cycles(organization_id,shop_id,cycle_key,reason,status,created_at) VALUES (?,?,?,'recurring_catalog_review','planned',?)",(org,shop_id,cycle_key,int(self.clock()))).lastrowid)
            created=0
            for signal in signals:
                subject=str(signal.get("subject_key") or ""); reason=str(signal.get("reason") or "")
                if not subject or reason not in {"new_product","stale_content","missing_content","performance_decline"}: continue
                priority=int(signal.get("priority",50)); evidence=signal.get("evidence") or {}
                c.execute("INSERT OR IGNORE INTO optimization_cycle_items(cycle_id,subject_key,reason,priority,evidence_json,status) VALUES (?,?,?,?,?,'queued')",(cycle,subject,reason,priority,stable_json(evidence))); created+=c.execute("SELECT changes()").fetchone()[0]
                if reason=="performance_decline":
                    alert_key=f"{cycle_key}:{subject}:{reason}"
                    c.execute("INSERT OR IGNORE INTO measurement_alerts(organization_id,shop_id,alert_key,severity,subject_key,message,evidence_json,created_at) VALUES (?,?,?,'warning',?,'Observed performance decline requires review',?,?)",(org,shop_id,alert_key,subject,stable_json(evidence),int(self.clock())))
        return {"cycle_id":cycle,"reused":False,"items":created,"automatic_actions":0}

    def alerts(self, shop_id: int, user_id: int) -> list[dict[str,Any]]:
        shop=self.tenants.shop_for_user(shop_id,user_id)
        with self.db.connect() as c: return [dict(row) for row in c.execute("SELECT * FROM measurement_alerts WHERE organization_id=? AND shop_id=? ORDER BY created_at DESC,id DESC",(shop["organization_id"],shop_id))]
