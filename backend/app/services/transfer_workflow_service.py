"""Framework-independent transfer workflow after a proposal is approved.

Reservation, dispatch, and receipt are full-quantity, one-time transitions.
Confirmed use retains its positive partial/repeated quantity contract. Partial use
residuals remain committed; this milestone never invents a return, release, or
disposition after dispatch.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from decimal import Decimal
from terra.quantities import amount, ordinary, json_default

from backend.app.repositories.transfer_repository import (
    TransferRepository,
    TransferRepositoryError,
    TransferRepositoryUnavailable,
    TransferWorkflowMutationError,
    TransferWorkflowState,
)
from backend.app.services.transfer_read_service import load_baseline_metadata


@dataclass(frozen=True)
class WorkflowInput:
    actor_label: str
    idempotency_key: str
    quantity: int | Decimal | str | None = None
    reason: str | None = None
    evidence_ref: str | None = None


class TransferWorkflowError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class TransferWorkflowInvalid(TransferWorkflowError): pass
class TransferWorkflowNotFound(TransferWorkflowError): pass
class TransferWorkflowConflict(TransferWorkflowError): pass
class TransferWorkflowUnavailable(TransferWorkflowError): pass


_CONFIG = {
    "reserve": (("REQUESTED", "APPROVED"), "ReserveTransfer", "RESERVED"),
    "dispatch": ("RESERVED", "DispatchTransfer", "DISPATCHED"),
    "receive": ("IN_TRANSIT", "ReceiveTransfer", "RECEIVED"),
    "confirm_use": (("RECEIVED", "REUSED"), "ConfirmTransferUse", "USED"),
    "cancel": (("REQUESTED", "APPROVED", "RESERVED"), "CancelTransfer", "CANCELLED"),
}


def _identity(key: str) -> tuple[str, str]:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"WFO-{digest}", f"EVT-WFO-{digest[:32]}"


def _fingerprint(action: str, transfer_id: str, request: WorkflowInput) -> str:
    value = {
        "action": action,
        "transfer_id": transfer_id,
        "quantity": request.quantity,
        "reason": request.reason,
        "actor_label": request.actor_label,
        "evidence_ref": request.evidence_ref,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"),default=json_default).encode()).hexdigest()


def _load(repository, transfer_id, operation_id, event_id):
    try:
        return repository.get_workflow_state(transfer_id, operation_id, event_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferWorkflowUnavailable("TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
            "Transfer workflow data could not be read.") from exc


def _replay(state, fingerprint, key):
    if state.operation is None:
        return False
    if state.operation["request_fingerprint"] != fingerprint:
        raise TransferWorkflowConflict("IDEMPOTENCY_KEY_REUSED",
            "The idempotency_key was already used with different workflow input.",
            {"idempotency_key": key})
    if state.transfer is None or state.event is None:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "The stored workflow operation is incomplete.")
    return True


def _demand(repository, demand_id):
    try:
        value = repository.get_demand_request(demand_id)
    except TransferRepositoryUnavailable as exc:
        raise TransferWorkflowUnavailable("TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "Demand commitment data could not be read.") from exc
    if value is None:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "The linked demand request is missing.")
    return value


def _validate(action, request, state, operation_date, repository):
    transfer = state.transfer
    if transfer is None:
        raise TransferWorkflowNotFound("TRANSFER_NOT_FOUND",
            "The requested transfer was not found.")
    if (action == "dispatch" and transfer["reserved_quantity"] > 0 and
            transfer["dispatched_quantity"] > 0):
        raise TransferWorkflowConflict("TRANSFER_PARTIALLY_DISPATCHED",
            "An existing partial dispatch cannot be continued or rewritten under the full-dispatch policy.")
    if (action == "receive" and transfer["received_quantity"] > 0 and
            transfer["received_quantity"] < transfer["dispatched_quantity"]):
        raise TransferWorkflowConflict("TRANSFER_PARTIALLY_RECEIVED",
            "An existing partial receipt cannot be completed or rewritten under the full-receipt policy.")
    expected = _CONFIG[action][0]
    if transfer["status"] not in ((expected,) if isinstance(expected, str) else expected):
        raise TransferWorkflowConflict("TRANSFER_INVALID_STAGE",
            f"The transfer cannot be {action.replace('_', ' ')} from its current stage.",
            {"current_status": transfer["status"]})
    if state.proposal is None or state.supply_offer is None or state.demand_request is None:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "The transfer's linked records are incomplete.")
    proposal, supply, demand = state.proposal, state.supply_offer, state.demand_request
    if proposal["status"] != "SELECTED" or proposal["compatibility_result"] != "ELIGIBLE":
        raise TransferWorkflowConflict("PROPOSAL_NOT_ELIGIBLE",
            "The linked proposal must remain SELECTED and ELIGIBLE.")
    if action == "reserve":
        if transfer["source_confirmation_status"] != "CONFIRMED" or transfer["destination_confirmation_status"] != "CONFIRMED":
            raise TransferWorkflowInvalid("TRANSFER_CONFIRMATIONS_REQUIRED",
                "Both transfer confirmations must be CONFIRMED before reservation.")
        if supply["material_id"] != demand["material_id"] or supply["unit"] != demand["unit"] or supply["unit"] != proposal["unit"]:
            raise TransferWorkflowConflict("MATERIAL_UNIT_MISMATCH",
                "Supply, demand, and proposal material/unit details no longer match.")
        if supply["surplus_status"] != "CONFIRMED" or supply["condition"] != "UNUSED" or supply["confirmed_quantity"] is None:
            raise TransferWorkflowConflict("SOURCE_STOCK_UNAVAILABLE",
                "The source is not confirmed, unused, reservable stock.")
        if not (supply["available_from"] <= operation_date and
                (supply["available_until"] is None or supply["available_until"] >= operation_date) and
                demand["needed_from"] <= operation_date <= demand["required_by"]):
            raise TransferWorkflowConflict("TRANSFER_DATE_INELIGIBLE",
                "The reservation date is outside the source or demand window.")
        quantity = transfer["approved_quantity"]
        if quantity <= 0:
            raise TransferWorkflowInvalid("RESERVATION_QUANTITY_INVALID",
                "The approved quantity must be positive.")
        available = supply["confirmed_quantity"] - supply["reserved_active_quantity"] - supply["transferred_out_quantity"]
        if quantity > available:
            raise TransferWorkflowConflict("SOURCE_STOCK_UNAVAILABLE",
                "The full approved quantity is no longer reservable.", {"reservable_quantity": available})
        live_demand = _demand(repository, demand["id"])
        if live_demand["request_status"] != "OPEN" or not live_demand["is_outstanding_need_confirmed"] or quantity > live_demand["uncommitted_quantity"]:
            raise TransferWorkflowConflict("DEMAND_UNAVAILABLE",
                "The recipient no longer has enough confirmed uncommitted demand.",
                {"uncommitted_quantity": live_demand["uncommitted_quantity"]})
        return quantity
    if action == "cancel":
        if transfer["dispatched_quantity"] != 0:
            raise TransferWorkflowConflict("TRANSFER_ALREADY_DISPATCHED",
                "A transfer cannot be cancelled after dispatch in this milestone.")
        return transfer["reserved_quantity"]
    if action == "dispatch":
        if request.quantity is not None:
            raise TransferWorkflowInvalid("DISPATCH_QUANTITY_NOT_ACCEPTED",
                "quantity is not accepted; dispatch moves the full reserved quantity.")
        if (transfer["source_confirmation_status"] != "CONFIRMED" or
                transfer["destination_confirmation_status"] != "CONFIRMED"):
            raise TransferWorkflowInvalid("TRANSFER_CONFIRMATIONS_REQUIRED",
                "Both transfer confirmations must remain CONFIRMED before dispatch.")
        quantity = transfer["reserved_quantity"]
        if quantity <= 0:
            raise TransferWorkflowConflict("DISPATCH_RESERVATION_INVALID",
                "Dispatch requires a positive current reservation.")
        if transfer["dispatched_quantity"] != 0:
            raise TransferWorkflowConflict("TRANSFER_PARTIALLY_DISPATCHED",
                "A transfer with a previous dispatched quantity cannot use full dispatch.")
        if quantity != transfer["approved_quantity"]:
            raise TransferWorkflowConflict("TRANSFER_PARTIAL_RESERVATION_UNSUPPORTED",
                "Full dispatch requires the intact full approved reservation.")
        confirmed = supply["confirmed_quantity"]
        if (confirmed is None or supply["reserved_active_quantity"] < quantity or
                supply["reserved_active_quantity"] < 0 or
                supply["transferred_out_quantity"] < 0 or
                supply["reserved_active_quantity"] +
                supply["transferred_out_quantity"] > confirmed):
            raise TransferWorkflowConflict("SOURCE_COUNTER_INVALID",
                "Source counters are inconsistent with the transfer reservation.")
        if not (supply["available_from"] <= operation_date and
                (supply["available_until"] is None or
                 supply["available_until"] >= operation_date)):
            raise TransferWorkflowConflict("TRANSFER_DATE_INELIGIBLE",
                "The dispatch date is outside the source window.")
        return quantity
    if action == "receive":
        if request.quantity is not None:
            raise TransferWorkflowInvalid("RECEIPT_QUANTITY_NOT_ACCEPTED",
                "quantity is not accepted; receipt confirms the full dispatched quantity.")
        quantity = transfer["dispatched_quantity"]
        if quantity <= 0:
            raise TransferWorkflowConflict("RECEIPT_DISPATCH_INVALID",
                "Receipt requires a positive dispatched quantity.")
        if transfer["reserved_quantity"] != 0:
            raise TransferWorkflowConflict("RECEIPT_RESERVATION_REMAINS",
                "Full receipt requires zero remaining reservation.")
        if transfer["received_quantity"] != 0 or transfer["actually_used_quantity"] != 0:
            raise TransferWorkflowConflict("RECEIPT_ALREADY_RECORDED",
                "Receipt requires zero previous received and used quantities.")
        if not demand["needed_from"] <= operation_date <= demand["required_by"]:
            raise TransferWorkflowConflict("TRANSFER_DATE_INELIGIBLE",
                "The receipt date is outside the demand window.")
        return quantity
    try:quantity=ordinary(amount(request.quantity,unit_name=proposal['unit']))
    except ValueError as exc:
        raise TransferWorkflowInvalid('TRANSFER_QUANTITY_INVALID',str(exc)) from exc
    if quantity <= 0:
        raise TransferWorkflowInvalid('TRANSFER_QUANTITY_INVALID','Quantity must be positive.')
    cap = {"confirm_use": "received_quantity"}[action]
    remaining = transfer[cap] - transfer["actually_used_quantity"]
    if quantity > remaining:
        raise TransferWorkflowInvalid("TRANSFER_QUANTITY_EXCEEDS_STAGE",
            "quantity cannot exceed the received quantity not already confirmed used.",
            {cap: transfer[cap], "already_used_quantity": transfer["actually_used_quantity"],
             "remaining_usable_quantity": remaining})
    return quantity


def _response(repository, state, key, replayed):
    try:
        supply = repository.get_supply_offer(state.proposal["supply_offer_id"])
        demand = repository.get_demand_request(state.proposal["demand_request_id"])
    except TransferRepositoryUnavailable as exc:
        raise TransferWorkflowUnavailable("TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.") from exc
    except TransferRepositoryError as exc:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "Workflow read-back could not be verified.") from exc
    return {"data": {"transfer": state.transfer, "event": state.event,
            "supply_offer": supply, "demand_request": demand,
            "idempotency_key": key, "replayed": replayed},
            "meta": load_baseline_metadata(), "error": None}


def run_transfer_workflow(transfer_id: str, action: str, request: WorkflowInput,
                          repository: TransferRepository | None = None,
                          clock: Callable[[], datetime] | None = None):
    """Run one post-approval transition atomically in the local emulator."""
    if action not in _CONFIG:
        raise ValueError(action)
    if not request.idempotency_key.strip() or len(request.idempotency_key) > 128:
        raise TransferWorkflowInvalid("IDEMPOTENCY_KEY_INVALID",
            "idempotency_key must contain 1 to 128 non-whitespace characters.")
    if not request.actor_label.strip() or len(request.actor_label) > 200:
        raise TransferWorkflowInvalid("ACTOR_LABEL_REQUIRED",
            "actor_label must contain 1 to 200 characters.")
    if request.evidence_ref is not None and len(request.evidence_ref) > 500:
        raise TransferWorkflowInvalid("EVIDENCE_REF_INVALID",
                                      "evidence_ref cannot exceed 500 characters.")
    if action == "cancel" and (request.reason is None or not request.reason.strip()):
        raise TransferWorkflowInvalid("CANCELLATION_REASON_REQUIRED",
                                      "reason is required for cancellation.")
    if repository is None:
        try:
            repository = TransferRepository()
        except TransferRepositoryError as exc:
            raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                        "Transfer workflow data could not be read.") from exc
    operation_id, event_id = _identity(request.idempotency_key)
    fingerprint = _fingerprint(action, transfer_id, request)
    state = _load(repository, transfer_id, operation_id, event_id)
    if _replay(state, fingerprint, request.idempotency_key):
        return _response(repository, state, request.idempotency_key, True)
    now = (clock or (lambda: datetime.now(timezone(timedelta(hours=8)))))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise TransferWorkflowError("TRANSFER_WORKFLOW_TIME_INVALID",
                                    "The workflow clock must return a timezone-aware timestamp.")
    quantity = _validate(action, request, state, now.date().isoformat(), repository)
    new_used_quantity = (state.transfer["actually_used_quantity"] + quantity
                         if action == "confirm_use" else 0)
    residual = state.transfer["received_quantity"] - new_used_quantity
    payload = {"quantity": quantity, "synthetic": True}
    command = {"transfer_id": transfer_id, "operation_id": operation_id,
        "request_fingerprint": fingerprint, "event_id": event_id, "quantity": quantity,
        "actor_label": request.actor_label, "evidence_ref": request.evidence_ref,
        "event_payload": payload, "occurred_at": now.isoformat(timespec="seconds"),
        "operation_date": now.date().isoformat(),
        "supply_offer_id": state.proposal["supply_offer_id"],
        "demand_request_id": state.proposal["demand_request_id"]}
    if action == "confirm_use":
        command["previous_used_quantity"] = state.transfer["actually_used_quantity"]
        command["new_used_quantity"] = new_used_quantity
        payload["cumulative_used_quantity"] = new_used_quantity
        payload["unresolved_quantity"] = residual
        # Current balances are quantity fields, not changing free-text notes.
        # Keep operator notes intact; the event retains the historical remainder.
        command["notes"] = state.transfer["notes"]
        command["demand_status"] = ("FULFILLED" if
            state.demand_request["fulfilled_quantity"] + quantity ==
            state.demand_request["required_quantity"] else "OPEN")
    if action == "cancel":
        command["reason"] = request.reason
        payload["reason"] = request.reason
        command["notes"] = f"Cancelled: {request.reason}"
    adapter=getattr(repository,'_adapter',None)
    if adapter is not None and adapter.execute('GetQuantityEncoding')['quantityEncoding']:
        command['matching_scopes']=[{'id':state.supply_offer['material_id'],'token':operation_id,'status':'PENDING','generationId':None,'payload':{}}]
        if action=='confirm_use':
            command['impact_intents']=[{'id':transfer_id,'token':operation_id,'status':'PENDING','payload':{'reason':'Saved actual use','use_operation_id':operation_id}}]
    try:
        repository.run_workflow(_CONFIG[action][1], command)
    except TransferRepositoryUnavailable as exc:
        raise TransferWorkflowUnavailable("TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.") from exc
    except TransferWorkflowMutationError as exc:
        latest = _load(repository, transfer_id, operation_id, event_id)
        if _replay(latest, fingerprint, request.idempotency_key):
            return _response(repository, latest, request.idempotency_key, True)
        _validate(action, request, latest, now.date().isoformat(), repository)
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "The atomic workflow transaction failed.") from exc
    persisted = _load(repository, transfer_id, operation_id, event_id)
    if not _replay(persisted, fingerprint, request.idempotency_key):
        raise TransferWorkflowError("TRANSFER_WORKFLOW_DATA_ERROR",
                                    "The workflow transaction could not be verified.")
    return _response(repository, persisted, request.idempotency_key, False)
