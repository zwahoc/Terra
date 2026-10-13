"""Candidate generation over current seed balances, without allocating stock."""
import copy
import unittest
from dataclasses import replace
from datetime import date
from types import MappingProxyType

from backend.app.domain.candidates import generate_candidate_pairs
from backend.app.domain.snapshot_mapping import map_record_collections
from terra.validation import load


COLLECTIONS = ('projects', 'materials', 'documents', 'extracted_rows', 'supply_offers',
               'demand_requests', 'optimisation_runs', 'allocation_proposals', 'transfers')


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.seed = load()
        self.snapshot = map_record_collections(as_of_date=date(2026, 10, 12),
                                               **{name: self.seed[name] for name in COLLECTIONS})
        self.candidates = generate_candidate_pairs(self.snapshot)
        self.pairs = {(p.supply_offer_id, p.demand_request_id): p for p in self.candidates.pairs}

    def test_every_cross_project_pair_once(self):
        expected = {(s.id, d.id) for s in self.snapshot.supplies.values()
                    for d in self.snapshot.demands.values()
                    if s.source_project_id != d.destination_project_id}
        self.assertEqual(set(self.pairs), expected)
        self.assertEqual(len(self.pairs), len(self.candidates.pairs))

    def test_categories_partition_results_with_existing_enum_values(self):
        groups = self.candidates.eligible + self.candidates.review_required + self.candidates.ineligible
        self.assertEqual(set(groups), set(self.candidates.pairs))
        self.assertEqual(len(groups), len(self.candidates.pairs))
        self.assertTrue(self.candidates.eligible)
        self.assertTrue(self.candidates.review_required)
        self.assertTrue(self.candidates.ineligible)

    def test_existing_commitments_limit_pair(self):
        result = self.pairs['SUP-003', 'DEM-003']
        self.assertEqual((result.compatibility_result, result.max_allocatable_quantity), ('ELIGIBLE', 200))
        self.assertEqual(result.lead_time_days, 2)
        self.assertEqual(result.earliest_delivery_date, date(2026, 10, 14))

    def test_competing_suppliers_are_candidates_not_allocations(self):
        self.assertEqual(self.pairs['SUP-002', 'DEM-021'].max_allocatable_quantity, 500)
        self.assertEqual(self.pairs['SUP-022', 'DEM-021'].max_allocatable_quantity, 350)
        self.assertEqual(self.snapshot.demands['DEM-021'].quantity.newly_allocatable_quantity, 800)
        # The later allocator must reduce the combined pair caps of 850 to <=800.

    def test_shared_supply_caps_are_not_deducted_during_generation(self):
        for did in ('DEM-005', 'DEM-007'):
            self.assertEqual(self.pairs['SUP-005', did].max_allocatable_quantity, 100)
        self.assertEqual(self.snapshot.supplies['SUP-005'].quantity.uncommitted_quantity, 100)

    def test_partial_reuse_and_depleted_stock_remain_explained(self):
        self.assertIn('DEMAND_ALREADY_COMMITTED', self.pairs['SUP-002', 'DEM-001'].reason_codes)
        self.assertIn('INSUFFICIENT_STOCK', self.pairs['SUP-001', 'DEM-021'].reason_codes)

    def test_spec_and_date_rejections_are_retained(self):
        self.assertIn('MATERIAL_SPEC_MISMATCH', self.pairs['SUP-008', 'DEM-007'].reason_codes)
        self.assertIn('INVALID_DATE_WINDOW', self.pairs['SUP-009', 'DEM-008'].reason_codes)
        self.assertEqual(self.pairs['SUP-009', 'DEM-008'].max_allocatable_quantity, 0)

    def test_potential_suspended_closed_and_cancelled_are_explained(self):
        for sid, did in [('SUP-007', 'DEM-012'), ('SUP-012', 'DEM-011'), ('SUP-013', 'DEM-012')]:
            self.assertIn('SUPPLY_NOT_CONFIRMED', self.pairs[sid, did].reason_codes)
        self.assertIn('DEMAND_NOT_OPEN', self.pairs['SUP-014', 'DEM-013'].reason_codes)

    def test_review_required_condition_is_retained(self):
        result = self.pairs['SUP-020', 'DEM-019']
        self.assertEqual(result.compatibility_result, 'REVIEW_REQUIRED')
        self.assertIn('CONDITION_REVIEW_REQUIRED', result.reason_codes)
        self.assertEqual(result.max_allocatable_quantity, 0)

    def test_missing_carbon_does_not_block_operational_candidate(self):
        result = self.pairs['SUP-010', 'DEM-009']
        self.assertEqual((result.compatibility_result, result.max_allocatable_quantity), ('ELIGIBLE', 150))

    def test_demo_township_policy_and_missing_timing(self):
        townships = dict(self.snapshot.project_townships)
        townships['PRJ-004'] = 'Elmina'
        changed = replace(self.snapshot, project_townships=MappingProxyType(townships))
        pairs = {(p.supply_offer_id, p.demand_request_id): p for p in generate_candidate_pairs(changed).pairs}
        self.assertEqual(pairs['SUP-003', 'DEM-003'].lead_time_days, 1)
        townships['PRJ-004'] = ''
        pairs = {(p.supply_offer_id, p.demand_request_id): p for p in generate_candidate_pairs(changed).pairs}
        self.assertEqual(pairs['SUP-003', 'DEM-003'].compatibility_result, 'REVIEW_REQUIRED')
        self.assertIn('LEAD_TIME_REVIEW_REQUIRED', pairs['SUP-003', 'DEM-003'].reason_codes)

    def test_future_confirmed_supply_is_plannable_not_reservable_today(self):
        supplies = dict(self.snapshot.supplies)
        supplies['SUP-003'] = replace(supplies['SUP-003'], available_from=date(2026, 10, 20))
        changed = replace(self.snapshot, supplies=MappingProxyType(supplies))
        result = next(p for p in generate_candidate_pairs(changed).eligible
                      if (p.supply_offer_id, p.demand_request_id) == ('SUP-003', 'DEM-003'))
        self.assertIn('FUTURE_CONFIRMED_RELEASE', result.reason_codes)
        self.assertEqual(result.source_reservable_quantity_on_planning_date, 0)
        self.assertEqual(result.earliest_delivery_date, date(2026, 10, 22))

    def test_deterministic_order_and_no_record_mutation(self):
        before = copy.deepcopy(self.seed)
        self.assertEqual(self.candidates, generate_candidate_pairs(self.snapshot))
        self.assertEqual(list(self.pairs), sorted(self.pairs))
        reordered = replace(self.snapshot,
                            supplies=dict(reversed(list(self.snapshot.supplies.items()))),
                            demands=dict(reversed(list(self.snapshot.demands.items()))))
        self.assertEqual(self.candidates, generate_candidate_pairs(reordered))
        self.assertEqual(self.seed, before)
        self.assertEqual(self.candidates.lead_time_policy_version, 'demo-township-v1')

    def test_empty_side_yields_empty_candidates(self):
        for field in ('supplies', 'demands'):
            changed = replace(self.snapshot, **{field: MappingProxyType({})})
            self.assertEqual(generate_candidate_pairs(changed).pairs, ())


if __name__ == '__main__':
    unittest.main()
