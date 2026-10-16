"""Typed HTTP inputs for impact calculation and export."""

from pydantic import BaseModel, ConfigDict, Field
from datetime import date
from typing import Literal


class ImpactCalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=1, max_length=128)
    revision_reason: str = Field(min_length=1, max_length=500)
    actor_label: str = Field(min_length=1, max_length=200)


class ForecastPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    supply_offer_id: str = Field(min_length=1, max_length=128)
    demand_request_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(gt=0, strict=True)
    planning_date: date
    factor_dataset_version: str = Field(min_length=1, max_length=128)


class OptimisationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    objective: Literal['MAX_REUSE', 'EARLIEST_DEADLINE', 'MAX_NET_CO2E_AVOIDED']
    planning_date: date
    factor_dataset_version: str = Field(min_length=1, max_length=128)
    destination_project_id: str | None = Field(default=None, min_length=1, max_length=128)


class OptimisationRunCreateRequest(OptimisationPreviewRequest):
    """Persist a selected optimisation calculation without creating a transfer."""

    idempotency_key: str = Field(min_length=1, max_length=128)
    actor_label: str = Field(min_length=1, max_length=200)
