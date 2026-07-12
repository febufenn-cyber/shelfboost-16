from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .brand import active_profile
from .batches import latest_batch_id
from .common import clean_text, json_dumps, normalized
from .db import connect

RISKY_CLAIM_RE = re.compile(
    r"\b(cure[sd]?|clinically proven|100% safe|guaranteed results?|doctor approved|"
    r"certified organic|eco[- ]?friendly|non[- ]?toxic|medical grade)\b",
    re.IGNORECASE,
)
ALLOWED_HTML_RE = re.compile(r"</?(?:p|ul|li|strong|em|br)\s*/?>", re.IGNORECASE)
ANY_HTML_RE = re.compile(r"<[^>]+>")


def _load_template(template_dir: Path, category_key: str) -> dict:
    candidate = template_dir / f"{category_key}.json"
    if not candidate.exists():
        candidate = template_dir / "general.json"
    return json.loads(candidate.read_text(encoding="utf-8"))


def _fact_sentence(facts: list[dict], max_items: int = 4) -> str:
    selected = facts[:max_items]
    return "; ".join(f"{item['name'].replace('_', ' ')}: {item['value']}" for item in selected)


def _description(title: str, facts: list[dict], profile: dict, template: dict) -> str:
    if not facts:
        return ""
    intro = profile.get("opening_pattern", "Verified details for {title} are presented below.").format(title=title)
    items = "".join(
        f"<li><strong>{html.escape(item['name'].replace('_', ' ').title())}:</strong> {html.escape(item['value'])}</li>"
        for item in facts[: template.get("max_facts", 6)]
    )
    return f"<p>{html.escape(intro)}</p><ul>{items}</ul>"


def _seo_title(title: str, profile: dict) -> str:
    value = f"{title} | {profile['brand_name']}"
    return value[:60].rstrip(" |-")


def _seo_description(title: str, facts: list[dict], profile: dict) -> str:
    fact_text = _fact_sentence(facts, max_items=3)
    value = f"Shop {title} from {profile['brand_name']}. {fact_text}." if fact_text else ""
    return value[:160].rstrip(" ;,.") + ("." if value else "")


def validate_draft(field_name: str, proposed: str, facts: list[dict], profile: dict) -> tuple[str, dict, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not proposed.strip():
        errors.append("empty_output")

    lower = clean_text(proposed).lower()
    prohibited = [term for term in profile.get("prohibited_terms", []) if term.lower() in lower]
    if prohibited:
        errors.append("prohibited_terms:" + ",".join(sorted(set(prohibited))))

    risky = sorted({match.group(0).lower() for match in RISKY_CLAIM_RE.finditer(proposed)})
    if risky:
        errors.append("risky_claim_language:" + ",".join(risky))

    if field_name == "Body (HTML)":
        remaining = ANY_HTML_RE.sub(lambda match: "" if ALLOWED_HTML_RE.fullmatch(match.group(0)) else match.group(0), proposed)
        if ANY_HTML_RE.search(remaining):
            errors.append("unsafe_html_tag")
        for fact in facts:
            if normalized(fact["value"]) and normalized(fact["value"]) not in normalized(proposed):
                warnings.append(f"fact_not_rendered:{fact['name']}")
    elif field_name == "SEO Title" and len(clean_text(proposed)) > 60:
        errors.append("seo_title_too_long")
    elif field_name == "SEO Description" and len(clean_text(proposed)) > 160:
        errors.append("seo_description_too_long")

    return ("blocked" if errors else "pass"), {"errors": errors, "warnings": warnings}, warnings


def generate_batch(workspace: Path, template_dir: Path, batch_id: int | None = None) -> dict:
    batch_id = batch_id or latest_batch_id(workspace)
    brand_profile_id, profile = active_profile(workspace)
    created = 0
    blocked = 0
    with connect(workspace) as connection:
        items = connection.execute(
            """
            SELECT bi.id AS batch_item_id, p.*
            FROM batch_items bi
            JOIN products p ON p.id = bi.product_id
            WHERE bi.batch_id = ?
            ORDER BY bi.rank
            """,
            (batch_id,),
        ).fetchall()
        for product in items:
            facts = [dict(row) for row in connection.execute(
                "SELECT id, name, value, source_field, source_kind FROM product_facts WHERE product_id = ? AND approved = 1 AND source_kind = 'merchant_fact' ORDER BY id",
                (product["id"],),
            ).fetchall()]
            template = _load_template(template_dir, product["category_key"])
            required = set(template.get("required_facts", []))
            available = {item["name"] for item in facts}
            missing_required = sorted(required - available)
            fields = {
                "Body (HTML)": (product["body_html"], _description(product["title"], facts, profile, template)),
                "SEO Title": (product["seo_title"], _seo_title(product["title"], profile)),
                "SEO Description": (product["seo_description"], _seo_description(product["title"], facts, profile)),
            }
            for field_name, (original, proposed) in fields.items():
                status, validation, warnings = validate_draft(field_name, proposed, facts, profile)
                if field_name == "Body (HTML)" and missing_required:
                    validation["errors"].append("missing_required_facts:" + ",".join(missing_required))
                    status = "blocked"
                if status == "blocked":
                    blocked += 1
                connection.execute(
                    """
                    INSERT INTO drafts(
                        batch_item_id, field_name, original_value, proposed_value,
                        facts_used_json, warnings_json, provider, brand_profile_id, template_key, template_version,
                        validation_status, validation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 'deterministic-safe-v1', ?, ?, '1', ?, ?)
                    ON CONFLICT(batch_item_id, field_name) DO UPDATE SET
                        original_value=excluded.original_value,
                        proposed_value=excluded.proposed_value,
                        facts_used_json=excluded.facts_used_json,
                        warnings_json=excluded.warnings_json,
                        provider=excluded.provider,
                        brand_profile_id=excluded.brand_profile_id,
                        template_key=excluded.template_key,
                        template_version=excluded.template_version,
                        validation_status=excluded.validation_status,
                        validation_json=excluded.validation_json,
                        created_at=CURRENT_TIMESTAMP
                    """,
                    (
                        product["batch_item_id"],
                        field_name,
                        original or "",
                        proposed,
                        json_dumps(facts),
                        json_dumps(warnings),
                        brand_profile_id,
                        product["category_key"],
                        status,
                        json_dumps(validation),
                    ),
                )
                created += 1

        duplicate_rows = connection.execute(
            "SELECT field_name, proposed_value, COUNT(*) AS count FROM drafts d JOIN batch_items bi ON bi.id=d.batch_item_id WHERE bi.batch_id=? AND validation_status='pass' GROUP BY field_name, proposed_value HAVING count > 1",
            (batch_id,),
        ).fetchall()
        duplicates = 0
        for duplicate in duplicate_rows:
            if len(normalized(duplicate["proposed_value"])) < 10:
                continue
            cursor = connection.execute(
                """
                UPDATE drafts SET validation_status='blocked',
                validation_json=json_set(validation_json, '$.errors[#]', 'duplicate_batch_output')
                WHERE id IN (
                    SELECT d.id FROM drafts d JOIN batch_items bi ON bi.id=d.batch_item_id
                    WHERE bi.batch_id=? AND d.field_name=? AND d.proposed_value=?
                )
                """,
                (batch_id, duplicate["field_name"], duplicate["proposed_value"]),
            )
            duplicates += cursor.rowcount
        connection.execute("UPDATE batches SET status='generated' WHERE id=?", (batch_id,))
    return {"batch_id": batch_id, "drafts": created, "blocked_initial": blocked, "blocked_duplicates": duplicates}
