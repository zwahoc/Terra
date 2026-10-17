"""Persist calculated matching plans without creating transfers or reservations."""
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from copy import deepcopy
from decimal import Decimal
import math

from backend.app.repositories.optimisation_repository import (
    OptimisationPersistenceError, OptimisationPersistenceState, OptimisationRepository,
    OptimisationRepositoryError, OptimisationRepositoryUnavailable,
)
from backend.app.services.optimisation_preview_service import preview_optimisation
from backend.app.services.impact_service import _hash
from terra.contract import camel
from terra.validation import sha
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
    return {"data": {"run": state.run, "proposals": state.proposals, 'assessments': state.assessments,
                     "idempotency_key": key, "replayed": replayed},
            "meta": load_baseline_metadata(), "error": None}


def _replay(state, fingerprint, key):
    if state.operation is None: return False
    if state.operation["request_fingerprint"] != fingerprint:
        raise OptimisationRunConflict("IDEMPOTENCY_KEY_REUSED", "The idempotency_key was already used with different optimisation input.", {"idempotency_key": key})
    if state.run is None:
        raise OptimisationRunError("OPTIMISATION_DATA_ERROR", "The stored optimisation operation is incomplete.")
    return True


def build_run_command(request, result, records, *, occurred, proposal_status='SELECTED'):
    """Build dictionary-shaped run, proposals, immutable forecasts and heads.

    Initial forecasts retain the preview's declared planning date/context. Later
    live recalculation remains Member 4's existing, separate revision behaviour.
    """
    operation_id, run_id, digest = _identity(request.idempotency_key)
    snapshot = {'as_of': request.planning_date.isoformat(),
                'factor_dataset_version': request.factor_dataset_version,
                'destination_project_id': request.destination_project_id}
    # Preserve all planning inputs/commitment provenance, not recursively nested
    # historical run snapshots or unrelated assessment history.
    for name in ('projects', 'materials', 'documents', 'extracted_rows', 'supply_offers',
                 'demand_requests', 'route_distances', 'emission_factors', 'transfers',
                 'allocation_proposals'):
        snapshot[name] = sorted(deepcopy(records[name]), key=lambda r: r['id'])
    proposals, assessments, heads = [], [], []
    forecasts = {(f['supply_offer_id'], f['demand_request_id']): f for f in result['forecast_previews']}
    for index, allocation in enumerate(result['plan']['allocations'], 1):
        pid = f'ALC-{digest[:24]}-{index:03}'
        proposals.append({'id': pid, 'runId': run_id,
            'supplyOfferId': allocation['supply_offer_id'], 'demandRequestId': allocation['demand_request_id'],
            'proposedQuantity': allocation['proposed_quantity'], 'unit': allocation['unit'],
            'compatibilityResult': 'ELIGIBLE', 'status': proposal_status,
            'reasonCodes': allocation['reason_codes'], 'createdAt': occurred})
        forecast = forecasts[allocation['supply_offer_id'], allocation['demand_request_id']]
        aid = f'IMP-{digest[:24]}-{index:03}'
        fingerprint = _hash(forecast)
        assumptions = {**forecast['assumptions'], 'missing_data': forecast['missing_data'],
            'factor_snapshots': forecast['factor_snapshots'],
            'forecast_activity_date': request.planning_date.isoformat(),
            'carbon_context_id': result['carbon_context_id'],
            'revision': {'number': 1, 'previous_assessment_id': None,
                         'reason': 'Initial optimisation forecast', 'actor_label': request.actor_label,
                         'input_fingerprint': fingerprint}}
        assessment = {'id': aid, 'basis': 'PROPOSAL_FORECAST', 'proposal_id': pid,
            'transfer_id': None, 'quantity_assessed': allocation['proposed_quantity'], 'unit': allocation['unit'],
            'baseline_description': forecast['baseline_description'], 'factor_ids': forecast['factor_ids'],
            'assumptions': assumptions, 'calculation_status': forecast['calculation_status'], 'calculated_at': occurred}
        for field in ('avoided_production_kgco2e', 'additional_transport_kgco2e',
                      'additional_processing_kgco2e', 'net_avoided_kgco2e'):
            value = forecast[field]
            numeric = None if value is None else float(Decimal(value))
            if numeric is not None and not math.isfinite(numeric):
                raise OptimisationRunInvalid('CARBON_VALUE_INVALID', 'Forecast exceeds supported stored numeric range.')
            assessment[field] = numeric
        assessments.append({camel(k): v for k, v in assessment.items()})
        heads.append({'id': f'PROPOSAL_FORECAST:{pid}', 'basis': 'PROPOSAL_FORECAST',
            'proposalId': pid, 'transferId': None, 'currentAssessmentId': aid, 'revision': 1,
            'inputFingerprint': fingerprint, 'updatedAt': occurred})
    return {'operationId': operation_id, 'runId': run_id, 'requestFingerprint': _fingerprint(request),
        'run': {'id': run_id, 'createdAt': occurred, 'objective': request.objective,
            'inputsSnapshotHash': sha(snapshot), 'inputSnapshot': snapshot,
            'factorDatasetVersion': request.factor_dataset_version, 'solverStatus': result['plan']['solver_status'],
            'assumptions': {**result['plan']['assumptions'],
                'allocation_snapshot_hash': result['allocation_snapshot_hash'],
                'carbon_context_id': result['carbon_context_id'],
                'forecast_summary': result['forecast_summary'],
                'reservation_timing_policy': 'reserve_and_dispatch_on_or_after_needed_from',
                'saved_forecasts_activity_date': request.planning_date.isoformat(),
                'later_live_recalculation_context_alignment': 'DEFERRED'}},
        'proposals': proposals, 'assessments': assessments, 'heads': heads}


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
    command = build_run_command(request, result, records, occurred=occurred)
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
    return {"data": {"run": state.run, "proposals": state.proposals, 'assessments': state.assessments}, "meta": load_baseline_metadata(), "error": None}
