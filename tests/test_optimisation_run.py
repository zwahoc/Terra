import asyncio
import copy
import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.repositories.optimisation_repository import OptimisationPersistenceError, OptimisationPersistenceState
from backend.app.services.optimisation_run_service import (
    OptimisationRunConflict, OptimisationRunInput, persist_optimisation_run,
)
from terra.validation import load
from tests.test_impact_api import request as api_request


class FakeOptimisationRepository:
    def __init__(self, records, commit_then_error=False):
        self.records = copy.deepcopy(records); self.operation = self.run = None; self.proposals = []
        self.commit_then_error = commit_then_error; self.commands = []

    def snapshot(self): return copy.deepcopy(self.records)

    def persistence_state(self, run_id, operation_id):
        return OptimisationPersistenceState(
            copy.deepcopy(self.run) if self.run and self.run["id"] == run_id else None,
            copy.deepcopy(self.operation) if self.operation and self.operation["id"] == operation_id else None,
            copy.deepcopy(self.proposals) if self.run and self.run["id"] == run_id else [],
        )

    def persist(self, command):
        self.commands.append(copy.deepcopy(command))
        run = command["run"]
        self.run = {"id": run["id"], "created_at": run["createdAt"], "objective": run["objective"],
                    "inputs_snapshot_hash": run["inputsSnapshotHash"], "input_snapshot": run["inputSnapshot"],
                    "factor_dataset_version": run["factorDatasetVersion"], "solver_status": run["solverStatus"], "assumptions": run["assumptions"]}
        self.proposals = [{"id": item["id"], "run_id": item["runId"], "supply_offer_id": item["supplyOfferId"],
            "demand_request_id": item["demandRequestId"], "proposed_quantity": item["proposedQuantity"], "unit": item["unit"],
            "compatibility_result": item["compatibilityResult"], "status": item["status"],
            "reason_codes": item["reasonCodes"], "created_at": item["createdAt"]} for item in command["proposals"]]
        self.operation = {"id": command["operationId"], "request_fingerprint": command["requestFingerprint"], "run_id": run["id"]}
        if self.commit_then_error: raise OptimisationPersistenceError("simulated response loss")


class OptimisationRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.records = load()

    def input(self, **changes):
        base = {"objective": "MAX_REUSE", "planning_date": date(2026, 10, 12), "factor_dataset_version": "demo-v1",
                "destination_project_id": "PRJ-001", "idempotency_key": "persist-plan-001", "actor_label": "Demo operator"}
        return OptimisationRunInput(**{**base, **changes})

    def persist(self, repo, value=None):
        return persist_optimisation_run(value or self.input(), repo,
            clock=lambda: datetime(2026, 10, 12, 9, tzinfo=timezone.utc))

    def test_persists_selected_eligible_proposals_without_transfers_or_stock_writes(self):
        repo = FakeOptimisationRepository(self.records)
        response = self.persist(repo)
        self.assertFalse(response["data"]["replayed"])
        self.assertTrue(response["data"]["proposals"])
        self.assertTrue(all(row["status"] == "SELECTED" and row["compatibility_result"] == "ELIGIBLE" for row in response["data"]["proposals"]))
        self.assertEqual(len(repo.commands), 1)
        self.assertEqual(repo.commands[0]["runId"], response["data"]["run"]["id"])
        self.assertNotIn("transfers", repo.commands[0])
        self.assertNotIn("supply_offers", repo.commands[0])

    def test_identical_retry_replays_and_changed_input_conflicts(self):
        repo = FakeOptimisationRepository(self.records)
        self.persist(repo)
        self.assertTrue(self.persist(repo)["data"]["replayed"])
        with self.assertRaises(OptimisationRunConflict):
            self.persist(repo, self.input(objective="EARLIEST_DEADLINE"))

    def test_committed_transaction_response_loss_replays_winner(self):
        repo = FakeOptimisationRepository(self.records, commit_then_error=True)
        self.assertTrue(self.persist(repo)["data"]["replayed"])

    def test_route_contract(self):
        successful = {"data": {"run": {"id": "RUN-test", "created_at": "2026-10-12T17:00:00+08:00", "objective": "MAX_REUSE", "inputs_snapshot_hash": "hash", "input_snapshot": {}, "factor_dataset_version": "demo-v1", "solver_status": "SUCCEEDED", "assumptions": {}}, "proposals": [], "idempotency_key": "route-key", "replayed": False}, "meta": {"dataset_version": "test", "synthetic": True, "as_of_date": "2026-10-12"}, "error": None}
        body = {"objective": "MAX_REUSE", "planning_date": "2026-10-12", "factor_dataset_version": "demo-v1", "idempotency_key": "route-key", "actor_label": "Demo operator"}
        with patch("backend.app.routes.impact.persist_optimisation_run", return_value=successful):
            status, _, payload = asyncio.run(api_request("POST", "/api/optimisation-runs", body=body))
        self.assertEqual((status, json.loads(payload)), (201, successful))


if __name__ == "__main__": unittest.main()
