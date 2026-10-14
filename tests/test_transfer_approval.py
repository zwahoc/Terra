import asyncio
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.repositories.transfer_repository import (
    TransferApprovalMutationError,
    TransferApprovalState,
    TransferRepositoryUnavailable,
)
from backend.app.services.transfer_approval_service import (
    TransferApprovalConflict,
    TransferApprovalInput,
    TransferApprovalInvalid,
    TransferApprovalNotFound,
    TransferApprovalUnavailable,
    approve_transfer,
)
from tests.test_transfers_api import request as api_request


APPROVAL_BODY = {
    "approved_quantity": 200,
    "source_confirmation_status": "CONFIRMED",
    "destination_confirmation_status": "CONFIRMED",
    "actor_label": "Demo operator",
    "idempotency_key": "approve-trf-001-postman-001",
    "evidence_ref": "SYNTHETIC Postman approval; no physical evidence",
}


class FakeApprovalRepository:
    def __init__(self, transfer, proposal, mutation_error=None, commit_then_error=False):
        self.transfer = copy.deepcopy(transfer)
        self.proposal = copy.deepcopy(proposal)
        self.operation = None
        self.event = None
        self.mutation_error = mutation_error
        self.commit_then_error = commit_then_error
        self.commands = []

    def get_approval_state(self, transfer_id, operation_id, event_id):
        transfer = self.transfer if self.transfer and self.transfer["id"] == transfer_id else None
        operation = (
            self.operation
            if self.operation and self.operation["id"] == operation_id
            else None
        )
        event = self.event if self.event and self.event["id"] == event_id else None
        return TransferApprovalState(
            copy.deepcopy(transfer),
            copy.deepcopy(self.proposal) if transfer else None,
            copy.deepcopy(operation),
            copy.deepcopy(event),
        )

    def approve(self, command):
        self.commands.append(copy.deepcopy(command))
        if self.mutation_error and not self.commit_then_error:
            raise self.mutation_error
        self.transfer.update(
            approved_quantity=command["approved_quantity"],
            status="APPROVED",
            source_confirmation_status=command["source_confirmation_status"],
            destination_confirmation_status=command[
                "destination_confirmation_status"
            ],
        )
        self.operation = {
            "id": command["operation_id"],
            "request_fingerprint": command["request_fingerprint"],
            "transfer_id": command["transfer_id"],
            "event_id": command["event_id"],
            "approved_quantity": command["approved_quantity"],
            "source_confirmation_status": command["source_confirmation_status"],
            "destination_confirmation_status": command[
                "destination_confirmation_status"
            ],
            "actor_label": command["actor_label"],
            "evidence_ref": command["evidence_ref"],
            "occurred_at": command["occurred_at"],
        }
        self.event = {
            "id": command["event_id"],
            "transfer_id": command["transfer_id"],
            "event_type": "APPROVED",
            "occurred_at": command["occurred_at"],
            "actor_label": command["actor_label"],
            "payload": command["event_payload"],
            "evidence_ref": command["evidence_ref"],
        }
        if self.mutation_error:
            raise self.mutation_error


class TransferApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_path = Path(__file__).resolve().parents[1] / "data" / "terra_seed.json"
        cls.seed = json.loads(seed_path.read_text(encoding="utf-8"))
        cls.transfer = next(row for row in cls.seed["transfers"] if row["id"] == "TRF-001")
        cls.proposal = next(
            row for row in cls.seed["allocation_proposals"] if row["id"] == "ALC-007"
        )
        cls.supply = next(
            row
            for row in cls.seed["supply_offers"]
            if row["id"] == cls.proposal["supply_offer_id"]
        )
        cls.demand = next(
            row
            for row in cls.seed["demand_requests"]
            if row["id"] == cls.proposal["demand_request_id"]
        )

    def approval(self, **changes):
        return TransferApprovalInput(**{**APPROVAL_BODY, **changes})

    def repository(self, **kwargs):
        return FakeApprovalRepository(self.transfer, self.proposal, **kwargs)

    def approve(self, repository, approval=None):
        return approve_transfer(
            "TRF-001",
            approval or self.approval(),
            repository,
            clock=lambda: datetime(2026, 10, 13, 10, 30, tzinfo=timezone.utc),
        )

    def test_success_persists_complete_approval_without_stock_or_demand_changes(self):
        repository = self.repository()
        supply_before = copy.deepcopy(self.supply)
        demand_before = copy.deepcopy(self.demand)

        response = self.approve(repository)

        self.assertEqual(response["data"]["transfer"]["status"], "APPROVED")
        self.assertEqual(response["data"]["transfer"]["approved_quantity"], 200)
        self.assertEqual(response["data"]["transfer"]["reserved_quantity"], 0)
        self.assertEqual(response["data"]["event"]["event_type"], "APPROVED")
        self.assertEqual(response["data"]["event"]["payload"]["quantity"], 200)
        self.assertFalse(response["data"]["replayed"])
        self.assertEqual(self.supply, supply_before)
        self.assertEqual(self.demand, demand_before)
        self.assertEqual(len(repository.commands), 1)

    def test_invalid_and_excessive_quantities_are_rejected_without_write(self):
        for quantity, code in [
            (0, "APPROVED_QUANTITY_INVALID"),
            (251, "APPROVED_QUANTITY_EXCEEDS_PROPOSAL"),
        ]:
            with self.subTest(quantity=quantity):
                repository = self.repository()
                with self.assertRaises(TransferApprovalInvalid) as raised:
                    self.approve(repository, self.approval(approved_quantity=quantity))
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(repository.commands, [])

    def test_both_confirmations_are_required(self):
        for field in (
            "source_confirmation_status",
            "destination_confirmation_status",
        ):
            repository = self.repository()
            with self.assertRaises(TransferApprovalInvalid) as raised:
                self.approve(repository, self.approval(**{field: "PENDING"}))
            self.assertEqual(raised.exception.code, "TRANSFER_CONFIRMATIONS_REQUIRED")
            self.assertEqual(repository.commands, [])

    def test_unknown_transfer_and_invalid_stage(self):
        missing = FakeApprovalRepository(None, self.proposal)
        with self.assertRaises(TransferApprovalNotFound):
            self.approve(missing)

        approved = {**self.transfer, "status": "APPROVED"}
        invalid_stage = FakeApprovalRepository(approved, self.proposal)
        with self.assertRaises(TransferApprovalConflict) as raised:
            self.approve(invalid_stage)
        self.assertEqual(raised.exception.code, "TRANSFER_INVALID_STAGE")

    def test_identical_retry_is_replayed_and_changed_input_conflicts(self):
        repository = self.repository()
        first = self.approve(repository)
        retry = self.approve(repository)

        self.assertFalse(first["data"]["replayed"])
        self.assertTrue(retry["data"]["replayed"])
        self.assertEqual(len(repository.commands), 1)
        with self.assertRaises(TransferApprovalConflict) as raised:
            self.approve(repository, self.approval(approved_quantity=199))
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(len(repository.commands), 1)

    def test_concurrent_retry_winner_is_returned_without_duplicate_effect(self):
        repository = self.repository(
            mutation_error=TransferApprovalMutationError("duplicate key"),
            commit_then_error=True,
        )

        response = self.approve(repository)

        self.assertTrue(response["data"]["replayed"])
        self.assertEqual(len(repository.commands), 1)
        self.assertEqual(repository.event["event_type"], "APPROVED")

    def test_transaction_failure_has_no_partial_persistence(self):
        repository = self.repository(
            mutation_error=TransferApprovalMutationError("event insert failed")
        )

        with self.assertRaisesRegex(Exception, "transaction failed"):
            self.approve(repository)

        self.assertEqual(repository.transfer, self.transfer)
        self.assertIsNone(repository.operation)
        self.assertIsNone(repository.event)

    def test_emulator_unavailability_is_503_domain_error(self):
        repository = self.repository()
        repository.get_approval_state = lambda *_args: (_ for _ in ()).throw(
            TransferRepositoryUnavailable("offline")
        )
        with self.assertRaises(TransferApprovalUnavailable):
            self.approve(repository)

    def test_route_success_error_envelope_and_dto_validation(self):
        successful = {
            "data": {
                "transfer": {**self.transfer, "approved_quantity": 200, "status": "APPROVED", "source_confirmation_status": "CONFIRMED", "destination_confirmation_status": "CONFIRMED"},
                "event": {
                    "id": "EVT-APR-test",
                    "transfer_id": "TRF-001",
                    "event_type": "APPROVED",
                    "occurred_at": "2026-10-13T18:30:00+08:00",
                    "actor_label": "Demo operator",
                    "payload": {"quantity": 200, "synthetic": True},
                    "evidence_ref": APPROVAL_BODY["evidence_ref"],
                },
                "idempotency_key": APPROVAL_BODY["idempotency_key"],
                "replayed": False,
            },
            "meta": {"dataset_version": "test", "synthetic": True, "as_of_date": "2026-10-12"},
            "error": None,
        }
        with patch(
            "backend.app.routes.transfers.approve_transfer", return_value=successful
        ):
            status, body = asyncio.run(
                api_request("POST", "/api/transfers/TRF-001/approve", APPROVAL_BODY)
            )
        self.assertEqual((status, body), (200, successful))

        invalid = {**APPROVAL_BODY, "approved_quantity": 0}
        status, body = asyncio.run(
            api_request("POST", "/api/transfers/TRF-001/approve", invalid)
        )
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "REQUEST_VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
