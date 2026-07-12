from __future__ import annotations

import csv
import json
from pathlib import Path

from .batches import latest_batch_id
from .common import json_loads
from .db import connect

FIELD_COLUMNS = {
    "Body (HTML)": "Body (HTML)",
    "SEO Title": "SEO Title",
    "SEO Description": "SEO Description",
}


def export_approved(workspace: Path, output_path: Path, batch_id: int | None = None) -> dict:
    batch_id = batch_id or latest_batch_id(workspace)
    with connect(workspace) as connection:
        batch = connection.execute("SELECT import_id FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise ValueError(f"Unknown batch: {batch_id}")
        import_row = connection.execute(
            "SELECT header_json FROM catalog_imports WHERE id=?", (batch["import_id"],)
        ).fetchone()
        headers = json.loads(import_row["header_json"])
        rows = [
            dict(json_loads(row["row_json"], {}))
            for row in connection.execute(
                "SELECT row_json FROM catalog_rows WHERE import_id=? ORDER BY row_index",
                (batch["import_id"],),
            ).fetchall()
        ]
        row_positions = {
            row["row_index"]: index
            for index, row in enumerate(
                connection.execute(
                    "SELECT row_index FROM catalog_rows WHERE import_id=? ORDER BY row_index",
                    (batch["import_id"],),
                ).fetchall()
            )
        }
        changes = connection.execute(
            """
            SELECT p.handle, p.primary_row_index, d.field_name, d.original_value, d.proposed_value,
                   r.decision, r.edited_value, r.reviewer_note
            FROM reviews r
            JOIN drafts d ON d.id=r.draft_id
            JOIN batch_items bi ON bi.id=d.batch_item_id
            JOIN products p ON p.id=bi.product_id
            WHERE bi.batch_id=? AND r.decision IN ('approved','edited') AND d.validation_status='pass'
            ORDER BY bi.rank, d.field_name
            """,
            (batch_id,),
        ).fetchall()

        changelog: list[dict] = []
        for change in changes:
            column = FIELD_COLUMNS.get(change["field_name"])
            if not column:
                continue
            if column not in headers:
                headers.append(column)
                for row in rows:
                    row[column] = ""
            position = row_positions[int(change["primary_row_index"])]
            final_value = change["edited_value"] if change["decision"] == "edited" else change["proposed_value"]
            rows[position][column] = final_value
            changelog.append({
                "handle": change["handle"],
                "field": column,
                "decision": change["decision"],
                "original": change["original_value"],
                "final": final_value,
                "reviewer_note": change["reviewer_note"],
            })

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        changelog_path = output_path.with_suffix(".changes.json")
        changelog_path.write_text(
            json.dumps(changelog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        connection.execute(
            "INSERT INTO exports(batch_id, output_name, change_count, changelog_json) VALUES (?, ?, ?, ?)",
            (batch_id, output_path.name, len(changelog), json.dumps(changelog, ensure_ascii=False)),
        )
        connection.execute("UPDATE batches SET status='exported' WHERE id=?", (batch_id,))
    return {
        "batch_id": batch_id,
        "changes": len(changelog),
        "csv": str(output_path),
        "changelog": str(changelog_path),
    }
