from __future__ import annotations

from pathlib import Path

from shelfboost_phase2.db import connect, initialize as initialize_phase2

PUBLISH_SCHEMA = """
CREATE TABLE IF NOT EXISTS publish_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_changes_name TEXT NOT NULL,
    source_changes_sha256 TEXT NOT NULL,
    source_approved_csv_name TEXT NOT NULL,
    source_approved_csv_sha256 TEXT NOT NULL,
    source_bridge_manifest_name TEXT NOT NULL,
    source_bridge_manifest_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'planned','blocked','running','partial','completed','failed',
        'rollback_running','rollback_partial','rolled_back'
    )),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    error_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS publish_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES publish_batches(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES shopify_products(id),
    shopify_gid TEXT NOT NULL,
    handle TEXT NOT NULL,
    original_updated_at TEXT NOT NULL,
    original_fields_json TEXT NOT NULL,
    proposed_fields_json TEXT NOT NULL,
    changed_fields_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'ready','conflict','publishing','succeeded','failed','uncertain',
        'already_applied','rolled_back','rollback_failed','rollback_conflict'
    )),
    conflict_reason TEXT NOT NULL DEFAULT '',
    error_text TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, product_id)
);

CREATE TABLE IF NOT EXISTS publish_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publish_item_id INTEGER NOT NULL REFERENCES publish_items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('planned_before','live_before','published_after','rollback_before','rollback_after')),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(publish_item_id, kind)
);

CREATE TABLE IF NOT EXISTS publish_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publish_item_id INTEGER NOT NULL REFERENCES publish_items(id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK(operation IN ('publish','reconcile','rollback')),
    request_sha256 TEXT NOT NULL DEFAULT '',
    request_json TEXT NOT NULL DEFAULT '{}',
    response_sha256 TEXT NOT NULL DEFAULT '',
    response_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    user_errors_json TEXT NOT NULL DEFAULT '[]',
    error_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rollback_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES publish_batches(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('planned','running','partial','completed','failed')),
    plan_json TEXT NOT NULL,
    audit_path TEXT NOT NULL DEFAULT '',
    audit_manifest_sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    error_text TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_publish_batches_shop_status
ON publish_batches(shop_id, status, id);

CREATE INDEX IF NOT EXISTS idx_publish_items_batch_status
ON publish_items(batch_id, status, id);

CREATE INDEX IF NOT EXISTS idx_rollback_runs_batch_status
ON rollback_runs(batch_id, status, id);
"""


def initialize(workspace: Path) -> Path:
    db_path = initialize_phase2(workspace)
    (workspace.resolve() / "publish" / "plans").mkdir(parents=True, exist_ok=True)
    (workspace.resolve() / "publish" / "reports").mkdir(parents=True, exist_ok=True)
    with connect(workspace) as connection:
        connection.executescript(PUBLISH_SCHEMA)
    return db_path
