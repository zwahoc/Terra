"""Typed HTTP inputs for impact calculation and export."""

from pydantic import BaseModel, ConfigDict, Field


class ImpactCalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=1, max_length=128)
    revision_reason: str = Field(min_length=1, max_length=500)
    actor_label: str = Field(min_length=1, max_length=200)
