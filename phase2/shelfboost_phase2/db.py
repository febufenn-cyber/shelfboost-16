from __future__ import annotations

import sqlite3
from pathlib import Path


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    api_version TEXT NOT NULL,
    token_reference TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK(mode IN ('full', 'incremental')),
    requested_since TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    page_count INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    product_count INTEGER NOT NULL DEFAULT 0,
    variant_count INTEGER NOT NULL DEFAULT 0,
    deleted_count INTEGER NOT NULL DEFAULT 0,
    requested_api_version TEXT NOT NULL,
    observed_api_version TEXT NOT NULL DEFAULT '',
    last_cursor TEXT NOT NULL DEFAULT '',
    error_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    operation TEXT NOT NULL,
    cursor_in TEXT NOT NULL DEFAULT '',
    cursor_out TEXT NOT NULL DEFAULT '',
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, operation, page_number, cursor_in)
);

CREATE TABLE IF NOT EXISTS shopify_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    shopify_gid TEXT NOT NULL,
    legacy_id TEXT NOT NULL DEFAULT '',
    handle TEXT NOT NULL,
    title TEXT NOT NULL,
    description_html TEXT NOT NULL,
    vendor TEXT NOT NULL,
    product_type TEXT NOT NULL,
    status TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    seo_title TEXT NOT NULL,
    seo_description TEXT NOT NULL,
    created_at_shopify TEXT NOT NULL,
    updated_at_shopify TEXT NOT NULL,
    metafields_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    variants_complete INTEGER NOT NULL DEFAULT 1,
    last_seen_run_id INTEGER NOT NULL REFERENCES sync_runs(id),
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    UNIQUE(shop_id, shopify_gid),
    UNIQUE(shop_id, handle)
);

CREATE TABLE IF NOT EXISTS shopify_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES shopify_products(id) ON DELETE CASCADE,
    shopify_gid TEXT NOT NULL,
    legacy_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    sku TEXT NOT NULL,
    barcode TEXT NOT NULL,
    price TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    last_seen_run_id INTEGER NOT NULL REFERENCES sync_runs(id),
    UNIQUE(product_id, shopify_gid)
);

CREATE INDEX IF NOT EXISTS idx_products_shop_updated
ON shopify_products(shop_id, updated_at_shopify DESC);

CREATE INDEX IF NOT EXISTS idx_products_shop_seen
ON shopify_products(shop_id, last_seen_run_id);

CREATE INDEX IF NOT EXISTS idx_variants_product
ON shopify_variants(product_id);
"""


def initialize(workspace: Path) -> Path:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    for directory in ("snapshots", "exports"):
        (workspace / directory).mkdir(exist_ok=True)
    db_path = workspace / "sync.db"
    with sqlite3.connect(db_path, factory=ClosingConnection) as connection:
        connection.executescript(SCHEMA)
    return db_path


def connect(workspace: Path) -> sqlite3.Connection:
    db_path = workspace.resolve() / "sync.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Phase 2 workspace is not initialized: {workspace}")
    connection = sqlite3.connect(db_path, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
