import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))

from audit_catalog import audit_product, duplicate_maps, load_products, write_outputs  # noqa: E402


class CatalogAuditTests(unittest.TestCase):
    def write_csv(self, directory: Path, rows: list[dict[str, str]]) -> Path:
        path = directory / "products.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_collapses_variant_rows_and_fills_missing_product_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {"Handle": "shirt", "Title": "Linen Shirt", "Body (HTML)": "", "Variant SKU": "S"},
                {"Handle": "shirt", "Title": "", "Body (HTML)": "<p>Breathable linen shirt for warm days.</p>", "Variant SKU": "M"},
            ]
            products = load_products(self.write_csv(Path(tmp), rows))
            self.assertEqual(len(products), 1)
            self.assertIn("Breathable linen", products[0]["Body (HTML)"])

    def test_flags_missing_fields_duplicate_copy_and_claim_review(self):
        body = "Clinically proven premium quality lamp for modern rooms with a polished finish and adaptable placement in home interiors."
        rows = [
            {"Handle": "a", "Title": "Classic Lamp", "Body (HTML)": body, "SEO Title": "", "SEO Description": "", "Image Alt Text": "", "Status": "active", "Vendor": "Acme", "Type": "Lamp"},
            {"Handle": "b", "Title": "Classic Lamp", "Body (HTML)": body, "SEO Title": "", "SEO Description": "", "Image Alt Text": "", "Status": "active", "Vendor": "Acme", "Type": "Lamp"},
        ]
        title_counts, body_counts = duplicate_maps(rows)
        audit = audit_product(rows[0], title_counts, body_counts)
        codes = {finding.code for finding in audit.findings}
        self.assertIn("duplicate_title", codes)
        self.assertIn("duplicate_description", codes)
        self.assertIn("claim_requires_human_review", codes)
        self.assertIn("missing_seo_title", codes)
        self.assertLess(audit.health_score, 60)

    def test_writes_ranked_csv_and_summary(self):
        rows = [
            {"Handle": "good", "Title": "Handwoven Cotton Throw", "Body (HTML)": " ".join(["Detailed"] * 90), "SEO Title": "Handwoven Cotton Throw for Calm Interiors", "SEO Description": "A handwoven cotton throw with a soft texture, clear care details, and a versatile design for layered living spaces.", "Image Alt Text": "Handwoven cotton throw on a sofa", "Status": "active", "Vendor": "Studio", "Type": "Throw"},
            {"Handle": "bad", "Title": "", "Body (HTML)": "", "SEO Title": "", "SEO Description": "", "Image Alt Text": "", "Status": "active", "Vendor": "Studio", "Type": "Throw"},
        ]
        title_counts, body_counts = duplicate_maps(rows)
        audits = [audit_product(row, title_counts, body_counts) for row in rows]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_outputs(audits, output, Path("products.csv"))
            with (output / "catalog-audit.csv").open(encoding="utf-8") as handle:
                report = list(csv.DictReader(handle))
            self.assertEqual(report[0]["handle"], "bad")
            summary = json.loads((output / "catalog-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["products_audited"], 2)
            self.assertEqual(summary["top_priority"][0]["handle"], "bad")


if __name__ == "__main__":
    unittest.main()
