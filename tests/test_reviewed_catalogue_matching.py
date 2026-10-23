"""Exercise published-catalogue matching with the vocabulary seen in D01.

Fixtures contain only material attributes, never source files or private batches.
The complete owner response is replayed separately in ignored local evidence.
"""
import copy
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from backend.app.domain.candidates import generate_candidate_pairs
from backend.app.domain.snapshot_mapping import map_record_collections
from backend.app.services.forecast_preview_service import COLLECTIONS
from backend.app.services.optimisation_preview_service import preview_comparison
from tests.test_checkpoint_a import DAY, runtime_records


MATERIALS = (
    ('PAVING', 'pcs', {'material_type': 'concrete', 'length_mm': '200',
        'width_mm': '100', 'thickness_mm': '80', 'colour': 'grey',
        'surface': 'smooth face', 'use': 'pedestrian hardscape',
        'laying_pattern': 'herringbone', 'type': 'interlocking paving block'}, 500, 300),
    ('MASONRY', 'pcs', {'material_type': 'fired clay', 'length_mm': '215',
        'width_mm': '102.5', 'height_mm': '65', 'compressive_strength_mpa': '20',
        'colour': 'red', 'use': 'non-loadbearing landscape wall'}, 500, 400),
    ('DRAINAGE', 'm', {'material_type': 'uPVC', 'nominal_diameter_mm': '110',
        'stiffness_class': 'SN8', 'length_m': '6', 'pipe_type': 'gravity drainage pipe',
        'use': 'subsoil drainage'}, 120, 96),
    ('CEMENT', 'bag', {'cement_type': 'CEM I 42.5 N', 'bag_mass_kg': '50',
        'packaging': 'sealed 50 kg bag', 'use': 'mortar and minor concrete works'}, 30, 20),
    ('REINFORCEMENT', 'kg', {'bar_type': 'deformed', 'diameter_mm': '12',
        'steel_grade': 'B500B', 'use': 'landscape retaining elements'}, 200, 100),
    ('GEOTEXTILE', 'm2', {'construction': 'non-woven', 'mass_per_area_g_m2': '200',
        'product_reference': 'GT-NW-200'}, 500, 300),
)


def reviewed_records(category, unit, specs, offered, needed):
    """A hypothetical later reviewed release/need, not D01 declaring surplus."""
    records = runtime_records()
    material = records['materials'][0]
    material.update(category=category, standard_unit=unit, specifications=copy.deepcopy(specs))
    records['supply_offers'][0].update(unit=unit, declared_quantity=offered, confirmed_quantity=offered)
    records['demand_requests'] = records['demand_requests'][:1]
    records['demand_requests'][0].update(unit=unit, required_quantity=needed)
    # Deliberately incomplete carbon must not suppress quantity/deadline plans.
    records['emission_factors'] = []
    return records


def candidates(records):
    snapshot = map_record_collections(as_of_date=DAY,
        **{key: records[key] for key in COLLECTIONS})
    return snapshot, generate_candidate_pairs(snapshot)


class ReviewedCatalogueMatchingTests(unittest.TestCase):
    def test_policy_changes_invalidate_matching_and_allocation_fingerprints(self):
        from backend.app.domain.allocator import allocation_snapshot_hash
        from backend.app.services.matching_service import dependency
        records = reviewed_records(*MATERIALS[0])
        snapshot, _ = candidates(records)
        current = dependency(records, records['materials'][0]['id'], DAY)
        current_allocation = allocation_snapshot_hash(snapshot)
        with patch('backend.app.services.matching_service.ELIGIBILITY_POLICY_VERSION', 'older-family-policy'):
            self.assertNotEqual(current, dependency(records, records['materials'][0]['id'], DAY))
        with patch('backend.app.domain.allocator.ELIGIBILITY_POLICY_VERSION', 'older-family-policy'):
            self.assertNotEqual(current_allocation, allocation_snapshot_hash(snapshot))

    def test_d01_vocabulary_and_new_family_reach_real_allocator_without_rewriting(self):
        for attributes in MATERIALS:
            with self.subTest(category=attributes[0]):
                records = reviewed_records(*attributes)
                original = copy.deepcopy(records)
                _, pairs = candidates(records)
                self.assertEqual(len(pairs.eligible), 1, pairs.pairs)
                result = preview_comparison(records, planning_date=DAY, factor_dataset_version='demo-v1')
                for alternative in result['alternatives'][:2]:
                    allocations = alternative['plan']['allocations']
                    self.assertEqual(len(allocations), 1)
                    self.assertEqual(Decimal(str(allocations[0]['proposed_quantity'])), Decimal(attributes[4]))
                    self.assertEqual(allocations[0]['unit'], attributes[1])
                self.assertFalse(result['alternatives'][2]['plan']['allocations'])
                self.assertTrue(result['alternatives'][2]['forecast_summary']['candidate_scoring_incomplete'])
                self.assertEqual(records, original)

    def test_same_description_with_different_catalogue_ids_is_still_blocked(self):
        records = reviewed_records(*MATERIALS[0])
        other = copy.deepcopy(records['materials'][0]); other['id'] = 'MAT-DIFFERENT'
        records['materials'].append(other)
        records['demand_requests'][0]['material_id'] = other['id']
        _, result = candidates(records)
        self.assertFalse(result.eligible)
        self.assertIn('MATERIAL_SPEC_MISMATCH', result.pairs[0].reason_codes)

    def test_same_id_with_conflicting_catalogue_snapshot_is_still_blocked(self):
        from backend.app.domain.eligibility import evaluate_eligibility
        snapshot, _ = candidates(reviewed_records(*MATERIALS[0]))
        supply = next(iter(snapshot.supplies.values())); demand = next(iter(snapshot.demands.values()))
        material = snapshot.materials[supply.material_id]
        for other in (replace(material, category='OTHER'),
                      replace(material, specifications={**material.specifications, 'thickness_mm': '60'})):
            with self.subTest(other=other):
                result = evaluate_eligibility(supply, demand, material, other,
                    planning_date=DAY, lead_time_days=2)
                self.assertEqual(result.compatibility_result, 'INELIGIBLE')
                self.assertIn('MATERIAL_SPEC_MISMATCH', result.reason_codes)

    def test_new_family_keeps_operational_guards_and_quantity_caps(self):
        def outcome(change):
            records = reviewed_records(*MATERIALS[-1]); change(records)
            return candidates(records)[1].pairs[0]
        cases = (
            (lambda r: r['supply_offers'][0].update(surplus_status='POTENTIAL', confirmed_quantity=None), 'SUPPLY_NOT_CONFIRMED'),
            (lambda r: r['supply_offers'][0].update(condition='UNKNOWN'), 'CONDITION_REVIEW_REQUIRED'),
            (lambda r: r['supply_offers'][0].update(batch_or_lot_code=None, evidence_refs=[]), 'TRACEABILITY_REVIEW_REQUIRED'),
            (lambda r: r['demand_requests'][0].update(is_outstanding_need_confirmed=False), 'DEMAND_NOT_CONFIRMED'),
            (lambda r: r['demand_requests'][0].update(unit='pcs'), 'UNIT_CONVERSION_UNSUPPORTED'),
            (lambda r: r['demand_requests'][0].update(needed_from=str(DAY), required_by=str(DAY)), 'INVALID_DATE_WINDOW'),
            (lambda r: r['supply_offers'][0].update(confirmed_quantity=0), 'INSUFFICIENT_STOCK'),
        )
        for change, reason in cases:
            with self.subTest(reason=reason):
                result = outcome(change)
                self.assertIn(reason, result.reason_codes)
                self.assertEqual(result.max_allocatable_quantity, 0)
        result = outcome(lambda r: r['supply_offers'][0].update(confirmed_quantity=100))
        self.assertEqual(result.max_allocatable_quantity, 100)

    def test_new_family_future_release_remains_unreservable_today(self):
        records = reviewed_records(*MATERIALS[-1])
        records['supply_offers'][0]['available_from'] = str(DAY + timedelta(days=1))
        pair = candidates(records)[1].eligible[0]
        self.assertEqual(pair.source_reservable_quantity_on_planning_date, 0)
        self.assertEqual(pair.earliest_delivery_date, DAY + timedelta(days=3))


if __name__ == '__main__':
    unittest.main()
