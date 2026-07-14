from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$", re.IGNORECASE)
ROLES = {"owner", "admin", "editor", "viewer"}


def canonical_shop(value: str) -> str:
    domain = value.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if not SHOP_RE.fullmatch(domain):
        raise ValueError("Invalid myshopify.com domain")
    return domain


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Settings:
    environment: str
    app_version: str
    state_secret: str
    token_key_id: str
    database_path: Path

    def validate(self) -> None:
        if self.environment not in {"local", "test", "staging", "production"}:
            raise ValueError("Unsupported environment")
        if len(self.state_secret.encode("utf-8")) < 32:
            raise ValueError("State signing secret must be at least 32 bytes")
        if not self.token_key_id.strip():
            raise ValueError("Token key id is required")
        if self.environment == "production" and self.database_path.name == ":memory:":
            raise ValueError("Production cannot use an in-memory database")


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS memberships(organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('owner','admin','editor','viewer')), PRIMARY KEY(organization_id,user_id));
CREATE TABLE IF NOT EXISTS app_shops(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, domain TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1, installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, uninstalled_at TEXT);
CREATE TABLE IF NOT EXISTS oauth_states(nonce_hash TEXT PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_domain TEXT NOT NULL, scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, consumed_at INTEGER);
CREATE TABLE IF NOT EXISTS token_envelopes(shop_id INTEGER PRIMARY KEY REFERENCES app_shops(id) ON DELETE CASCADE, key_id TEXT NOT NULL, ciphertext_b64 TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, rotated_at TEXT);
CREATE TABLE IF NOT EXISTS webhook_events(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, shop_id INTEGER NOT NULL REFERENCES app_shops(id) ON DELETE CASCADE, topic TEXT NOT NULL, payload_sha256 TEXT NOT NULL, correlation_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('received','queued','processed','ignored','failed')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER REFERENCES app_shops(id) ON DELETE CASCADE, kind TEXT NOT NULL, payload_json TEXT NOT NULL, correlation_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','cancelled','dead_letter')), attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, available_at INTEGER NOT NULL, last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS dead_letters(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE, reason TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER REFERENCES app_shops(id) ON DELETE SET NULL, actor TEXT NOT NULL, action TEXT NOT NULL, correlation_id TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS deletion_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE, shop_id INTEGER REFERENCES app_shops(id) ON DELETE SET NULL, status TEXT NOT NULL CHECK(status IN ('requested','exported','purged','failed')), requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, details_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status,available_at,id);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_events(organization_id,shop_id,id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")

    def ready(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False


class EnvelopeCipher(Protocol):
    def encrypt(self, plaintext: bytes, key_id: str) -> bytes: ...
    def decrypt(self, ciphertext: bytes, key_id: str) -> bytes: ...


class TenantService:
    def __init__(self, db: Database): self.db = db

    def create_organization(self, slug: str, name: str, owner_email: str) -> tuple[int, int]:
        slug = slug.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", slug):
            raise ValueError("Invalid organization slug")
        email = owner_email.strip().lower()
        with self.db.connect() as c:
            org = c.execute("INSERT INTO organizations(slug,name) VALUES (?,?)", (slug,name.strip())).lastrowid
            c.execute("INSERT INTO users(email) VALUES (?) ON CONFLICT(email) DO NOTHING", (email,))
            user = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
            c.execute("INSERT INTO memberships(organization_id,user_id,role) VALUES (?,?,'owner')", (org,user))
        return int(org), int(user)

    def add_member(self, organization_id: int, email: str, role: str) -> int:
        if role not in ROLES: raise ValueError("Invalid role")
        with self.db.connect() as c:
            c.execute("INSERT INTO users(email) VALUES (?) ON CONFLICT(email) DO NOTHING", (email.lower(),))
            user = c.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()["id"]
            c.execute("INSERT OR REPLACE INTO memberships(organization_id,user_id,role) VALUES (?,?,?)", (organization_id,user,role))
        return int(user)

    def require_role(self, organization_id: int, user_id: int, allowed: set[str]) -> str:
        with self.db.connect() as c:
            row = c.execute("SELECT role FROM memberships WHERE organization_id=? AND user_id=?", (organization_id,user_id)).fetchone()
        if not row or row["role"] not in allowed: raise PermissionError("Tenant access denied")
        return str(row["role"])

    def shop_for_user(self, shop_id: int, user_id: int) -> dict[str, Any]:
        with self.db.connect() as c:
            row = c.execute("""SELECT s.*,m.role FROM app_shops s JOIN memberships m ON m.organization_id=s.organization_id WHERE s.id=? AND m.user_id=?""", (shop_id,user_id)).fetchone()
        if not row: raise PermissionError("Cross-tenant shop access denied")
        return dict(row)


class StateSigner:
    def __init__(self, db: Database, secret: str, ttl_seconds: int = 600, clock=time.time):
        self.db, self.secret, self.ttl, self.clock = db, secret.encode(), ttl_seconds, clock

    def issue(self, organization_id: int, shop: str, scopes: list[str]) -> str:
        nonce = secrets.token_urlsafe(24); exp = int(self.clock()) + self.ttl
        payload = {"nonce":nonce,"org":organization_id,"shop":canonical_shop(shop),"scopes":sorted(set(scopes)),"exp":exp}
        raw = stable_json(payload).encode(); sig = hmac.new(self.secret,raw,hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")
        with self.db.connect() as c:
            c.execute("INSERT INTO oauth_states(nonce_hash,organization_id,shop_domain,scopes_json,expires_at) VALUES (?,?,?,?,?)", (hashlib.sha256(nonce.encode()).hexdigest(),organization_id,payload["shop"],stable_json(payload["scopes"]),exp))
        return token

    def consume(self, token: str, expected_shop: str) -> dict[str, Any]:
        try:
            left,right=token.split(".",1); raw=base64.urlsafe_b64decode(left+"="*((4-len(left)%4)%4)); supplied=base64.urlsafe_b64decode(right+"="*((4-len(right)%4)%4))
        except Exception as exc: raise PermissionError("Malformed authorization state") from exc
        expected=hmac.new(self.secret,raw,hashlib.sha256).digest()
        if not hmac.compare_digest(expected,supplied): raise PermissionError("Invalid authorization state signature")
        payload=json.loads(raw); now=int(self.clock())
        if int(payload.get("exp",0)) < now: raise PermissionError("Authorization state expired")
        if canonical_shop(str(payload.get("shop",""))) != canonical_shop(expected_shop): raise PermissionError("Authorization shop substitution")
        nonce_hash=hashlib.sha256(str(payload.get("nonce","")).encode()).hexdigest()
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM oauth_states WHERE nonce_hash=?",(nonce_hash,)).fetchone()
            if not row or row["consumed_at"] is not None: raise PermissionError("Authorization state replayed or unknown")
            if row["expires_at"] < now: raise PermissionError("Authorization state expired")
            c.execute("UPDATE oauth_states SET consumed_at=? WHERE nonce_hash=?",(now,nonce_hash))
        return payload


class TokenVault:
    def __init__(self, db: Database, cipher: EnvelopeCipher, key_id: str): self.db,self.cipher,self.key_id=db,cipher,key_id

    def put(self, shop_id: int, token: str) -> None:
        if not token.strip(): raise ValueError("Empty token")
        ciphertext=self.cipher.encrypt(token.encode(),self.key_id)
        with self.db.connect() as c:
            c.execute("""INSERT INTO token_envelopes(shop_id,key_id,ciphertext_b64) VALUES (?,?,?) ON CONFLICT(shop_id) DO UPDATE SET key_id=excluded.key_id,ciphertext_b64=excluded.ciphertext_b64,rotated_at=CURRENT_TIMESTAMP""",(shop_id,self.key_id,base64.b64encode(ciphertext).decode()))

    def get(self, shop_id: int) -> str:
        with self.db.connect() as c: row=c.execute("SELECT * FROM token_envelopes WHERE shop_id=?",(shop_id,)).fetchone()
        if not row: raise LookupError("No token envelope")
        return self.cipher.decrypt(base64.b64decode(row["ciphertext_b64"]),row["key_id"]).decode()

    def rotate(self, shop_id: int, new_key_id: str) -> None:
        token=self.get(shop_id); old=self.key_id; self.key_id=new_key_id
        try: self.put(shop_id,token)
        except Exception: self.key_id=old; raise


class InstallationService:
    def __init__(self, db: Database, signer: StateSigner, vault: TokenVault): self.db,self.signer,self.vault=db,signer,vault

    def complete(self, state: str, shop: str, access_token: str, actor: str="system") -> int:
        payload=self.signer.consume(state,shop); domain=canonical_shop(shop); org=int(payload["org"])
        with self.db.connect() as c:
            c.execute("""INSERT INTO app_shops(organization_id,domain,active) VALUES (?,?,1) ON CONFLICT(domain) DO UPDATE SET organization_id=excluded.organization_id,active=1,uninstalled_at=NULL""",(org,domain))
            shop_id=int(c.execute("SELECT id FROM app_shops WHERE domain=?",(domain,)).fetchone()["id"])
            c.execute("INSERT INTO audit_events(organization_id,shop_id,actor,action,correlation_id,details_json) VALUES (?,?,?,?,?,?)",(org,shop_id,actor,"shop.install",secrets.token_hex(8),stable_json({"scopes":payload["scopes"]})))
        self.vault.put(shop_id,access_token)
        return shop_id


class JobQueue:
    def __init__(self, db: Database, clock=time.time): self.db,self.clock=db,clock

    def ingest_webhook(self, shop_id: int, event_id: str, topic: str, payload: bytes, correlation_id: str) -> dict[str, Any]:
        digest=hashlib.sha256(payload).hexdigest()
        with self.db.connect() as c:
            shop=c.execute("SELECT organization_id,active FROM app_shops WHERE id=?",(shop_id,)).fetchone()
            if not shop or int(shop["active"])!=1: raise PermissionError("Inactive shop")
            try:
                cursor=c.execute("INSERT INTO webhook_events(event_id,shop_id,topic,payload_sha256,correlation_id,status) VALUES (?,?,?,?,?,'received')",(event_id,shop_id,topic,digest,correlation_id))
            except sqlite3.IntegrityError:
                return {"duplicate":True,"event_id":event_id}
            c.execute("INSERT INTO jobs(organization_id,shop_id,kind,payload_json,correlation_id,status,available_at) VALUES (?,?,?,?,?,'pending',?)",(shop["organization_id"],shop_id,f"webhook:{topic}",payload.decode("utf-8","replace"),correlation_id,int(self.clock())))
            c.execute("UPDATE webhook_events SET status='queued' WHERE id=?",(cursor.lastrowid,))
        return {"duplicate":False,"event_id":event_id,"sha256":digest}

    def claim(self) -> dict[str, Any] | None:
        now=int(self.clock())
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM jobs WHERE status='pending' AND available_at<=? ORDER BY id LIMIT 1",(now,)).fetchone()
            if not row: return None
            c.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(row["id"],))
            return dict(c.execute("SELECT * FROM jobs WHERE id=?",(row["id"],)).fetchone())

    def complete(self, job_id: int) -> None:
        with self.db.connect() as c: c.execute("UPDATE jobs SET status='completed',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))

    def fail(self, job_id: int, error: str, delay_seconds: int=60) -> str:
        with self.db.connect() as c:
            row=c.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if not row: raise LookupError(job_id)
            if int(row["attempts"]) >= int(row["max_attempts"]):
                c.execute("UPDATE jobs SET status='dead_letter',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(error,job_id))
                c.execute("INSERT OR REPLACE INTO dead_letters(job_id,reason,payload_json) VALUES (?,?,?)",(job_id,error,row["payload_json"]))
                return "dead_letter"
            c.execute("UPDATE jobs SET status='pending',available_at=?,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(int(self.clock())+delay_seconds,error,job_id))
            return "pending"

    def cancel_shop(self, shop_id: int) -> int:
        with self.db.connect() as c:
            return c.execute("UPDATE jobs SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE shop_id=? AND status IN ('pending','running','failed')",(shop_id,)).rowcount


class PrivacyService:
    def __init__(self, db: Database, queue: JobQueue): self.db,self.queue=db,queue

    def uninstall(self, shop_id: int, actor: str="shopify") -> None:
        with self.db.connect() as c:
            shop=c.execute("SELECT * FROM app_shops WHERE id=?",(shop_id,)).fetchone()
            if not shop: return
            c.execute("UPDATE app_shops SET active=0,uninstalled_at=CURRENT_TIMESTAMP WHERE id=?",(shop_id,))
            c.execute("DELETE FROM token_envelopes WHERE shop_id=?",(shop_id,))
            c.execute("INSERT INTO audit_events(organization_id,shop_id,actor,action,correlation_id) VALUES (?,?,?,?,?)",(shop["organization_id"],shop_id,actor,"shop.uninstall",secrets.token_hex(8)))
        self.queue.cancel_shop(shop_id)

    def export_tenant(self, organization_id: int) -> dict[str, Any]:
        with self.db.connect() as c:
            shops=[dict(r) for r in c.execute("SELECT id,domain,active,installed_at,uninstalled_at FROM app_shops WHERE organization_id=? ORDER BY id",(organization_id,))]
            events=[dict(r) for r in c.execute("SELECT action,actor,correlation_id,created_at FROM audit_events WHERE organization_id=? ORDER BY id",(organization_id,))]
        return {"organization_id":organization_id,"shops":shops,"audit_events":events}

    def request_purge(self, organization_id: int, shop_id: int | None=None) -> int:
        with self.db.connect() as c: return int(c.execute("INSERT INTO deletion_requests(organization_id,shop_id,status) VALUES (?,?,'requested')",(organization_id,shop_id)).lastrowid)

    def purge_shop(self, request_id: int) -> None:
        with self.db.connect() as c:
            request=c.execute("SELECT * FROM deletion_requests WHERE id=?",(request_id,)).fetchone()
            if not request or request["status"]!="requested": raise RuntimeError("Invalid deletion request")
            if request["shop_id"] is not None: c.execute("DELETE FROM app_shops WHERE id=? AND organization_id=?",(request["shop_id"],request["organization_id"]))
            c.execute("UPDATE deletion_requests SET status='purged',completed_at=CURRENT_TIMESTAMP WHERE id=?",(request_id,))


class AppStatus:
    def __init__(self, settings: Settings, db: Database): self.settings,self.db=settings,db
    def health(self) -> dict[str, Any]: return {"status":"ok","version":self.settings.app_version,"environment":self.settings.environment}
    def readiness(self) -> dict[str, Any]: return {"status":"ready" if self.db.ready() else "not_ready","database":self.db.ready()}
