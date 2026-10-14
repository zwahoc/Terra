"""Independent exhaustive checks for deadline and linear carbon objectives."""
import itertools
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from backend.app.domain.allocator import allocate, allocation_snapshot_hash, LinearCarbonScores
from backend.app.domain.candidates import generate_candidate_pairs
from tests.test_allocator import small_snapshot, COLLECTIONS
from backend.app.domain.snapshot_mapping import map_record_collections
from terra.validation import load


class ObjectiveTests(unittest.TestCase):
    def score(self, snapshot, values):
        return LinearCarbonScores(allocation_snapshot_hash(snapshot), 'demo-v1',
                                  'full-carbon-context-1', values, True)

    def carbon(self, snapshot, values):
        return allocate(snapshot, objective='MAX_NET_CO2E_AVOIDED',
                        carbon_scores=self.score(snapshot, values),
                        factor_dataset_version='demo-v1', carbon_context_id='full-carbon-context-1')

    def quantities(self, plan):
        return {(a.supply_offer_id, a.demand_request_id): a.proposed_quantity for a in plan.allocations}

    def test_dispatch_and_baseline(self):
        records = load()
        snapshot = map_record_collections(as_of_date=date(2026, 10, 12),
                                         **{n: records[n] for n in COLLECTIONS})
        reuse = allocate(snapshot, objective='MAX_REUSE')
        deadline = allocate(snapshot, objective='EARLIEST_DEADLINE')
        self.assertEqual((reuse.total_proposed_quantity, deadline.total_proposed_quantity), (4480, 4480))
        self.assertEqual(reuse.allocations, tuple(replace(a, reason_codes=tuple(
            'MAX_REUSE_QUANTITY_OPTIMUM' if r == 'EARLIEST_DEADLINE_OPTIMUM' else r
            for r in a.reason_codes)) for a in deadline.allocations))
        scores = {(p.supply_offer_id, p.demand_request_id): Decimal('1')
                  for p in generate_candidate_pairs(snapshot).eligible}
        carbon = self.carbon(snapshot, scores)
        self.assertEqual(self.quantities(carbon), self.quantities(reuse))
        self.assertEqual(carbon.estimated_net_avoided_kgco2e, Decimal('4480'))
        self.assertFalse(carbon.incomplete_carbon)

    def test_deadline_groups_preserve_urgency_before_pair_preferences(self):
        snapshot = small_snapshot()
        demands = {k: replace(v, required_by=date(2026, 10, 16 if k == 'DEM-1' else 30))
                   for k, v in snapshot.demands.items()}
        snapshot = replace(snapshot, demands=demands)
        plan = allocate(snapshot, objective='EARLIEST_DEADLINE')
        self.assertEqual(plan.assumptions['deadline_groups'], ('2026-10-16', '2026-10-30'))
        self.assertEqual(plan.total_proposed_quantity, 4)

    def test_all_small_graphs_match_exhaustive_objective_vectors(self):
        snapshot = small_snapshot()
        snapshot = replace(snapshot, demands={k: replace(v, required_by=date(
            2026, 10, 16 if k == 'DEM-1' else 30)) for k, v in snapshot.demands.items()})
        candidates = generate_candidate_pairs(snapshot)
        # Actual ranked pair order is deadline, delivery, distance, IDs.
        order = [('SUP-1', 'DEM-1'), ('SUP-2', 'DEM-1'),
                 ('SUP-1', 'DEM-2'), ('SUP-2', 'DEM-2')]
        for bits in itertools.product((0, 1), repeat=4):
            allowed = {p for p, b in zip(order, bits) if b}
            subset = replace(candidates, pairs=tuple(p for p in candidates.pairs
                if (p.supply_offer_id, p.demand_request_id) in allowed))
            feasible = []
            for q in itertools.product(range(3), repeat=4):
                if any(v and p not in allowed for p, v in zip(order, q)):
                    continue
                a, b, c, d = q
                if a + c <= 2 and b + d <= 2 and a + b <= 2 and c + d <= 2:
                    feasible.append(q)
            with patch('backend.app.domain.allocator.generate_candidate_pairs', return_value=subset):
                deadline = allocate(snapshot, objective='EARLIEST_DEADLINE')
                expected = max(feasible, key=lambda q: (q[0] + q[1], q[2] + q[3], *q))
                self.assertEqual(tuple(self.quantities(deadline).get(p, 0) for p in order), expected)
                for coefficients in ((Decimal('1.25'), Decimal('0.1'), Decimal('3.5'), Decimal('0')),
                                     (Decimal('-1'), Decimal('0'), Decimal('0.001'), Decimal('2')),
                                     (Decimal('1'),) * 4):
                    scores = {p: c for p, c in zip(order, coefficients) if p in allowed}
                    plan = self.carbon(snapshot, scores)
                    nonnegative = [q for q in feasible if all(v == 0 or c >= 0
                                                             for v, c in zip(q, coefficients))]
                    expected = max(nonnegative, key=lambda q: (
                        sum(v * c for v, c in zip(q, coefficients)), sum(q), *q))
                    with self.subTest(bits=bits, coefficients=coefficients):
                        self.assertEqual(tuple(self.quantities(plan).get(p, 0) for p in order), expected)

    def test_missing_negative_zero_and_no_scoring(self):
        snapshot = small_snapshot()
        values = {('SUP-1', 'DEM-1'): Decimal('-1'), ('SUP-1', 'DEM-2'): Decimal('0')}
        plan = self.carbon(snapshot, values)
        self.assertTrue(plan.incomplete_carbon)
        self.assertTrue(plan.carbon_scoring_available)
        self.assertEqual(plan.estimated_net_avoided_kgco2e, Decimal('0'))
        self.assertEqual(plan.negative_carbon_pairs, (('SUP-1', 'DEM-1'),))
        self.assertEqual(self.quantities(plan), {('SUP-1', 'DEM-2'): 2})
        empty = self.carbon(snapshot, {})
        self.assertFalse(empty.carbon_scoring_available)
        self.assertIsNone(empty.estimated_net_avoided_kgco2e)
        self.assertTrue(empty.incomplete_carbon)
        self.assertEqual(empty.solver_status, 'SUCCEEDED')

    def test_carbon_can_sacrifice_quantity_and_equal_deadlines_reroute(self):
        snapshot = small_snapshot()
        candidates = generate_candidate_pairs(snapshot)
        subset = replace(candidates, pairs=tuple(p for p in candidates.pairs
            if (p.supply_offer_id, p.demand_request_id) != ('SUP-2', 'DEM-2')))
        values = {('SUP-1', 'DEM-1'): Decimal('10'), ('SUP-1', 'DEM-2'): Decimal('1'),
                  ('SUP-2', 'DEM-1'): Decimal('1')}
        with patch('backend.app.domain.allocator.generate_candidate_pairs', return_value=subset):
            carbon = self.carbon(snapshot, values)
            deadline = allocate(snapshot, objective='EARLIEST_DEADLINE')
        self.assertEqual(self.quantities(carbon), {('SUP-1', 'DEM-1'): 2})
        self.assertEqual(carbon.estimated_net_avoided_kgco2e, Decimal('20'))
        self.assertEqual(deadline.total_proposed_quantity, 4)
        self.assertEqual(self.quantities(deadline), {('SUP-1', 'DEM-2'): 2, ('SUP-2', 'DEM-1'): 2})

    def test_all_negative_is_complete_zero_and_empty_graph_is_valid(self):
        snapshot = small_snapshot()
        values = {(p.supply_offer_id, p.demand_request_id): Decimal('-1')
                  for p in generate_candidate_pairs(snapshot).eligible}
        plan = self.carbon(snapshot, values)
        self.assertFalse(plan.incomplete_carbon)
        self.assertTrue(plan.carbon_scoring_available)
        self.assertEqual(plan.estimated_net_avoided_kgco2e, Decimal(0))
        self.assertEqual(plan.allocations, ())
        empty = replace(snapshot, supplies={})
        for objective in ('MAX_REUSE', 'EARLIEST_DEADLINE'):
            self.assertEqual(allocate(empty, objective=objective).total_proposed_quantity, 0)
        self.assertFalse(self.carbon(empty, {}).incomplete_carbon)

    def test_exact_carbon_and_determinism_without_mutation(self):
        snapshot = small_snapshot()
        values = {(p.supply_offer_id, p.demand_request_id): Decimal('0.12345678901234567890123456789')
                  for p in generate_candidate_pairs(snapshot).eligible}
        plan = self.carbon(snapshot, values)
        self.assertEqual(plan.estimated_net_avoided_kgco2e, Decimal('0.49382715604938271560493827156'))
        reordered = replace(snapshot, supplies=dict(reversed(list(snapshot.supplies.items()))))
        self.assertEqual(allocation_snapshot_hash(snapshot), allocation_snapshot_hash(reordered))
        self.assertEqual(plan, self.carbon(reordered, dict(reversed(list(values.items())))))
        self.assertEqual(snapshot.supplies['SUP-1'].quantity.uncommitted_quantity, 2)
        with self.assertRaises(TypeError):
            plan.remaining_uncommitted_quantity_by_supply['SUP-1'] = 0

    def test_score_validation_and_context_mismatch(self):
        snapshot = small_snapshot()
        scores = self.score(snapshot, {('SUP-1', 'DEM-1'): Decimal('1')})
        for kwargs in ({'factor_dataset_version': 'other', 'carbon_context_id': 'full-carbon-context-1'},
                       {'factor_dataset_version': 'demo-v1', 'carbon_context_id': 'other'}, {}):
            with self.assertRaises(ValueError):
                allocate(snapshot, objective='MAX_NET_CO2E_AVOIDED', carbon_scores=scores, **kwargs)
        with self.assertRaises(ValueError):
            allocate(replace(snapshot, as_of_date=date(2026, 10, 13)),
                     objective='MAX_NET_CO2E_AVOIDED', carbon_scores=scores,
                     factor_dataset_version='demo-v1', carbon_context_id='full-carbon-context-1')
        for bad in (1.0, True, Decimal('NaN'), Decimal('Infinity')):
            with self.assertRaises(ValueError):
                self.score(snapshot, {('SUP-1', 'DEM-1'): bad})
        with self.assertRaises(ValueError):
            replace(scores, linear_scaling_guaranteed=False)
        with self.assertRaises(ValueError):
            self.carbon(snapshot, {('SUP-unknown', 'DEM-1'): Decimal('1')})
        values = {('SUP-1', 'DEM-1'): Decimal('1')}
        copied = self.score(snapshot, values)
        values.clear()
        self.assertEqual(len(copied.net_kgco2e_per_piece), 1)

    def test_unknown_objective_and_wrong_scoring_inputs(self):
        snapshot = small_snapshot()
        with self.assertRaises(ValueError):
            allocate(snapshot, objective='MAX_CO2')
        with self.assertRaises(ValueError):
            allocate(snapshot, objective='MAX_NET_CO2E_AVOIDED')
        for objective in ('MAX_REUSE', 'EARLIEST_DEADLINE'):
            with self.assertRaises(ValueError):
                allocate(snapshot, objective=objective, carbon_scores=self.score(snapshot, {}))


if __name__ == '__main__':
    unittest.main()
