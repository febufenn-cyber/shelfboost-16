from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from .common import clean_text, first_value, json_dumps, normalized, sha256_file
from .db import connect

SEVERITY_WEIGHT = {"critical": 30, "high": 14, "medium": 6, "low": 2}
RISKY_CLAIM_RE = re.compile(
    r"\b(cure[sd]?|clinically proven|100% safe|guaranteed results?|doctor approved|"
    r"certified organic|eco[- ]?friendly|non[- ]?toxic|medical grade)\b",
    re.IGNORECASE,
)

CATEGORY_ALIASES = {
    "shirt": "apparel",
    "shirts": "apparel",
    "dress": "apparel",
    "dresses": "apparel",
    "apparel": "apparel",
    "clothing": "apparel",
    "lamp": "home_decor",
    "lamps": "home_decor",
    "decor": "home_decor",
    "home decor": "home_decor",
    "furniture": "home_decor",
    "jewelry": "jewelry",
    "jewellery": "jewelry",
}


def classify_category(product_type: str, tags: str) -> str:
    haystack = f"{product_type} {tags}".lower()
    for alias, key in CATEGORY_ALIASES.items():
        if alias in haystack:
            return key
    return "general"


def _group_rows(rows: list[dict[str, str]]) -> list[tuple[str, list[tuple[int, dict[str, str]]]]]:
    grouped: dict[str, list[tuple[int, dict[str, str]]]] = {}
    order: list[str] = []
    for index, row in enumerate(rows, start=1):
        handle = first_value(row, "Handle", "handle") or f"row-{index}"
        if handle not in grouped:
            grouped[handle] = []
            order.append(handle)
        grouped[handle].append((index, row))
    return [(handle, grouped[handle]) for handle in order]


def _representative(rows: list[tuple[int, dict[str, str]]]) -> tuple[int, dict[str, str]]:
    primary_index, primary = rows[0]
    merged = dict(primary)
    for _, row in rows[1:]:
        for key, value in row.items():
            if not (merged.get(key) or "").strip() and (value or "").strip():
                merged[key] = value
    return primary_index, merged


def _extract_facts(row: dict[str, str]) -> list[tuple[str, str, str, str]]:
    facts: list[tuple[str, str, str, str]] = []
    standard = {
        "vendor": first_value(row, "Vendor", "vendor"),
        "product_type": first_value(row, "Type", "Product Type", "product_type"),
    }
    for name, value in standard.items():
        if value:
            facts.append((name, value, name, "structured"))

    for field, value in row.items():
        value = (value or "").strip()
        if not value:
            continue
        lower = field.lower().strip()
        if lower.startswith("fact:"):
            name = field.split(":", 1)[1].strip().lower().replace(" ", "_")
            facts.append((name, value, field, "merchant_fact"))
        elif lower.startswith("metafield: facts."):
            name = field.split(".", 1)[1].strip().lower().replace(" ", "_")
            facts.append((name, value, field, "merchant_fact"))
    return facts


def _audit_rows(products: Iterable[dict[str, str]]) -> tuple[Counter[str], Counter[str]]:
    titles: Counter[str] = Counter()
    bodies: Counter[str] = Counter()
    for row in products:
        title = normalized(first_value(row, "Title", "title"))
        body = normalized(first_value(row, "Body (HTML)", "Body", "Description", "description"))
        if title:
            titles[title] += 1
        if len(body) >= 40:
            bodies[body] += 1
    return titles, bodies


def audit_product(row: dict[str, str], title_counts: Counter[str], body_counts: Counter[str], fact_count: int) -> dict:
    findings: list[dict[str, str]] = []

    def add(severity: str, code: str, evidence: str) -> None:
        findings.append({"severity": severity, "code": code, "evidence": evidence})

    title = first_value(row, "Title", "title")
    body = clean_text(first_value(row, "Body (HTML)", "Body", "Description", "description"))
    seo_title = first_value(row, "SEO Title", "SEO title", "seo_title")
    seo_description = first_value(row, "SEO Description", "SEO description", "Meta Description", "seo_description")
    alt_text = first_value(row, "Image Alt Text", "Alt Text", "image_alt_text")

    if not title:
        add("critical", "missing_title", "Product title is empty")
    elif title_counts[normalized(title)] > 1:
        add("high", "duplicate_title", f"Normalized title appears {title_counts[normalized(title)]} times")

    words = len(body.split())
    if not body:
        add("critical", "missing_description", "Description is empty")
    elif words < 40:
        add("high", "very_thin_description", f"Description contains {words} words")
    elif words < 80:
        add("medium", "thin_description", f"Description contains {words} words")

    normalized_body = normalized(body)
    if len(normalized_body) >= 40 and body_counts[normalized_body] > 1:
        add("high", "duplicate_description", f"Normalized description appears {body_counts[normalized_body]} times")

    risky = sorted({match.group(0).lower() for match in RISKY_CLAIM_RE.finditer(body)})
    if risky:
        add("high", "claim_requires_human_review", "Matched language: " + ", ".join(risky))

    if not seo_title:
        add("high", "missing_seo_title", "SEO title is empty")
    elif len(clean_text(seo_title)) > 60:
        add("medium", "long_seo_title", f"SEO title contains {len(clean_text(seo_title))} characters")

    if not seo_description:
        add("high", "missing_meta_description", "SEO/meta description is empty")
    elif len(clean_text(seo_description)) > 160:
        add("medium", "long_meta_description", f"Meta description contains {len(clean_text(seo_description))} characters")

    if not alt_text:
        add("low", "missing_image_alt_text", "No image alt text found on representative row")

    if fact_count == 0:
        add("high", "no_approved_product_facts", "No merchant-approved copy facts are available")

    penalty = sum(SEVERITY_WEIGHT[item["severity"]] for item in findings)
    priority = min(100, penalty)
    eligibility = "eligible"
    if not title:
        eligibility = "blocked_missing_identity"
    elif fact_count == 0:
        eligibility = "blocked_missing_facts"
    return {"findings": findings, "priority_score": priority, "eligibility": eligibility, "description_words": words}


def import_catalog(workspace: Path, csv_path: Path) -> dict:
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        headers = list(reader.fieldnames)
        rows = [dict(row) for row in reader]

    grouped = _group_rows(rows)
    representatives = [_representative(group)[1] for _, group in grouped]
    title_counts, body_counts = _audit_rows(representatives)

    with connect(workspace) as connection:
        cursor = connection.execute(
            "INSERT INTO catalog_imports(source_name, source_sha256, header_json, row_count, product_count) VALUES (?, ?, ?, ?, ?)",
            (csv_path.name, sha256_file(csv_path), json_dumps(headers), len(rows), len(grouped)),
        )
        import_id = int(cursor.lastrowid)

        for handle, group in grouped:
            primary_index, representative = _representative(group)
            for row_index, row in group:
                connection.execute(
                    "INSERT INTO catalog_rows(import_id, row_index, handle, is_primary, row_json) VALUES (?, ?, ?, ?, ?)",
                    (import_id, row_index, handle, int(row_index == primary_index), json_dumps(row)),
                )

            facts = _extract_facts(representative)
            category = classify_category(
                first_value(representative, "Type", "Product Type", "product_type"),
                first_value(representative, "Tags", "tags"),
            )
            copy_fact_count = sum(1 for _, _, _, source_kind in facts if source_kind == "merchant_fact")
            audit = audit_product(representative, title_counts, body_counts, copy_fact_count)
            product_cursor = connection.execute(
                """
                INSERT INTO products(
                    import_id, handle, title, body_html, vendor, product_type, tags, status,
                    seo_title, seo_description, category_key, primary_row_index, audit_json,
                    priority_score, eligibility
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    handle,
                    first_value(representative, "Title", "title"),
                    first_value(representative, "Body (HTML)", "Body", "Description", "description"),
                    first_value(representative, "Vendor", "vendor"),
                    first_value(representative, "Type", "Product Type", "product_type"),
                    first_value(representative, "Tags", "tags"),
                    first_value(representative, "Status", "status"),
                    first_value(representative, "SEO Title", "SEO title", "seo_title"),
                    first_value(representative, "SEO Description", "SEO description", "Meta Description", "seo_description"),
                    category,
                    primary_index,
                    json_dumps(audit),
                    audit["priority_score"],
                    audit["eligibility"],
                ),
            )
            product_id = int(product_cursor.lastrowid)

            for name, value, source_field, source_kind in facts:
                connection.execute(
                    "INSERT OR IGNORE INTO product_facts(product_id, name, value, source_field, source_kind, approved) VALUES (?, ?, ?, ?, ?, 1)",
                    (product_id, name, value, source_field, source_kind),
                )

            for row_index, row in group:
                connection.execute(
                    """
                    INSERT INTO variants(
                        product_id, row_index, sku, option1_name, option1_value,
                        option2_name, option2_value, option3_name, option3_value, row_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product_id,
                        row_index,
                        first_value(row, "Variant SKU", "SKU"),
                        first_value(row, "Option1 Name"),
                        first_value(row, "Option1 Value"),
                        first_value(row, "Option2 Name"),
                        first_value(row, "Option2 Value"),
                        first_value(row, "Option3 Name"),
                        first_value(row, "Option3 Value"),
                        json_dumps(row),
                    ),
                )

    return {
        "import_id": import_id,
        "source": csv_path.name,
        "rows": len(rows),
        "products": len(grouped),
        "eligible": sum(
            1
            for row in representatives
            if first_value(row, "Title", "title")
            and any(source_kind == "merchant_fact" for _, _, _, source_kind in _extract_facts(row))
        ),
    }


def latest_import_id(workspace: Path) -> int:
    with connect(workspace) as connection:
        row = connection.execute("SELECT id FROM catalog_imports ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError("No catalog import exists")
    return int(row["id"])
