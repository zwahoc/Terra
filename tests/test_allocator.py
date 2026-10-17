"""Exact quantity and pair preference checks, including an independent oracle."""
import copy
import itertools
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from unittest.mock import patch

from backend.app.domain.allocator import allocate_max_reuse
from backend.app.domain.candidates import generate_candidate_pairs
from backend.app.domain.eligibility import Material, Supply, Demand, SupplyQuantity, DemandQuantity
from backend.app.domain.snapshot_mapping import DomainSnapshot, RouteDistance, map_record_collections
from terra.validation import load


COLLECTIONS = ('projects', 'materials', 'documents', 'extracted_rows', 'supply_offers',
               'demand_requests', 'optimisation_runs', 'allocation_proposals', 'transfers', 'route_distances')


def small_snapshot():
    material = Material('MAT-001', 'PAVING_BLOCK', 'pcs', {
        'material_type': 'concrete', 'length_mm': 200, 'width_mm': 100,
        'thickness_mm': 60, 'colour': 'grey', 'finish': 'smooth', 'intended_use': 'paving',
    })
    supplies = {f'SUP-{i}': Supply(f'SUP-{i}', f'PRJ-S{i}', 'MAT-001', 'pcs', 'CONFIRMED',
                                  'UNUSED', date(2026, 10, 12), None,
                                  SupplyQuantity(2, 0, 0), batch_or_lot_code='DEMO')
                for i in (1, 2)}
    demands = {f'DEM-{i}': Demand(f'DEM-{i}', f'PRJ-D{i}', 'MAT-001', 'pcs', 'OPEN', True,
                                 date(2026, 10, 12), date(2026, 10, 30), DemandQuantity(2, 0, 0))
               for i in (1, 2)}
    routes = {tuple(sorted((f'PRJ-S{i}', f'PRJ-D{j}'))): RouteDistance(
        f'RTE-{i}{j}', Decimal((i - 1) * 2 + j), True) for i in (1, 2) for j in (1, 2)}
    townships = {p: p for p in ['PRJ-S1', 'PRJ-S2', 'PRJ-D1', 'PRJ-D2']}
    return DomainSnapshot(date(2026, 10, 12), townships, {'MAT-001': material},
                          supplies, demands, {}, routes)


class AllocatorTests(unittest.TestCase):
    def setUp(self):
        self.seed = load()
        self.snapshot = map_record_collections(as_of_date=date(2026, 10, 12),
                                               **{name: self.seed[name] for name in COLLECTIONS})

    def quantities(self, plan):
        return {(a.supply_offer_id, a.demand_request_id): a.proposed_quantity for a in plan.allocations}

    def test_baseline_maximum_and_shared_budgets(self):
        plan = allocate_max_reuse(self.snapshot)
        self.assertEqual(plan.total_proposed_quantity, 4480)
        self.assertEqual(plan.total_proposed_quantity, sum(a.proposed_quantity for a in plan.allocations))
        quantities = self.quantities(plan)
        self.assertEqual(quantities['SUP-002', 'DEM-021'], 500)
        self.assertEqual(quantities['SUP-022', 'DEM-021'], 300)
        self.assertEqual(quantities['SUP-005', 'DEM-005'], 100)
        self.assertNotIn(('SUP-005', 'DEM-007'), quantities)
        self.assertEqual(quantities['SUP-006', 'DEM-006'], 300)
        self.assertEqual(quantities['SUP-006', 'DEM-022'], 400)
        for sid, s in self.snapshot.supplies.items():
            self.assertLessEqual(sum(a.proposed_quantity for a in plan.allocations if a.supply_offer_id == sid),
                                 s.quantity.uncommitted_quantity)
        for did, d in self.snapshot.demands.items():
            self.assertLessEqual(sum(a.proposed_quantity for a in plan.allocations if a.demand_request_id == did),
                                 d.quantity.newly_allocatable_quantity)

    def test_only_eligible_pairs_are_proposed(self):
        eligible = {(p.supply_offer_id, p.demand_request_id) for p in generate_candidate_pairs(self.snapshot).eligible}
        plan = allocate_max_reuse(self.snapshot)
        for a in plan.allocations:
            self.assertIn((a.supply_offer_id, a.demand_request_id), eligible)
            self.assertEqual((a.unit, a.status, a.compatibility_result), ('pcs', 'PROPOSED', 'ELIGIBLE'))
            self.assertGreater(a.proposed_quantity, 0)
        self.assertNotIn(('SUP-020', 'DEM-019'), self.quantities(plan))

    def test_greedy_trap_preserves_primary_quantity(self):
        snapshot = small_snapshot()
        candidates = generate_candidate_pairs(snapshot)
        # S1 can supply D1/D2; S2 only D1. S1->D1 has the best distance.
        candidates = replace(candidates, pairs=tuple(p for p in candidates.pairs
                                                     if (p.supply_offer_id, p.demand_request_id) != ('SUP-2', 'DEM-2')))
        with patch('backend.app.domain.allocator.generate_candidate_pairs', return_value=candidates):
            plan = allocate_max_reuse(snapshot)
        self.assertEqual(plan.total_proposed_quantity, 4)
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-2'): 2, ('SUP-2', 'DEM-1'): 2})

    def test_all_small_graphs_match_independent_exhaustive_oracle(self):
        snapshot = small_snapshot()
        candidates = generate_candidate_pairs(snapshot)
        ordered = [('SUP-1', 'DEM-1'), ('SUP-1', 'DEM-2'), ('SUP-2', 'DEM-1'), ('SUP-2', 'DEM-2')]
        for bits in itertools.product((0, 1), repeat=4):
            allowed = {edge for edge, bit in zip(ordered, bits) if bit}
            subset = replace(candidates, pairs=tuple(p for p in candidates.pairs
                                                     if (p.supply_offer_id, p.demand_request_id) in allowed))
            feasible = []
            for quantities in itertools.product(range(3), repeat=4):
                if any(q and edge not in allowed for edge, q in zip(ordered, quantities)):
                    continue
                a, b, c, d = quantities
                if a + b <= 2 and c + d <= 2 and a + c <= 2 and b + d <= 2:
                    feasible.append((sum(quantities), *quantities))
            expected = max(feasible)
            with self.subTest(bits=bits), patch('backend.app.domain.allocator.generate_candidate_pairs', return_value=subset):
                plan = allocate_max_reuse(snapshot)
                actual = self.quantities(plan)
                self.assertEqual((plan.total_proposed_quantity, *(actual.get(edge, 0) for edge in ordered)), expected)

    def test_earliest_delivery_precedes_distance(self):
        snapshot = small_snapshot()
        supplies = dict(snapshot.supplies)
        supplies['SUP-2'] = replace(supplies['SUP-2'], available_from=date(2026, 10, 15))
        snapshot = replace(snapshot, supplies=supplies, demands={'DEM-1': snapshot.demands['DEM-1']})
        routes = dict(snapshot.route_distances)
        routes[tuple(sorted(('PRJ-S1', 'PRJ-D1')))] = RouteDistance('RTE-11', Decimal(100), True)
        routes[tuple(sorted(('PRJ-S2', 'PRJ-D1')))] = RouteDistance('RTE-21', Decimal(1), True)
        plan = allocate_max_reuse(replace(snapshot, route_distances=routes))
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-1'): 2})

    def test_deadline_precedes_delivery_and_distance(self):
        snapshot = small_snapshot()
        demands = dict(snapshot.demands)
        # D1 can receive earlier and has a shorter route, but D2 is more urgent.
        demands['DEM-2'] = replace(demands['DEM-2'], needed_from=date(2026, 10, 14),
                                   required_by=date(2026, 10, 16))
        snapshot = replace(snapshot, supplies={'SUP-1': snapshot.supplies['SUP-1']}, demands=demands)
        plan = allocate_max_reuse(snapshot)
        self.assertEqual(plan.total_proposed_quantity, 2)
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-2'): 2})
        self.assertEqual(plan.allocations[0].required_by, date(2026, 10, 16))
        self.assertEqual(plan.assumptions['tie_break_order'][:2], ('required_by', 'earliest_delivery'))

    def test_deadline_preference_cannot_reduce_maximum_quantity(self):
        snapshot = small_snapshot()
        demands = dict(snapshot.demands)
        demands['DEM-1'] = replace(demands['DEM-1'], required_by=date(2026, 10, 16))
        snapshot = replace(snapshot, demands=demands)
        candidates = generate_candidate_pairs(snapshot)
        candidates = replace(candidates, pairs=tuple(p for p in candidates.pairs
                                                     if (p.supply_offer_id, p.demand_request_id) != ('SUP-2', 'DEM-2')))
        with patch('backend.app.domain.allocator.generate_candidate_pairs', return_value=candidates):
            plan = allocate_max_reuse(snapshot)
        self.assertEqual(plan.total_proposed_quantity, 4)
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-2'): 2, ('SUP-2', 'DEM-1'): 2})

    def test_equal_deadline_uses_earliest_delivery(self):
        snapshot = small_snapshot()
        demands = dict(snapshot.demands)
        demands['DEM-1'] = replace(demands['DEM-1'], needed_from=date(2026, 10, 15))
        snapshot = replace(snapshot, supplies={'SUP-1': snapshot.supplies['SUP-1']}, demands=demands)
        plan = allocate_max_reuse(snapshot)
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-2'): 2})

    def test_shortest_distance_then_stable_ids(self):
        snapshot = small_snapshot()
        snapshot = replace(snapshot, demands={'DEM-1': snapshot.demands['DEM-1']})
        routes = dict(snapshot.route_distances)
        key = tuple(sorted(('PRJ-S2', 'PRJ-D1')))
        routes[key] = RouteDistance('RTE-21', Decimal('0.5'), True)
        self.assertEqual(self.quantities(allocate_max_reuse(replace(snapshot, route_distances=routes))),
                         {('SUP-2', 'DEM-1'): 2})
        routes[key] = RouteDistance('RTE-21', Decimal(1), True)
        self.assertEqual(self.quantities(allocate_max_reuse(replace(snapshot, route_distances=routes))),
                         {('SUP-1', 'DEM-1'): 2})

    def test_missing_distance_is_flagged_and_does_not_reduce_quantity(self):
        snapshot = replace(self.snapshot, route_distances=MappingProxyType({}))
        plan = allocate_max_reuse(snapshot)
        self.assertEqual(plan.total_proposed_quantity, 4480)
        self.assertEqual(len(plan.missing_distance_pairs), 15)
        for a in plan.allocations:
            self.assertIsNone(a.distance_km)
            self.assertIn('ROUTE_DISTANCE_MISSING', a.reason_codes)
            self.assertIn('DISTANCE_TIE_BREAK_UNAVAILABLE', a.reason_codes)

    def test_mixed_missing_distance_uses_explicit_group_fallback(self):
        snapshot = small_snapshot()
        snapshot = replace(snapshot, demands={'DEM-1': snapshot.demands['DEM-1']})
        routes = dict(snapshot.route_distances)
        del routes[tuple(sorted(('PRJ-S1', 'PRJ-D1')))]
        plan = allocate_max_reuse(replace(snapshot, route_distances=routes))
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-1'): 2})
        self.assertIn('DISTANCE_TIE_BREAK_UNAVAILABLE', plan.allocations[0].reason_codes)

    def test_no_match_is_successful_empty_plan(self):
        snapshot = replace(self.snapshot, supplies=MappingProxyType({}))
        plan = allocate_max_reuse(snapshot)
        self.assertEqual((plan.solver_status, plan.total_proposed_quantity, plan.allocations), ('SUCCEEDED', 0, ()))

    def test_partial_use_is_not_allocated_again(self):
        plan = allocate_max_reuse(self.snapshot)
        self.assertFalse(any(a.demand_request_id == 'DEM-001' for a in plan.allocations))
        self.assertEqual(plan.remaining_newly_allocatable_quantity_by_demand['DEM-001'], 0)

    def test_deterministic_and_no_mutation(self):
        before = copy.deepcopy(self.seed)
        first = allocate_max_reuse(self.snapshot)
        reordered = replace(self.snapshot, supplies=dict(reversed(list(self.snapshot.supplies.items()))),
                            demands=dict(reversed(list(self.snapshot.demands.items()))))
        self.assertEqual(first, allocate_max_reuse(reordered))
        self.assertEqual(self.seed, before)
        self.assertEqual(self.snapshot.supplies['SUP-003'].quantity.reserved_active_quantity, 300)
        with self.assertRaises(TypeError):
            first.remaining_uncommitted_quantity_by_supply['SUP-003'] = 1


if __name__ == '__main__':
    unittest.main()
