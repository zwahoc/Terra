"""Operator review DTOs, independent of immutable AI output and publication."""
from datetime import datetime
from typing import Literal
from pydantic import Field, JsonValue, field_validator
from backend.app.schemas.analysis import AnalysisModel, DraftRecord, ExtractedProject, ProposedEntity


class RevisionCommand(AnalysisModel):
    expected_revision: int = Field(ge=1, strict=True)


class SelectReview(RevisionCommand):
    comparison_id: str
    run_id: str


class Conversion(AnalysisModel):
    to_unit: str = Field(min_length=1)
    factor: str
    basis: str = Field(min_length=1)
    confirmed: bool = False

    @field_validator('factor')
    @classmethod
    def positive(cls, value):
        from decimal import Decimal
        from backend.app.services.analysis_output import PLAIN_DECIMAL
        if not PLAIN_DECIMAL.fullmatch(value) or Decimal(value) <= 0:
            raise ValueError('Conversion factor must be a positive plain decimal string')
        return value


class ReviewRow(AnalysisModel):
    id: str
    original: DraftRecord | None = None
    current: DraftRecord
    decision: Literal['PENDING', 'ACCEPTED', 'EXCLUDED'] = 'PENDING'
    assumptions_confirmed: bool = False
    conversion: Conversion | None = None
    release_confirmed: bool = False
    edited_by_operator: bool = False
    provenance: Literal['AI_DOCUMENT', 'OPERATOR_MANUAL'] = 'AI_DOCUMENT'
    preparation: dict[str, JsonValue] = Field(default_factory=dict)


class RowEdit(RevisionCommand):
    release_confirmed: bool = False
    current: DraftRecord
    decision: Literal['PENDING', 'ACCEPTED', 'EXCLUDED']
    assumptions_confirmed: bool = False
    conversion: Conversion | None = None


class ReviewProject(AnalysisModel):
    id: str
    original: ExtractedProject | None = None
    current: ExtractedProject
    confirmed: bool = False
    edited_by_operator: bool = False
    master_updates: dict[str, str] = Field(default_factory=dict)


class ProjectEdit(RevisionCommand):
    current: ExtractedProject
    confirmed: bool
    master_updates: dict[str, str] = Field(default_factory=dict)


class ReviewEntity(AnalysisModel):
    original: ProposedEntity | None = None
    proposal: ProposedEntity
    confirmed: bool = False
    edited_by_operator: bool = False


class EntityEdit(RevisionCommand):
    kind: Literal['PROJECT', 'MATERIAL']
    attributes: dict[str, JsonValue]
    confirmed: bool = False


class ReviewSubmission(AnalysisModel):
    id: str
    kind: Literal['FILE', 'MANUAL']
    label: str
    rows: list[ReviewRow] = Field(default_factory=list)
    projects: list[ReviewProject] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    summary_confirmed: bool = False
    approval_digest: str | None = None
    approved_at: datetime | None = None
    resolution: Literal['EXTRACTED', 'SKIPPED', 'MANUAL_REPLACEMENT'] = 'EXTRACTED'


class ReviewState(AnalysisModel):
    version: Literal['ingestion.review.v1'] = 'ingestion.review.v1'
    prepared: bool = False
    comparison_id: str | None = None
    run_id: str | None = None
    source_digest: str | None = None
    context_epoch: int = 0
    submissions: list[ReviewSubmission] = Field(default_factory=list)
    entities: list[ReviewEntity] = Field(default_factory=list)
    # Explicit completeness acknowledgement per calculation group, never LLM-set.
    confirmed_stock_scopes: list[str] = Field(default_factory=list)
    audit: list[dict[str, JsonValue]] = Field(default_factory=list)


class ManualSubmission(RevisionCommand):
    prepared: bool = False
    label: str = Field('Manual entry', min_length=1)
    records: list[DraftRecord] = Field(default_factory=list)
    conversions: list[Conversion | None] = Field(default_factory=list)
    replaces_submission_id: str | None = None
    analysis_run_id: str | None = None


class EditorPreview(RevisionCommand):
    current: DraftRecord
    conversion: Conversion | None = None
    row_id: str | None = None


class ResolveFile(RevisionCommand):
    resolution: Literal['SKIPPED', 'ANALYSE']
    analysis_run_id: str | None = None


class ScopeConfirmation(RevisionCommand):
    scopes: list[str]


class ApproveSubmission(RevisionCommand):
    preview_digest: str
    summary_confirmed: bool
    accept_recommendations: bool = False


class BulkDecision(RevisionCommand):
    row_ids: list[str] = Field(min_length=1)
    decision: Literal['ACCEPTED', 'EXCLUDED']
    application: Literal['ADD', 'HISTORY_ONLY']
    assumptions_confirmed: bool
