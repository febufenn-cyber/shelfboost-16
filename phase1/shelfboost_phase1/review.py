from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from .batches import latest_batch_id
from .brand import active_profile
from .common import json_loads
from .db import connect
from .generation import validate_draft

DECISIONS = {"approved", "edited", "rejected", "deferred"}


def create_review_pack(workspace: Path, batch_id: int | None = None) -> dict:
    batch_id = batch_id or latest_batch_id(workspace)
    output_dir = workspace / "artifacts" / f"batch-{batch_id}-review"
    output_dir.mkdir(parents=True, exist_ok=True)
    with connect(workspace) as connection:
        rows = connection.execute(
            """
            SELECT d.*, p.handle, p.title, p.category_key, bi.rank
            FROM drafts d
            JOIN batch_items bi ON bi.id=d.batch_item_id
            JOIN products p ON p.id=bi.product_id
            WHERE bi.batch_id=?
            ORDER BY bi.rank, d.field_name
            """,
            (batch_id,),
        ).fetchall()
    decision_path = output_dir / "review-decisions.csv"
    with decision_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["draft_id", "handle", "field_name", "validation_status", "decision", "edited_value", "reviewer_note"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "draft_id": row["id"],
                "handle": row["handle"],
                "field_name": row["field_name"],
                "validation_status": row["validation_status"],
                "decision": "",
                "edited_value": "",
                "reviewer_note": "",
            })

    cards: list[str] = []
    for row in rows:
        facts = json.loads(row["facts_used_json"])
        validation = json.loads(row["validation_json"])
        fact_list = "".join(
            f"<li><strong>{html.escape(item['name'])}</strong>: {html.escape(item['value'])} <small>({html.escape(item['source_field'])})</small></li>"
            for item in facts
        ) or "<li>No approved facts available</li>"
        cards.append(f"""
        <article class="card {html.escape(row['validation_status'])}">
          <header><span>#{row['rank']} · {html.escape(row['handle'])}</span><strong>{html.escape(row['field_name'])}</strong></header>
          <h2>{html.escape(row['title'])}</h2>
          <div class="columns"><section><h3>Original</h3><pre>{html.escape(row['original_value'])}</pre></section>
          <section><h3>Proposed</h3><pre>{html.escape(row['proposed_value'])}</pre></section></div>
          <details><summary>Facts and validation</summary><ul>{fact_list}</ul><pre>{html.escape(json.dumps(validation, indent=2))}</pre></details>
          <p class="status">Validation: {html.escape(row['validation_status'])}</p>
        </article>
        """)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Shelfboost review batch {batch_id}</title><style>
    body{{font-family:system-ui,sans-serif;margin:0;background:#f5f5f3;color:#181816}}main{{max-width:1200px;margin:auto;padding:32px}}
    .card{{background:white;border:1px solid #ddd;border-radius:14px;padding:20px;margin:18px 0}}.card.blocked{{border-left:6px solid #a33}}
    header{{display:flex;justify-content:space-between;gap:20px}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
    pre{{white-space:pre-wrap;background:#f7f7f5;padding:14px;border-radius:8px;min-height:80px}}small{{color:#666}}.status{{font-weight:700}}
    @media(max-width:760px){{.columns{{grid-template-columns:1fr}}}}
    </style></head><body><main><h1>Shelfboost review batch {batch_id}</h1>
    <p>Read-only review pack. Record decisions in <code>review-decisions.csv</code>. Blocked drafts cannot be exported as approved.</p>
    {''.join(cards)}</main></body></html>"""
    html_path = output_dir / "review.html"
    html_path.write_text(page, encoding="utf-8")
    return {"batch_id": batch_id, "drafts": len(rows), "html": str(html_path), "decisions": str(decision_path)}


def apply_decisions(workspace: Path, decisions_path: Path) -> dict:
    applied = 0
    skipped = 0
    _, profile = active_profile(workspace)
    with decisions_path.open("r", encoding="utf-8-sig", newline="") as handle, connect(workspace) as connection:
        reader = csv.DictReader(handle)
        required = {"draft_id", "decision", "edited_value", "reviewer_note"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("Decision CSV is missing required columns")
        for row in reader:
            decision = (row.get("decision") or "").strip().lower()
            if not decision:
                skipped += 1
                continue
            if decision not in DECISIONS:
                raise ValueError(f"Invalid decision for draft {row.get('draft_id')}: {decision}")
            draft = connection.execute(
                "SELECT field_name, validation_status, facts_used_json FROM drafts WHERE id=?",
                (int(row["draft_id"]),),
            ).fetchone()
            if not draft:
                raise ValueError(f"Unknown draft id: {row['draft_id']}")
            if decision in {"approved", "edited"} and draft["validation_status"] != "pass":
                raise ValueError(f"Blocked draft {row['draft_id']} cannot be approved")
            edited_value = row.get("edited_value") or ""
            if decision == "edited" and not edited_value.strip():
                raise ValueError(f"Edited draft {row['draft_id']} requires edited_value")
            if decision == "edited":
                status, validation, _ = validate_draft(
                    draft["field_name"], edited_value, json_loads(draft["facts_used_json"], []), profile
                )
                if status != "pass":
                    raise ValueError(
                        f"Edited draft {row['draft_id']} failed validation: "
                        + ", ".join(validation["errors"])
                    )
            connection.execute(
                """
                INSERT INTO reviews(draft_id, decision, edited_value, reviewer_note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    decision=excluded.decision,
                    edited_value=excluded.edited_value,
                    reviewer_note=excluded.reviewer_note,
                    reviewed_at=CURRENT_TIMESTAMP
                """,
                (int(row["draft_id"]), decision, edited_value, row.get("reviewer_note") or ""),
            )
            applied += 1
    return {"applied": applied, "skipped_blank": skipped}
