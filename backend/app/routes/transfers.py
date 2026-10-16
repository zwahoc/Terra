"""HTTP routes for reading and approving Terra emulator transfers."""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.schemas.transfers import (
    TransferApprovalRequest,
    TransferApprovalResponse,
    TransferRequestCreateRequest,
    TransferRequestCreateResponse,
    TransferCancelRequest,
    TransferDispatchRequest,
    TransferQuantityRequest,
    TransferReceiveRequest,
    TransferReserveRequest,
    TransferWorkflowResponse,
)
from backend.app.services.transfer_approval_service import (
    TransferApprovalConflict,
    TransferApprovalError,
    TransferApprovalInput,
    TransferApprovalInvalid,
    TransferApprovalNotFound,
    TransferApprovalUnavailable,
    approve_transfer,
)
from backend.app.services.transfer_request_service import (
    TransferRequestConflict, TransferRequestError, TransferRequestInput,
    TransferRequestInvalid, TransferRequestNotFound, TransferRequestUnavailable,
    create_transfer_request,
)
from backend.app.services.transfer_read_service import (
    RelatedRecordNotFound,
    TransferNotFound,
    TransferReadError,
    TransferReadUnavailable,
    get_transfer,
    get_transfer_events,
    get_supply_offer,
    get_demand_request,
    list_transfers,
)
from backend.app.services.transfer_workflow_service import (
    TransferWorkflowConflict,
    TransferWorkflowError,
    TransferWorkflowInvalid,
    TransferWorkflowNotFound,
    TransferWorkflowUnavailable,
    WorkflowInput,
    run_transfer_workflow,
)


router = APIRouter(prefix="/api", tags=["transfers"])


def _envelope_error(
    status_code: int, code: str, message: str, details: dict[str, Any]
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "meta": None,
            "error": {"code": code, "message": message, "details": details},
        },
    )


def _error_response(status_code: int, error: TransferReadError) -> JSONResponse:
    details = {}
    if isinstance(error, TransferNotFound):
        details["transfer_id"] = error.transfer_id
    if isinstance(error, RelatedRecordNotFound):
        details["id"] = error.record_id
    return _envelope_error(status_code, error.code, error.message, details)


def _run_read(action) -> dict[str, Any] | JSONResponse:
    try:
        return action()
    except (TransferNotFound, RelatedRecordNotFound) as exc:
        return _error_response(404, exc)
    except TransferReadUnavailable as exc:
        return _error_response(503, exc)
    except TransferReadError as exc:
        return _error_response(500, exc)


@router.get(
    "/transfers",
    response_model=None,
    summary="List transfers from the local emulator",
    description=(
        "Returns transfer records from Terra's local SQL Connect emulator through "
        "the existing ListTransfers named operation. Baseline version, synthetic, "
        "and as-of metadata remain sourced from terra_seed.json."
    ),
    responses={
        500: {"description": "The provider response or baseline metadata is invalid."},
        503: {"description": "The local SQL Connect emulator is unavailable."},
    },
)
def get_transfers() -> dict[str, Any] | JSONResponse:
    """Return current emulator transfers; never fall back to JSON transfer rows."""

    return _run_read(list_transfers)


@router.get(
    "/transfers/{transfer_id}",
    response_model=None,
    summary="Get one transfer from the local emulator",
    description=(
        "Looks up one exact transfer ID in the bounded 1,000-row result of the "
        "existing ListTransfers operation; no single-record connector query exists."
    ),
    responses={
        404: {"description": "No transfer has the requested ID."},
        500: {"description": "The provider response or baseline metadata is invalid."},
        503: {"description": "The local SQL Connect emulator is unavailable."},
    },
)
def get_transfer_by_id(transfer_id: str) -> dict[str, Any] | JSONResponse:
    """Return one current emulator transfer by its stable string ID."""

    return _run_read(lambda: get_transfer(transfer_id))


@router.post(
    "/transfers/{transfer_id}/approve",
    response_model=TransferApprovalResponse,
    summary="Approve a requested transfer",
    description=(
        "Loads the transfer and selected allocation proposal from Terra's local SQL "
        "Connect emulator, requires both simulated confirmations, and atomically "
        "stores the APPROVED transfer state, audit event, and replay-safe operation. "
        "Approval does not reserve stock or establish a demand commitment."
    ),
    responses={
        400: {"description": "Approval input or confirmations are invalid."},
        404: {"description": "No transfer has the requested ID."},
        409: {"description": "Stage or idempotency-key conflict."},
        422: {"description": "The JSON request does not match the approval DTO."},
        500: {"description": "Provider data or the approval transaction is invalid."},
        503: {"description": "The local SQL Connect emulator is unavailable."},
    },
)
def approve_transfer_by_id(
    transfer_id: str, body: TransferApprovalRequest
) -> dict[str, Any] | JSONResponse:
    """Approve only; reservation and demand commitments remain unchanged."""

    request = TransferApprovalInput(**body.model_dump())
    try:
        return approve_transfer(transfer_id, request)
    except TransferApprovalNotFound as exc:
        return _envelope_error(404, exc.code, exc.message, exc.details)
    except TransferApprovalInvalid as exc:
        return _envelope_error(400, exc.code, exc.message, exc.details)
    except TransferApprovalConflict as exc:
        return _envelope_error(409, exc.code, exc.message, exc.details)
    except TransferApprovalUnavailable as exc:
        return _envelope_error(503, exc.code, exc.message, exc.details)
    except TransferApprovalError as exc:
        return _envelope_error(500, exc.code, exc.message, exc.details)


@router.post(
    "/allocation-proposals/{proposal_id}/approve",
    response_model=TransferRequestCreateResponse,
    status_code=201,
    summary="Approve a matching proposal and create its transfer request",
    description=(
        "Approves one selected eligible matching proposal and atomically creates its "
        "REQUESTED transfer and REQUESTED audit event. The requested quantity equals "
        "the proposal quantity; no stock is reserved and no incoming demand commitment "
        "is created."
    ),
)
def create_transfer_request_for_proposal(
    proposal_id: str, body: TransferRequestCreateRequest
) -> dict[str, Any] | JSONResponse:
    try:
        return create_transfer_request(proposal_id, TransferRequestInput(**body.model_dump()))
    except TransferRequestNotFound as exc:
        return _envelope_error(404, exc.code, exc.message, exc.details)
    except TransferRequestInvalid as exc:
        return _envelope_error(400, exc.code, exc.message, exc.details)
    except TransferRequestConflict as exc:
        return _envelope_error(409, exc.code, exc.message, exc.details)
    except TransferRequestUnavailable as exc:
        return _envelope_error(503, exc.code, exc.message, exc.details)
    except TransferRequestError as exc:
        return _envelope_error(500, exc.code, exc.message, exc.details)


def _run_workflow(transfer_id: str, action: str, body) -> dict[str, Any] | JSONResponse:
    request = WorkflowInput(**body.model_dump())
    try:
        return run_transfer_workflow(transfer_id, action, request)
    except TransferWorkflowNotFound as exc:
        return _envelope_error(404, exc.code, exc.message, {"transfer_id": transfer_id})
    except TransferWorkflowInvalid as exc:
        return _envelope_error(400, exc.code, exc.message, exc.details)
    except TransferWorkflowConflict as exc:
        return _envelope_error(409, exc.code, exc.message, exc.details)
    except TransferWorkflowUnavailable as exc:
        return _envelope_error(503, exc.code, exc.message, exc.details)
    except TransferWorkflowError as exc:
        return _envelope_error(500, exc.code, exc.message, exc.details)


@router.post("/transfers/{transfer_id}/reserve", response_model=TransferWorkflowResponse,
    summary="Reserve the full approved transfer quantity")
def reserve_transfer(transfer_id: str, body: TransferReserveRequest):
    """Atomically establish source and recipient commitments in the emulator."""
    return _run_workflow(transfer_id, "reserve", body)


@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferWorkflowResponse,
    summary="Dispatch the transfer's full reserved quantity")
def dispatch_transfer(transfer_id: str, body: TransferDispatchRequest):
    """Atomically move the full reservation to transferred-out exactly once."""
    return _run_workflow(transfer_id, "dispatch", body)


@router.post("/transfers/{transfer_id}/receive", response_model=TransferWorkflowResponse,
    summary="Receive the transfer's full dispatched quantity")
def receive_transfer(transfer_id: str, body: TransferReceiveRequest):
    """Atomically confirm full delivery without counting actual use."""
    return _run_workflow(transfer_id, "receive", body)


@router.post("/transfers/{transfer_id}/confirm-use", response_model=TransferWorkflowResponse,
    summary="Confirm actual use and fulfil demand")
def confirm_transfer_use(transfer_id: str, body: TransferQuantityRequest):
    return _run_workflow(transfer_id, "confirm_use", body)


@router.post("/transfers/{transfer_id}/cancel", response_model=TransferWorkflowResponse,
    summary="Cancel an approved or reserved transfer")
def cancel_transfer(transfer_id: str, body: TransferCancelRequest):
    return _run_workflow(transfer_id, "cancel", body)


@router.get("/transfers/{transfer_id}/events", response_model=None,
            summary="Read a transfer's ordered lifecycle events")
def transfer_events(transfer_id: str):
    return _run_read(lambda: get_transfer_events(transfer_id))


@router.get("/supply-offers/{offer_id}", response_model=None,
            summary="Read source transfer counters")
def supply_offer(offer_id: str):
    return _run_read(lambda: get_supply_offer(offer_id))


@router.get("/demand-requests/{demand_id}", response_model=None,
            summary="Read demand fulfilment and incoming commitment counters")
def demand_request(demand_id: str):
    return _run_read(lambda: get_demand_request(demand_id))
