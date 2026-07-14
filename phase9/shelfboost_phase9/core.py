from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from shelfboost_phase4.core import Database, stable_json

OPERATIONS_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS feature_flags(key TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, rollout_percent INTEGER NOT NULL DEFAULT 0 CHECK(rollout_percent BETWEEN 0 AND 100), kill_switch INTEGER NOT NULL DEFAULT 0, environments_json TEXT NOT NULL DEFAULT '[]', description TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS launch_gates(key TEXT PRIMARY KEY, category TEXT NOT NULL CHECK(category IN ('code','staging','provider','security','legal','shopify','operations')), required INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL CHECK(status IN ('pending','passed','blocked','not_applicable')), evidence TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS slo_definitions(key TEXT PRIMARY KEY, target REAL NOT NULL CHECK(target>0 AND target<=1), window_seconds INTEGER NOT NULL CHECK(window_seconds>0), owner TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS slo_observations(id INTEGER PRIMARY KEY AUTOINCREMENT, slo_key TEXT NOT NULL REFERENCES slo_definitions(key) ON DELETE CASCADE, success INTEGER NOT NULL, latency_ms REAL NOT NULL CHECK(latency_ms>=0), observed_at INTEGER NOT NULL, correlation_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backup_manifests(id INTEGER PRIMARY KEY AUTOINCREMENT, backup_key TEXT NOT NULL UNIQUE, source_path TEXT NOT NULL, backup_path TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, file_count INTEGER NOT NULL, created_at INTEGER NOT NULL, verified_at INTEGER, restore_verified_at INTEGER);
CREATE TABLE IF NOT EXISTS security_findings(id INTEGER PRIMARY KEY AUTOINCREMENT, finding_key TEXT NOT NULL UNIQUE, severity TEXT NOT NULL CHECK(severity IN ('low','medium','high','critical')), category TEXT NOT NULL, location TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open','accepted','fixed','false_positive')), evidence TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_key TEXT NOT NULL UNIQUE, severity TEXT NOT NULL CHECK(severity IN ('sev1','sev2','sev3','sev4')), title TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('declared','investigating','mitigated','resolved','closed')), owner TEXT NOT NULL, declared_at INTEGER NOT NULL, resolved_at INTEGER, summary TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS incident_events(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE, status TEXT NOT NULL, actor TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS readiness_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, report_sha256 TEXT NOT NULL UNIQUE, code_complete INTEGER NOT NULL, production_ready INTEGER NOT NULL, payload_json TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_slo_window ON slo_observations(slo_key,observed_at,id);
CREATE INDEX IF NOT EXISTS idx_incident_events ON incident_events(incident_id,created_at,id);
"""

SECRET_KEY_RE=re.compile(r"(?:token|secret|authorization|password|private[_-]?key|api[_-]?key)",re.I)
SECRET_VALUE_PATTERNS=[
    re.compile(r"\bshpat_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk_(?:live|test|proj)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
PLACEHOLDERS={"[REDACTED]","<redacted>","example-secret","fixture-token","test-token"}


def initialize_operations(db: Database) -> None:
    db.migrate()
    with db.connect() as c:
        c.executescript(OPERATIONS_SCHEMA); c.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (9)")


def redact(value: Any) -> Any:
    if isinstance(value,dict):
        return {key:("[REDACTED]" if SECRET_KEY_RE.search(str(key)) else redact(item)) for key,item in value.items()}
    if isinstance(value,list): return [redact(item) for item in value]
    if isinstance(value,str):
        result=value
        for pattern in SECRET_VALUE_PATTERNS: result=pattern.sub("[REDACTED]",result)
        return result
    return value


class SecretScanner:
    def scan_text(self, text: str, location: str="memory") -> list[dict[str,str]]:
        findings=[]
        if text.strip() in PLACEHOLDERS: return findings
        for index,pattern in enumerate(SECRET_VALUE_PATTERNS):
            for match in pattern.finditer(text): findings.append({"location":location,"pattern":f"secret_pattern_{index}","match_sha256":hashlib.sha256(match.group(0).encode()).hexdigest()})
        return findings
    def scan_tree(self, root: Path) -> list[dict[str,str]]:
        findings=[]
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.stat().st_size>2_000_000: continue
            try: text=path.read_text(encoding="utf-8")
            except (UnicodeDecodeError,OSError): continue
            findings.extend(self.scan_text(text,str(path.relative_to(root))))
        return findings


def security_headers() -> dict[str,str]:
    return {
        "Content-Security-Policy":"default-src 'self'; frame-ancestors https://admin.shopify.com https://*.myshopify.com; object-src 'none'; base-uri 'self'",
        "Referrer-Policy":"strict-origin-when-cross-origin",
        "X-Content-Type-Options":"nosniff",
        "Permissions-Policy":"camera=(), microphone=(), geolocation=()",
        "Strict-Transport-Security":"max-age=31536000; includeSubDomains",
    }


@dataclass
class RateLimiter:
    limit: int
    window_seconds: int
    clock: Callable[[],float]=time.time
    def __post_init__(self): self._buckets:dict[str,tuple[int,int]]={}
    def allow(self,key:str,cost:int=1)->dict[str,int|bool]:
        if cost<=0: raise ValueError("Rate-limit cost must be positive")
        now=int(self.clock()); window=now-(now%self.window_seconds); start,used=self._buckets.get(key,(window,0))
        if start!=window: start,used=window,0
        allowed=used+cost<=self.limit
        if allowed: used+=cost
        self._buckets[key]=(start,used)
        return {"allowed":allowed,"remaining":max(0,self.limit-used),"reset_at":window+self.window_seconds}


@dataclass
class CircuitBreaker:
    failure_threshold: int
    recovery_seconds: int
    clock: Callable[[],float]=time.time
    def __post_init__(self): self.failures=0; self.opened_at:float|None=None; self.state="closed"
    def permit(self)->bool:
        if self.state=="open" and self.opened_at is not None and self.clock()-self.opened_at>=self.recovery_seconds: self.state="half_open"
        return self.state!="open"
    def success(self)->None: self.failures=0; self.opened_at=None; self.state="closed"
    def failure(self)->None:
        self.failures+=1
        if self.state=="half_open" or self.failures>=self.failure_threshold: self.state="open"; self.opened_at=self.clock()


@dataclass
class FeatureFlagService:
    db: Database
    def set(self,key:str,description:str,*,enabled:bool=False,rollout_percent:int=0,kill_switch:bool=False,environments:list[str]|None=None)->None:
        with self.db.connect() as c: c.execute("INSERT INTO feature_flags(key,enabled,rollout_percent,kill_switch,environments_json,description) VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET enabled=excluded.enabled,rollout_percent=excluded.rollout_percent,kill_switch=excluded.kill_switch,environments_json=excluded.environments_json,description=excluded.description,updated_at=CURRENT_TIMESTAMP",(key,int(enabled),rollout_percent,int(kill_switch),stable_json(sorted(set(environments or []))),description))
    def enabled(self,key:str,subject:str,environment:str)->bool:
        with self.db.connect() as c: row=c.execute("SELECT * FROM feature_flags WHERE key=?",(key,)).fetchone()
        if not row or int(row["kill_switch"]) or not int(row["enabled"]): return False
        environments=set(json.loads(row["environments_json"]));
        if environments and environment not in environments: return False
        bucket=int(hashlib.sha256(f"{key}:{subject}".encode()).hexdigest()[:8],16)%100
        return bucket<int(row["rollout_percent"])
    def kill(self,key:str)->None:
        with self.db.connect() as c: c.execute("UPDATE feature_flags SET kill_switch=1,updated_at=CURRENT_TIMESTAMP WHERE key=?",(key,))


@dataclass
class SLOService:
    db: Database
    clock: Callable[[],float]=time.time
    def define(self,key:str,target:float,window_seconds:int,owner:str,description:str)->None:
        with self.db.connect() as c: c.execute("INSERT INTO slo_definitions(key,target,window_seconds,owner,description) VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET target=excluded.target,window_seconds=excluded.window_seconds,owner=excluded.owner,description=excluded.description",(key,target,window_seconds,owner,description))
    def observe(self,key:str,success:bool,latency_ms:float,correlation_id:str)->None:
        with self.db.connect() as c:
            if not c.execute("SELECT 1 FROM slo_definitions WHERE key=?",(key,)).fetchone(): raise LookupError(key)
            c.execute("INSERT INTO slo_observations(slo_key,success,latency_ms,observed_at,correlation_id) VALUES (?,?,?,?,?)",(key,int(success),latency_ms,int(self.clock()),correlation_id))
    def report(self,key:str)->dict[str,Any]:
        now=int(self.clock())
        with self.db.connect() as c:
            definition=c.execute("SELECT * FROM slo_definitions WHERE key=?",(key,)).fetchone()
            if not definition: raise LookupError(key)
            rows=[dict(row) for row in c.execute("SELECT * FROM slo_observations WHERE slo_key=? AND observed_at>=?",(key,now-int(definition["window_seconds"])))]
        total=len(rows); successes=sum(int(row["success"]) for row in rows); availability=None if not total else successes/total; target=float(definition["target"]); allowed_error=1-target; actual_error=None if availability is None else 1-availability; burn=None if actual_error is None or allowed_error==0 else actual_error/allowed_error
        return {"key":key,"target":target,"samples":total,"availability":availability,"error_budget_burn":burn,"within_slo":None if availability is None else availability>=target}


@dataclass
class BackupService:
    db: Database
    clock: Callable[[],float]=time.time
    def create(self,source:Path,backup_root:Path,backup_key:str)->dict[str,Any]:
        source=source.resolve(); destination=(backup_root.resolve()/backup_key)
        if not source.is_dir(): raise ValueError("Backup source must be a directory")
        if destination.exists(): raise FileExistsError(destination)
        destination.mkdir(parents=True)
        files=[]
        for path in sorted(source.rglob("*")):
            if path.is_symlink(): raise RuntimeError("Backup refuses symbolic links")
            if not path.is_file(): continue
            relative=path.relative_to(source); target=destination/relative; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,target); digest=hashlib.sha256(target.read_bytes()).hexdigest(); files.append({"path":str(relative),"sha256":digest,"size":target.stat().st_size})
        manifest={"format":"shelfboost-backup-v1","backup_key":backup_key,"created_at":int(self.clock()),"files":files}; manifest_path=destination/"manifest.json"; manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8"); manifest_digest=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        with self.db.connect() as c: c.execute("INSERT INTO backup_manifests(backup_key,source_path,backup_path,manifest_sha256,file_count,created_at) VALUES (?,?,?,?,?,?)",(backup_key,str(source),str(destination),manifest_digest,len(files),int(self.clock())))
        return {"backup_key":backup_key,"path":str(destination),"manifest_sha256":manifest_digest,"files":len(files)}
    def verify(self,backup_path:Path)->dict[str,Any]:
        manifest_path=backup_path.resolve()/"manifest.json"; manifest=json.loads(manifest_path.read_text(encoding="utf-8")); errors=[]
        for item in manifest["files"]:
            path=backup_path/item["path"]
            if not path.is_file(): errors.append(f"missing:{item['path']}")
            elif hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]: errors.append(f"digest:{item['path']}")
        if errors: raise RuntimeError("Backup verification failed: "+", ".join(errors))
        with self.db.connect() as c: c.execute("UPDATE backup_manifests SET verified_at=? WHERE backup_key=?",(int(self.clock()),manifest["backup_key"]))
        return {"verified":True,"files":len(manifest["files"]),"backup_key":manifest["backup_key"]}
    def restore(self,backup_path:Path,target:Path)->dict[str,Any]:
        self.verify(backup_path)
        target=target.resolve()
        if target.exists() and any(target.iterdir()): raise RuntimeError("Restore target must be empty")
        target.mkdir(parents=True,exist_ok=True); manifest=json.loads((backup_path/"manifest.json").read_text())
        for item in manifest["files"]:
            source=backup_path/item["path"]; destination=target/item["path"]; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,destination)
        for item in manifest["files"]:
            if hashlib.sha256((target/item["path"]).read_bytes()).hexdigest()!=item["sha256"]: raise RuntimeError("Restored file verification failed")
        with self.db.connect() as c: c.execute("UPDATE backup_manifests SET restore_verified_at=? WHERE backup_key=?",(int(self.clock()),manifest["backup_key"]))
        return {"restored":True,"target":str(target),"files":len(manifest["files"])}


@dataclass
class IncidentService:
    db: Database
    clock: Callable[[],float]=time.time
    def declare(self,key:str,severity:str,title:str,owner:str,actor:str)->int:
        with self.db.connect() as c:
            incident=int(c.execute("INSERT INTO incidents(incident_key,severity,title,status,owner,declared_at) VALUES (?,?,?,'declared',?,?)",(key,severity,title,owner,int(self.clock()))).lastrowid); c.execute("INSERT INTO incident_events(incident_id,status,actor,message,created_at) VALUES (?,'declared',?,'Incident declared',?)",(incident,actor,int(self.clock())))
        return incident
    def transition(self,incident_id:int,status:str,actor:str,message:str)->None:
        allowed={"declared":{"investigating"},"investigating":{"mitigated","resolved"},"mitigated":{"resolved"},"resolved":{"closed"},"closed":set()}
        with self.db.connect() as c:
            row=c.execute("SELECT status FROM incidents WHERE id=?",(incident_id,)).fetchone()
            if not row: raise LookupError(incident_id)
            if status not in allowed[row["status"]]: raise ValueError(f"Invalid incident transition {row['status']} -> {status}")
            resolved=int(self.clock()) if status in {"resolved","closed"} else None
            c.execute("UPDATE incidents SET status=?,resolved_at=COALESCE(?,resolved_at),summary=CASE WHEN ?='closed' THEN ? ELSE summary END WHERE id=?",(status,resolved,status,message,incident_id)); c.execute("INSERT INTO incident_events(incident_id,status,actor,message,created_at) VALUES (?,?,?,?,?)",(incident_id,status,actor,message,int(self.clock())))


@dataclass
class LaunchService:
    db: Database
    clock: Callable[[],float]=time.time
    def set_gate(self,key:str,category:str,description:str,status:str,*,evidence:str="",owner:str="",required:bool=True)->None:
        with self.db.connect() as c: c.execute("INSERT INTO launch_gates(key,category,required,status,evidence,owner) VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET category=excluded.category,required=excluded.required,status=excluded.status,evidence=excluded.evidence,owner=excluded.owner,updated_at=CURRENT_TIMESTAMP",(key,category,int(required),status,evidence,owner))
    def readiness(self,required_keys:list[str])->dict[str,Any]:
        with self.db.connect() as c: gates={row["key"]:dict(row) for row in c.execute("SELECT * FROM launch_gates")}
        blockers=[]
        for key in required_keys:
            gate=gates.get(key)
            if not gate: blockers.append(f"missing:{key}")
            elif int(gate["required"]) and (gate["status"]!="passed" or not gate["evidence"].strip()): blockers.append(f"blocked:{key}:{gate['status']}")
        return {"production_ready":not blockers,"blockers":blockers,"gates":gates}
    def final_report(self,required_keys:list[str],code_packages:list[str])->dict[str,Any]:
        readiness=self.readiness(required_keys); payload={"code_complete":True,"completed_packages":code_packages,"production_ready":readiness["production_ready"],"blockers":readiness["blockers"],"gates":readiness["gates"],"generated_at":int(self.clock()),"statement":"Fixture-backed code completion is distinct from production verification."}; digest=hashlib.sha256(stable_json(payload).encode()).hexdigest()
        with self.db.connect() as c: c.execute("INSERT OR IGNORE INTO readiness_reports(report_sha256,code_complete,production_ready,payload_json,created_at) VALUES (?,1,?,?,?)",(digest,int(readiness["production_ready"]),stable_json(payload),int(self.clock())))
        return {"report_sha256":digest,**payload}
