from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Protocol

from shelfboost_phase4.core import Database, TenantService, stable_json

COMMERCIAL_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS billing_plans(code TEXT PRIMARY KEY, name TEXT NOT NULL, limits_json TEXT NOT NULL, features_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL UNIQUE REFERENCES app_shops(id) ON DELETE CASCADE, provider TEXT NOT NULL, provider_customer_id TEXT NOT NULL DEFAULT '', provider_subscription_id TEXT NOT NULL DEFAULT '', plan_code TEXT NOT NULL REFERENCES billing_plans(code), status TEXT NOT NULL CHECK(status IN ('trialing','active','past_due','cancelled','unpaid','expired')), current_period_start INTEGER NOT NULL DEFAULT 0, current_period_end INTEGER NOT NULL DEFAULT 0, grace_until INTEGER NOT NULL DEFAULT 0, event_effective_at INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS billing_events(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, event_id TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL, effective_at INTEGER NOT NULL, payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL, signature_verified INTEGER NOT NULL CHECK(signature_verified=1), received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, applied INTEGER NOT NULL DEFAULT 0, apply_note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS usage_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, metric TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0), period_start INTEGER NOT NULL, period_end INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK(status IN ('reserved','settled','released')), reference TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS consent_records(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, purpose TEXT NOT NULL, document_version TEXT NOT NULL, granted INTEGER NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS data_inventory(key TEXT PRIMARY KEY, category TEXT NOT NULL, purpose TEXT NOT NULL, retention_days INTEGER NOT NULL, deletion_behavior TEXT NOT NULL, contains_personal_data INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS compliance_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER REFERENCES app_shops(id) ON DELETE SET NULL, request_type TEXT NOT NULL CHECK(request_type IN ('access','export','delete','correct')), status TEXT NOT NULL CHECK(status IN ('requested','processing','completed','failed','blocked')), requested_by TEXT NOT NULL, response_json TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL, completed_at INTEGER, error_text TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS retention_records(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, last_required_at INTEGER NOT NULL, legal_hold INTEGER NOT NULL DEFAULT 0, purged_at INTEGER, UNIQUE(organization_id,resource_type,resource_id));
CREATE TABLE IF NOT EXISTS scope_justifications(scope TEXT PRIMARY KEY, feature TEXT NOT NULL, reason TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS app_review_checks(key TEXT PRIMARY KEY, category TEXT NOT NULL CHECK(category IN ('code','owner','provider','legal')), description TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','passed','blocked','not_applicable')), evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_usage_period ON usage_ledger(organization_id,shop_id,metric,period_start,period_end,status);
CREATE INDEX IF NOT EXISTS idx_compliance_status ON compliance_requests(status,created_at,id);
"""

STATUSES={"trialing","active","past_due","cancelled","unpaid","expired"}
ALWAYS_AVAILABLE={"read","export","privacy_request"}
METRIC_BY_OPERATION={"generate":"generations","publish":"publishes","add_team_member":"team_members","add_catalog_product":"catalog_products"}


def initialize_commercial(db: Database) -> None:
    db.migrate()
    with db.connect() as c:
        c.executescript(COMMERCIAL_SCHEMA); c.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (7)")


class BillingProvider(Protocol):
    name: str
    def verify_and_decode(self, raw_body: bytes, signature: str) -> dict[str,Any]: ...


@dataclass
class BillingService:
    db: Database
    provider: BillingProvider

    def seed_plan(self, code: str, name: str, limits: dict[str,int], features: list[str]) -> None:
        if any(int(value)<0 for value in limits.values()): raise ValueError("Plan limits cannot be negative")
        with self.db.connect() as c:
            c.execute("INSERT INTO billing_plans(code,name,limits_json,features_json) VALUES (?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,limits_json=excluded.limits_json,features_json=excluded.features_json,active=1",(code,name,stable_json(limits),stable_json(sorted(set(features)))))

    def ingest(self, raw_body: bytes, signature: str) -> dict[str,Any]:
        payload=self.provider.verify_and_decode(raw_body,signature)
        event_id=str(payload.get("id") or ""); event_type=str(payload.get("type") or ""); effective=int(payload.get("created") or 0)
        if not event_id or not event_type or effective<=0: raise ValueError("Invalid billing event envelope")
        import hashlib
        digest=hashlib.sha256(raw_body).hexdigest()
        with self.db.connect() as c:
            try:
                cursor=c.execute("INSERT INTO billing_events(provider,event_id,event_type,effective_at,payload_sha256,payload_json,signature_verified) VALUES (?,?,?,?,?,?,1)",(self.provider.name,event_id,event_type,effective,digest,stable_json(payload)))
            except sqlite3.IntegrityError:
                return {"event_id":event_id,"duplicate":True,"applied":False}
            event_row_id=int(cursor.lastrowid)
            data=payload.get("data") or {}; obj=data.get("object") if isinstance(data,dict) else None
            if not isinstance(obj,dict):
                c.execute("UPDATE billing_events SET apply_note='no_subscription_object' WHERE id=?",(event_row_id,)); return {"event_id":event_id,"duplicate":False,"applied":False}
            shop_id=int(obj.get("metadata",{}).get("shop_id") or 0); org=int(obj.get("metadata",{}).get("organization_id") or 0)
            status=str(obj.get("status") or "").replace("canceled","cancelled")
            plan=str(obj.get("metadata",{}).get("plan_code") or "")
            if not shop_id or not org or status not in STATUSES or not plan:
                c.execute("UPDATE billing_events SET apply_note='unsupported_or_incomplete_subscription' WHERE id=?",(event_row_id,)); return {"event_id":event_id,"duplicate":False,"applied":False}
            shop=c.execute("SELECT organization_id FROM app_shops WHERE id=?",(shop_id,)).fetchone()
            if not shop or int(shop["organization_id"])!=org: raise PermissionError("Billing event tenant mismatch")
            if not c.execute("SELECT 1 FROM billing_plans WHERE code=? AND active=1",(plan,)).fetchone(): raise ValueError("Unknown billing plan")
            current=c.execute("SELECT event_effective_at FROM subscriptions WHERE shop_id=?",(shop_id,)).fetchone()
            if current and int(current["event_effective_at"])>effective:
                c.execute("UPDATE billing_events SET apply_note='stale_event_ignored' WHERE id=?",(event_row_id,)); return {"event_id":event_id,"duplicate":False,"applied":False,"stale":True}
            period_start=int(obj.get("current_period_start") or 0); period_end=int(obj.get("current_period_end") or 0); grace=int(obj.get("metadata",{}).get("grace_until") or 0)
            c.execute("""INSERT INTO subscriptions(organization_id,shop_id,provider,provider_customer_id,provider_subscription_id,plan_code,status,current_period_start,current_period_end,grace_until,event_effective_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(shop_id) DO UPDATE SET provider=excluded.provider,provider_customer_id=excluded.provider_customer_id,provider_subscription_id=excluded.provider_subscription_id,plan_code=excluded.plan_code,status=excluded.status,current_period_start=excluded.current_period_start,current_period_end=excluded.current_period_end,grace_until=excluded.grace_until,event_effective_at=excluded.event_effective_at,updated_at=CURRENT_TIMESTAMP""",(org,shop_id,self.provider.name,str(obj.get("customer") or ""),str(obj.get("id") or ""),plan,status,period_start,period_end,grace,effective))
            c.execute("UPDATE billing_events SET applied=1,apply_note='subscription_state_applied' WHERE id=?",(event_row_id,))
        return {"event_id":event_id,"duplicate":False,"applied":True,"shop_id":shop_id,"status":status}


@dataclass
class EntitlementService:
    db: Database
    tenants: TenantService
    clock: Any=time.time

    def _context(self, shop_id: int, user_id: int | None=None) -> tuple[dict[str,Any],dict[str,Any],dict[str,int],set[str]]:
        with self.db.connect() as c:
            shop=c.execute("SELECT * FROM app_shops WHERE id=?",(shop_id,)).fetchone()
            if not shop: raise LookupError(shop_id)
            if user_id is not None: self.tenants.shop_for_user(shop_id,user_id)
            subscription=c.execute("SELECT * FROM subscriptions WHERE shop_id=?",(shop_id,)).fetchone()
            if not subscription: raise PermissionError("No verified subscription")
            plan=c.execute("SELECT * FROM billing_plans WHERE code=? AND active=1",(subscription["plan_code"],)).fetchone()
            if not plan: raise PermissionError("Subscription plan unavailable")
        return dict(shop),dict(subscription),{key:int(value) for key,value in json.loads(plan["limits_json"]).items()},set(json.loads(plan["features_json"]))

    def allowed(self, shop_id: int, operation: str, user_id: int | None=None) -> dict[str,Any]:
        if operation in ALWAYS_AVAILABLE:
            if user_id is not None: self.tenants.shop_for_user(shop_id,user_id)
            return {"allowed":True,"reason":"always_available"}
        shop,sub,limits,features=self._context(shop_id,user_id); now=int(self.clock())
        status=sub["status"]; paid=status in {"trialing","active"} or (status=="past_due" and now<=int(sub["grace_until"]))
        if not paid: return {"allowed":False,"reason":f"subscription_{status}"}
        if operation not in features and operation not in METRIC_BY_OPERATION: return {"allowed":False,"reason":"feature_not_in_plan"}
        metric=METRIC_BY_OPERATION.get(operation)
        return {"allowed":True,"reason":"entitled","metric":metric,"limit":limits.get(metric,-1),"period_start":int(sub["current_period_start"]),"period_end":int(sub["current_period_end"]),"organization_id":int(shop["organization_id"])}

    def reserve(self, shop_id: int, operation: str, quantity: int, idempotency_key: str, *, user_id: int | None=None, reference: str="") -> dict[str,Any]:
        if quantity<=0 or not idempotency_key.strip(): raise ValueError("Positive quantity and idempotency key required")
        entitlement=self.allowed(shop_id,operation,user_id)
        if not entitlement["allowed"]: raise PermissionError(entitlement["reason"])
        metric=entitlement.get("metric")
        if not metric: return {"reserved":False,"reason":"unmetered"}
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            existing=c.execute("SELECT * FROM usage_ledger WHERE idempotency_key=?",(idempotency_key,)).fetchone()
            if existing: return {"reserved":existing["status"] in {"reserved","settled"},"reused":True,"usage_id":int(existing["id"])}
            used=int(c.execute("SELECT COALESCE(SUM(quantity),0) FROM usage_ledger WHERE organization_id=? AND shop_id=? AND metric=? AND period_start=? AND period_end=? AND status IN ('reserved','settled')",(entitlement["organization_id"],shop_id,metric,entitlement["period_start"],entitlement["period_end"])).fetchone()[0])
            limit=int(entitlement["limit"])
            if limit>=0 and used+quantity>limit: raise PermissionError(f"{metric}_limit_exceeded")
            cursor=c.execute("INSERT INTO usage_ledger(organization_id,shop_id,metric,quantity,period_start,period_end,idempotency_key,status,reference) VALUES (?,?,?,?,?,?,?,'reserved',?)",(entitlement["organization_id"],shop_id,metric,quantity,entitlement["period_start"],entitlement["period_end"],idempotency_key,reference))
        return {"reserved":True,"reused":False,"usage_id":int(cursor.lastrowid),"remaining":None if limit<0 else limit-used-quantity}

    def settle(self, usage_id: int) -> None:
        with self.db.connect() as c: c.execute("UPDATE usage_ledger SET status='settled',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='reserved'",(usage_id,))
    def release(self, usage_id: int) -> None:
        with self.db.connect() as c: c.execute("UPDATE usage_ledger SET status='released',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='reserved'",(usage_id,))


@dataclass
class ComplianceService:
    db: Database
    tenants: TenantService
    clock: Any=time.time

    def record_consent(self, organization_id: int, user_id: int, purpose: str, version: str, granted: bool, source: str) -> int:
        self.tenants.require_role(organization_id,user_id,{"owner","admin","editor","viewer"})
        with self.db.connect() as c: return int(c.execute("INSERT INTO consent_records(organization_id,user_id,purpose,document_version,granted,source) VALUES (?,?,?,?,?,?)",(organization_id,user_id,purpose,version,int(granted),source)).lastrowid)

    def inventory(self, key: str, category: str, purpose: str, retention_days: int, deletion_behavior: str, personal: bool=False) -> None:
        if retention_days<0: raise ValueError("Retention cannot be negative")
        with self.db.connect() as c: c.execute("INSERT INTO data_inventory(key,category,purpose,retention_days,deletion_behavior,contains_personal_data) VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET category=excluded.category,purpose=excluded.purpose,retention_days=excluded.retention_days,deletion_behavior=excluded.deletion_behavior,contains_personal_data=excluded.contains_personal_data",(key,category,purpose,retention_days,deletion_behavior,int(personal)))

    def request(self, organization_id: int, request_type: str, requested_by: str, shop_id: int|None=None) -> int:
        if request_type not in {"access","export","delete","correct"}: raise ValueError("Unsupported compliance request")
        if shop_id is not None:
            with self.db.connect() as c:
                row=c.execute("SELECT organization_id FROM app_shops WHERE id=?",(shop_id,)).fetchone()
                if not row or int(row["organization_id"])!=organization_id: raise PermissionError("Compliance request tenant mismatch")
        with self.db.connect() as c: return int(c.execute("INSERT INTO compliance_requests(organization_id,shop_id,request_type,status,requested_by,created_at) VALUES (?,?,?,'requested',?,?)",(organization_id,shop_id,request_type,requested_by,int(self.clock()))).lastrowid)

    def export(self, request_id: int) -> dict[str,Any]:
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM compliance_requests WHERE id=?",(request_id,)).fetchone()
            if not row: raise LookupError(request_id)
            org=int(row["organization_id"]); shop=row["shop_id"]
            shops=[dict(item) for item in c.execute("SELECT id,domain,active,installed_at,uninstalled_at FROM app_shops WHERE organization_id=? AND (? IS NULL OR id=?)",(org,shop,shop))]
            consents=[dict(item) for item in c.execute("SELECT purpose,document_version,granted,source,created_at FROM consent_records WHERE organization_id=?",(org,))]
            subscriptions=[dict(item) for item in c.execute("SELECT plan_code,status,current_period_start,current_period_end FROM subscriptions WHERE organization_id=?",(org,))]
            payload={"organization_id":org,"shops":shops,"consents":consents,"subscriptions":subscriptions}
            c.execute("UPDATE compliance_requests SET status='completed',response_json=?,completed_at=? WHERE id=?",(stable_json(payload),int(self.clock()),request_id))
        return payload

    def mark_retention(self, organization_id: int, resource_type: str, resource_id: str, last_required_at: int, legal_hold: bool=False) -> None:
        with self.db.connect() as c: c.execute("INSERT INTO retention_records(organization_id,resource_type,resource_id,last_required_at,legal_hold) VALUES (?,?,?,?,?) ON CONFLICT(organization_id,resource_type,resource_id) DO UPDATE SET last_required_at=excluded.last_required_at,legal_hold=excluded.legal_hold",(organization_id,resource_type,resource_id,last_required_at,int(legal_hold)))
    def purge_eligible(self, before: int) -> list[dict[str,Any]]:
        with self.db.connect() as c: return [dict(row) for row in c.execute("SELECT * FROM retention_records WHERE purged_at IS NULL AND legal_hold=0 AND last_required_at<=? ORDER BY id",(before,))]

    def justify_scope(self, scope: str, feature: str, reason: str, approved: bool=False) -> None:
        if not reason.strip(): raise ValueError("Scope reason required")
        with self.db.connect() as c: c.execute("INSERT INTO scope_justifications(scope,feature,reason,approved) VALUES (?,?,?,?) ON CONFLICT(scope) DO UPDATE SET feature=excluded.feature,reason=excluded.reason,approved=excluded.approved,reviewed_at=CURRENT_TIMESTAMP",(scope,feature,reason,int(approved)))
    def set_review_check(self, key: str, category: str, description: str, status: str, evidence: str="") -> None:
        with self.db.connect() as c: c.execute("INSERT INTO app_review_checks(key,category,description,status,evidence) VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET category=excluded.category,description=excluded.description,status=excluded.status,evidence=excluded.evidence,updated_at=CURRENT_TIMESTAMP",(key,category,description,status,evidence))
    def readiness(self, required_scopes: list[str], required_checks: list[str]) -> dict[str,Any]:
        with self.db.connect() as c:
            scopes={row["scope"]:dict(row) for row in c.execute("SELECT * FROM scope_justifications")}; checks={row["key"]:dict(row) for row in c.execute("SELECT * FROM app_review_checks")}
        blockers=[]
        for scope in required_scopes:
            if scope not in scopes or int(scopes[scope]["approved"])!=1: blockers.append(f"scope_unapproved:{scope}")
        for key in required_checks:
            if key not in checks or checks[key]["status"]!="passed": blockers.append(f"check_incomplete:{key}")
        return {"ready":not blockers,"blockers":blockers,"scopes":scopes,"checks":checks}
