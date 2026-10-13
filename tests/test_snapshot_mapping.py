"""Snapshot preparation tests using the real portable fixture; no database I/O."""
import copy
import unittest
from datetime import date

from backend.app.domain.eligibility import DemandQuantity, SupplyQuantity, evaluate_eligibility
from backend.app.domain.snapshot_mapping import SnapshotMappingError, map_record_collections
from terra.validation import load


COLLECTIONS = ('projects', 'materials', 'documents', 'extracted_rows', 'supply_offers',
               'demand_requests', 'optimisation_runs', 'allocation_proposals', 'transfers')


class SnapshotMappingTests(unittest.TestCase):
    def setUp(self):
        self.seed = load()

    def map(self, seed=None):
        seed = self.seed if seed is None else seed
        return map_record_collections(as_of_date=date(2026, 10, 12),
                                      **{name: seed[name] for name in COLLECTIONS})

    def row(self, entity, rid):
        return next(row for row in self.seed[entity] if row['id'] == rid)

    def test_baseline_counts_and_evaluator_integration(self):
        snapshot = self.map()
        self.assertEqual((len(snapshot.materials), len(snapshot.supplies), len(snapshot.demands)),
                         (20, 22, 22))
        s, d = snapshot.supplies['SUP-003'], snapshot.demands['DEM-003']
        self.assertEqual(s.quantity.uncommitted_quantity, 500)
        self.assertEqual(d.quantity.incoming_committed_quantity, 300)
        self.assertEqual(d.quantity.newly_allocatable_quantity, 200)
        self.assertEqual(snapshot.incoming_transfer_ids_by_demand['DEM-003'], ('TRF-003',))
        result = evaluate_eligibility(s, d, snapshot.materials[s.material_id],
                                      snapshot.materials[d.material_id],
                                      planning_date=snapshot.as_of_date, lead_time_days=1)
        self.assertEqual((result.compatibility_result, result.max_allocatable_quantity),
                         ('ELIGIBLE', 200))

    def test_stages_and_residual_commitments(self):
        snapshot = self.map()
        expected = {'DEM-001': 50, 'DEM-002': 0, 'DEM-003': 300, 'DEM-004': 250,
                    'DEM-005': 200, 'DEM-006': 0, 'DEM-010': 0, 'DEM-021': 0}
        for did, quantity in expected.items():
            with self.subTest(did=did):
                self.assertEqual(snapshot.demands[did].quantity.incoming_committed_quantity, quantity)
        self.assertEqual(snapshot.incoming_transfer_ids_by_demand['DEM-001'], ('TRF-006',))
        self.assertEqual(snapshot.demands['DEM-001'].quantity.newly_allocatable_quantity, 0)
        self.assertEqual(snapshot.supplies['SUP-001'].quantity.transferred_out_quantity, 1000)
        self.assertEqual(snapshot.supplies['SUP-022'].quantity.reserved_active_quantity, 0)

    def test_no_counts_baseline_or_synthetic_requirement(self):
        empty = map_record_collections(as_of_date=date(2027, 1, 1),
                                       **{name: [] for name in COLLECTIONS})
        self.assertEqual(len(empty.supplies), 0)
        self.row('materials', 'MAT-001')['is_synthetic'] = False
        self.assertEqual(self.map().materials['MAT-001'].id, 'MAT-001')

    def test_dates_are_python_objects_and_future_release_is_retained(self):
        snapshot = self.map()
        self.assertEqual(snapshot.supplies['SUP-009'].available_from, date(2026, 10, 25))
        self.assertEqual(snapshot.demands['DEM-008'].required_by, date(2026, 10, 18))
        self.assertEqual(snapshot.supplies['SUP-007'].surplus_status, 'POTENTIAL')

    def test_duplicate_ids_orphan_references_and_unknown_fields(self):
        changes = [
            lambda: self.seed['transfers'].append(copy.deepcopy(self.seed['transfers'][0])),
            lambda: self.row('supply_offers', 'SUP-003').update(material_id='MAT-999'),
            lambda: self.row('transfers', 'TRF-003').update(proposal_id='ALC-999'),
            lambda: self.row('supply_offers', 'SUP-003').update(incoming_quantity=1),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.seed = load()
                change()
                with self.assertRaises(SnapshotMappingError):
                    self.map()

    def test_invalid_enums_and_missing_counters_fail(self):
        self.row('transfers', 'TRF-003')['status'] = 'DONE'
        with self.assertRaises(SnapshotMappingError):
            self.map()
        self.seed = load()
        del self.row('supply_offers', 'SUP-003')['reserved_active_quantity']
        with self.assertRaises(SnapshotMappingError):
            self.map()

    def test_shape_uses_shared_snake_case_contract(self):
        r = self.row('supply_offers', 'SUP-003')
        r['confirmedQuantity'] = r.pop('confirmed_quantity')
        with self.assertRaises(SnapshotMappingError):
            self.map()

    def test_counter_drift_and_incomplete_transfer_collection_fail(self):
        self.row('supply_offers', 'SUP-003')['reserved_active_quantity'] = 299
        with self.assertRaisesRegex(SnapshotMappingError, 'SUP-003.*reconcile'):
            self.map()
        self.seed = load()
        self.seed['transfers'] = [t for t in self.seed['transfers'] if t['id'] != 'TRF-003']
        with self.assertRaisesRegex(SnapshotMappingError, 'SUP-003.*reconcile'):
            self.map()

    def test_fulfilled_counter_is_actual_use_not_receipt(self):
        self.row('demand_requests', 'DEM-005')['fulfilled_quantity'] = 200
        with self.assertRaisesRegex(SnapshotMappingError, 'DEM-005.*actual use'):
            self.map()

    def test_declared_confirmed_and_recipient_overbooking(self):
        self.row('supply_offers', 'SUP-003')['declared_quantity'] = 799
        with self.assertRaisesRegex(SnapshotMappingError, 'confirmed.*declared'):
            self.map()
        self.seed = load()
        self.row('demand_requests', 'DEM-003')['required_quantity'] = 299
        with self.assertRaisesRegex(SnapshotMappingError, 'commitments exceed'):
            self.map()

    def test_review_and_provenance_validation(self):
        changes = [
            lambda: self.row('extracted_rows', 'ROW-003').update(review_status='PENDING'),
            lambda: self.row('extracted_rows', 'ROW-003').update(suggested_material_id='MAT-001'),
            lambda: self.row('documents', 'DOC-001').update(project_id='PRJ-002'),
            lambda: self.row('extracted_rows', 'ROW-003')['parsed_fields'].update(record_kind='PURCHASE_ORDER'),
            lambda: self.row('extracted_rows', 'ROW-025')['parsed_fields'].update(record_kind='ON_HAND_INVENTORY'),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.seed = load()
                change()
                with self.assertRaises(SnapshotMappingError):
                    self.map()

    def test_manual_origin_is_allowed(self):
        self.row('supply_offers', 'SUP-003')['origin_document_row_id'] = None
        self.row('demand_requests', 'DEM-003')['origin_document_row_id'] = None
        self.assertEqual(self.map().demands['DEM-003'].quantity.newly_allocatable_quantity, 200)

    def test_duplicate_transfer_for_proposal_is_rejected(self):
        t = copy.deepcopy(self.row('transfers', 'TRF-003'))
        t['id'] = 'TRF-009'
        self.seed['transfers'].append(t)
        with self.assertRaisesRegex(SnapshotMappingError, 'duplicate transfer for proposal'):
            self.map()

    def test_alternative_proposals_do_not_consume_balances(self):
        p = copy.deepcopy(self.row('allocation_proposals', 'ALC-009'))
        p['id'] = 'ALC-016'
        self.seed['allocation_proposals'].append(p)
        self.assertEqual(self.map().demands['DEM-021'].quantity.newly_allocatable_quantity, 800)
        self.assertEqual(self.map().supplies['SUP-002'].quantity.uncommitted_quantity, 500)

    def test_bad_transfer_stages_and_quantities_are_rejected(self):
        changes = [
            lambda: self.row('transfers', 'TRF-002').update(reserved_quantity=1),
            lambda: self.row('transfers', 'TRF-006').update(actually_used_quantity=581),
            lambda: self.row('transfers', 'TRF-003').update(source_confirmation_status='PENDING'),
            lambda: self.row('allocation_proposals', 'ALC-003').update(compatibility_result='INELIGIBLE'),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.seed = load()
                change()
                with self.assertRaises(SnapshotMappingError):
                    self.map()

    def test_post_dispatch_cancellation_is_not_silently_restocked(self):
        self.row('transfers', 'TRF-004')['status'] = 'CANCELLED'
        with self.assertRaisesRegex(SnapshotMappingError, 'post-dispatch cancellation'):
            self.map()

    def test_invalid_dates_and_future_history_are_rejected(self):
        self.row('demand_requests', 'DEM-003')['required_by'] = '2026-02-30'
        with self.assertRaisesRegex(SnapshotMappingError, 'invalid ISO date'):
            self.map()
        self.seed = load()
        self.row('transfers', 'TRF-003')['requested_at'] = '2026-10-13T09:00:00+08:00'
        with self.assertRaisesRegex(SnapshotMappingError, 'after snapshot'):
            self.map()

    def test_output_is_detached_immutable_and_order_independent(self):
        before = copy.deepcopy(self.seed)
        snapshot = self.map()
        self.assertEqual(self.seed, before)
        shuffled = {name: list(reversed(rows)) if name in COLLECTIONS else rows
                    for name, rows in self.seed.items()}
        self.assertEqual(snapshot, self.map(shuffled))
        self.row('materials', 'MAT-002')['specifications']['thickness_mm'] = 60
        self.assertEqual(snapshot.materials['MAT-002'].specifications['thickness_mm'], 80)
        with self.assertRaises(TypeError):
            snapshot.materials['MAT-002'].specifications['thickness_mm'] = 60
        with self.assertRaises(TypeError):
            snapshot.supplies['SUP-003'] = None

    def test_quantity_counters_cannot_default_to_zero(self):
        with self.assertRaises(TypeError):
            SupplyQuantity(800)
        with self.assertRaises(TypeError):
            DemandQuantity(500)


if __name__ == '__main__':
    unittest.main()
