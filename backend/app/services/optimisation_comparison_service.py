"""Two alternative objectives on one prepared snapshot, with atomic saving."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from backend.app.services.optimisation_run_service import (
    OptimisationRunInput, OptimisationRunInvalid, OptimisationRunError,
    OptimisationRunUnavailable, _identity, _load, _replay, _response, build_run_command,
    _fingerprint,
)
from backend.app.services.impact_service import ImpactError
from backend.app.services.optimisation_preview_service import preview_comparison
from backend.app.repositories.optimisation_repository import (
    OptimisationRepository, OptimisationRepositoryUnavailable,
    OptimisationRepositoryError, OptimisationPersistenceError,
)
from backend.app.services.transfer_read_service import load_baseline_metadata


@dataclass(frozen=True)
class OptimisationComparisonInput:
    planning_date: date
    factor_dataset_version: str
    destination_project_id: str | None
    idempotency_key: str
    actor_label: str


def persist_optimisation_comparison(request, repository=None, clock=None):
    if not request.idempotency_key.strip() or len(request.idempotency_key) > 128:
        raise OptimisationRunInvalid('IDEMPOTENCY_KEY_INVALID', 'A key of 1 to 128 characters is required.')
    if not request.actor_label.strip() or len(request.actor_label) > 200:
        raise OptimisationRunInvalid('ACTOR_LABEL_REQUIRED', 'An actor label of 1 to 200 characters is required.')
    repo = repository or OptimisationRepository()
    inputs = [OptimisationRunInput(objective, request.planning_date, request.factor_dataset_version,
        request.destination_project_id, f'comparison:{request.idempotency_key}:{objective}', request.actor_label)
        for objective in ('MAX_REUSE', 'MAX_NET_CO2E_AVOIDED')]

    def saved(replayed):
        alternatives = []
        for item in inputs:
            operation_id, run_id, _ = _identity(item.idempotency_key)
            state = _load(repo, run_id, operation_id)
            # The composite transaction guarantees both children or neither.
            if not _replay(state, _fingerprint(item), request.idempotency_key):
                return None
            alternatives.append(_response(state, request.idempotency_key, replayed)['data'])
        return {'data': {'alternatives': alternatives, 'idempotency_key': request.idempotency_key,
                         'replayed': replayed}, 'meta': load_baseline_metadata(), 'error': None}

    replay = saved(True)
    if replay is not None:
        return replay
    try:
        records = repo.snapshot()
        comparison = preview_comparison(records, planning_date=request.planning_date,
            factor_dataset_version=request.factor_dataset_version,
            destination_project_id=request.destination_project_id)
    except OptimisationRepositoryUnavailable as exc:
        raise OptimisationRunUnavailable('OPTIMISATION_DATA_UNAVAILABLE', 'The local emulator is unavailable.') from exc
    except OptimisationRepositoryError as exc:
        raise OptimisationRunError('OPTIMISATION_DATA_ERROR', 'Comparison inputs could not be read.') from exc
    except (ValueError, ImpactError) as exc:
        raise OptimisationRunInvalid('OPTIMISATION_INPUT_INVALID', str(exc)) from exc
    now = (clock or (lambda: datetime.now(timezone(timedelta(hours=8)))))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise OptimisationRunError('OPTIMISATION_TIME_INVALID', 'The comparison clock must be timezone-aware.')
    commands = [build_run_command(item, alternative, records, occurred=now.isoformat(timespec='seconds'),
                                 proposal_status='PROPOSED')
                for item, alternative in zip(inputs, comparison['alternatives'])]
    command = {'runs': [c['run'] for c in commands],
               'operations': [{'id': c['operationId'], 'requestFingerprint': c['requestFingerprint'],
                               'runId': c['runId']} for c in commands]}
    for field in ('proposals', 'assessments', 'heads'):
        command[field] = [row for c in commands for row in c[field]]
    try:
        repo.persist_comparison(command)
    except OptimisationRepositoryUnavailable as exc:
        raise OptimisationRunUnavailable('OPTIMISATION_DATA_UNAVAILABLE', 'The local emulator is unavailable.') from exc
    except OptimisationPersistenceError as exc:
        replay = saved(True)
        if replay is not None:
            return replay
        raise OptimisationRunError('OPTIMISATION_PERSISTENCE_FAILED', 'The atomic comparison transaction failed.') from exc
    response = saved(False)
    if response is None:
        raise OptimisationRunError('OPTIMISATION_PERSISTENCE_FAILED', 'Comparison read-back failed.')
    return response
