"""Named SQL Connect operations for persisted optimisation runs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terra.local_adapter import AdapterError, AdapterUnavailableError, LocalDataConnect


class OptimisationRepositoryError(RuntimeError): pass
class OptimisationRepositoryUnavailable(OptimisationRepositoryError): pass
class OptimisationPersistenceError(OptimisationRepositoryError): pass


@dataclass(frozen=True)
class OptimisationPersistenceState:
    run: dict[str, Any] | None
    operation: dict[str, Any] | None
    proposals: list[dict[str, Any]]


def _run(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "created_at": row["createdAt"], "objective": row["objective"],
            "inputs_snapshot_hash": row["inputsSnapshotHash"], "input_snapshot": row["inputSnapshot"],
            "factor_dataset_version": row["factorDatasetVersion"], "solver_status": row["solverStatus"],
            "assumptions": row["assumptions"]}


def _proposal(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "run_id": row["runId"], "supply_offer_id": row["supplyOfferId"],
            "demand_request_id": row["demandRequestId"], "proposed_quantity": row["proposedQuantity"],
            "unit": row["unit"], "compatibility_result": row["compatibilityResult"],
            "status": row["status"], "reason_codes": row["reasonCodes"], "created_at": row["createdAt"]}


class OptimisationRepository:
    def __init__(self, adapter: LocalDataConnect | None = None):
        try: self._adapter = adapter or LocalDataConnect()
        except ValueError as exc: raise OptimisationRepositoryError("The local adapter configuration is invalid.") from exc

    def snapshot(self):
        try: return self._adapter.snapshot()
        except AdapterUnavailableError as exc: raise OptimisationRepositoryUnavailable("The local emulator is unavailable.") from exc
        except AdapterError as exc: raise OptimisationRepositoryError("Optimisation inputs could not be read.") from exc

    def persistence_state(self, run_id: str, operation_id: str) -> OptimisationPersistenceState:
        try:
            result = self._adapter.execute("GetOptimisationRunPersistenceState", {"runId": run_id, "operationId": operation_id})
            operation = result["optimisationRunOperation"]
            return OptimisationPersistenceState(
                _run(result["optimisationRun"]) if result["optimisationRun"] else None,
                None if operation is None else {"id": operation["id"], "request_fingerprint": operation["requestFingerprint"], "run_id": operation["runId"]},
                [_proposal(row) for row in result["allocationProposals"]],
            )
        except AdapterUnavailableError as exc: raise OptimisationRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc: raise OptimisationRepositoryError("Optimisation persistence state is invalid.") from exc

    def persist(self, command: dict[str, Any]) -> None:
        try: self._adapter.execute("PersistOptimisationRun", command, write=True)
        except AdapterUnavailableError as exc: raise OptimisationRepositoryUnavailable("The local emulator is unavailable.") from exc
        except AdapterError as exc: raise OptimisationPersistenceError("The optimisation-run transaction was rejected.") from exc

    def get(self, run_id: str) -> OptimisationPersistenceState:
        try:
            result = self._adapter.execute("GetOptimisationRun", {"runId": run_id})
            return OptimisationPersistenceState(_run(result["optimisationRun"]) if result["optimisationRun"] else None, None, [_proposal(row) for row in result["allocationProposals"]])
        except AdapterUnavailableError as exc: raise OptimisationRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc: raise OptimisationRepositoryError("Optimisation run response is invalid.") from exc
