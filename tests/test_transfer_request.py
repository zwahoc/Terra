import asyncio
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.repositories.transfer_repository import (
    TransferRequestMutationError, TransferRequestState,
)
from backend.app.services.transfer_request_service import (
    TransferRequestConflict, TransferRequestInput, create_transfer_request,
)
from tests.test_transfers_api import request as api_request


BODY = {"actor_label": "Demo operator", "idempotency_key": "matching-request-001",
        "evidence_ref": "Synthetic matching review", "notes": "Awaiting release decision"}


class FakeRequestRepository:
    def __init__(self, proposal, mutation_error=None, commit_then_error=False):
        self.proposal = copy.deepcopy(proposal)
        self.transfers = []
        self.operation = self.transfer = self.event = None
        self.mutation_error, self.commit_then_error = mutation_error, commit_then_error
        self.commands = []

    def get_request_state(self, proposal_id, operation_id, transfer_id, event_id):
        return TransferRequestState(
            copy.deepcopy(self.proposal) if self.proposal and self.proposal["id"] == proposal_id else None,
            copy.deepcopy(self.transfers),
            copy.deepcopy(self.operation) if self.operation and self.operation["id"] == operation_id else None,
            copy.deepcopy(self.transfer) if self.transfer and self.transfer["id"] == transfer_id else None,
            copy.deepcopy(self.event) if self.event and self.event["id"] == event_id else None,
        )

    def create_request(self, command):
        self.commands.append(copy.deepcopy(command))
        if self.mutation_error and not self.commit_then_error:
            raise self.mutation_error
        self.transfer = {"id": command["transfer_id"], "proposal_id": command["proposal_id"],
            "approved_quantity": command["approved_quantity"], "reserved_quantity": 0, "dispatched_quantity": 0,
            "received_quantity": 0, "actually_used_quantity": 0, "status": "REQUESTED",
            "source_confirmation_status": "CONFIRMED", "destination_confirmation_status": "CONFIRMED",
            "requested_at": command["occurred_at"], "delivered_at": None,
            "reuse_confirmed_at": None, "notes": command["notes"]}
        self.transfers = [self.transfer]
        self.event = {"id": command["event_id"], "transfer_id": command["transfer_id"],
            "event_type": "REQUESTED", "occurred_at": command["occurred_at"],
            "actor_label": command["actor_label"], "payload": command["event_payload"],
            "evidence_ref": command["evidence_ref"]}
        self.operation = {"id": command["operation_id"], "request_fingerprint": command["request_fingerprint"],
            "proposal_id": command["proposal_id"], "transfer_id": command["transfer_id"],
            "event_id": command["event_id"]}
        if self.mutation_error:
            raise self.mutation_error


class TransferRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed = json.loads((Path(__file__).resolve().parents[1] / "data" / "terra_seed.json").read_text(encoding="utf-8"))
        cls.proposal = next(row for row in seed["allocation_proposals"] if row["id"] == "ALC-007")

    def call(self, repository, request=None):
        return create_transfer_request("ALC-007", request or TransferRequestInput(**BODY), repository,
            clock=lambda: datetime(2026, 10, 13, 10, 30, tzinfo=timezone.utc))

    def test_creates_requested_transfer_and_event_without_reservation(self):
        repository = FakeRequestRepository(self.proposal)
        response = self.call(repository)
        transfer = response["data"]["transfer"]
        self.assertEqual(transfer["status"], "REQUESTED")
        self.assertEqual(transfer["approved_quantity"], self.proposal["proposed_quantity"])
        self.assertEqual(transfer["reserved_quantity"], 0)
        self.assertEqual(response["data"]["event"]["event_type"], "REQUESTED")
        self.assertFalse(response["data"]["event"]["payload"]["reservation_created"])
        self.assertFalse(response["data"]["replayed"])

    def test_identical_retry_replays_and_changed_input_conflicts(self):
        repository = FakeRequestRepository(self.proposal)
        self.call(repository)
        self.assertTrue(self.call(repository)["data"]["replayed"])
        self.assertEqual(len(repository.commands), 1)
        with self.assertRaises(TransferRequestConflict) as raised:
            self.call(repository, TransferRequestInput(**{**BODY, "notes": "changed"}))
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")

    def test_only_one_request_can_be_created_for_a_proposal(self):
        repository = FakeRequestRepository(self.proposal)
        self.call(repository)
        with self.assertRaises(TransferRequestConflict) as raised:
            self.call(repository, TransferRequestInput(**{**BODY, "idempotency_key": "different-key"}))
        self.assertEqual(raised.exception.code, "TRANSFER_REQUEST_ALREADY_EXISTS")

    def test_committed_concurrent_winner_is_replayed(self):
        repository = FakeRequestRepository(self.proposal,
            mutation_error=TransferRequestMutationError("duplicate key"), commit_then_error=True)
        self.assertTrue(self.call(repository)["data"]["replayed"])

    def test_route_uses_201_contract_and_validation_envelope(self):
        successful = {"data": {"transfer": {"id": "TRF-test", "proposal_id": "ALC-007", "approved_quantity": 0,
            "reserved_quantity": 0, "dispatched_quantity": 0, "received_quantity": 0, "actually_used_quantity": 0,
            "status": "REQUESTED", "source_confirmation_status": "CONFIRMED", "destination_confirmation_status": "CONFIRMED",
            "requested_at": "2026-10-13T18:30:00+08:00", "delivered_at": None, "reuse_confirmed_at": None, "notes": None},
            "event": {"id": "EVT-test", "transfer_id": "TRF-test", "event_type": "REQUESTED",
            "occurred_at": "2026-10-13T18:30:00+08:00", "actor_label": "Demo operator", "payload": {}, "evidence_ref": None},
            "idempotency_key": BODY["idempotency_key"], "replayed": False},
            "meta": {"dataset_version": "test", "synthetic": True, "as_of_date": "2026-10-12"}, "error": None}
        with patch("backend.app.routes.transfers.create_transfer_request", return_value=successful):
            status, response = asyncio.run(api_request("POST", "/api/allocation-proposals/ALC-007/approve", BODY))
        self.assertEqual((status, response), (201, successful))
        status, response = asyncio.run(api_request("POST", "/api/allocation-proposals/ALC-007/approve", {"actor_label": "Demo operator"}))
        self.assertEqual(status, 422)
        self.assertEqual(response["error"]["code"], "REQUEST_VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
