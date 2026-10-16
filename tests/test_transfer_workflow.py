import copy
import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.app.repositories.transfer_repository import (
    TransferRepositoryUnavailable,
    TransferWorkflowState,
)
from backend.app.services.transfer_workflow_service import (
    TransferWorkflowConflict,
    TransferWorkflowInvalid,
    TransferWorkflowNotFound,
    TransferWorkflowUnavailable,
    WorkflowInput,
    _validate,
    run_transfer_workflow,
)


NOW = lambda: datetime(2026, 10, 13, 12, 0, tzinfo=timezone(timedelta(hours=8)))


class FakeRepository:
    def __init__(self, state, demand=None, unavailable=False):
        self.state, self.demand, self.unavailable = state, demand, unavailable
        self.writes = []

    def get_workflow_state(self, *_args):
        if self.unavailable:
            raise TransferRepositoryUnavailable("offline")
        return self.state

    def get_demand_request(self, _id):
        return self.demand


class TransferWorkflowValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed = json.loads((Path(__file__).resolve().parents[1] / "data" / "terra_seed.json").read_text(encoding="utf-8"))
        cls.transfer = copy.deepcopy(seed["transfers"][0])
        cls.proposal = copy.deepcopy(next(x for x in seed["allocation_proposals"] if x["id"] == "ALC-007"))
        cls.supply = copy.deepcopy(next(x for x in seed["supply_offers"] if x["id"] == "SUP-011"))
        cls.demand = copy.deepcopy(next(x for x in seed["demand_requests"] if x["id"] == "DEM-010"))

    def state(self, status="APPROVED", **updates):
        transfer = {**self.transfer, "status": status, "approved_quantity": 200,
                    "source_confirmation_status": "CONFIRMED",
                    "destination_confirmation_status": "CONFIRMED", **updates}
        return TransferWorkflowState(transfer, self.proposal, self.supply,
                                     self.demand, None, None)

    def request(self, quantity=None, reason=None):
        return WorkflowInput("Demo operator", "unit-key", quantity, reason)

    def repository(self, state, **demand_updates):
        demand = {**self.demand, "committed_incoming_quantity": 0,
                  "uncommitted_quantity": 250, **demand_updates}
        return FakeRepository(state, demand)

    def assert_code(self, exception, code, action, state, request, repository=None):
        with self.assertRaises(exception) as raised:
            run_transfer_workflow("TRF-001", action, request,
                                  repository or self.repository(state), NOW)
        self.assertEqual(raised.exception.code, code)

    def test_unknown_invalid_stage_and_unavailable(self):
        missing = TransferWorkflowState(None, None, None, None, None, None)
        self.assert_code(TransferWorkflowNotFound, "TRANSFER_NOT_FOUND", "reserve",
                         missing, self.request())
        self.assert_code(TransferWorkflowConflict, "TRANSFER_INVALID_STAGE", "reserve",
                         self.state("CANCELLED"), self.request())
        with self.assertRaises(TransferWorkflowUnavailable):
            run_transfer_workflow("TRF-001", "reserve", self.request(),
                                  FakeRepository(None, unavailable=True), NOW)

    def test_reservation_rechecks_confirmations_stock_demand_and_dates(self):
        self.assert_code(TransferWorkflowInvalid, "TRANSFER_CONFIRMATIONS_REQUIRED", "reserve",
                         self.state(source_confirmation_status="PENDING"), self.request())
        low_supply = copy.deepcopy(self.supply); low_supply["confirmed_quantity"] = 100
        state = self.state(); state = TransferWorkflowState(state.transfer, state.proposal,
            low_supply, state.demand_request, None, None)
        self.assert_code(TransferWorkflowConflict, "SOURCE_STOCK_UNAVAILABLE", "reserve",
                         state, self.request())
        self.assert_code(TransferWorkflowConflict, "DEMAND_UNAVAILABLE", "reserve",
                         self.state(), self.request(), self.repository(self.state(), uncommitted_quantity=100))
        late = copy.deepcopy(self.supply); late["available_until"] = "2026-10-12"
        state = self.state(); state = TransferWorkflowState(state.transfer, state.proposal,
            late, state.demand_request, None, None)
        self.assert_code(TransferWorkflowConflict, "TRANSFER_DATE_INELIGIBLE", "reserve",
                         state, self.request())

    def test_dispatch_derives_full_reservation_and_rejects_inconsistent_state(self):
        state = self.state("RESERVED", reserved_quantity=100,
                           approved_quantity=100, dispatched_quantity=0)
        supply = {**state.supply_offer, "reserved_active_quantity": 100}
        state = TransferWorkflowState(state.transfer, state.proposal, supply,
                                      state.demand_request, None, None)
        self.assertEqual(
            _validate("dispatch", self.request(), state, "2026-10-13",
                      self.repository(state)),
            100,
        )
        self.assert_code(TransferWorkflowInvalid, "DISPATCH_QUANTITY_NOT_ACCEPTED",
                         "dispatch", state, self.request(100))
        self.assert_code(TransferWorkflowConflict, "DISPATCH_RESERVATION_INVALID",
                         "dispatch", self.state("RESERVED", reserved_quantity=0),
                         self.request())
        self.assert_code(TransferWorkflowConflict, "TRANSFER_PARTIALLY_DISPATCHED",
                         "dispatch", self.state("IN_TRANSIT", reserved_quantity=100,
                         dispatched_quantity=100), self.request())
        self.assert_code(TransferWorkflowConflict,
                         "TRANSFER_PARTIAL_RESERVATION_UNSUPPORTED", "dispatch",
                         self.state("RESERVED", reserved_quantity=100,
                                    dispatched_quantity=0), self.request())

    def test_receipt_derives_full_dispatch_and_rejects_inconsistent_state(self):
        state = self.state("IN_TRANSIT", reserved_quantity=0,
                           dispatched_quantity=100, received_quantity=0,
                           actually_used_quantity=0)
        self.assertEqual(
            _validate("receive", self.request(), state, "2026-10-13",
                      self.repository(state)),
            100,
        )
        self.assert_code(TransferWorkflowInvalid, "RECEIPT_QUANTITY_NOT_ACCEPTED",
                         "receive", state, self.request(100))
        self.assert_code(TransferWorkflowConflict, "RECEIPT_DISPATCH_INVALID",
                         "receive", self.state("IN_TRANSIT", reserved_quantity=0,
                         dispatched_quantity=0), self.request())
        self.assert_code(TransferWorkflowConflict, "RECEIPT_RESERVATION_REMAINS",
                         "receive", self.state("IN_TRANSIT", reserved_quantity=1,
                         dispatched_quantity=100), self.request())
        self.assert_code(TransferWorkflowConflict, "TRANSFER_PARTIALLY_RECEIVED",
                         "receive", self.state("RECEIVED", reserved_quantity=0,
                         dispatched_quantity=100, received_quantity=50), self.request())

    def test_use_quantity_and_cancellation_reason(self):
        self.assert_code(TransferWorkflowInvalid, "TRANSFER_QUANTITY_EXCEEDS_STAGE", "confirm_use",
                         self.state("RECEIVED", received_quantity=140), self.request(141))
        self.assert_code(TransferWorkflowInvalid, "CANCELLATION_REASON_REQUIRED", "cancel",
                         self.state("RESERVED", reserved_quantity=200), self.request(reason=" "))
        self.assert_code(TransferWorkflowConflict, "TRANSFER_INVALID_STAGE", "cancel",
                         self.state("IN_TRANSIT", dispatched_quantity=1), self.request(reason="test"))

    def test_repeated_confirm_use_accepts_only_remaining_received_quantity(self):
        repeated = self.state(
            "REUSED", approved_quantity=200, dispatched_quantity=200,
            received_quantity=200, actually_used_quantity=120,
        )
        self.assertEqual(
            _validate("confirm_use", self.request(50), repeated, "2026-10-13",
                      self.repository(repeated)),
            50,
        )
        self.assert_code(
            TransferWorkflowInvalid, "TRANSFER_QUANTITY_EXCEEDS_STAGE", "confirm_use",
            repeated, self.request(81), self.repository(repeated),
        )


if __name__ == "__main__":
    unittest.main()
