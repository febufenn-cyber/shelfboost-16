from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PHASE1_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE1_ROOT))

from shelfboost_phase1.batches import select_batch  # noqa: E402
from shelfboost_phase1.brand import activate_profile  # noqa: E402
from shelfboost_phase1.catalog import import_catalog  # noqa: E402
from shelfboost_phase1.db import connect, initialize  # noqa: E402
from shelfboost_phase1.exporter import export_approved  # noqa: E402
from shelfboost_phase1.generation import generate_batch  # noqa: E402
from shelfboost_phase1.review import apply_decisions, create_review_pack  # noqa: E402


HEADERS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Type", "Tags", "Status",
    "SEO Title", "SEO Description", "Image Alt Text", "Variant SKU",
    "Option1 Name", "Option1 Value", "Fact: Material", "Fact: Fit"
]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def write_profile(path: Path) -> None:
    path.write_text(json.dumps({
        "brand_name": "Test Brand",
        "tone": ["clear", "specific"],
        "prohibited_terms": ["perfect", "guaranteed"],
        "regional_language": "en-IN",
        "opening_pattern": "Verified details for {title} are presented below."
    }), encoding="utf-8")


class Phase1WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        initialize(self.workspace)
        self.csv_path = self.root / "products.csv"
        self.profile_path = self.root / "brand.json"
        write_profile(self.profile_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def base_rows(self) -> list[dict[str, str]]:
        return [
            dict.fromkeys(HEADERS, "") | {
                "Handle": "shirt", "Title": "Linen Shirt", "Body (HTML)": "<p>Short copy.</p>",
                "Vendor": "Studio", "Type": "Shirts", "Status": "active", "Variant SKU": "S",
                "Option1 Name": "Size", "Option1 Value": "S", "Fact: Material": "Linen", "Fact: Fit": "Relaxed"
            },
            dict.fromkeys(HEADERS, "") | {
                "Handle": "shirt", "Variant SKU": "M", "Option1 Name": "Size", "Option1 Value": "M"
            },
            dict.fromkeys(HEADERS, "") | {
                "Handle": "lamp", "Title": "Brass Lamp", "Body (HTML)": "", "Vendor": "Studio",
                "Type": "Lamps", "Status": "active", "Variant SKU": "BL", "Fact: Material": "Brass"
            },
        ]

    def prepare_generated_batch(self) -> int:
        write_csv(self.csv_path, self.base_rows())
        import_catalog(self.workspace, self.csv_path)
        activate_profile(self.workspace, self.profile_path)
        batch = select_batch(self.workspace, "Pilot", limit=2)
        templates = PHASE1_ROOT / "category_templates"
        generate_batch(self.workspace, templates, batch["batch_id"])
        return batch["batch_id"]

    def test_import_collapses_variants_and_builds_approved_fact_ledger(self):
        write_csv(self.csv_path, self.base_rows())
        result = import_catalog(self.workspace, self.csv_path)
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["products"], 2)
        with connect(self.workspace) as connection:
            product = connection.execute("SELECT * FROM products WHERE handle='shirt'").fetchone()
            facts = connection.execute("SELECT name, value FROM product_facts WHERE product_id=?", (product["id"],)).fetchall()
            variants = connection.execute("SELECT * FROM variants WHERE product_id=?", (product["id"],)).fetchall()
        self.assertEqual(len(variants), 2)
        self.assertIn(("material", "Linen"), {(row["name"], row["value"]) for row in facts})
        self.assertEqual(product["eligibility"], "eligible")

    def test_generation_uses_fact_values_and_passes_safe_validation(self):
        batch_id = self.prepare_generated_batch()
        with connect(self.workspace) as connection:
            drafts = connection.execute(
                "SELECT d.* FROM drafts d JOIN batch_items bi ON bi.id=d.batch_item_id WHERE bi.batch_id=?",
                (batch_id,),
            ).fetchall()
        self.assertEqual(len(drafts), 6)
        body = next(row for row in drafts if row["field_name"] == "Body (HTML)" and "Linen Shirt" in row["proposed_value"])
        self.assertIn("Linen", body["proposed_value"])
        self.assertEqual(body["validation_status"], "pass")
        self.assertNotIn("perfect", body["proposed_value"].lower())

    def test_review_pack_contains_traceability_and_decision_csv(self):
        batch_id = self.prepare_generated_batch()
        result = create_review_pack(self.workspace, batch_id)
        html_text = Path(result["html"]).read_text(encoding="utf-8")
        self.assertIn("Facts and validation", html_text)
        with Path(result["decisions"]).open(encoding="utf-8") as handle:
            decisions = list(csv.DictReader(handle))
        self.assertEqual(len(decisions), 6)
        self.assertIn("validation_status", decisions[0])

    def test_blocked_draft_cannot_be_approved(self):
        batch_id = self.prepare_generated_batch()
        with connect(self.workspace) as connection:
            draft = connection.execute(
                "SELECT d.id FROM drafts d JOIN batch_items bi ON bi.id=d.batch_item_id WHERE bi.batch_id=? LIMIT 1",
                (batch_id,),
            ).fetchone()
            connection.execute("UPDATE drafts SET validation_status='blocked' WHERE id=?", (draft["id"],))
        decisions = self.root / "decisions.csv"
        with decisions.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["draft_id", "decision", "edited_value", "reviewer_note"])
            writer.writeheader()
            writer.writerow({"draft_id": draft["id"], "decision": "approved", "edited_value": "", "reviewer_note": ""})
        with self.assertRaises(ValueError):
            apply_decisions(self.workspace, decisions)

    def test_export_changes_only_approved_fields_and_preserves_variant_rows(self):
        batch_id = self.prepare_generated_batch()
        with connect(self.workspace) as connection:
            drafts = connection.execute(
                """
                SELECT d.id, d.field_name, p.handle FROM drafts d
                JOIN batch_items bi ON bi.id=d.batch_item_id
                JOIN products p ON p.id=bi.product_id
                WHERE bi.batch_id=? AND d.validation_status='pass'
                ORDER BY d.id
                """,
                (batch_id,),
            ).fetchall()
        target = next(row for row in drafts if row["handle"] == "shirt" and row["field_name"] == "SEO Title")
        decisions = self.root / "decisions.csv"
        with decisions.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["draft_id", "decision", "edited_value", "reviewer_note"])
            writer.writeheader()
            writer.writerow({"draft_id": target["id"], "decision": "edited", "edited_value": "Edited Linen Shirt | Test Brand", "reviewer_note": "approved wording"})
        apply_decisions(self.workspace, decisions)
        output = self.root / "approved.csv"
        result = export_approved(self.workspace, output, batch_id)
        self.assertEqual(result["changes"], 1)
        with output.open(encoding="utf-8") as handle:
            exported = list(csv.DictReader(handle))
        self.assertEqual(len(exported), 3)
        self.assertEqual(exported[0]["SEO Title"], "Edited Linen Shirt | Test Brand")
        self.assertEqual(exported[1]["Variant SKU"], "M")
        self.assertEqual(exported[1]["SEO Title"], "")

    def test_products_without_explicit_copy_facts_are_blocked_from_default_batch(self):
        rows = self.base_rows()
        rows.append(dict.fromkeys(HEADERS, "") | {
            "Handle": "unsafe", "Title": "Wellness Object", "Body (HTML)": "<p>Clinically proven.</p>",
            "Vendor": "Studio", "Type": "Decor", "Status": "active", "Variant SKU": "W1"
        })
        write_csv(self.csv_path, rows)
        result = import_catalog(self.workspace, self.csv_path)
        self.assertEqual(result["eligible"], 2)
        batch = select_batch(self.workspace, "Safe only", limit=10)
        self.assertNotIn("unsafe", batch["handles"])
        with connect(self.workspace) as connection:
            product = connection.execute("SELECT eligibility FROM products WHERE handle='unsafe'").fetchone()
        self.assertEqual(product["eligibility"], "blocked_missing_facts")

    def test_duplicate_generated_seo_titles_are_blocked(self):
        rows = self.base_rows()
        rows.append(dict.fromkeys(HEADERS, "") | {
            "Handle": "shirt-two", "Title": "Linen Shirt", "Body (HTML)": "",
            "Vendor": "Studio", "Type": "Shirts", "Status": "active", "Variant SKU": "X",
            "Fact: Material": "Cotton", "Fact: Fit": "Regular"
        })
        write_csv(self.csv_path, rows)
        import_catalog(self.workspace, self.csv_path)
        activate_profile(self.workspace, self.profile_path)
        batch = select_batch(self.workspace, "Duplicates", limit=3)
        result = generate_batch(self.workspace, PHASE1_ROOT / "category_templates", batch["batch_id"])
        self.assertEqual(result["blocked_duplicates"], 2)
        with connect(self.workspace) as connection:
            statuses = connection.execute(
                "SELECT validation_status FROM drafts WHERE field_name='SEO Title' AND proposed_value='Linen Shirt | Test Brand'"
            ).fetchall()
        self.assertEqual({row["validation_status"] for row in statuses}, {"blocked"})

    def test_edited_value_is_revalidated_before_review_acceptance(self):
        batch_id = self.prepare_generated_batch()
        with connect(self.workspace) as connection:
            draft = connection.execute(
                "SELECT d.id FROM drafts d JOIN batch_items bi ON bi.id=d.batch_item_id "
                "WHERE bi.batch_id=? AND d.field_name='SEO Description' AND d.validation_status='pass' LIMIT 1",
                (batch_id,),
            ).fetchone()
        decisions = self.root / "unsafe-edit.csv"
        with decisions.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["draft_id", "decision", "edited_value", "reviewer_note"])
            writer.writeheader()
            writer.writerow({
                "draft_id": draft["id"], "decision": "edited",
                "edited_value": "Guaranteed perfect results for everyone.", "reviewer_note": ""
            })
        with self.assertRaises(ValueError):
            apply_decisions(self.workspace, decisions)


if __name__ == "__main__":
    unittest.main()
