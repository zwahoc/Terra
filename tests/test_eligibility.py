"""Operational scenarios for the draft evaluator, independent of HTTP/Firebase."""
import copy
import unittest
from dataclasses import replace
from datetime import date

from backend.app.domain.eligibility import (
    Demand, DemandQuantity, Material, Supply, SupplyQuantity, evaluate_eligibility,
)
from terra.validation import balances, load


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.seed = load()
        self.rows = {name: {row['id']: row for row in rows}
                     for name, rows in self.seed.items() if isinstance(rows, list)}
        self.incoming = balances(self.seed)[3]

    def pair(self, sid='SUP-003', did='DEM-003'):
        s, d = self.rows['supply_offers'][sid], self.rows['demand_requests'][did]
        supply = Supply(
            s['id'], s['source_project_id'], s['material_id'], s['unit'],
            s['surplus_status'], s['condition'], date.fromisoformat(s['available_from']),
            date.fromisoformat(s['available_until']) if s['available_until'] else None,
            SupplyQuantity(s['confirmed_quantity'], s['reserved_active_quantity'],
                           s['transferred_out_quantity']),
            s['batch_or_lot_code'], tuple(s['evidence_refs']),
        )
        demand = Demand(
            d['id'], d['destination_project_id'], d['material_id'], d['unit'],
            d['request_status'], d['is_outstanding_need_confirmed'],
            date.fromisoformat(d['needed_from']), date.fromisoformat(d['required_by']),
            DemandQuantity(d['required_quantity'], d['fulfilled_quantity'], self.incoming[did]),
        )
        def material(mid):
            m = self.rows['materials'][mid]
            return Material(m['id'], m['category'], m['standard_unit'], m['specifications'])
        return supply, demand, material(s['material_id']), material(d['material_id'])

    def evaluate(self, pair, **kwargs):
        return evaluate_eligibility(*pair, planning_date=date(2026, 10, 12),
                                    lead_time_days=kwargs.pop('lead_time_days', 1), **kwargs)

    def test_reserved_source_and_recipient_limit(self):
        result = self.evaluate(self.pair())
        self.assertEqual(result.compatibility_result, 'ELIGIBLE')
        self.assertEqual((result.source_uncommitted_quantity,
                          result.demand_newly_allocatable_quantity,
                          result.max_allocatable_quantity), (500, 200, 200))

    def test_partial_use_retains_recipient_commitment(self):
        result = self.evaluate(self.pair('SUP-002', 'DEM-001'))
        self.assertEqual(result.compatibility_result, 'INELIGIBLE')
        self.assertEqual(result.demand_newly_allocatable_quantity, 0)
        self.assertIn('DEMAND_ALREADY_COMMITTED', result.reason_codes)

    def test_received_unused_still_commits_demand(self):
        result = self.evaluate(self.pair('SUP-005', 'DEM-005'))
        self.assertEqual(result.max_allocatable_quantity, 100)

    def test_requested_and_approved_do_not_commit(self):
        self.assertEqual(self.evaluate(self.pair('SUP-006', 'DEM-006')).max_allocatable_quantity, 300)
        self.assertEqual(self.evaluate(self.pair('SUP-011', 'DEM-010')).max_allocatable_quantity, 250)

    def test_dispatched_stock_is_not_available_again(self):
        result = self.evaluate(self.pair('SUP-001', 'DEM-021'))
        self.assertIn('INSUFFICIENT_STOCK', result.reason_codes)
        self.assertEqual(result.max_allocatable_quantity, 0)

    def test_potential_suspended_closed_are_blocked(self):
        for sid, did in [('SUP-007', 'DEM-012'), ('SUP-012', 'DEM-011'), ('SUP-013', 'DEM-012')]:
            with self.subTest(sid=sid):
                result = self.evaluate(self.pair(sid, did))
                self.assertEqual(result.compatibility_result, 'INELIGIBLE')
                self.assertIn('SUPPLY_NOT_CONFIRMED', result.reason_codes)

    def test_unknown_and_recovered_condition_require_review(self):
        pair = self.pair('SUP-020', 'DEM-019')
        for condition in ('UNKNOWN', 'RECOVERED'):
            result = self.evaluate((replace(pair[0], condition=condition), *pair[1:]))
            self.assertEqual(result.compatibility_result, 'REVIEW_REQUIRED')
            self.assertEqual(result.max_allocatable_quantity, 0)

    def test_tile_spec_mismatch(self):
        result = self.evaluate(self.pair('SUP-008', 'DEM-007'))
        self.assertIn('MATERIAL_SPEC_MISMATCH', result.reason_codes)
        self.assertEqual(result.compatibility_result, 'INELIGIBLE')

    def test_same_id_cannot_hide_conflicting_specs(self):
        s, d, sm, dm = self.pair()
        dm = replace(dm, specifications={**dm.specifications, 'thickness_mm': 60})
        self.assertIn('MATERIAL_SPEC_MISMATCH', self.evaluate((s, d, sm, dm)).reason_codes)

    def test_missing_critical_spec_requires_review(self):
        s, d, sm, dm = self.pair('SUP-006', 'DEM-006')
        specs = {**sm.specifications, 'grade': None}
        result = self.evaluate((s, d, replace(sm, specifications=specs), replace(dm, specifications=specs)))
        self.assertEqual(result.compatibility_result, 'REVIEW_REQUIRED')

    def test_explicit_context_spec_requirement(self):
        result = self.evaluate(self.pair('SUP-021', 'DEM-020'),
                               extra_required_spec_fields=('slip_rating',))
        self.assertIn('MATERIAL_SPEC_REVIEW_REQUIRED', result.reason_codes)

    def test_unit_conversion_not_assumed(self):
        pair = self.pair()
        result = self.evaluate((replace(pair[0], unit='m2'), *pair[1:]))
        self.assertIn('UNIT_CONVERSION_UNSUPPORTED', result.reason_codes)

    def test_self_project_is_blocked(self):
        pair = self.pair()
        result = self.evaluate((replace(pair[0], source_project_id=pair[1].destination_project_id), *pair[1:]))
        self.assertIn('SAME_PROJECT', result.reason_codes)

    def test_fulfilled_and_cancelled_demand_are_blocked(self):
        for sid, did in [('SUP-002', 'DEM-002'), ('SUP-014', 'DEM-013')]:
            self.assertIn('DEMAND_NOT_OPEN', self.evaluate(self.pair(sid, did)).reason_codes)

    def test_unconfirmed_demand_and_missing_traceability_require_review(self):
        s, d, sm, dm = self.pair()
        result = self.evaluate((replace(s, batch_or_lot_code=None, evidence_refs=()),
                                replace(d, is_outstanding_need_confirmed=False), sm, dm))
        self.assertEqual(result.compatibility_result, 'REVIEW_REQUIRED')
        self.assertIn('TRACEABILITY_REVIEW_REQUIRED', result.reason_codes)
        self.assertIn('DEMAND_NOT_CONFIRMED', result.reason_codes)

    def test_release_after_deadline(self):
        result = self.evaluate(self.pair('SUP-009', 'DEM-008'))
        self.assertIn('INVALID_DATE_WINDOW', result.reason_codes)
        self.assertIsNone(result.earliest_delivery_date)

    def test_future_release_can_be_planned_but_not_reserved_today(self):
        s, d, sm, dm = self.pair()
        s = replace(s, available_from=date(2026, 10, 20))
        result = self.evaluate((s, d, sm, dm))
        self.assertEqual(result.compatibility_result, 'ELIGIBLE')
        self.assertEqual(result.max_allocatable_quantity, 200)
        self.assertEqual(result.source_reservable_quantity_on_planning_date, 0)
        self.assertEqual(result.earliest_delivery_date, date(2026, 10, 21))

    def test_lead_time_and_dispatch_window_are_enforced(self):
        s, d, sm, dm = self.pair()
        d = replace(d, needed_from=date(2026, 10, 20), required_by=date(2026, 10, 22))
        s = replace(s, available_until=date(2026, 10, 18))
        result = self.evaluate((s, d, sm, dm))
        self.assertEqual(result.compatibility_result, 'INELIGIBLE')
        result = self.evaluate((s, d, sm, dm), lead_time_days=2)
        self.assertEqual(result.earliest_dispatch_date, date(2026, 10, 18))
        self.assertEqual(result.earliest_delivery_date, date(2026, 10, 20))
        self.assertEqual(result.compatibility_result, 'ELIGIBLE')

    def test_missing_lead_time_requires_review(self):
        result = self.evaluate(self.pair(), lead_time_days=None)
        self.assertEqual(result.compatibility_result, 'REVIEW_REQUIRED')
        self.assertIsNone(result.earliest_delivery_date)

    def test_no_carbon_factor_does_not_block_operational_match(self):
        result = self.evaluate(self.pair('SUP-010', 'DEM-009'))
        self.assertEqual(result.compatibility_result, 'ELIGIBLE')
        self.assertEqual(result.max_allocatable_quantity, 150)

    def test_bad_balances_fail_instead_of_clamping(self):
        for args in [(100, 80, 30), (None, 1, 0), (-1, 0, 0), (True, 0, 0), (1.5, 0, 0)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                SupplyQuantity(*args)
        with self.assertRaises(ValueError):
            DemandQuantity(600, 550, 51)

    def test_identity_and_reversed_windows_fail(self):
        s, d, sm, dm = self.pair()
        with self.assertRaises(ValueError):
            self.evaluate((s, d, replace(sm, id='MAT-999'), dm))
        with self.assertRaises(ValueError):
            replace(s, available_until=date(2026, 1, 1))
        with self.assertRaises(ValueError):
            replace(d, required_by=date(2026, 1, 1))

    def test_deterministic_and_no_input_mutation(self):
        pair = self.pair()
        before = copy.deepcopy(self.seed)
        self.assertEqual(self.evaluate(pair), self.evaluate(pair))
        self.assertEqual(self.seed, before)


if __name__ == '__main__':
    unittest.main()
