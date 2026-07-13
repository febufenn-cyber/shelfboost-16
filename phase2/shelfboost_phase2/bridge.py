from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .common import canonical_shop_domain, json_dumps, sha256_bytes, write_json
from .db import connect, initialize

BASE_HEADERS = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Type",
    "Tags",
    "Status",
    "SEO Title",
    "SEO Description",
    "Image Alt Text",
    "Variant SKU",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Option3 Name",
    "Option3 Value",
]

ALLOWED_FACT_TYPES = {
    "single_line_text_field",
    "multi_line_text_field",
    "number_integer",
    "number_decimal",
    "boolean",
    "date",
    "date_time",
    "url",
    "color",
}


def _safe_fact_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not key or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
        raise ValueError(f"Unsafe facts metafield key: {value!r}")
    return key


def _json_list(value: str, label: str) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Stored {label} JSON is invalid: {exc}") from exc
    if not isinstance(decoded, list):
        raise ValueError(f"Stored {label} must be a JSON list")
    return decoded


def _fact_values(product: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    values: dict[str, str] = {}
    warnings: list[dict[str, str]] = []
    for metafield in _json_list(product["metafields_json"], "metafields"):
        if not isinstance(metafield, dict) or metafield.get("namespace") != "facts":
            continue
        key = _safe_fact_key(str(metafield.get("key") or ""))
        field_type = str(metafield.get("type") or "")
        raw_value = str(metafield.get("value") or "").strip()
        if not raw_value:
            continue
        if field_type not in ALLOWED_FACT_TYPES:
            warnings.append(
                {
                    "product_gid": product["shopify_gid"],
                    "key": key,
                    "type": field_type,
                    "reason": "unsupported_fact_type",
                }
            )
            continue
        existing = values.get(key)
        if existing is not None and existing != raw_value:
            raise ValueError(
                f"Product {product['shopify_gid']} has conflicting facts.{key} values"
            )
        values[key] = raw_value
    return values, warnings


def _variant_fields(variant: dict[str, Any] | None) -> dict[str, str]:
    row = {
        "Variant SKU": "",
        "Option1 Name": "",
        "Option1 Value": "",
        "Option2 Name": "",
        "Option2 Value": "",
        "Option3 Name": "",
        "Option3 Value": "",
    }
    if variant is None:
        return row
    row["Variant SKU"] = variant["sku"] or ""
    options = _json_list(variant["options_json"], "variant options")
    for index, option in enumerate(options[:3], start=1):
        if not isinstance(option, dict):
            raise ValueError(f"Variant {variant['shopify_gid']} contains an invalid option")
        row[f"Option{index} Name"] = str(option.get("name") or "")
        row[f"Option{index} Value"] = str(option.get("value") or "")
    return row


def export_phase1_catalog(
    workspace: Path,
    shop_domain: str,
    output_csv: Path,
) -> dict[str, Any]:
    """Export the current read-only mirror as a Phase 1-compatible Shopify CSV.

    The bridge fails closed when completeness or freshness cannot be established.
    """
    initialize(workspace)
    domain = canonical_shop_domain(shop_domain)
    with connect(workspace) as connection:
        shop_row = connection.execute(
            "SELECT id, domain, api_version, active, uninstalled_at FROM shops WHERE domain=?",
            (domain,),
        ).fetchone()
        if not shop_row:
            raise LookupError(f"Shop is not registered: {domain}")
        shop = dict(shop_row)
        if int(shop["active"]) != 1:
            raise PermissionError("Cannot bridge an inactive or uninstalled shop")

        baseline = connection.execute(
            """
            SELECT id, completed_at, observed_api_version
            FROM sync_runs
            WHERE shop_id=? AND mode='full' AND status='completed'
            ORDER BY id DESC LIMIT 1
            """,
            (shop["id"],),
        ).fetchone()
        if not baseline:
            raise RuntimeError("A completed full sync is required before Phase 1 export")
        latest = connection.execute(
            """
            SELECT id, mode, completed_at, observed_api_version
            FROM sync_runs
            WHERE shop_id=? AND status='completed'
            ORDER BY id DESC LIMIT 1
            """,
            (shop["id"],),
        ).fetchone()

        unresolved = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM refresh_queue
            WHERE shop_id=? AND status IN ('pending','processing','failed')
            GROUP BY status
            """,
            (shop["id"],),
        ).fetchall()
        if unresolved:
            detail = ", ".join(f"{row['status']}={row['count']}" for row in unresolved)
            raise RuntimeError(f"Refresh queue is not clean: {detail}")

        product_rows = connection.execute(
            """
            SELECT * FROM shopify_products
            WHERE shop_id=? AND is_deleted=0
            ORDER BY handle, id
            """,
            (shop["id"],),
        ).fetchall()
        products = [dict(row) for row in product_rows]
        incomplete = [item["shopify_gid"] for item in products if int(item["variants_complete"]) != 1]
        if incomplete:
            raise RuntimeError("Variant data is incomplete for: " + ", ".join(incomplete))

        handles = [item["handle"] for item in products]
        if any(not handle for handle in handles):
            raise RuntimeError("All active products must have a handle")
        if len(handles) != len(set(handles)):
            raise RuntimeError("Active product handles are not unique")

        facts_by_product: dict[int, dict[str, str]] = {}
        warning_rows: list[dict[str, str]] = []
        all_fact_keys: set[str] = set()
        for product in products:
            facts, warnings = _fact_values(product)
            facts_by_product[int(product["id"])] = facts
            warning_rows.extend(warnings)
            all_fact_keys.update(facts)

        variants_by_product: dict[int, list[dict[str, Any]]] = {}
        for product in products:
            variants_by_product[int(product["id"])] = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM shopify_variants WHERE product_id=? ORDER BY id",
                    (product["id"],),
                ).fetchall()
            ]

    fact_keys = sorted(all_fact_keys)
    fact_headers = [f"Metafield: facts.{key}" for key in fact_keys]
    headers = BASE_HEADERS + fact_headers
    output_csv = output_csv.resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    provenance: list[dict[str, Any]] = []
    row_count = 0
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        for product in products:
            product_id = int(product["id"])
            variants = variants_by_product[product_id] or [None]
            tags = _json_list(product["tags_json"], "tags")
            if not all(isinstance(tag, str) for tag in tags):
                raise ValueError(f"Product {product['shopify_gid']} has non-string tags")
            facts = facts_by_product[product_id]
            for index, variant in enumerate(variants):
                row = {header: "" for header in headers}
                row["Handle"] = product["handle"]
                row.update(_variant_fields(variant))
                if index == 0:
                    row.update(
                        {
                            "Title": product["title"],
                            "Body (HTML)": product["description_html"],
                            "Vendor": product["vendor"],
                            "Type": product["product_type"],
                            "Tags": ", ".join(tags),
                            "Status": product["status"].lower(),
                            "SEO Title": product["seo_title"],
                            "SEO Description": product["seo_description"],
                        }
                    )
                    for key, value in facts.items():
                        row[f"Metafield: facts.{key}"] = value
                writer.writerow(row)
                row_count += 1
            provenance.append(
                {
                    "shopify_gid": product["shopify_gid"],
                    "legacy_id": product["legacy_id"],
                    "handle": product["handle"],
                    "updated_at_shopify": product["updated_at_shopify"],
                    "last_seen_run_id": product["last_seen_run_id"],
                    "variant_count": len(variants_by_product[product_id]),
                    "fact_keys": sorted(facts),
                }
            )

    csv_digest = sha256_bytes(output_csv.read_bytes())
    manifest_path = output_csv.with_name(output_csv.stem + ".manifest.json")
    manifest = {
        "format": "shelfboost-phase1-bridge-v1",
        "shop": domain,
        "shop_api_version": shop["api_version"],
        "baseline_full_sync": {
            "run_id": int(baseline["id"]),
            "completed_at": baseline["completed_at"],
            "observed_api_version": baseline["observed_api_version"],
        },
        "latest_completed_sync": {
            "run_id": int(latest["id"]),
            "mode": latest["mode"],
            "completed_at": latest["completed_at"],
            "observed_api_version": latest["observed_api_version"],
        },
        "output_csv": output_csv.name,
        "csv_sha256": csv_digest,
        "product_count": len(products),
        "row_count": row_count,
        "fact_headers": fact_headers,
        "warnings": warning_rows,
        "products": provenance,
        "trust_boundary": [
            "Only active, non-deleted products are exported.",
            "A completed full sync and a clean refresh queue are required.",
            "Only allowlisted scalar facts metafields are admitted to the Phase 1 fact ledger.",
            "The CSV is an input to human-reviewed Phase 1 drafting, not a Shopify write operation.",
        ],
    }
    write_json(manifest_path, manifest)

    with connect(workspace) as connection:
        connection.execute(
            """
            INSERT INTO bridge_exports(
                shop_id, sync_run_id, output_name, csv_sha256,
                product_count, row_count, manifest_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shop["id"],
                latest["id"],
                output_csv.name,
                csv_digest,
                len(products),
                row_count,
                json_dumps(manifest),
            ),
        )

    return {
        "shop": domain,
        "output_csv": str(output_csv),
        "manifest": str(manifest_path),
        "csv_sha256": csv_digest,
        "products": len(products),
        "rows": row_count,
        "fact_headers": fact_headers,
        "warnings": len(warning_rows),
    }
