"""Approve a persisted matching proposal and create its transfer request.

The approval creates a REQUESTED transfer ready for reservation. It deliberately
creates no stock reservation, dispatch, receipt, demand commitment, or reuse.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backend.app.repositories.transfer_repository import (
    TransferRepository, TransferRepositoryError, TransferRepositoryUnavailable,
    TransferRequestMutationError, TransferRequestState,
)
from backend.app.services.transfer_read_service import load_baseline_metadata


@dataclass(frozen=True)
class TransferRequestInput:
    actor_label: str
    idempotency_key: str
    evidence_ref: str | None = None
    notes: str | None = None


class TransferRequestError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class TransferRequestNotFound(TransferRequestError): pass
class TransferRequestInvalid(TransferRequestError): pass
class TransferRequestConflict(TransferRequestError): pass
class TransferRequestUnavailable(TransferRequestError): pass


def _identity(key: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"REQ-{digest}", f"TRF-REQ-{digest[:32]}", f"EVT-REQ-{digest[:32]}"


def _fingerprint(proposal_id: str, request: TransferRequestInput) -> str:
    payload = {"proposal_id": proposal_id, "actor_label": request.actor_label,
               "evidence_ref": request.evidence_ref, "notes": request.notes}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _load(repository: TransferRepository, proposal_id: str, operation_id: str,
          transfer_id: str, event_id: str) -> TransferRequestState:
    try:
        return repository.get_request_state(proposal_id, operation_id, transfer_id, event_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferRequestUnavailable("TRANSFER_DATA_UNAVAILABLE",
                                         "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferRequestError("TRANSFER_REQUEST_DATA_ERROR",
                                   "Transfer request data could not be read.") from exc


def _replay(state: TransferRequestState, fingerprint: str, key: str) -> bool:
    if state.operation is None:
        return False
    if state.operation["request_fingerprint"] != fingerprint:
        raise TransferRequestConflict("IDEMPOTENCY_KEY_REUSED",
                                     "The idempotency_key was already used with different request input.",
                                     {"idempotency_key": key})
    if state.transfer is None or state.event is None:
        raise TransferRequestError("TRANSFER_REQUEST_DATA_ERROR",
                                   "The stored transfer-request operation is incomplete.")
    return True


def _validate(state: TransferRequestState, proposal_id: str, request: TransferRequestInput) -> None:
    if state.proposal is None:
        raise TransferRequestNotFound("PROPOSAL_NOT_FOUND", "The allocation proposal was not found.",
                                      {"proposal_id": proposal_id})
    if state.transfers_for_proposal:
        raise TransferRequestConflict("TRANSFER_REQUEST_ALREADY_EXISTS",
                                     "This allocation proposal already has a transfer request.",
                                     {"proposal_id": proposal_id,
                                      "transfer_id": state.transfers_for_proposal[0]["id"]})
    if state.proposal["status"] not in ('PROPOSED', 'SELECTED') or state.proposal["compatibility_result"] != "ELIGIBLE":
        raise TransferRequestConflict("PROPOSAL_NOT_REQUESTABLE",
                                     "Only a PROPOSED or SELECTED eligible proposal can be selected for a transfer request.",
                                     {"proposal_id": proposal_id})
    if not request.actor_label.strip() or len(request.actor_label) > 200:
        raise TransferRequestInvalid("ACTOR_LABEL_REQUIRED",
                                    "actor_label must contain 1 to 200 characters.")
    if request.evidence_ref is not None and len(request.evidence_ref) > 500:
        raise TransferRequestInvalid("EVIDENCE_REF_INVALID", "evidence_ref cannot exceed 500 characters.")
    if request.notes is not None and len(request.notes) > 1000:
        raise TransferRequestInvalid("NOTES_INVALID", "notes cannot exceed 1,000 characters.")


def _response(state: TransferRequestState, key: str, replayed: bool) -> dict[str, Any]:
    return {"data": {"transfer": state.transfer, "event": state.event,
                     "idempotency_key": key, "replayed": replayed},
            "meta": load_baseline_metadata(), "error": None}


def create_transfer_request(proposal_id: str, request: TransferRequestInput,
                            repository: TransferRepository | None = None,
                            clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Atomically approve one proposal and create its REQUESTED transfer/event."""
    if not request.idempotency_key.strip() or len(request.idempotency_key) > 128:
        raise TransferRequestInvalid("IDEMPOTENCY_KEY_INVALID",
                                    "idempotency_key must contain 1 to 128 non-whitespace characters.")
    repository = repository or TransferRepository()
    operation_id, transfer_id, event_id = _identity(request.idempotency_key)
    fingerprint = _fingerprint(proposal_id, request)
    state = _load(repository, proposal_id, operation_id, transfer_id, event_id)
    if _replay(state, fingerprint, request.idempotency_key):
        return _response(state, request.idempotency_key, True)
    _validate(state, proposal_id, request)
    if getattr(repository,'_adapter',None) is not None and state.proposal.get('run_id'):
        from backend.app.services.matching_service import MatchingService
        run=repository._adapter.execute('GetOptimisationRun',{'runId':state.proposal['run_id']})['optimisationRun']
        if run and run['assumptions'].get('matching_generation'):
            raise TransferRequestConflict('COMBINED_CONFIRMATION_REQUIRED','Use current proposal confirmation to approve and reserve together.')
        MatchingService(repository._adapter,clock).require_current(state.proposal)
    now = (clock or (lambda: datetime.now(timezone(timedelta(hours=8)))))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise TransferRequestError("TRANSFER_REQUEST_TIME_INVALID",
                                   "The request clock must return a timezone-aware timestamp.")
    command = {"proposal_id": proposal_id, "operation_id": operation_id,
               "request_fingerprint": fingerprint, "transfer_id": transfer_id, "event_id": event_id,
               "actor_label": request.actor_label, "evidence_ref": request.evidence_ref,
               "notes": request.notes, "approved_quantity": state.proposal["proposed_quantity"],
               "occurred_at": now.isoformat(timespec="seconds"),
               "event_payload": {"quantity": state.proposal["proposed_quantity"], "synthetic": True,
                                 "proposal_id": proposal_id, "reservation_created": False}}
    try:
        repository.create_request(command)
    except TransferRepositoryUnavailable as exc:
        raise TransferRequestUnavailable("TRANSFER_DATA_UNAVAILABLE",
                                         "The local SQL Connect emulator is unavailable.") from exc
    except TransferRequestMutationError as exc:
        latest = _load(repository, proposal_id, operation_id, transfer_id, event_id)
        if _replay(latest, fingerprint, request.idempotency_key):
            return _response(latest, request.idempotency_key, True)
        _validate(latest, proposal_id, request)
        raise TransferRequestError("TRANSFER_REQUEST_DATA_ERROR",
                                   "The transfer request transaction failed.") from exc
    persisted = _load(repository, proposal_id, operation_id, transfer_id, event_id)
    if not _replay(persisted, fingerprint, request.idempotency_key):
        raise TransferRequestError("TRANSFER_REQUEST_DATA_ERROR",
                                   "The transfer request transaction could not be verified.")
    return _response(persisted, request.idempotency_key, False)
