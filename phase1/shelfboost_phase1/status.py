from __future__ import annotations

from pathlib import Path

from .db import connect


def workspace_status(workspace: Path) -> dict:
    with connect(workspace) as connection:
        counts = {}
        for table in ("catalog_imports", "products", "product_facts", "brand_profiles", "batches", "drafts", "reviews", "exports"):
            counts[table] = int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
        latest_batch = connection.execute("SELECT id, name, status FROM batches ORDER BY id DESC LIMIT 1").fetchone()
        validation = {
            row["validation_status"]: int(row["count"])
            for row in connection.execute(
                "SELECT validation_status, COUNT(*) AS count FROM drafts GROUP BY validation_status"
            ).fetchall()
        }
        decisions = {
            row["decision"]: int(row["count"])
            for row in connection.execute(
                "SELECT decision, COUNT(*) AS count FROM reviews GROUP BY decision"
            ).fetchall()
        }
    return {
        "counts": counts,
        "latest_batch": dict(latest_batch) if latest_batch else None,
        "validation": validation,
        "decisions": decisions,
    }
