from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shelfboost_phase2.common import sha256_bytes, write_json
from shelfboost_phase2.db import connect

from .db import initialize

SECRET_KEYS = {"access_token", "authorization", "client_secret", "secret", "token", "x-shopify-access-token"}
JSON_COLUMNS = {"request_json", "response_json", "user_errors_json", "payload_json", "plan_json"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SECRET_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in row.items():
        if key in JSON_COLUMNS and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        sanitized[key] = _redact(value)
    return sanitized


def build_audit_bundle(workspace: Path, batch_id: int) -> dict[str, Any]:
    initialize(workspace)
    root = workspace.resolve() / "publish" / "reports" / f"batch-{batch_id}-audit"
    root.mkdir(parents=True, exist_ok=True)
    with connect(workspace) as connection:
        batch_row = connection.execute("SELECT * FROM publish_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch_row:
            raise ValueError(f"Unknown publish batch: {batch_id}")
        batch = dict(batch_row)
        shop = dict(connection.execute("SELECT * FROM shops WHERE id=?", (batch["shop_id"],)).fetchone())
        items = [dict(row) for row in connection.execute(
            "SELECT * FROM publish_items WHERE batch_id=? ORDER BY id", (batch_id,)
        )]
        snapshots = [dict(row) for row in connection.execute(
            """
            SELECT ps.* FROM publish_snapshots ps
            JOIN publish_items pi ON pi.id=ps.publish_item_id
            WHERE pi.batch_id=? ORDER BY ps.publish_item_id, ps.kind
            """,
            (batch_id,),
        )]
        attempts = [dict(row) for row in connection.execute(
            """
            SELECT pa.* FROM publish_attempts pa
            JOIN publish_items pi ON pi.id=pa.publish_item_id
            WHERE pi.batch_id=? ORDER BY pa.id
            """,
            (batch_id,),
        )]
        rollbacks = [dict(row) for row in connection.execute(
            "SELECT * FROM rollback_runs WHERE batch_id=? ORDER BY id", (batch_id,)
        )]
    files: dict[str, Any] = {
        "batch.json": _sanitize_row(batch),
        "shop.json": _sanitize_row({key: shop[key] for key in shop if key != "token_reference"}),
        "items.json": [_sanitize_row(item) for item in items],
        "snapshots.json": [_sanitize_row(item) for item in snapshots],
        "attempts.json": [_sanitize_row(item) for item in attempts],
        "rollback-runs.json": [_sanitize_row(item) for item in rollbacks],
        "source-digests.json": {
            "changes": {"name": batch["source_changes_name"], "sha256": batch["source_changes_sha256"]},
            "approved_csv": {"name": batch["source_approved_csv_name"], "sha256": batch["source_approved_csv_sha256"]},
            "bridge_manifest": {"name": batch["source_bridge_manifest_name"], "sha256": batch["source_bridge_manifest_sha256"]},
        },
    }
    manifest_files: list[dict[str, str]] = []
    for name, payload in files.items():
        path = root / name
        write_json(path, payload)
        manifest_files.append({"path": name, "sha256": sha256_bytes(path.read_bytes())})
    manifest = {
        "format": "shelfboost-publish-audit-v1",
        "batch_id": batch_id,
        "shop": shop["domain"],
        "files": sorted(manifest_files, key=lambda item: item["path"]),
    }
    manifest_path = root / "manifest.json"
    write_json(manifest_path, manifest)
    digest = sha256_bytes(manifest_path.read_bytes())
    with connect(workspace) as connection:
        connection.execute(
            "UPDATE rollback_runs SET audit_path=?, audit_manifest_sha256=? WHERE batch_id=?",
            (str(root), digest, batch_id),
        )
    return {
        "batch_id": batch_id,
        "audit_dir": str(root),
        "manifest": str(manifest_path),
        "manifest_sha256": digest,
        "files": len(manifest_files),
    }
