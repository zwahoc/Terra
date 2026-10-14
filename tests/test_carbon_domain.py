import unittest
from datetime import date
from decimal import Decimal

from backend.app.domain.carbon import calculate_components, select_factor


BOUNDARY = "boundary"


def factor(identifier, kind, value, unit, **extra):
    return {
        "id": identifier,
        "factor_type": kind,
        "material_id": extra.get("material_id"),
        "material_category": extra.get("material_category"),
        "transport_mode": extra.get("transport_mode"),
        "value": value,
        "unit": unit,
        "version": extra.get("version", "demo-v1"),
        "valid_from": extra.get("valid_from", "2026-09-01"),
        "lifecycle_boundary": extra.get("lifecycle_boundary", BOUNDARY),
    }


class CarbonDomainTests(unittest.TestCase):
    def test_seed_regression_uses_explicit_12_kg_processing(self):
        result = calculate_components(
            quantity_assessed=Decimal("600"),
            moved_quantity=Decimal("600"),
            processed_quantity=Decimal("600"),
            mass_kg_per_unit=Decimal("2.5"),
            distance_km=Decimal("25"),
            production_factor=factor("EF-001", "NEW_MATERIAL_PRODUCTION", 0.75, "kgCO2e/pcs"),
            transport_factor=factor("EF-007", "TRANSPORT", 0.12, "kgCO2e/t-km"),
            processing_factor=factor("EF-008", "PROCESSING", 0.02, "kgCO2e/pcs"),
        )
        self.assertEqual(result.avoided_production_kgco2e, Decimal("450.00"))
        self.assertEqual(result.additional_transport_kgco2e, Decimal("4.50000"))
        self.assertEqual(result.additional_processing_kgco2e, Decimal("12.00"))
        self.assertEqual(result.net_avoided_kgco2e, Decimal("433.50000"))

    def test_per_kg_production_and_negative_net_are_preserved(self):
        result = calculate_components(
            quantity_assessed=Decimal("2"), moved_quantity=Decimal("2"),
            processed_quantity=Decimal("2"), mass_kg_per_unit=Decimal("10"),
            distance_km=Decimal("100"),
            production_factor=factor("P", "NEW_MATERIAL_PRODUCTION", 0.1, "kgCO2e/kg"),
            transport_factor=factor("T", "TRANSPORT", 20, "kgCO2e/t-km"),
            processing_factor=factor("H", "PROCESSING", 2, "kgCO2e/pcs"),
        )
        self.assertEqual(result.avoided_production_kgco2e, Decimal("2.0"))
        self.assertEqual(result.additional_transport_kgco2e, Decimal("40.0"))
        self.assertEqual(result.net_avoided_kgco2e, Decimal("-42.0"))

    def test_partial_use_retains_known_components_but_null_net(self):
        result = calculate_components(
            quantity_assessed=Decimal("550"), moved_quantity=Decimal("600"),
            processed_quantity=None, mass_kg_per_unit=Decimal("2.5"),
            distance_km=Decimal("25"),
            production_factor=factor("P", "NEW_MATERIAL_PRODUCTION", .75, "kgCO2e/pcs"),
            transport_factor=factor("T", "TRANSPORT", .12, "kgCO2e/t-km"),
            processing_factor=None,
        )
        self.assertEqual(result.avoided_production_kgco2e, Decimal("412.50"))
        self.assertEqual(result.additional_transport_kgco2e, Decimal("4.50000"))
        self.assertIsNone(result.additional_processing_kgco2e)
        self.assertIsNone(result.net_avoided_kgco2e)
        self.assertIn("PROCESSING_BOUNDARY", result.missing_data)

    def test_factor_selection_obeys_specificity_date_version_unit_mode_boundary(self):
        factors = [
            factor("GENERAL", "NEW_MATERIAL_PRODUCTION", 1, "kgCO2e/pcs"),
            factor("CATEGORY", "NEW_MATERIAL_PRODUCTION", 2, "kgCO2e/pcs", material_category="PAVING_BLOCK"),
            factor("EXACT-OLD", "NEW_MATERIAL_PRODUCTION", 3, "kgCO2e/pcs", material_id="MAT-001", valid_from="2026-08-01"),
            factor("EXACT-NEW", "NEW_MATERIAL_PRODUCTION", 4, "kgCO2e/pcs", material_id="MAT-001"),
            factor("WRONG-VERSION", "NEW_MATERIAL_PRODUCTION", 9, "kgCO2e/pcs", material_id="MAT-001", version="v2"),
        ]
        choice = select_factor(
            factors, factor_type="NEW_MATERIAL_PRODUCTION", material_id="MAT-001",
            material_category="PAVING_BLOCK", transport_mode=None, version="demo-v1",
            activity_date=date(2026, 10, 1), lifecycle_boundary=BOUNDARY,
            supported_units={"kgCO2e/pcs", "kgCO2e/kg"},
        )
        self.assertEqual(choice.factor["id"], "EXACT-NEW")

    def test_equally_ranked_factors_are_ambiguous_not_silently_chosen(self):
        factors = [
            factor("A", "TRANSPORT", .1, "kgCO2e/t-km", transport_mode="ROAD_FREIGHT"),
            factor("B", "TRANSPORT", .2, "kgCO2e/t-km", transport_mode="ROAD_FREIGHT"),
        ]
        choice = select_factor(
            factors, factor_type="TRANSPORT", material_id="MAT-001",
            material_category="PAVING_BLOCK", transport_mode="ROAD_FREIGHT",
            version="demo-v1", activity_date=date(2026, 10, 1),
            lifecycle_boundary=BOUNDARY, supported_units={"kgCO2e/t-km"},
        )
        self.assertIsNone(choice.factor)
        self.assertEqual(choice.issue, "AMBIGUOUS_TRANSPORT_FACTOR")


if __name__ == "__main__":
    unittest.main()
