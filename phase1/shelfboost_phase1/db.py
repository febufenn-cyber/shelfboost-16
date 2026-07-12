from __future__ import annotations

import sqlite3
from pathlib import Path


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback and close when used as a context manager."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS catalog_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    header_json TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    product_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES catalog_imports(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    handle TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    row_json TEXT NOT NULL,
    UNIQUE(import_id, row_index)
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES catalog_imports(id) ON DELETE CASCADE,
    handle TEXT NOT NULL,
    title TEXT NOT NULL,
    body_html TEXT NOT NULL,
    vendor TEXT NOT NULL,
    product_type TEXT NOT NULL,
    tags TEXT NOT NULL,
    status TEXT NOT NULL,
    seo_title TEXT NOT NULL,
    seo_description TEXT NOT NULL,
    category_key TEXT NOT NULL,
    primary_row_index INTEGER NOT NULL,
    audit_json TEXT NOT NULL DEFAULT '{}',
    priority_score INTEGER NOT NULL DEFAULT 0,
    eligibility TEXT NOT NULL DEFAULT 'unknown',
    UNIQUE(import_id, handle)
);

CREATE TABLE IF NOT EXISTS variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    sku TEXT NOT NULL,
    option1_name TEXT NOT NULL,
    option1_value TEXT NOT NULL,
    option2_name TEXT NOT NULL,
    option2_value TEXT NOT NULL,
    option3_name TEXT NOT NULL,
    option3_value TEXT NOT NULL,
    row_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    source_field TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 1,
    UNIQUE(product_id, name, value, source_field)
);

CREATE TABLE IF NOT EXISTS brand_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    brand_name TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    import_id INTEGER NOT NULL REFERENCES catalog_imports(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'selected'
);

CREATE TABLE IF NOT EXISTS batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    rank INTEGER NOT NULL,
    UNIQUE(batch_id, product_id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_item_id INTEGER NOT NULL REFERENCES batch_items(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    original_value TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    facts_used_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    provider TEXT NOT NULL,
    brand_profile_id INTEGER NOT NULL REFERENCES brand_profiles(id),
    template_key TEXT NOT NULL,
    template_version TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validation_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_item_id, field_name)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER NOT NULL UNIQUE REFERENCES drafts(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    edited_value TEXT NOT NULL DEFAULT '',
    reviewer_note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    output_name TEXT NOT NULL,
    change_count INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changelog_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_import_priority
ON products(import_id, priority_score DESC);

CREATE INDEX IF NOT EXISTS idx_facts_product
ON product_facts(product_id);

CREATE INDEX IF NOT EXISTS idx_drafts_batch_item
ON drafts(batch_item_id);
"""


def workspace_paths(workspace: Path) -> tuple[Path, Path]:
    workspace = workspace.resolve()
    return workspace, workspace / "pilot.db"


def initialize(workspace: Path) -> Path:
    root, db_path = workspace_paths(workspace)
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("artifacts", "imports", "exports"):
        (root / directory).mkdir(exist_ok=True)
    with sqlite3.connect(db_path, factory=ClosingConnection) as connection:
        connection.executescript(SCHEMA)
    return db_path


def connect(workspace: Path) -> sqlite3.Connection:
    _, db_path = workspace_paths(workspace)
    if not db_path.exists():
        raise FileNotFoundError(f"Workspace is not initialized: {workspace}")
    connection = sqlite3.connect(db_path, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
