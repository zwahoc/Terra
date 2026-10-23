"""Framework-independent orchestration for approving requested transfers.

Approval records both simulated confirmations and an approved quantity. It does
not reserve supply, increment demand commitments, dispatch, receive, or record use.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from terra.quantities import json_default

from backend.app.repositories.transfer_repository import (
    TransferApprovalMutationError,
    TransferApprovalState,
    TransferRepository,
    TransferRepositoryError,
    TransferRepositoryUnavailable,
)
from backend.app.services.transfer_read_service import load_baseline_metadata


@dataclass(frozen=True)
class TransferApprovalInput:
    approved_quantity: int
    source_confirmation_status: str
    destination_confirmation_status: str
    actor_label: str
    idempotency_key: str
    evidence_ref: str | None = None


class TransferApprovalError(Exception):
    """A safe domain/service failure suitable for Terra's API envelope."""

    def __init__(
        self, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class TransferApprovalNotFound(TransferApprovalError):
    pass


class TransferApprovalInvalid(TransferApprovalError):
    pass


class TransferApprovalConflict(TransferApprovalError):
    pass


class TransferApprovalUnavailable(TransferApprovalError):
    pass


def _repository() -> TransferRepository:
    try:
        return TransferRepository()
    except TransferRepositoryError as exc:
        raise TransferApprovalError(
            "TRANSFER_APPROVAL_DATA_ERROR", "Transfer approval data could not be read."
        ) from exc


def _identity(idempotency_key: str) -> tuple[str, str]:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"APR-{digest}", f"EVT-APR-{digest[:32]}"


def _fingerprint(transfer_id: str, request: TransferApprovalInput) -> str:
    semantic_input = {
        "transfer_id": transfer_id,
        "approved_quantity": request.approved_quantity,
        "source_confirmation_status": request.source_confirmation_status,
        "destination_confirmation_status": request.destination_confirmation_status,
        "actor_label": request.actor_label,
        "evidence_ref": request.evidence_ref,
    }
    canonical = json.dumps(
        semantic_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=json_default
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_state(
    repository: TransferRepository,
    transfer_id: str,
    operation_id: str,
    event_id: str,
) -> TransferApprovalState:
    try:
        return repository.get_approval_state(transfer_id, operation_id, event_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferApprovalUnavailable(
            "TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.",
        ) from exc
    except TransferRepositoryError as exc:
        raise TransferApprovalError(
            "TRANSFER_APPROVAL_DATA_ERROR", "Transfer approval data could not be read."
        ) from exc


def _validate_new(
    transfer_id: str,
    request: TransferApprovalInput,
    state: TransferApprovalState,
) -> None:
    if state.transfer is None:
        raise TransferApprovalNotFound(
            "TRANSFER_NOT_FOUND",
            "The requested transfer was not found.",
            {"transfer_id": transfer_id},
        )
    if state.proposal is None:
        raise TransferApprovalError(
            "TRANSFER_PROPOSAL_INVALID",
            "The transfer's allocation proposal could not be loaded.",
        )
    if state.transfer["status"] != "REQUESTED":
        raise TransferApprovalConflict(
            "TRANSFER_INVALID_STAGE",
            "Only a REQUESTED transfer can be approved.",
            {"current_status": state.transfer["status"]},
        )
    if (
        state.proposal["status"] != "SELECTED"
        or state.proposal["compatibility_result"] != "ELIGIBLE"
    ):
        raise TransferApprovalConflict(
            "PROPOSAL_NOT_APPROVABLE",
            "The linked proposal must be SELECTED and ELIGIBLE.",
            {"proposal_id": state.proposal["id"]},
        )
    if type(request.approved_quantity) is not int or request.approved_quantity <= 0:
        raise TransferApprovalInvalid(
            "APPROVED_QUANTITY_INVALID",
            "approved_quantity must be a positive integer.",
        )
    if request.approved_quantity > state.proposal["proposed_quantity"]:
        raise TransferApprovalInvalid(
            "APPROVED_QUANTITY_EXCEEDS_PROPOSAL",
            "approved_quantity cannot exceed the proposal quantity.",
            {"proposed_quantity": state.proposal["proposed_quantity"]},
        )
    if (
        request.source_confirmation_status != "CONFIRMED"
        or request.destination_confirmation_status != "CONFIRMED"
    ):
        raise TransferApprovalInvalid(
            "TRANSFER_CONFIRMATIONS_REQUIRED",
            "Both source and destination confirmation statuses must be CONFIRMED.",
        )
    if not request.actor_label.strip():
        raise TransferApprovalInvalid(
            "ACTOR_LABEL_REQUIRED", "actor_label must not be empty."
        )


def _replay_or_conflict(
    state: TransferApprovalState,
    fingerprint: str,
    idempotency_key: str,
) -> bool:
    if state.operation is None:
        return False
    if state.operation["request_fingerprint"] != fingerprint:
        raise TransferApprovalConflict(
            "IDEMPOTENCY_KEY_REUSED",
            "The idempotency_key was already used with different approval input.",
            {"idempotency_key": idempotency_key},
        )
    if state.transfer is None or state.event is None:
        raise TransferApprovalError(
            "TRANSFER_APPROVAL_DATA_ERROR",
            "The stored approval operation is incomplete.",
        )
    return True


def _response(
    state: TransferApprovalState, idempotency_key: str, replayed: bool
) -> dict[str, Any]:
    return {
        "data": {
            "transfer": state.transfer,
            "event": state.event,
            "idempotency_key": idempotency_key,
            "replayed": replayed,
        },
        "meta": load_baseline_metadata(),
        "error": None,
    }


def approve_transfer(
    transfer_id: str,
    request: TransferApprovalInput,
    repository: TransferRepository | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Approve one emulator transfer with atomic and replay-safe persistence."""

    if not request.idempotency_key.strip() or len(request.idempotency_key) > 128:
        raise TransferApprovalInvalid(
            "IDEMPOTENCY_KEY_INVALID",
            "idempotency_key must contain 1 to 128 non-whitespace characters.",
        )
    if not request.actor_label.strip() or len(request.actor_label) > 200:
        raise TransferApprovalInvalid(
            "ACTOR_LABEL_REQUIRED", "actor_label must contain 1 to 200 characters."
        )
    if request.evidence_ref is not None and len(request.evidence_ref) > 500:
        raise TransferApprovalInvalid(
            "EVIDENCE_REF_INVALID", "evidence_ref cannot exceed 500 characters."
        )
    repository = repository or _repository()
    operation_id, event_id = _identity(request.idempotency_key)
    fingerprint = _fingerprint(transfer_id, request)
    state = _load_state(repository, transfer_id, operation_id, event_id)
    if _replay_or_conflict(state, fingerprint, request.idempotency_key):
        return _response(state, request.idempotency_key, replayed=True)

    _validate_new(transfer_id, request, state)
    malaysia_time = timezone(timedelta(hours=8))
    now = (clock or (lambda: datetime.now(malaysia_time)))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise TransferApprovalError(
            "TRANSFER_APPROVAL_TIME_INVALID",
            "The approval clock must return a timezone-aware timestamp.",
        )
    command = {
        "transfer_id": transfer_id,
        "operation_id": operation_id,
        "request_fingerprint": fingerprint,
        "event_id": event_id,
        "approved_quantity": request.approved_quantity,
        "source_confirmation_status": request.source_confirmation_status,
        "destination_confirmation_status": request.destination_confirmation_status,
        "actor_label": request.actor_label,
        "evidence_ref": request.evidence_ref,
        "event_payload": {
            "quantity": request.approved_quantity,
            "synthetic": True,
            "source_confirmation_status": request.source_confirmation_status,
            "destination_confirmation_status": request.destination_confirmation_status,
        },
        "occurred_at": now.isoformat(timespec="seconds"),
    }
    try:
        repository.approve(command)
    except TransferRepositoryUnavailable as exc:
        raise TransferApprovalUnavailable(
            "TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.",
        ) from exc
    except TransferApprovalMutationError as exc:
        # A concurrent identical request may win after our initial read. Re-read
        # before classifying the provider rejection; the unique operation key is
        # the database-level concurrency guard.
        latest = _load_state(repository, transfer_id, operation_id, event_id)
        if _replay_or_conflict(latest, fingerprint, request.idempotency_key):
            return _response(latest, request.idempotency_key, replayed=True)
        try:
            _validate_new(transfer_id, request, latest)
        except TransferApprovalError:
            raise
        raise TransferApprovalError(
            "TRANSFER_APPROVAL_DATA_ERROR",
            "The transfer approval transaction failed.",
        ) from exc

    persisted = _load_state(repository, transfer_id, operation_id, event_id)
    if not _replay_or_conflict(persisted, fingerprint, request.idempotency_key):
        raise TransferApprovalError(
            "TRANSFER_APPROVAL_DATA_ERROR",
            "The transfer approval transaction could not be verified.",
        )
    return _response(persisted, request.idempotency_key, replayed=False)
