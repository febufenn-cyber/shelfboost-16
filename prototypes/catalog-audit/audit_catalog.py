#!/usr/bin/env python3
"""Deterministic, read-only Shopify CSV catalog audit for Phase 0.

The tool produces evidence-oriented flags. It does not call Shopify, use an AI
model, alter input data, or claim that a content score predicts SEO outcomes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
RISKY_CLAIM_RE = re.compile(
    r"\b(cure[sd]?|clinically proven|100% safe|guaranteed results?|doctor approved|"
    r"certified organic|eco[- ]?friendly|non[- ]?toxic|medical grade)\b",
    re.IGNORECASE,
)
GENERIC_PHRASES = (
    "high quality",
    "premium quality",
    "best in class",
    "must-have",
    "perfect for everyone",
)
SEVERITY_WEIGHT = {"critical": 25, "high": 12, "medium": 5, "low": 2}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    evidence: str


@dataclass
class ProductAudit:
    handle: str
    title: str
    status: str
    vendor: str
    product_type: str
    description_words: int
    health_score: int
    findings: list[Finding]

    @property
    def priority_score(self) -> int:
        return 100 - self.health_score


def clean_text(value: str | None) -> str:
    raw = html.unescape(value or "")
    no_tags = HTML_TAG_RE.sub(" ", raw)
    return SPACE_RE.sub(" ", no_tags).strip()


def normalized(value: str | None) -> str:
    text = clean_text(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def first_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return row[name].strip()
    return ""


def load_products(path: Path) -> list[dict[str, str]]:
    """Collapse Shopify variant rows into one representative product row."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        rows = list(reader)

    products: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=1):
        handle_value = first_value(row, "Handle", "handle") or f"row-{index}"
        if handle_value not in products:
            products[handle_value] = row
            continue
        existing = products[handle_value]
        for key, value in row.items():
            if not (existing.get(key) or "").strip() and (value or "").strip():
                existing[key] = value
    return list(products.values())


def fingerprint(value: str) -> str:
    return hashlib.sha256(normalized(value).encode("utf-8")).hexdigest()


def duplicate_maps(products: Iterable[dict[str, str]]) -> tuple[Counter[str], Counter[str]]:
    title_counts: Counter[str] = Counter()
    body_counts: Counter[str] = Counter()
    for row in products:
        title = first_value(row, "Title", "title")
        body = first_value(row, "Body (HTML)", "Body", "Description", "description")
        if normalized(title):
            title_counts[fingerprint(title)] += 1
        if len(normalized(body)) >= 40:
            body_counts[fingerprint(body)] += 1
    return title_counts, body_counts


def audit_product(row: dict[str, str], title_counts: Counter[str], body_counts: Counter[str]) -> ProductAudit:
    handle_value = first_value(row, "Handle", "handle") or "unknown"
    title = first_value(row, "Title", "title")
    body_html = first_value(row, "Body (HTML)", "Body", "Description", "description")
    body = clean_text(body_html)
    seo_title = first_value(row, "SEO Title", "SEO title", "seo_title")
    seo_description = first_value(row, "SEO Description", "SEO description", "Meta Description", "seo_description")
    alt_text = first_value(row, "Image Alt Text", "Alt Text", "image_alt_text")
    status = first_value(row, "Status", "status")
    vendor = first_value(row, "Vendor", "vendor")
    product_type = first_value(row, "Type", "Product Type", "product_type")
    findings: list[Finding] = []

    def add(severity: str, code: str, evidence: str) -> None:
        findings.append(Finding(severity, code, evidence))

    if not title:
        add("critical", "missing_title", "Product title is empty")
    elif title_counts[fingerprint(title)] > 1:
        add("high", "duplicate_title", f"Normalized title appears {title_counts[fingerprint(title)]} times")

    words = len(body.split())
    if not body:
        add("critical", "missing_description", "Description is empty")
    elif words < 40:
        add("high", "very_thin_description", f"Description contains {words} words")
    elif words < 80:
        add("medium", "thin_description", f"Description contains {words} words")

    if body and len(normalized(body)) >= 40 and body_counts[fingerprint(body)] > 1:
        add("high", "duplicate_description", f"Normalized description appears {body_counts[fingerprint(body)]} times")

    lower_body = body.lower()
    matched_generic = [phrase for phrase in GENERIC_PHRASES if phrase in lower_body]
    if matched_generic:
        add("low", "generic_language", "Matched: " + ", ".join(matched_generic))

    risky = sorted({match.group(0).lower() for match in RISKY_CLAIM_RE.finditer(body)})
    if risky:
        add("high", "claim_requires_human_review", "Matched language: " + ", ".join(risky))

    if not seo_title:
        add("high", "missing_seo_title", "SEO title is empty")
    else:
        seo_title_length = len(clean_text(seo_title))
        if seo_title_length > 60:
            add("medium", "long_seo_title", f"SEO title contains {seo_title_length} characters")
        elif seo_title_length < 20:
            add("low", "short_seo_title", f"SEO title contains {seo_title_length} characters")

    if not seo_description:
        add("high", "missing_meta_description", "SEO/meta description is empty")
    else:
        meta_length = len(clean_text(seo_description))
        if meta_length > 160:
            add("medium", "long_meta_description", f"Meta description contains {meta_length} characters")
        elif meta_length < 70:
            add("low", "short_meta_description", f"Meta description contains {meta_length} characters")

    if not alt_text:
        add("low", "missing_image_alt_text", "No image alt text found on the representative row")

    penalty = sum(SEVERITY_WEIGHT[item.severity] for item in findings)
    score = max(0, 100 - min(100, penalty))
    return ProductAudit(
        handle=handle_value,
        title=title,
        status=status,
        vendor=vendor,
        product_type=product_type,
        description_words=words,
        health_score=score,
        findings=findings,
    )


def write_outputs(audits: list[ProductAudit], output_dir: Path, source: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(audits, key=lambda item: (-item.priority_score, item.handle))
    csv_path = output_dir / "catalog-audit.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "handle", "title", "status", "vendor", "product_type",
            "description_words", "health_score", "priority_score",
            "severity_max", "finding_codes", "evidence",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for audit in ordered:
            severities = [item.severity for item in audit.findings]
            severity_order = ["critical", "high", "medium", "low"]
            severity_max = next((level for level in severity_order if level in severities), "none")
            writer.writerow({
                "handle": audit.handle,
                "title": audit.title,
                "status": audit.status,
                "vendor": audit.vendor,
                "product_type": audit.product_type,
                "description_words": audit.description_words,
                "health_score": audit.health_score,
                "priority_score": audit.priority_score,
                "severity_max": severity_max,
                "finding_codes": "|".join(item.code for item in audit.findings),
                "evidence": " || ".join(item.evidence for item in audit.findings),
            })

    finding_counts = Counter(item.code for audit in audits for item in audit.findings)
    severity_counts = Counter(item.severity for audit in audits for item in audit.findings)
    summary = {
        "source_file": source.name,
        "products_audited": len(audits),
        "average_health_score": round(sum(item.health_score for item in audits) / len(audits), 1) if audits else None,
        "products_with_findings": sum(bool(item.findings) for item in audits),
        "severity_counts": dict(sorted(severity_counts.items())),
        "finding_counts": dict(sorted(finding_counts.items())),
        "top_priority": [
            {
                "handle": item.handle,
                "title": item.title,
                "health_score": item.health_score,
                "finding_codes": [finding.code for finding in item.findings],
            }
            for item in ordered[:10]
        ],
        "limitations": [
            "Content checks do not predict search ranking, traffic, conversion, or revenue.",
            "Claim-language matches require human verification and are not declarations of falsity.",
            "Variant rows are collapsed by Handle; category-specific metafields require separate review.",
        ],
    }
    (output_dir / "catalog-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a read-only Phase 0 Shopify CSV catalog audit")
    parser.add_argument("csv_path", type=Path, help="Path to a Shopify products CSV export")
    parser.add_argument("--output-dir", type=Path, default=Path(".audit-output"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.csv_path.is_file():
        raise SystemExit(f"Input CSV not found: {args.csv_path}")
    products = load_products(args.csv_path)
    title_counts, body_counts = duplicate_maps(products)
    audits = [audit_product(row, title_counts, body_counts) for row in products]
    write_outputs(audits, args.output_dir, args.csv_path)
    print(f"Audited {len(audits)} products")
    print(f"Wrote {args.output_dir / 'catalog-audit.csv'}")
    print(f"Wrote {args.output_dir / 'catalog-summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
