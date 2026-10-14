import json
import unittest
from pathlib import Path

from backend.app.repositories.transfer_repository import (
    TransferRepository,
    TransferRepositoryError,
    TransferRepositoryUnavailable,
)
from terra.contract import camel, fields
from terra.local_adapter import AdapterError, AdapterUnavailableError


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def execute(self, operation, variables=None, write=False):
        self.calls.append((operation, variables, write))
        if self.error:
            raise self.error
        return self.result


def provider_transfer(transfer):
    return {
        camel(name): transfer[name]
        for name, _spec, _optional in fields("transfers")
    }


class TransferRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_path = Path(__file__).resolve().parents[1] / "data" / "terra_seed.json"
        cls.transfers = json.loads(seed_path.read_text(encoding="utf-8"))["transfers"]

    def test_list_uses_actual_named_operation_and_maps_provider_fields(self):
        provider_rows = [provider_transfer(row) for row in self.transfers]
        provider_rows[0]["requestedAt"] = "2026-10-02T01:00:00Z"
        adapter = FakeAdapter({"transfers": provider_rows})

        records = TransferRepository(adapter).list()

        self.assertEqual(adapter.calls, [("ListTransfers", None, False)])
        self.assertEqual(records, self.transfers)
        self.assertIn("proposal_id", records[0])
        self.assertNotIn("proposalId", records[0])

    def test_get_uses_bounded_list_and_returns_exact_id(self):
        adapter = FakeAdapter(
            {"transfers": [provider_transfer(row) for row in self.transfers]}
        )
        repository = TransferRepository(adapter)

        self.assertEqual(repository.get("TRF-001"), self.transfers[0])
        self.assertIsNone(repository.get("TRF-999"))
        self.assertEqual(
            adapter.calls,
            [("ListTransfers", None, False), ("ListTransfers", None, False)],
        )

    def test_transport_failure_is_unavailable(self):
        adapter = FakeAdapter(error=AdapterUnavailableError("connection refused"))

        with self.assertRaises(TransferRepositoryUnavailable):
            TransferRepository(adapter).list()

    def test_provider_failure_is_not_unavailable(self):
        adapter = FakeAdapter(error=AdapterError("GraphQL schema error"))

        with self.assertRaises(TransferRepositoryError) as raised:
            TransferRepository(adapter).list()
        self.assertNotIsInstance(raised.exception, TransferRepositoryUnavailable)

    def test_invalid_provider_shape_is_data_error(self):
        adapter = FakeAdapter({"transfers": [{"id": "TRF-001"}]})

        with self.assertRaises(TransferRepositoryError):
            TransferRepository(adapter).list()

    def test_approval_state_uses_named_query_and_maps_all_provider_fields(self):
        transfer = self.transfers[0]
        provider_row = provider_transfer(transfer)
        provider_row["proposal"] = {
            "id": "ALC-007",
            "proposedQuantity": 250,
            "unit": "pcs",
            "compatibilityResult": "ELIGIBLE",
            "status": "SELECTED",
            "supplyOfferId": "SUP-011",
            "demandRequestId": "DEM-010",
        }
        adapter = FakeAdapter(
            {
                "transfer": provider_row,
                "transferApprovalOperation": None,
                "transferEvent": None,
            }
        )

        state = TransferRepository(adapter).get_approval_state(
            "TRF-001", "APR-key", "EVT-APR-key"
        )

        self.assertEqual(state.transfer, transfer)
        self.assertEqual(state.proposal["proposed_quantity"], 250)
        self.assertIsNone(state.operation)
        self.assertEqual(
            adapter.calls,
            [
                (
                    "GetTransferApprovalState",
                    {
                        "transferId": "TRF-001",
                        "operationId": "APR-key",
                        "eventId": "EVT-APR-key",
                    },
                    False,
                )
            ],
        )

    def test_approve_uses_actual_atomic_named_mutation(self):
        adapter = FakeAdapter({"transferApprovalOperation_insert": "APR-key"})
        command = {
            "transfer_id": "TRF-001",
            "operation_id": "APR-key",
            "request_fingerprint": "fingerprint",
            "event_id": "EVT-APR-key",
            "approved_quantity": 200,
            "source_confirmation_status": "CONFIRMED",
            "destination_confirmation_status": "CONFIRMED",
            "actor_label": "Demo operator",
            "evidence_ref": None,
            "event_payload": {"quantity": 200, "synthetic": True},
            "occurred_at": "2026-10-13T18:30:00+08:00",
        }

        TransferRepository(adapter).approve(command)

        operation, variables, write = adapter.calls[0]
        self.assertEqual(operation, "ApproveTransfer")
        self.assertTrue(write)
        self.assertEqual(variables["approvedQuantity"], 200)
        self.assertEqual(variables["eventPayload"], command["event_payload"])
        self.assertNotIn("reservedQuantity", variables)


if __name__ == "__main__":
    unittest.main()
