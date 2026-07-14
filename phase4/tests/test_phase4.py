from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from shelfboost_phase4.core import (
    AppStatus, Database, InstallationService, JobQueue, PrivacyService,
    Settings, StateSigner, TenantService, TokenVault,
)


class TestCipher:
    def __init__(self): self.keys={"k1":b"a"*32,"k2":b"b"*32}
    def encrypt(self, plaintext: bytes, key_id: str) -> bytes:
        key=self.keys[key_id]; nonce=hashlib.sha256(plaintext+key).digest()[:16]
        stream=hashlib.sha256(key+nonce).digest(); body=bytes(value ^ stream[index%len(stream)] for index,value in enumerate(plaintext))
        return nonce+body+hmac.new(key,nonce+body,hashlib.sha256).digest()
    def decrypt(self, ciphertext: bytes, key_id: str) -> bytes:
        key=self.keys[key_id]; nonce,body,tag=ciphertext[:16],ciphertext[16:-32],ciphertext[-32:]
        if not hmac.compare_digest(tag,hmac.new(key,nonce+body,hashlib.sha256).digest()): raise ValueError("bad envelope")
        stream=hashlib.sha256(key+nonce).digest(); return bytes(value ^ stream[index%len(stream)] for index,value in enumerate(body))


class Phase4Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/"app.db"
        self.db=Database(self.path); self.db.migrate()
        self.tenants=TenantService(self.db); self.org,self.owner=self.tenants.create_organization("north-studio","North Studio","owner@example.com")
        self.signer=StateSigner(self.db,"s"*40,clock=lambda:1000)
        self.cipher=TestCipher(); self.vault=TokenVault(self.db,self.cipher,"k1")
        self.install=InstallationService(self.db,self.signer,self.vault)
    def tearDown(self): self.temp.cleanup()

    def install_shop(self):
        state=self.signer.issue(self.org,"north-studio.myshopify.com",["read_products","write_products"])
        return self.install.complete(state,"north-studio.myshopify.com","shpat_super_secret")

    def test_health_readiness_and_settings(self):
        settings=Settings("test","4.0.0","x"*32,"k1",self.path); settings.validate()
        status=AppStatus(settings,self.db)
        self.assertEqual(status.health()["status"],"ok"); self.assertTrue(status.readiness()["database"])

    def test_state_rejects_tamper_replay_and_shop_substitution(self):
        state=self.signer.issue(self.org,"north-studio.myshopify.com",["read_products"])
        with self.assertRaises(PermissionError): self.signer.consume(state+"x","north-studio.myshopify.com")
        with self.assertRaises(PermissionError): self.signer.consume(state,"other-shop.myshopify.com")
        payload=self.signer.consume(state,"north-studio.myshopify.com"); self.assertEqual(payload["org"],self.org)
        with self.assertRaises(PermissionError): self.signer.consume(state,"north-studio.myshopify.com")

    def test_cross_tenant_access_is_denied(self):
        shop=self.install_shop(); other_org,other_user=self.tenants.create_organization("other-org","Other","other@example.com")
        self.assertEqual(self.tenants.shop_for_user(shop,self.owner)["organization_id"],self.org)
        with self.assertRaises(PermissionError): self.tenants.shop_for_user(shop,other_user)
        self.assertNotEqual(other_org,self.org)

    def test_token_is_enveloped_and_rotates_without_plaintext_storage(self):
        shop=self.install_shop(); self.assertEqual(self.vault.get(shop),"shpat_super_secret")
        raw=self.path.read_bytes(); self.assertNotIn(b"shpat_super_secret",raw)
        self.vault.rotate(shop,"k2"); self.assertEqual(self.vault.get(shop),"shpat_super_secret")
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT key_id FROM token_envelopes WHERE shop_id=?",(shop,)).fetchone()["key_id"],"k2")

    def test_webhook_dedupe_retry_and_dead_letter(self):
        shop=self.install_shop(); queue=JobQueue(self.db,clock=lambda:1000)
        first=queue.ingest_webhook(shop,"evt-1","products/update",b'{"id":1}',"corr-1")
        duplicate=queue.ingest_webhook(shop,"evt-1","products/update",b'{"id":1}',"corr-1")
        self.assertFalse(first["duplicate"]); self.assertTrue(duplicate["duplicate"])
        for expected in ("pending","pending","dead_letter"):
            job=queue.claim(); self.assertIsNotNone(job); self.assertEqual(queue.fail(job["id"],"boom",delay_seconds=0),expected)
        with self.db.connect() as c: self.assertEqual(c.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0],1)

    def test_uninstall_revokes_token_cancels_jobs_and_purge_is_tenant_scoped(self):
        shop=self.install_shop(); queue=JobQueue(self.db,clock=lambda:1000); queue.ingest_webhook(shop,"evt-2","products/update",b'{}',"corr-2")
        privacy=PrivacyService(self.db,queue); privacy.uninstall(shop)
        with self.assertRaises(LookupError): self.vault.get(shop)
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT active FROM app_shops WHERE id=?",(shop,)).fetchone()["active"],0)
            self.assertEqual(c.execute("SELECT status FROM jobs WHERE shop_id=?",(shop,)).fetchone()["status"],"cancelled")
        exported=privacy.export_tenant(self.org); self.assertEqual(exported["shops"][0]["domain"],"north-studio.myshopify.com")
        request=privacy.request_purge(self.org,shop); privacy.purge_shop(request)
        with self.db.connect() as c: self.assertIsNone(c.execute("SELECT id FROM app_shops WHERE id=?",(shop,)).fetchone())


if __name__ == "__main__": unittest.main()
