"""Typed HTTP contracts for Terra transfer endpoints."""

from typing import Any, Literal
from decimal import Decimal
from pydantic import BeforeValidator, PlainSerializer
from typing import Annotated
from terra.quantities import amount

def validate_quantity(value):
    return amount(value)

ExactQuantity = Annotated[Decimal, BeforeValidator(validate_quantity), PlainSerializer(lambda v: int(v) if v == v.to_integral_value() else str(v), return_type=int | str, when_used="json")]

from pydantic import BaseModel, ConfigDict, Field


ConfirmationStatus = Literal["PENDING", "CONFIRMED", "DECLINED"]


class TransferApprovalRequest(BaseModel):
    """Explicit approval input; no reservation or commitment fields are accepted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    approved_quantity: int = Field(gt=0, strict=True)
    source_confirmation_status: ConfirmationStatus
    destination_confirmation_status: ConfirmationStatus
    actor_label: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=128)
    evidence_ref: str | None = Field(default=None, max_length=500)


class TransferRequestCreateRequest(BaseModel):
    """Create a review request only; this cannot reserve stock."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    actor_label: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=128)
    evidence_ref: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)


class TransferRecord(BaseModel):
    id: str
    proposal_id: str
    approved_quantity: ExactQuantity
    reserved_quantity: ExactQuantity
    dispatched_quantity: ExactQuantity
    received_quantity: ExactQuantity
    actually_used_quantity: ExactQuantity
    status: str
    source_confirmation_status: str
    destination_confirmation_status: str
    requested_at: str
    delivered_at: str | None
    reuse_confirmed_at: str | None
    notes: str | None


class TransferEventRecord(BaseModel):
    id: str
    transfer_id: str
    event_type: str
    occurred_at: str
    actor_label: str
    payload: dict[str, Any]
    evidence_ref: str | None


class TransferApprovalData(BaseModel):
    transfer: TransferRecord
    event: TransferEventRecord
    idempotency_key: str
    replayed: bool


class DatasetMeta(BaseModel):
    dataset_version: str
    synthetic: bool
    as_of_date: str


class TransferApprovalResponse(BaseModel):
    data: TransferApprovalData
    meta: DatasetMeta
    error: None = None


class TransferRequestCreateData(BaseModel):
    transfer: TransferRecord
    event: TransferEventRecord
    idempotency_key: str
    replayed: bool


class TransferRequestCreateResponse(BaseModel):
    data: TransferRequestCreateData
    meta: DatasetMeta
    error: None = None


class WorkflowBaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    actor_label: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=128)
    evidence_ref: str | None = Field(default=None, max_length=500)


class TransferReserveRequest(WorkflowBaseRequest):
    """Reservation always takes the full approved quantity; no quantity is accepted."""


class TransferDispatchRequest(WorkflowBaseRequest):
    """Dispatch always moves the full current reservation; quantity is not accepted."""


class TransferReceiveRequest(WorkflowBaseRequest):
    """Receipt confirms the full dispatched quantity; quantity is not accepted."""


class TransferQuantityRequest(WorkflowBaseRequest):
    """A positive quantity for confirmed use."""

    quantity: ExactQuantity = Field(gt=0)


class TransferCancelRequest(WorkflowBaseRequest):
    reason: str = Field(min_length=1, max_length=500)


class SupplyEffectRecord(BaseModel):
    id: str
    source_project_id: str
    material_id: str
    declared_quantity: ExactQuantity
    confirmed_quantity: ExactQuantity | None
    reserved_active_quantity: ExactQuantity
    transferred_out_quantity: ExactQuantity
    unit: str
    surplus_status: str
    condition: str
    available_from: str
    available_until: str | None


class DemandEffectRecord(BaseModel):
    id: str
    destination_project_id: str
    material_id: str
    required_quantity: ExactQuantity
    fulfilled_quantity: ExactQuantity
    committed_incoming_quantity: ExactQuantity
    uncommitted_quantity: ExactQuantity
    unit: str
    needed_from: str
    required_by: str
    request_status: str
    is_outstanding_need_confirmed: bool


class TransferWorkflowData(BaseModel):
    transfer: TransferRecord
    event: TransferEventRecord
    supply_offer: SupplyEffectRecord
    demand_request: DemandEffectRecord
    idempotency_key: str
    replayed: bool


class TransferWorkflowResponse(BaseModel):
    data: TransferWorkflowData
    meta: DatasetMeta
    error: None = None

class TransferConfirmationRequest(WorkflowBaseRequest):
    quantity: ExactQuantity = Field(gt=0)
    generation_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0, strict=True)
