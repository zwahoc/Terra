"""Persist calculated matching plans without creating transfers or reservations."""
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from backend.app.repositories.optimisation_repository import (
    OptimisationPersistenceError, OptimisationPersistenceState, OptimisationRepository,
    OptimisationRepositoryError, OptimisationRepositoryUnavailable,
)
from backend.app.services.optimisation_preview_service import preview_optimisation
from backend.app.services.transfer_read_service import load_baseline_metadata


@dataclass(frozen=True)
class OptimisationRunInput:
    objective: str
    planning_date: date
    factor_dataset_version: str
    destination_project_id: str | None
    idempotency_key: str
    actor_label: str


class OptimisationRunError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message); self.code, self.message, self.details = code, message, details or {}
class OptimisationRunConflict(OptimisationRunError): pass
class OptimisationRunInvalid(OptimisationRunError): pass
class OptimisationRunNotFound(OptimisationRunError): pass
class OptimisationRunUnavailable(OptimisationRunError): pass


def _identity(key: str):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"OPR-{digest}", f"RUN-{digest[:32]}", digest


def _fingerprint(request: OptimisationRunInput):
    value = {"objective": request.objective, "planning_date": request.planning_date.isoformat(),
             "factor_dataset_version": request.factor_dataset_version,
             "destination_project_id": request.destination_project_id, "actor_label": request.actor_label}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(repo, run_id, operation_id):
    try: return repo.persistence_state(run_id, operation_id)
    except OptimisationRepositoryUnavailable as exc: raise OptimisationRunUnavailable("OPTIMISATION_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except OptimisationRepositoryError as exc: raise OptimisationRunError("OPTIMISATION_DATA_ERROR", "Optimisation data could not be read.") from exc


def _response(state, key, replayed):
    return {"data": {"run": state.run, "proposals": state.proposals,
                     "idempotency_key": key, "replayed": replayed},
            "meta": load_baseline_metadata(), "error": None}


def _replay(state, fingerprint, key):
    if state.operation is None: return False
    if state.operation["request_fingerprint"] != fingerprint:
        raise OptimisationRunConflict("IDEMPOTENCY_KEY_REUSED", "The idempotency_key was already used with different optimisation input.", {"idempotency_key": key})
    if state.run is None:
        raise OptimisationRunError("OPTIMISATION_DATA_ERROR", "The stored optimisation operation is incomplete.")
    return True


def persist_optimisation_run(request: OptimisationRunInput, repository: OptimisationRepository | None = None,
                             clock: Callable[[], datetime] | None = None):
    if not request.idempotency_key.strip() or len(request.idempotency_key) > 128:
        raise OptimisationRunInvalid("IDEMPOTENCY_KEY_INVALID", "idempotency_key must contain 1 to 128 non-whitespace characters.")
    if not request.actor_label.strip() or len(request.actor_label) > 200:
        raise OptimisationRunInvalid("ACTOR_LABEL_REQUIRED", "actor_label must contain 1 to 200 characters.")
    repo = repository or OptimisationRepository()
    operation_id, run_id, digest = _identity(request.idempotency_key)
    fingerprint = _fingerprint(request)
    state = _load(repo, run_id, operation_id)
    if _replay(state, fingerprint, request.idempotency_key): return _response(state, request.idempotency_key, True)
    try:
        records = repo.snapshot()
        result = preview_optimisation(records, objective=request.objective, planning_date=request.planning_date,
                                      factor_dataset_version=request.factor_dataset_version,
                                      destination_project_id=request.destination_project_id)
    except OptimisationRepositoryUnavailable as exc:
        raise OptimisationRunUnavailable("OPTIMISATION_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except OptimisationRepositoryError as exc:
        raise OptimisationRunError("OPTIMISATION_DATA_ERROR", "Optimisation inputs could not be read.") from exc
    except Exception as exc:
        # Preview validation raises its established domain errors; preserve a safe API boundary.
        raise OptimisationRunInvalid("OPTIMISATION_INPUT_INVALID", str(exc)) from exc
    now = (clock or (lambda: datetime.now(timezone(timedelta(hours=8)))))()
    if now.tzinfo is None or now.utcoffset() is None: raise OptimisationRunError("OPTIMISATION_TIME_INVALID", "The run clock must return a timezone-aware timestamp.")
    occurred = now.isoformat(timespec="seconds")
    proposals = []
    for index, allocation in enumerate(result["plan"]["allocations"], 1):
        proposals.append({"id": f"ALC-{digest[:24]}-{index:03}", "runId": run_id,
            "supplyOfferId": allocation["supply_offer_id"], "demandRequestId": allocation["demand_request_id"],
            "proposedQuantity": allocation["proposed_quantity"], "unit": allocation["unit"],
            "compatibilityResult": "ELIGIBLE", "status": "SELECTED",
            "reasonCodes": allocation["reason_codes"], "createdAt": occurred})
    command = {"operationId": operation_id, "runId": run_id, "requestFingerprint": fingerprint,
        "run": {"id": run_id, "createdAt": occurred, "objective": request.objective,
            "inputsSnapshotHash": result["allocation_snapshot_hash"],
            "inputSnapshot": {"planning_date": request.planning_date.isoformat(),
                              "destination_project_id": request.destination_project_id,
                              "allocation_snapshot_hash": result["allocation_snapshot_hash"],
                              "actor_label": request.actor_label},
            "factorDatasetVersion": result["factor_dataset_version"], "solverStatus": result["plan"]["solver_status"],
            "assumptions": {**result["plan"]["assumptions"], "persisted_from_preview": False}},
        "proposals": proposals}
    try: repo.persist(command)
    except OptimisationRepositoryUnavailable as exc: raise OptimisationRunUnavailable("OPTIMISATION_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except OptimisationPersistenceError as exc:
        latest = _load(repo, run_id, operation_id)
        if _replay(latest, fingerprint, request.idempotency_key): return _response(latest, request.idempotency_key, True)
        raise OptimisationRunError("OPTIMISATION_PERSISTENCE_FAILED", "The optimisation-run transaction failed.") from exc
    persisted = _load(repo, run_id, operation_id)
    if not _replay(persisted, fingerprint, request.idempotency_key):
        raise OptimisationRunError("OPTIMISATION_PERSISTENCE_FAILED", "The optimisation-run transaction could not be verified.")
    return _response(persisted, request.idempotency_key, False)


def get_optimisation_run(run_id: str, repository: OptimisationRepository | None = None):
    try: state = (repository or OptimisationRepository()).get(run_id)
    except OptimisationRepositoryUnavailable as exc: raise OptimisationRunUnavailable("OPTIMISATION_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable.") from exc
    except OptimisationRepositoryError as exc: raise OptimisationRunError("OPTIMISATION_DATA_ERROR", "Optimisation data could not be read.") from exc
    if state.run is None: raise OptimisationRunNotFound("OPTIMISATION_RUN_NOT_FOUND", "The optimisation run was not found.", {"run_id": run_id})
    return {"data": {"run": state.run, "proposals": state.proposals}, "meta": load_baseline_metadata(), "error": None}
