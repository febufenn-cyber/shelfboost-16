from __future__ import annotations

from pathlib import Path

from .catalog import latest_import_id
from .db import connect


def select_batch(workspace: Path, name: str, limit: int = 10, include_blocked: bool = False) -> dict:
    import_id = latest_import_id(workspace)
    where = "import_id = ?"
    params: list[object] = [import_id]
    if not include_blocked:
        where += " AND eligibility = 'eligible'"
    with connect(workspace) as connection:
        products = connection.execute(
            f"SELECT id, handle, priority_score, eligibility FROM products WHERE {where} ORDER BY priority_score DESC, id ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        if not products:
            raise ValueError("No products match the batch selection criteria")
        cursor = connection.execute(
            "INSERT INTO batches(name, import_id, status) VALUES (?, ?, 'selected')", (name, import_id)
        )
        batch_id = int(cursor.lastrowid)
        for rank, product in enumerate(products, start=1):
            connection.execute(
                "INSERT INTO batch_items(batch_id, product_id, rank) VALUES (?, ?, ?)",
                (batch_id, product["id"], rank),
            )
    return {
        "batch_id": batch_id,
        "name": name,
        "items": len(products),
        "handles": [row["handle"] for row in products],
    }


def latest_batch_id(workspace: Path) -> int:
    with connect(workspace) as connection:
        row = connection.execute("SELECT id FROM batches ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError("No batch exists")
    return int(row["id"])
