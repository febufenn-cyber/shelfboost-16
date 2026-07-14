from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from shelfboost_phase4.core import Database, TenantService, stable_json

AI_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ai_prompt_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, name TEXT NOT NULL, version INTEGER NOT NULL, template TEXT NOT NULL, template_sha256 TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(shop_id,name,version));
CREATE TABLE IF NOT EXISTS ai_generation_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, prompt_version_id INTEGER NOT NULL REFERENCES ai_prompt_versions(id), status TEXT NOT NULL CHECK(status IN ('queued','running','completed','partial','failed')), budget_micros INTEGER NOT NULL, spent_micros INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ai_generation_items(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL REFERENCES ai_generation_jobs(id) ON DELETE CASCADE, product_key TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','passed','blocked','failed','duplicate')), request_json TEXT NOT NULL, response_json TEXT NOT NULL DEFAULT '{}', validation_json TEXT NOT NULL DEFAULT '{}', cost_micros INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, output_fingerprint TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(job_id,product_key));
CREATE TABLE IF NOT EXISTS ai_usage(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, job_id INTEGER NOT NULL REFERENCES ai_generation_jobs(id) ON DELETE CASCADE, item_id INTEGER NOT NULL REFERENCES ai_generation_items(id) ON DELETE CASCADE, model TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_micros INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ai_evaluation_cases(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, input_json TEXT NOT NULL, expected_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS ai_evaluation_results(id INTEGER PRIMARY KEY AUTOINCREMENT, prompt_version_id INTEGER NOT NULL REFERENCES ai_prompt_versions(id), case_id INTEGER NOT NULL REFERENCES ai_evaluation_cases(id), passed INTEGER NOT NULL, score REAL NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ai_feedback_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, scope TEXT NOT NULL CHECK(scope IN ('product','category','brand')), pattern TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('proposed','confirmed','rejected')), evidence_count INTEGER NOT NULL DEFAULT 1, created_by INTEGER NOT NULL REFERENCES users(id), confirmed_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(shop_id,scope,pattern));
CREATE INDEX IF NOT EXISTS idx_ai_items_job_status ON ai_generation_items(job_id,status,id);
"""

ALLOWED_FIELDS={"description_html","seo_title","seo_description"}
RISKY_RE=re.compile(r"\b(cure[sd]?|clinically proven|guaranteed results?|100% safe|medical grade|certified organic|eco[- ]?friendly|non[- ]?toxic)\b",re.I)


def initialize_ai(db: Database) -> None:
    db.migrate()
    with db.connect() as c:
        c.executescript(AI_SCHEMA); c.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (6)")


@dataclass(frozen=True)
class ProviderResult:
    output: dict[str,Any]
    input_tokens: int
    output_tokens: int
    raw: dict[str,Any]


class ModelProvider(Protocol):
    def generate(self, model: str, prompt: str, payload: dict[str,Any]) -> ProviderResult: ...


@dataclass(frozen=True)
class ModelSpec:
    name: str
    input_micros_per_million: int
    output_micros_per_million: int


class ModelRouter:
    def __init__(self, cheap: ModelSpec, strong: ModelSpec): self.cheap,self.strong=cheap,strong
    def choose(self, request: dict[str,Any]) -> ModelSpec:
        risk=str(request.get("risk") or "normal"); complexity=int(request.get("complexity",1)); missing=len(request.get("missing_facts") or [])
        return self.strong if risk=="high" or complexity>=4 or missing else self.cheap
    @staticmethod
    def cost(spec: ModelSpec, input_tokens: int, output_tokens: int) -> int:
        return (input_tokens*spec.input_micros_per_million + output_tokens*spec.output_micros_per_million)//1_000_000


class ValidationError(RuntimeError): pass


def _plain(value: str) -> str:
    return re.sub(r"<[^>]+>"," ",value).strip()


def validate_output(request: dict[str,Any], output: dict[str,Any]) -> dict[str,Any]:
    errors:list[str]=[]; warnings:list[str]=[]
    if not isinstance(output,dict): raise ValidationError("Provider output must be an object")
    fields=output.get("fields")
    if not isinstance(fields,dict) or not fields: errors.append("fields_missing")
    approved={str(k):str(v) for k,v in (request.get("approved_facts") or {}).items()}
    prohibited={str(item).lower() for item in request.get("prohibited_terms") or []}
    required={str(item) for item in request.get("required_facts") or []}
    abstentions={str(item) for item in output.get("abstentions") or []}
    for fact in sorted(required):
        if not approved.get(fact) and fact not in abstentions: errors.append(f"missing_required_fact_without_abstention:{fact}")
    seen_fact_values={value.lower() for value in approved.values() if value}
    if isinstance(fields,dict):
        for name,record in fields.items():
            if name not in ALLOWED_FIELDS: errors.append(f"unsupported_field:{name}"); continue
            if not isinstance(record,dict): errors.append(f"invalid_field_record:{name}"); continue
            value=str(record.get("value") or "").strip(); facts_used=record.get("facts_used") or []
            if not value: errors.append(f"empty_field:{name}")
            if not isinstance(facts_used,list): errors.append(f"facts_used_not_list:{name}"); facts_used=[]
            for fact_key in facts_used:
                if str(fact_key) not in approved: errors.append(f"unapproved_fact:{name}:{fact_key}")
            lower=_plain(value).lower()
            for term in prohibited:
                if term and term in lower: errors.append(f"prohibited_term:{name}:{term}")
            if RISKY_RE.search(lower): errors.append(f"risky_claim:{name}")
            if name=="seo_title" and len(value)>60: errors.append("seo_title_too_long")
            if name=="seo_description" and len(value)>160: errors.append("seo_description_too_long")
            for token in re.findall(r"\b\d+(?:\.\d+)?%?\b",lower):
                if token not in seen_fact_values and not any(token in val for val in seen_fact_values): warnings.append(f"numeric_claim_review:{name}:{token}")
    status="blocked" if errors else "pass"
    return {"status":status,"errors":sorted(set(errors)),"warnings":sorted(set(warnings)),"abstentions":sorted(abstentions)}


def output_fingerprint(output: dict[str,Any]) -> str:
    fields=output.get("fields") or {}; normalized={key:re.sub(r"\s+"," ",_plain(str(value.get("value") or "")).lower()) for key,value in fields.items() if isinstance(value,dict)}
    return hashlib.sha256(stable_json(normalized).encode()).hexdigest()


@dataclass
class AIService:
    db: Database
    tenants: TenantService
    router: ModelRouter
    provider: ModelProvider

    def create_prompt(self, shop_id: int, user_id: int, name: str, template: str, activate: bool=True) -> int:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin","editor"})
        if "{{approved_facts}}" not in template or "{{brand_profile}}" not in template: raise ValueError("Prompt template must expose governed inputs")
        digest=hashlib.sha256(template.encode()).hexdigest()
        with self.db.connect() as c:
            version=int(c.execute("SELECT COALESCE(MAX(version),0)+1 FROM ai_prompt_versions WHERE shop_id=? AND name=?",(shop_id,name)).fetchone()[0])
            if activate: c.execute("UPDATE ai_prompt_versions SET active=0 WHERE shop_id=? AND name=?",(shop_id,name))
            return int(c.execute("INSERT INTO ai_prompt_versions(organization_id,shop_id,name,version,template,template_sha256,active,created_by) VALUES (?,?,?,?,?,?,?,?)",(org,shop_id,name,version,template,digest,int(activate),user_id)).lastrowid)

    def create_job(self, shop_id: int, user_id: int, prompt_id: int, budget_micros: int) -> int:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin","editor"})
        if budget_micros<=0: raise ValueError("Budget must be positive")
        with self.db.connect() as c:
            prompt=c.execute("SELECT id FROM ai_prompt_versions WHERE id=? AND organization_id=? AND shop_id=? AND active=1",(prompt_id,org,shop_id)).fetchone()
            if not prompt: raise PermissionError("Prompt is not active in tenant context")
            return int(c.execute("INSERT INTO ai_generation_jobs(organization_id,shop_id,prompt_version_id,status,budget_micros,created_by) VALUES (?,?,?,'running',?,?)",(org,shop_id,prompt_id,budget_micros,user_id)).lastrowid)

    def generate(self, job_id: int, product_key: str, request: dict[str,Any], *, max_attempts: int=2) -> dict[str,Any]:
        with self.db.connect() as c:
            job=c.execute("SELECT j.*,p.template,p.template_sha256,p.version FROM ai_generation_jobs j JOIN ai_prompt_versions p ON p.id=j.prompt_version_id WHERE j.id=?",(job_id,)).fetchone()
            if not job: raise LookupError(job_id)
            existing=c.execute("SELECT * FROM ai_generation_items WHERE job_id=? AND product_key=?",(job_id,product_key)).fetchone()
            if existing: return dict(existing)
        spec=self.router.choose(request); estimated=self.router.cost(spec,int(request.get("estimated_input_tokens",1000)),int(request.get("estimated_output_tokens",500)))
        if int(job["spent_micros"])+estimated>int(job["budget_micros"]): raise RuntimeError("Tenant AI budget exceeded")
        with self.db.connect() as c:
            item_id=int(c.execute("INSERT INTO ai_generation_items(job_id,product_key,model,status,request_json) VALUES (?,?,?,'pending',?)",(job_id,product_key,spec.name,stable_json(request))).lastrowid)
        last_error=""; result:ProviderResult|None=None; validation:dict[str,Any]={}
        for attempt in range(1,max_attempts+1):
            try:
                result=self.provider.generate(spec.name,str(job["template"]),request)
                validation=validate_output(request,result.output)
                last_error=""; break
            except (ValidationError,ValueError,TypeError,KeyError) as exc: last_error=str(exc)
            except Exception as exc: last_error=f"provider_error:{exc}"; break
        if result is None:
            with self.db.connect() as c: c.execute("UPDATE ai_generation_items SET status='failed',attempts=?,validation_json=? WHERE id=?",(max_attempts,stable_json({"status":"failed","errors":[last_error]}),item_id))
            return {"item_id":item_id,"status":"failed","error":last_error}
        cost=self.router.cost(spec,result.input_tokens,result.output_tokens); fingerprint=output_fingerprint(result.output)
        with self.db.connect() as c:
            duplicate=c.execute("SELECT id FROM ai_generation_items WHERE job_id=? AND output_fingerprint=? AND id<>? AND status='passed'",(job_id,fingerprint,item_id)).fetchone()
            status="duplicate" if duplicate else ("blocked" if validation["status"]=="blocked" else "passed")
            if int(job["spent_micros"])+cost>int(job["budget_micros"]): status="blocked"; validation["errors"].append("actual_cost_exceeded_budget")
            c.execute("UPDATE ai_generation_items SET status=?,response_json=?,validation_json=?,cost_micros=?,attempts=?,output_fingerprint=? WHERE id=?",(status,stable_json({"output":result.output,"raw":result.raw}),stable_json(validation),cost,attempt,fingerprint,item_id))
            c.execute("INSERT INTO ai_usage(organization_id,shop_id,job_id,item_id,model,input_tokens,output_tokens,cost_micros) VALUES (?,?,?,?,?,?,?,?)",(job["organization_id"],job["shop_id"],job_id,item_id,spec.name,result.input_tokens,result.output_tokens,cost))
            c.execute("UPDATE ai_generation_jobs SET spent_micros=spent_micros+? WHERE id=?",(cost,job_id))
        return {"item_id":item_id,"status":status,"model":spec.name,"cost_micros":cost,"validation":validation,"prompt_version":int(job["version"]),"prompt_sha256":job["template_sha256"]}

    def propose_feedback_rule(self, shop_id: int, user_id: int, scope: str, pattern: str) -> int:
        shop=self.tenants.shop_for_user(shop_id,user_id); org=int(shop["organization_id"]); self.tenants.require_role(org,user_id,{"owner","admin","editor"})
        with self.db.connect() as c:
            c.execute("INSERT INTO ai_feedback_rules(organization_id,shop_id,scope,pattern,status,created_by) VALUES (?,?,?,?,'proposed',?) ON CONFLICT(shop_id,scope,pattern) DO UPDATE SET evidence_count=evidence_count+1",(org,shop_id,scope,pattern,user_id))
            return int(c.execute("SELECT id FROM ai_feedback_rules WHERE shop_id=? AND scope=? AND pattern=?",(shop_id,scope,pattern)).fetchone()["id"])

    def confirm_feedback_rule(self, rule_id: int, user_id: int) -> None:
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM ai_feedback_rules WHERE id=?",(rule_id,)).fetchone()
            if not row: raise LookupError(rule_id)
            self.tenants.require_role(int(row["organization_id"]),user_id,{"owner","admin"})
            c.execute("UPDATE ai_feedback_rules SET status='confirmed',confirmed_by=? WHERE id=?",(user_id,rule_id))


class EvaluationSuite:
    def __init__(self, db: Database): self.db=db
    def add_case(self, name: str, request: dict[str,Any], expected: dict[str,Any]) -> int:
        with self.db.connect() as c: return int(c.execute("INSERT INTO ai_evaluation_cases(name,input_json,expected_json) VALUES (?,?,?)",(name,stable_json(request),stable_json(expected))).lastrowid)
    def record(self, prompt_id: int, case_id: int, output: dict[str,Any]) -> dict[str,Any]:
        with self.db.connect() as c:
            case=c.execute("SELECT * FROM ai_evaluation_cases WHERE id=? AND active=1",(case_id,)).fetchone()
            if not case: raise LookupError(case_id)
            request=json.loads(case["input_json"]); expected=json.loads(case["expected_json"])
            validation=validate_output(request,output); required_fields=set(expected.get("required_fields") or [])
            actual_fields=set((output.get("fields") or {}).keys()); field_score=1.0 if required_fields.issubset(actual_fields) else 0.0
            score=field_score if validation["status"]=="pass" else 0.0; passed=int(score>=float(expected.get("minimum_score",1.0)))
            c.execute("INSERT INTO ai_evaluation_results(prompt_version_id,case_id,passed,score,details_json) VALUES (?,?,?,?,?)",(prompt_id,case_id,passed,score,stable_json({"validation":validation,"required_fields":sorted(required_fields)})))
        return {"passed":bool(passed),"score":score,"validation":validation}
