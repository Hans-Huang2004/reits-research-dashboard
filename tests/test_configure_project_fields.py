"""Display exclusions must not alter the reference workbook's column mapping."""
import copy
import json
from pathlib import Path
import unittest

from scripts.configure_project_fields import PUBLIC, INSTITUTIONAL, build_catalog


ROOT = Path(__file__).resolve().parents[1]


def reference_headers():
    return [
        {"sheet": sheet, "coordinate": f"{chr(65 + index)}1", "value": f"source_{key}",
         "data_type": "s", "number_format": "General"}
        for sheet, definitions in (("公募REITs项目", PUBLIC), ("私募REITs项目", INSTITUTIONAL))
        for index, (key, *_rest) in enumerate(definitions)
    ]


class ConfigureProjectFieldsTests(unittest.TestCase):
    def test_excluded_public_issuer_keeps_following_source_columns_aligned(self):
        headers = reference_headers()
        original = copy.deepcopy(headers)
        catalog, mapping = build_catalog(headers)
        self.assertEqual(headers, original)
        self.assertEqual((len(catalog["public"]), len(catalog["institutional"])), (19, 13))
        self.assertNotIn("issuer", [field["key"] for field in catalog["public"]])
        public_mapping = {row["key"]: row for row in mapping if row["category"] == "public"}
        self.assertFalse(public_mapping["issuer"]["included_in_display"])
        self.assertEqual(public_mapping["issuer"]["source_header"], "source_issuer")
        for key, coordinate in (("issuer", "F1"), ("manager", "G1"), ("financial_advisor", "H1"),
                                ("proposed_sale_amount_application_cny_100m", "I1"), ("guarantee_support", "S1")):
            self.assertEqual(public_mapping[key]["source_cell"], coordinate)
        self.assertEqual(public_mapping["manager"]["label"], "基金管理人")
        self.assertNotIn("发行人", public_mapping["origin"]["value_policy"])
        configured = json.loads((ROOT / "config/project_field_scope.json").read_text())
        for population in ("public", "institutional"):
            self.assertEqual([field["key"] for field in catalog[population]],
                             [field["key"] for field in configured[population]])

    def test_missing_source_column_fails_before_mapping(self):
        headers = [row for row in reference_headers()
                   if not (row["sheet"] == "公募REITs项目" and row["coordinate"] == "F1")]
        with self.assertRaisesRegex(ValueError, "Reference header count changed"):
            build_catalog(headers)


if __name__ == "__main__":
    unittest.main()
