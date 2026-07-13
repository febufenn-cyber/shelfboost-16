from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from shelfboost_phase2.common import canonical_shop_domain, json_dumps, sha256_bytes, write_json
from shelfboost_phase2.db import connect

from .db import initialize

FIELD_MAP = {
    "Body (HTML)": "description_html",
    "SEO Title": "seo_title",
    "SEO Description": "seo_description",
}
MUTABLE_FIELDS = tuple(FIELD_MAP)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _primary_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Approved CSV has no header row")
        missing = [name for name in ("Handle", *MUTABLE_FIELDS) if name not in reader.fieldnames]
        if missing:
            raise ValueError("Approved CSV is missing columns: " + ", ".join(missing))
        rows: dict[str, dict[str, str]] = {}
        for raw in reader:
            handle_value = (raw.get("Handle") or "").strip()
            if not handle_value:
                continue
            if handle_value not in rows:
                rows[handle_value] = {key: raw.get(key) or "" for key in reader.fieldnames}
        return rows


def _load_changes(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError("Phase 1 changes JSON must be a list")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Change {index} is not an object")
        handle = str(item.get("handle") or "").strip()
        field = str(item.get("field") or "").strip()
        decision = str(item.get("decision") or "").strip()
        original = str(item.get("original") or "")
        final = str(item.get("final") or "")
        if not handle:
            raise ValueError(f"Change {index} has no handle")
        if field not in FIELD_MAP:
            raise ValueError(f"Change {index} uses unsupported field: {field}")
        if decision not in {"approved", "edited"}:
            raise ValueError(f"Change {index} is not an approved Phase 1 decision")
        key = (handle, field)
        if key in seen:
            raise ValueError(f"Duplicate change for {handle} / {field}")
        seen.add(key)
        if original == final:
            raise ValueError(f"No-op change for {handle} / {field}")
        result.append(
            {
                "handle": handle,
                "field": field,
                "decision": decision,
                "original": original,
                "final": final,
                "reviewer_note": str(item.get("reviewer_note") or ""),
            }
        )
    if not result:
        raise ValueError("No approved changes were supplied")
    return result


def _field_state(product: dict[str, Any]) -> dict[str, str]:
    return {field: str(product[column] or "") for field, column in FIELD_MAP.items()}


def _snapshot_payload(product: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
    return {
        "shopify_gid": product["shopify_gid"],
        "legacy_id": product["legacy_id"],
        "handle": product["handle"],
        "updated_at_shopify": product["updated_at_shopify"],
        "fields": fields,
        "source_payload": json.loads(product["payload_json"] or "{}"),
    }


def _insert_snapshot(connection, item_id: int, kind: str, payload: dict[str, Any]) -> str:
    encoded = json_dumps(payload).encode("utf-8")
    digest = sha256_bytes(encoded)
    connection.execute(
        """
        INSERT INTO publish_snapshots(publish_item_id, kind, payload_sha256, payload_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(publish_item_id, kind) DO UPDATE SET
            payload_sha256=excluded.payload_sha256,
            payload_json=excluded.payload_json,
            created_at=CURRENT_TIMESTAMP
        """,
        (item_id, kind, digest, encoded.decode("utf-8")),
    )
    return digest


def _validate_shop_state(connection, domain: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = connection.execute("SELECT * FROM shops WHERE domain=?", (domain,)).fetchone()
    if not row:
        raise LookupError(f"Shop is not registered: {domain}")
    shop = dict(row)
    if int(shop["active"]) != 1:
        raise PermissionError("Cannot plan a publish for an inactive or uninstalled shop")
    baseline = connection.execute(
        """
        SELECT * FROM sync_runs
        WHERE shop_id=? AND mode='full' AND status='completed'
        ORDER BY id DESC LIMIT 1
        """,
        (shop["id"],),
    ).fetchone()
    if not baseline:
        raise RuntimeError("A completed full sync is required before publishing")
    unresolved = connection.execute(
        """
        SELECT status, COUNT(*) AS count FROM refresh_queue
        WHERE shop_id=? AND status IN ('pending','processing','failed')
        GROUP BY status
        """,
        (shop["id"],),
    ).fetchall()
    if unresolved:
        detail = ", ".join(f"{item['status']}={item['count']}" for item in unresolved)
        raise RuntimeError(f"Refresh queue is not clean: {detail}")
    return shop, dict(baseline)


def plan_publish(
    workspace: Path,
    shop_domain: str,
    approved_csv: Path,
    changes_json: Path,
    bridge_manifest: Path,
) -> dict[str, Any]:
    initialize(workspace)
    domain = canonical_shop_domain(shop_domain)
    approved_csv = approved_csv.resolve()
    changes_json = changes_json.resolve()
    bridge_manifest = bridge_manifest.resolve()
    for path in (approved_csv, changes_json, bridge_manifest):
        if not path.is_file():
            raise FileNotFoundError(path)

    changes = _load_changes(changes_json)
    approved_rows = _primary_rows(approved_csv)
    manifest = _read_json(bridge_manifest)
    if not isinstance(manifest, dict) or manifest.get("format") != "shelfboost-phase1-bridge-v1":
        raise ValueError("Unsupported or invalid Phase 2 bridge manifest")
    if canonical_shop_domain(str(manifest.get("shop") or "")) != domain:
        raise ValueError("Bridge manifest belongs to a different shop")
    provenance_by_handle = {
        str(item.get("handle") or ""): item
        for item in (manifest.get("products") or [])
        if isinstance(item, dict)
    }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for change in changes:
        grouped[change["handle"]].append(change)

    changes_sha = _digest(changes_json)
    approved_sha = _digest(approved_csv)
    manifest_sha = _digest(bridge_manifest)
    identity_payload = {
        "shop": domain,
        "changes_sha256": changes_sha,
        "approved_csv_sha256": approved_sha,
        "bridge_manifest_sha256": manifest_sha,
        "changes": sorted(changes, key=lambda item: (item["handle"], item["field"])),
    }
    idempotency_key = sha256_bytes(json_dumps(identity_payload).encode("utf-8"))

    with connect(workspace) as connection:
        shop, baseline = _validate_shop_state(connection, domain)
        existing = connection.execute(
            "SELECT id, status FROM publish_batches WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return {
                "batch_id": int(existing["id"]),
                "status": existing["status"],
                "idempotency_key": idempotency_key,
                "reused": True,
            }

        cursor = connection.execute(
            """
            INSERT INTO publish_batches(
                shop_id, idempotency_key, source_changes_name, source_changes_sha256,
                source_approved_csv_name, source_approved_csv_sha256,
                source_bridge_manifest_name, source_bridge_manifest_sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned')
            """,
            (
                shop["id"],
                idempotency_key,
                changes_json.name,
                changes_sha,
                approved_csv.name,
                approved_sha,
                bridge_manifest.name,
                manifest_sha,
            ),
        )
        batch_id = int(cursor.lastrowid)
        conflicts = 0
        report_items: list[dict[str, Any]] = []

        for handle in sorted(grouped):
            product_row = connection.execute(
                "SELECT * FROM shopify_products WHERE shop_id=? AND handle=?",
                (shop["id"], handle),
            ).fetchone()
            conflict_reasons: list[str] = []
            if not product_row:
                conflict_reasons.append("product_not_found")
                product = {
                    "id": 0,
                    "shopify_gid": "",
                    "legacy_id": "",
                    "handle": handle,
                    "updated_at_shopify": "",
                    "description_html": "",
                    "seo_title": "",
                    "seo_description": "",
                    "payload_json": "{}",
                    "is_deleted": 1,
                    "variants_complete": 0,
                }
            else:
                product = dict(product_row)
                if int(product["is_deleted"]) == 1:
                    conflict_reasons.append("product_deleted")
                if int(product["variants_complete"]) != 1:
                    conflict_reasons.append("variants_incomplete")

            approved_row = approved_rows.get(handle)
            if not approved_row:
                conflict_reasons.append("approved_csv_row_missing")

            source_provenance = provenance_by_handle.get(handle)
            if not source_provenance:
                conflict_reasons.append("bridge_provenance_missing")
            elif str(source_provenance.get("updated_at_shopify") or "") != str(product["updated_at_shopify"] or ""):
                conflict_reasons.append("bridge_source_stale")

            original_fields = _field_state(product)
            proposed_fields = dict(original_fields)
            changed_fields: list[str] = []
            for change in grouped[handle]:
                field = change["field"]
                if original_fields[field] != change["original"]:
                    conflict_reasons.append(f"original_mismatch:{field}")
                if approved_row and approved_row.get(field, "") != change["final"]:
                    conflict_reasons.append(f"approved_csv_mismatch:{field}")
                proposed_fields[field] = change["final"]
                changed_fields.append(field)

            status = "conflict" if conflict_reasons else "ready"
            if status == "conflict":
                conflicts += 1
            product_id = int(product["id"]) if int(product["id"]) else None
            if product_id is None:
                report_items.append(
                    {
                        "handle": handle,
                        "status": status,
                        "conflicts": sorted(set(conflict_reasons)),
                        "changed_fields": sorted(changed_fields),
                    }
                )
                continue
            item_cursor = connection.execute(
                """
                INSERT INTO publish_items(
                    batch_id, product_id, shopify_gid, handle, original_updated_at,
                    original_fields_json, proposed_fields_json, changed_fields_json,
                    status, conflict_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    product_id,
                    product["shopify_gid"],
                    handle,
                    product["updated_at_shopify"],
                    json_dumps(original_fields),
                    json_dumps(proposed_fields),
                    json_dumps(sorted(changed_fields)),
                    status,
                    ";".join(sorted(set(conflict_reasons))),
                ),
            )
            item_id = int(item_cursor.lastrowid)
            snapshot = _snapshot_payload(product, original_fields)
            snapshot_sha = _insert_snapshot(connection, item_id, "planned_before", snapshot)
            report_items.append(
                {
                    "item_id": item_id,
                    "handle": handle,
                    "shopify_gid": product["shopify_gid"],
                    "status": status,
                    "conflicts": sorted(set(conflict_reasons)),
                    "changed_fields": sorted(changed_fields),
                    "planned_before_sha256": snapshot_sha,
                }
            )

        if conflicts or len(report_items) != len(grouped):
            connection.execute(
                "UPDATE publish_batches SET status='blocked', error_text=? WHERE id=?",
                (f"{conflicts} conflicting product plans", batch_id),
            )
            batch_status = "blocked"
        else:
            batch_status = "planned"

    report = {
        "format": "shelfboost-publish-plan-v1",
        "batch_id": batch_id,
        "shop": domain,
        "status": batch_status,
        "idempotency_key": idempotency_key,
        "baseline_sync_run_id": int(baseline["id"]),
        "sources": {
            "changes": {"name": changes_json.name, "sha256": changes_sha},
            "approved_csv": {"name": approved_csv.name, "sha256": approved_sha},
            "bridge_manifest": {"name": bridge_manifest.name, "sha256": manifest_sha},
        },
        "items": report_items,
        "trust_boundary": [
            "Planning performs no Shopify mutation.",
            "Only Phase 1 approved or edited decisions are admitted.",
            "Original values must match the current read-only mirror.",
            "The approved CSV and Phase 1 change log must agree field by field.",
            "Any conflict blocks the whole batch.",
        ],
    }
    report_path = workspace.resolve() / "publish" / "plans" / f"batch-{batch_id}.json"
    write_json(report_path, report)
    return {
        "batch_id": batch_id,
        "status": batch_status,
        "idempotency_key": idempotency_key,
        "products": len(report_items),
        "conflicts": sum(1 for item in report_items if item["status"] == "conflict"),
        "report": str(report_path),
        "reused": False,
    }


def publish_status(workspace: Path) -> dict[str, Any]:
    initialize(workspace)
    with connect(workspace) as connection:
        batches = [
            dict(row)
            for row in connection.execute(
                "SELECT id, shop_id, status, idempotency_key, created_at, started_at, completed_at, error_text FROM publish_batches ORDER BY id"
            )
        ]
        counts = [
            dict(row)
            for row in connection.execute(
                "SELECT batch_id, status, COUNT(*) AS count FROM publish_items GROUP BY batch_id, status ORDER BY batch_id, status"
            )
        ]
    return {"batches": batches, "item_counts": counts}
