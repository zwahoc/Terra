"""Phase 1 intake DTOs. These carry drafts, never approved stock changes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from backend.app.schemas.analysis import AnalysisComparison
from backend.app.schemas.review import ReviewState


Identifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9:_-]+$")]


class IntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CreateBatch(IntakeModel):
    selected_project_id: Identifier | None = None


class ContextPatch(IntakeModel):
    expected_revision: int = Field(ge=1, strict=True)
    operator_notes: str = ""
    operator_input: dict[str, JsonValue] = Field(default_factory=dict)


class CaptureProjectContext(IntakeModel):
    expected_revision: int = Field(ge=1, strict=True)
    project_id: Identifier


class SourceFile(IntakeModel):
    id: Identifier
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_size: int = Field(ge=0, strict=True)
    display_filename: str
    # Client MIME claims never decide browser execution or reader support.
    media_type: str = "application/octet-stream"


class FileSubmission(IntakeModel):
    id: Identifier
    source: SourceFile
    added_at: datetime
    analysis_status: Literal["NOT_STARTED", "ANALYSING", "COMPLETE", "PARTIAL", "FAILED"] = "NOT_STARTED"
    resolution: Literal['ANALYSE', 'SKIPPED', 'MANUAL'] = 'ANALYSE'
    manual_submission_id: str | None = None


class ContextObservation(IntakeModel):
    project_id: Identifier
    observed_at: datetime
    read_token: str
    facts: dict[str, JsonValue]
    # A token identifies observed contents; it is not transaction isolation.
    consistency: Literal["OBSERVED_READS"] = "OBSERVED_READS"


class DraftContext(IntakeModel):
    operator_notes: str = ""
    operator_input: dict[str, JsonValue] = Field(default_factory=dict)
    project_observations: list[ContextObservation] = Field(default_factory=list)
    refresh_required: bool = False
    epoch: int = Field(0, ge=0)


class IngestionBatch(IntakeModel):
    contract_version: Literal["ingestion.intake.v1"] = "ingestion.intake.v1"
    id: Identifier
    revision: int = Field(ge=1, strict=True)
    state: Literal["INTAKE", "PUBLISHED"] = "INTAKE"
    publication_id: str | None = None
    selected_project_id: Identifier | None = None
    created_at: datetime
    updated_at: datetime
    submissions: list[FileSubmission] = Field(default_factory=list)
    context: DraftContext = Field(default_factory=DraftContext)
    restored_from_revision: int | None = None
    comparisons: list[AnalysisComparison] = Field(default_factory=list)
    review: ReviewState | None = None
