from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Any

from shelfboost_phase4.core import Database, TenantService, stable_json

EXPERIENCE_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS merchant_onboarding(organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, state TEXT NOT NULL CHECK(state IN ('installed','syncing','audit_ready','brand_ready','pilot_ready','active','error')), error_text TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(organization_id,shop_id));
CREATE TABLE IF NOT EXISTS merchant_products(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, handle TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, priority_score INTEGER NOT NULL, health_score INTEGER NOT NULL, facts_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(shop_id,handle));
CREATE TABLE IF NOT EXISTS merchant_findings(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES merchant_products(id) ON DELETE CASCADE, code TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('critical','high','medium','low')), label TEXT NOT NULL, evidence TEXT NOT NULL, source_type TEXT NOT NULL CHECK(source_type IN ('deterministic','model')), UNIQUE(product_id,code));
CREATE TABLE IF NOT EXISTS brand_profile_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, version INTEGER NOT NULL, profile_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(shop_id,version));
CREATE TABLE IF NOT EXISTS merchant_review_batches(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, name TEXT NOT NULL, risk TEXT NOT NULL CHECK(risk IN ('normal','high')), requires_two_person INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL CHECK(status IN ('draft','reviewing','ready_to_publish','published','cancelled')), created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS merchant_review_fields(id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES merchant_review_batches(id) ON DELETE CASCADE, product_id INTEGER NOT NULL REFERENCES merchant_products(id), field_name TEXT NOT NULL, original_value TEXT NOT NULL, proposed_value TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]', decision TEXT NOT NULL CHECK(decision IN ('pending','approved','edited','rejected','deferred')), edited_value TEXT NOT NULL DEFAULT '', reviewer_note TEXT NOT NULL DEFAULT '', reviewed_by INTEGER REFERENCES users(id), reviewed_at TEXT, UNIQUE(batch_id,product_id,field_name));
CREATE TABLE IF NOT EXISTS merchant_publish_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL UNIQUE REFERENCES merchant_review_batches(id) ON DELETE CASCADE, requested_by INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL CHECK(status IN ('ready','submitted','completed','failed','cancelled')), payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS merchant_activity(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, subject_type TEXT NOT NULL, subject_id INTEGER, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_merchant_products_queue ON merchant_products(shop_id,priority_score DESC,id);
CREATE INDEX IF NOT EXISTS idx_review_fields_batch_decision ON merchant_review_fields(batch_id,decision,id);
"""

STATE_TRANSITIONS = {
    "installed": {"syncing", "error"},
    "syncing": {"audit_ready", "error"},
    "audit_ready": {"brand_ready", "error"},
    "brand_ready": {"pilot_ready", "error"},
    "pilot_ready": {"active", "error"},
    "active": {"syncing", "error"},
    "error": {"syncing", "audit_ready"},
}


def initialize_experience(db: Database) -> None:
    db.migrate()
    with db.connect() as connection:
        connection.executescript(EXPERIENCE_SCHEMA)
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (5)")


@dataclass
class MerchantExperience:
    db: Database
    tenants: TenantService

    def _shop(self, shop_id: int, user_id: int) -> dict[str, Any]:
        return self.tenants.shop_for_user(shop_id, user_id)

    def _role(self, organization_id: int, user_id: int, allowed: set[str]) -> str:
        return self.tenants.require_role(organization_id, user_id, allowed)

    def _activity(self, organization_id: int, shop_id: int, user_id: int | None, action: str, subject_type: str, subject_id: int | None, details: dict[str, Any] | None = None) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO merchant_activity(organization_id,shop_id,user_id,action,subject_type,subject_id,details_json) VALUES (?,?,?,?,?,?,?)",
                (organization_id, shop_id, user_id, action, subject_type, subject_id, stable_json(details or {})),
            )

    def set_onboarding(self, shop_id: int, user_id: int, state: str, error: str = "") -> dict[str, str]:
        shop = self._shop(shop_id, user_id); org = int(shop["organization_id"])
        self._role(org, user_id, {"owner", "admin"})
        with self.db.connect() as connection:
            current = connection.execute("SELECT state FROM merchant_onboarding WHERE organization_id=? AND shop_id=?", (org, shop_id)).fetchone()
            if current is None:
                if state not in {"installed", "syncing"}: raise ValueError("Onboarding must start at installed or syncing")
                connection.execute("INSERT INTO merchant_onboarding(organization_id,shop_id,state,error_text) VALUES (?,?,?,?)", (org,shop_id,state,error))
            else:
                previous = str(current["state"])
                if state != previous and state not in STATE_TRANSITIONS[previous]: raise ValueError(f"Invalid onboarding transition: {previous} -> {state}")
                connection.execute("UPDATE merchant_onboarding SET state=?,error_text=?,updated_at=CURRENT_TIMESTAMP WHERE organization_id=? AND shop_id=?", (state,error,org,shop_id))
        self._activity(org,shop_id,user_id,"onboarding.state","shop",shop_id,{"state":state,"error":error})
        return {"state":state,"error":error}

    def upsert_product(self, shop_id: int, user_id: int, product: dict[str, Any], findings: list[dict[str, str]]) -> int:
        shop=self._shop(shop_id,user_id); org=int(shop["organization_id"]); self._role(org,user_id,{"owner","admin","editor"})
        handle=str(product.get("handle") or "").strip(); title=str(product.get("title") or "").strip()
        if not handle or not title: raise ValueError("Product handle and title are required")
        with self.db.connect() as c:
            c.execute("""INSERT INTO merchant_products(organization_id,shop_id,handle,title,status,priority_score,health_score,facts_json) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(shop_id,handle) DO UPDATE SET title=excluded.title,status=excluded.status,priority_score=excluded.priority_score,health_score=excluded.health_score,facts_json=excluded.facts_json,updated_at=CURRENT_TIMESTAMP""",(org,shop_id,handle,title,str(product.get("status") or "active"),int(product.get("priority_score",0)),int(product.get("health_score",100)),stable_json(product.get("facts") or {})))
            product_id=int(c.execute("SELECT id FROM merchant_products WHERE shop_id=? AND handle=?",(shop_id,handle)).fetchone()["id"])
            c.execute("DELETE FROM merchant_findings WHERE product_id=?",(product_id,))
            for finding in findings:
                source=str(finding.get("source_type") or "deterministic")
                if source not in {"deterministic","model"}: raise ValueError("Invalid finding source")
                c.execute("INSERT INTO merchant_findings(product_id,code,severity,label,evidence,source_type) VALUES (?,?,?,?,?,?)",(product_id,finding["code"],finding["severity"],finding["label"],finding.get("evidence","") ,source))
        return product_id

    def dashboard(self, shop_id: int, user_id: int, *, query: str="", severity: str="", source_type: str="", page: int=1, page_size: int=25, sort: str="priority") -> dict[str, Any]:
        shop=self._shop(shop_id,user_id); org=int(shop["organization_id"])
        page_size=max(1,min(page_size,100)); page=max(1,page); order="p.priority_score DESC,p.id" if sort=="priority" else "p.title COLLATE NOCASE,p.id"
        where=["p.organization_id=?","p.shop_id=?"]; args:[Any]=[org,shop_id]
        if query: where.append("(p.title LIKE ? OR p.handle LIKE ?)"); args.extend([f"%{query}%",f"%{query}%"])
        if severity: where.append("EXISTS(SELECT 1 FROM merchant_findings f WHERE f.product_id=p.id AND f.severity=?)"); args.append(severity)
        if source_type: where.append("EXISTS(SELECT 1 FROM merchant_findings f WHERE f.product_id=p.id AND f.source_type=?)"); args.append(source_type)
        clause=" AND ".join(where)
        with self.db.connect() as c:
            total=int(c.execute(f"SELECT COUNT(*) FROM merchant_products p WHERE {clause}",args).fetchone()[0])
            rows=[dict(r) for r in c.execute(f"SELECT p.* FROM merchant_products p WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",(*args,page_size,(page-1)*page_size))]
            for row in rows:
                row["facts"]=json.loads(row.pop("facts_json")); row["findings"]=[dict(f) for f in c.execute("SELECT code,severity,label,evidence,source_type FROM merchant_findings WHERE product_id=? ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,id",(row["id"],))]
            summary={r["severity"]:int(r["count"]) for r in c.execute("SELECT f.severity,COUNT(*) count FROM merchant_findings f JOIN merchant_products p ON p.id=f.product_id WHERE p.organization_id=? AND p.shop_id=? GROUP BY f.severity",(org,shop_id))}
        return {"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size,"summary":summary,"products":rows}

    def create_brand_version(self, shop_id: int, user_id: int, profile: dict[str, Any], activate: bool=True) -> int:
        shop=self._shop(shop_id,user_id); org=int(shop["organization_id"]); self._role(org,user_id,{"owner","admin","editor"})
        required={"tone","audience","prohibited_terms","claims_policy"}
        if not required.issubset(profile): raise ValueError("Brand profile is incomplete")
        with self.db.connect() as c:
            version=int(c.execute("SELECT COALESCE(MAX(version),0)+1 FROM brand_profile_versions WHERE shop_id=?",(shop_id,)).fetchone()[0])
            if activate: c.execute("UPDATE brand_profile_versions SET active=0 WHERE shop_id=?",(shop_id,))
            cursor=c.execute("INSERT INTO brand_profile_versions(organization_id,shop_id,version,profile_json,active,created_by) VALUES (?,?,?,?,?,?)",(org,shop_id,version,stable_json(profile),int(activate),user_id))
        self._activity(org,shop_id,user_id,"brand.version","brand_profile",int(cursor.lastrowid),{"version":version,"active":activate})
        return int(cursor.lastrowid)

    def active_brand(self, shop_id: int, user_id: int) -> dict[str, Any] | None:
        self._shop(shop_id,user_id)
        with self.db.connect() as c: row=c.execute("SELECT * FROM brand_profile_versions WHERE shop_id=? AND active=1 ORDER BY version DESC LIMIT 1",(shop_id,)).fetchone()
        if not row: return None
        result=dict(row); result["profile"]=json.loads(result.pop("profile_json")); return result

    def create_review_batch(self, shop_id: int, user_id: int, name: str, items: list[dict[str, Any]], *, risk: str="normal", requires_two_person: bool=False) -> int:
        shop=self._shop(shop_id,user_id); org=int(shop["organization_id"]); self._role(org,user_id,{"owner","admin","editor"})
        if not 1 <= len(items) <= 25: raise ValueError("Review batches must contain 1 to 25 product fields")
        if risk not in {"normal","high"}: raise ValueError("Invalid risk")
        with self.db.connect() as c:
            batch=int(c.execute("INSERT INTO merchant_review_batches(organization_id,shop_id,name,risk,requires_two_person,status,created_by) VALUES (?,?,?,?,?,'reviewing',?)",(org,shop_id,name,risk,int(requires_two_person or risk=="high"),user_id)).lastrowid)
            for item in items:
                product=c.execute("SELECT id FROM merchant_products WHERE id=? AND organization_id=? AND shop_id=?",(int(item["product_id"]),org,shop_id)).fetchone()
                if not product: raise PermissionError("Product is outside tenant context")
                c.execute("INSERT INTO merchant_review_fields(batch_id,product_id,field_name,original_value,proposed_value,warnings_json,decision) VALUES (?,?,?,?,?,?,'pending')",(batch,int(item["product_id"]),item["field_name"],str(item.get("original","")),str(item.get("proposed","")),stable_json(item.get("warnings") or [])))
        self._activity(org,shop_id,user_id,"review.batch_created","review_batch",batch,{"count":len(items),"risk":risk})
        return batch

    def decide_field(self, field_id: int, user_id: int, decision: str, *, edited_value: str="", note: str="", acknowledge_warnings: bool=False) -> None:
        if decision not in {"approved","edited","rejected","deferred"}: raise ValueError("Invalid decision")
        with self.db.connect() as c:
            row=c.execute("""SELECT f.*,b.organization_id,b.shop_id FROM merchant_review_fields f JOIN merchant_review_batches b ON b.id=f.batch_id WHERE f.id=?""",(field_id,)).fetchone()
            if not row: raise LookupError(field_id)
            self._role(int(row["organization_id"]),user_id,{"owner","admin","editor"})
            warnings=json.loads(row["warnings_json"])
            if decision in {"approved","edited"} and warnings and not acknowledge_warnings: raise RuntimeError("Warnings must be acknowledged")
            if decision=="edited" and not edited_value: raise ValueError("Edited decision requires a value")
            c.execute("UPDATE merchant_review_fields SET decision=?,edited_value=?,reviewer_note=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(decision,edited_value,note,user_id,field_id))
        self._activity(int(row["organization_id"]),int(row["shop_id"]),user_id,"review.field_decided","review_field",field_id,{"decision":decision})

    def request_publish(self, batch_id: int, user_id: int) -> dict[str, Any]:
        with self.db.connect() as c:
            batch=c.execute("SELECT * FROM merchant_review_batches WHERE id=?",(batch_id,)).fetchone()
            if not batch: raise LookupError(batch_id)
            self._role(int(batch["organization_id"]),user_id,{"owner","admin"})
            fields=[dict(r) for r in c.execute("SELECT f.*,p.handle FROM merchant_review_fields f JOIN merchant_products p ON p.id=f.product_id WHERE f.batch_id=? ORDER BY f.id",(batch_id,))]
            if any(item["decision"]=="pending" for item in fields): raise RuntimeError("All fields must be decided")
            approved=[item for item in fields if item["decision"] in {"approved","edited"}]
            if not approved: raise RuntimeError("No approved fields")
            reviewers={int(item["reviewed_by"]) for item in approved if item["reviewed_by"] is not None}
            if int(batch["requires_two_person"]) and (not reviewers or reviewers=={user_id}): raise PermissionError("Two-person approval requires a different reviewer")
            payload={"batch_id":batch_id,"shop_id":int(batch["shop_id"]),"fields":[{"handle":item["handle"],"field":item["field_name"],"final":item["edited_value"] if item["decision"]=="edited" else item["proposed_value"],"reviewed_by":item["reviewed_by"]} for item in approved]}
            c.execute("INSERT INTO merchant_publish_requests(batch_id,requested_by,status,payload_json) VALUES (?,?,'ready',?)",(batch_id,user_id,stable_json(payload)))
            c.execute("UPDATE merchant_review_batches SET status='ready_to_publish' WHERE id=?",(batch_id,))
        self._activity(int(batch["organization_id"]),int(batch["shop_id"]),user_id,"publish.requested","review_batch",batch_id,{"field_count":len(approved)})
        return payload

    def activity(self, shop_id: int, user_id: int, limit: int=50) -> list[dict[str, Any]]:
        shop=self._shop(shop_id,user_id)
        with self.db.connect() as c: return [dict(r) for r in c.execute("SELECT * FROM merchant_activity WHERE organization_id=? AND shop_id=? ORDER BY id DESC LIMIT ?",(shop["organization_id"],shop_id,max(1,min(limit,200))))]


def render_dashboard(view: dict[str, Any]) -> str:
    rows=[]
    for product in view["products"]:
        findings="; ".join(f"{f['severity']}: {f['label']} ({f['source_type']})" for f in product["findings"]) or "No findings"
        rows.append(f"<tr><th scope='row'>{html.escape(product['title'])}</th><td>{html.escape(product['handle'])}</td><td>{product['health_score']}</td><td>{product['priority_score']}</td><td>{html.escape(findings)}</td></tr>")
    summary=", ".join(f"{key}: {value}" for key,value in sorted(view["summary"].items())) or "No findings"
    return "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Catalog health</title></head><body><main><h1>Catalog health</h1><p aria-live='polite'>"+html.escape(summary)+"</p><table><caption>Products, health, priority, and finding source</caption><thead><tr><th>Product</th><th>Handle</th><th>Health</th><th>Priority</th><th>Findings</th></tr></thead><tbody>"+"".join(rows)+"</tbody></table></main></body></html>"


def render_review(fields: list[dict[str, Any]]) -> str:
    sections=[]
    for field in fields:
        warnings=json.loads(field.get("warnings_json") or "[]")
        warning_text="; ".join(str(item) for item in warnings) or "None"
        sections.append(f"<section aria-labelledby='field-{field['id']}'><h2 id='field-{field['id']}'>{html.escape(field['field_name'])}</h2><h3>Original</h3><pre>{html.escape(field['original_value'])}</pre><h3>Proposed</h3><pre>{html.escape(field['proposed_value'])}</pre><p><strong>Warnings:</strong> {html.escape(warning_text)}</p><label for='decision-{field['id']}'>Decision</label><select id='decision-{field['id']}' name='decision'><option>Approve</option><option>Edit</option><option>Reject</option><option>Defer</option></select></section>")
    return "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Review changes</title></head><body><main><h1>Review changes</h1>"+"".join(sections)+"</main></body></html>"
