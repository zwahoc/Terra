import csv
import io
import json
import unittest
from pathlib import Path

from backend.app.services.impact_export_service import export_csv, export_json
from tests.test_impact_service import FakeImpactRepository


class ImpactExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = json.loads((Path(__file__).parents[1] / "data" / "terra_seed.json").read_text(encoding="utf-8"))

    def test_actual_json_exports_traceable_current_records_without_aggregation(self):
        response = export_json("ACTUAL_CONFIRMED_USE", FakeImpactRepository(self.seed))
        self.assertIsNone(response["data"]["aggregation"])
        records = response["data"]["records"]
        self.assertEqual({row["assessment_id"] for row in records}, {"IMP-005", "IMP-006"})
        partial = next(row for row in records if row["assessment_id"] == "IMP-005")
        self.assertEqual(partial["quantity_assessed"], 550)
        self.assertEqual(partial["moved_quantity"], 600)
        self.assertIsNone(partial["components_kgco2e"]["net_avoided"])
        self.assertTrue(partial["missing_data"])
        self.assertTrue(partial["factors"])
        self.assertIn("not an official Scope 1/2/3 deduction", partial["disclaimer"])

    def test_csv_has_one_flat_row_per_current_assessment_and_json_trace_fields(self):
        content = export_csv("PROPOSAL_FORECAST", FakeImpactRepository(self.seed))
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(len(rows), 6)
        alc001 = next(row for row in rows if row["proposal_id"] == "ALC-001")
        self.assertEqual(alc001["net_avoided_kgco2e"], "433.5")
        self.assertEqual(alc001["factor_ids"], "EF-001|EF-007|EF-008")
        self.assertEqual(len(json.loads(alc001["factors_json"])), 3)
        self.assertEqual(json.loads(alc001["revision_json"])["number"], 1)


if __name__ == "__main__":
    unittest.main()
