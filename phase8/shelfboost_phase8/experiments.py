from __future__ import annotations

import hashlib
import statistics
import time
from dataclasses import dataclass
from typing import Any

from shelfboost_phase4.core import Database, TenantService, stable_json


@dataclass
class ControlledExperimentService:
    db: Database
    tenants: TenantService
    clock: Any=time.time

    def create(self, shop_id: int, user_id: int, name: str, metric: str, unit: str, hypothesis: str, treatment_percent: int, minimum_sample: int, window_start: int, window_end: int) -> int:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin"})
        if not all([name,metric,unit,hypothesis]) or window_end<=window_start: raise ValueError("Experiment declaration is incomplete")
        with self.db.connect() as c:
            return int(c.execute(
                """INSERT INTO experiments(organization_id,shop_id,name,primary_metric,unit,hypothesis,treatment_percent,minimum_sample,window_start,window_end,status,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,'draft',?)""",
                (org,shop_id,name,metric,unit,hypothesis,treatment_percent,minimum_sample,window_start,window_end,user_id),
            ).lastrowid)

    def activate(self, experiment_id: int, user_id: int) -> None:
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM experiments WHERE id=?",(experiment_id,)).fetchone()
            if not row: raise LookupError(experiment_id)
            self.tenants.require_role(int(row["organization_id"]),user_id,{"owner","admin"})
            if row["status"]!="draft": raise RuntimeError("Only draft experiments can activate")
            c.execute("UPDATE experiments SET status='active' WHERE id=?",(experiment_id,))

    def amend_draft(self, experiment_id: int, user_id: int, *, hypothesis: str|None=None, minimum_sample: int|None=None) -> None:
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM experiments WHERE id=?",(experiment_id,)).fetchone()
            if not row: raise LookupError(experiment_id)
            self.tenants.require_role(int(row["organization_id"]),user_id,{"owner","admin"})
            if row["status"]!="draft": raise RuntimeError("Active experiment objectives are immutable")
            c.execute("UPDATE experiments SET hypothesis=?,minimum_sample=? WHERE id=?",(hypothesis or row["hypothesis"],minimum_sample or row["minimum_sample"],experiment_id))

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
            groups={"control":[float(row["value"]) for row in rows if row["arm"]=="control"],"treatment":[float(row["value"]) for row in rows if row["arm"]=="treatment"]}
            if len(rows)<int(experiment["minimum_sample"]): raise RuntimeError("Minimum completed sample not reached")
            if not groups["control"] or not groups["treatment"]: raise RuntimeError("Both control and treatment outcomes are required")
            control=statistics.fmean(groups["control"]); treatment=statistics.fmean(groups["treatment"]); delta=treatment-control
            payload={"experiment_id":experiment_id,"primary_metric":experiment["primary_metric"],"unit":experiment["unit"],"sample":{"control":len(groups["control"]),"treatment":len(groups["treatment"])},"mean":{"control":control,"treatment":treatment},"difference":delta,"relative_difference":None if control==0 else delta/control,"claim_type":"controlled_estimate","limitations":["estimate applies only to the declared sample and window","statistical significance is not inferred","no universal performance guarantee"]}
            c.execute("INSERT INTO measurement_reports(organization_id,shop_id,report_type,subject_reference,claim_type,payload_json,created_at) VALUES (?,?,'experiment',?,'controlled_estimate',?,?)",(experiment["organization_id"],experiment["shop_id"],str(experiment_id),stable_json(payload),int(self.clock())))
        return payload
