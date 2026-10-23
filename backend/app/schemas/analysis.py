"""Provisional Phase 2 analysis contracts; nothing here grants publication approval."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


ModelSlot = Literal["gemini_flash", "gemini_flash_lite", "deepseek_flash"]


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AnalyseRequest(AnalysisModel):
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160)
    reanalyse: bool = False
    mode: Literal["DEFAULT", "COMPARE"] = "DEFAULT"


class SelectPrimaryRequest(AnalysisModel):
    expected_revision: int = Field(ge=1, strict=True)
    expected_preference_revision: int = Field(ge=0, strict=True)
    comparison_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class ModelPreference(AnalysisModel):
    revision: int = Field(0, ge=0)
    primary_model_slot: ModelSlot | None = None
    model_id: str | None = None
    selected_at: datetime | None = None
    batch_id: str | None = None
    comparison_id: str | None = None
    run_id: str | None = None
    input_digest: str | None = None


class RetryAnalysisRequest(AnalysisModel):
    expected_revision: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160)
    submission_ids: list[str] | None = Field(None, min_length=1)


class EntityRef(AnalysisModel):
    kind: Literal["EXISTING", "PROPOSED"]
    id: str = Field(min_length=1)


class DraftRecord(AnalysisModel):
    material_name: str | None = None
    evidence_basis: Literal['EXPLICIT', 'INFERRED'] = 'EXPLICIT'
    inferred_fields: list[str] = Field(default_factory=list)
    inference_explanation: str | None = None
    quantity_basis: Literal['MATERIAL', 'SOURCE_WORK', 'UNKNOWN'] = 'UNKNOWN'
    project_ref: EntityRef | None = None
    material_ref: EntityRef | None = None
    raw_description: str
    raw_quantity: str | None = None
    raw_unit: str | None = None
    raw_fields: dict[str, str] = Field(default_factory=dict)
    specifications: dict[str, str] = Field(default_factory=dict)
    quantity: str | None = None
    unit: str | None = None
    record_kind: Literal["PLANNED_REQUIREMENT", "PURCHASE_ORDER", "RECEIPT", "ON_HAND_INVENTORY", "REMAINING_LOCAL_REQUIREMENT", "POTENTIAL_SURPLUS", "CONFIRMED_SURPLUS", "OUTSTANDING_DEMAND", "UNKNOWN"] = "UNKNOWN"
    effective_date: date | None = None
    available_from: date | None = None
    available_until: date | None = None
    needed_from: date | None = None
    required_by: date | None = None
    application: Literal["ADD", "REPLACE", "HISTORY_ONLY", "UNDECIDED"] = "UNDECIDED"
    replaces_record_ids: list[str] = Field(default_factory=list)
    source_locator: str | None = None
    source_page: int | None = Field(None, ge=1)
    additional_source_pages: list[int] = Field(default_factory=list)
    continues_from: str | None = None
    source_item_ref: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    requires_operator_confirmation: Literal[True] = True

    @field_validator("quantity")
    @classmethod
    def exact_quantity(cls, value):
        if value is not None:
            try:
                number = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("Quantity must be an exact decimal string or null") from exc
            if not number.is_finite() or number < 0:
                raise ValueError("Quantity must be finite and nonnegative")
        return value


class ExtractedProject(AnalysisModel):
    project_ref: EntityRef | None = None
    name: str | None = None
    reference: str | None = None
    location: str | None = None
    managing_organisation: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    source_page: int | None = Field(None, ge=1)
    source_locator: str | None = None
    association_explanation: str
    inferred_fields: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class SourceItem(AnalysisModel):
    source_page: int | None = Field(None, ge=1)
    source_item_ref: str
    disposition: Literal['MATERIAL', 'CONTEXT', 'UNREADABLE']
    record_indices: list[int] = Field(default_factory=list)
    explanation: str


class FileDraft(AnalysisModel):
    extraction_version: Literal['LEGACY', 'MATERIAL_V2'] = 'LEGACY'
    project_info: list[ExtractedProject] = Field(default_factory=list)
    source_items: list[SourceItem] = Field(default_factory=list)
    document_type: Literal["BOQ", "PURCHASE_ORDER", "INVENTORY", "DEMAND", "MIXED", "OTHER"]
    summary: str
    project_refs: list[EntityRef] = Field(default_factory=list)
    records: list[DraftRecord] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    page_coverage: list[int] = Field(default_factory=list)


class CrossFileFinding(AnalysisModel):
    submission_ids: list[str] = Field(min_length=1)
    kind: Literal["POSSIBLE_DUPLICATE", "POSSIBLE_REVISION", "CONFLICT", "SHARED_CONTEXT", "MISSING_INFORMATION"]
    explanation: str
    requires_operator_confirmation: Literal[True] = True


class BatchCrossCheck(AnalysisModel):
    findings: list[CrossFileFinding] = Field(default_factory=list)
    summary: str


class ProjectProposal(AnalysisModel):
    name: str = Field(min_length=1)
    code: str | None = None
    township: str | None = None
    managing_organisation: str | None = None
    start_date: date | None = None
    target_end_date: date | None = None


class MaterialProposal(AnalysisModel):
    canonical_name: str = Field(min_length=1)
    category_code: str | None = None
    specifications: dict[str, str] = Field(default_factory=dict)
    standard_unit: str | None = None
    reference_code: str | None = None


class ProposedEntity(AnalysisModel):
    id: str
    kind: Literal["PROJECT", "MATERIAL"]
    attributes: dict[str, JsonValue]
    requires_operator_confirmation: Literal[True] = True


class ToolObservation(AnalysisModel):
    tool: str
    arguments: dict[str, JsonValue]
    result: dict[str, JsonValue]
    observed_at: datetime


class UsageRecord(AnalysisModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    thinking_tokens: int = Field(0, ge=0)
    cached_input_tokens: int = Field(0, ge=0)
    estimated_cost_myr: str
    billing_mode: Literal["PAID", "FREE_TIER", "LEGACY_PAID_RATE_REFERENCE"] = "LEGACY_PAID_RATE_REFERENCE"
    latency_ms: int = Field(ge=0)
    pricing_version: str
    stage: str | None = None
    submission_id: str | None = None


class AnalysisFailure(AnalysisModel):
    code: str
    message: str
    validation_errors: list[dict[str, JsonValue]] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class StoredRecordRef(AnalysisModel):
    project_id: str
    collection: Literal['documents', 'extracted_rows', 'supply_offers', 'demand_requests', 'allocation_proposals', 'transfers', 'demand_commitments', 'published_records', 'stock_heads']
    record_id: str


class MaterialRelationship(AnalysisModel):
    record_index: int = Field(ge=0)
    relationship: Literal['NEW_INFORMATION', 'ADDITIONAL_EVIDENCE', 'NEWER_OBSERVATION', 'POSSIBLE_DUPLICATE', 'POSSIBLE_REVISION', 'CONFLICT', 'UNRESOLVED']
    existing_records: list[StoredRecordRef] = Field(default_factory=list)
    explanation: str
    suggested_treatment: Literal['ADD', 'REPLACE', 'HISTORY_ONLY', 'UNDECIDED'] = 'UNDECIDED'
    assumptions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    requires_operator_confirmation: Literal[True] = True


class ProjectComparison(AnalysisModel):
    project_info_index: int = Field(ge=0)
    explanation: str
    issues: list[str] = Field(default_factory=list)
    requires_operator_confirmation: Literal[True] = True


class ReconciliationResult(AnalysisModel):
    summary: str
    projects: list[ProjectComparison] = Field(default_factory=list)
    materials: list[MaterialRelationship] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class ReconciliationAnalysis(AnalysisModel):
    status: Literal['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'] = 'PENDING'
    attempt: int = 0
    result: ReconciliationResult | None = None
    error: AnalysisFailure | None = None
    observed_at: datetime | None = None
    extraction_digest: str | None = None
    context_digest: str | None = None
    project_context: dict[str, JsonValue] = Field(default_factory=dict)
    response_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    recoveries: list[dict[str, JsonValue]] = Field(default_factory=list)
    previous_attempts: list[dict[str, JsonValue]] = Field(default_factory=list)
    group_results: dict[str, ReconciliationResult] = Field(default_factory=dict)
    repair_state: dict[str, JsonValue] | None = None
    processing_stage: str | None = None


KnownFamily = Literal['BOQ', 'MATERIAL_REQUIREMENTS', 'PURCHASE_ORDER', 'DELIVERY_ORDER',
    'GOODS_RECEIVED_NOTE', 'INVENTORY', 'MATERIAL_MOVEMENT', 'DEMAND', 'SURPLUS_SALVAGE',
    'MATERIAL_TRANSFER', 'TECHNICAL_SUPPORT', 'INVOICE', 'PROGRESS_CONTEXT']


class DocumentClassification(AnalysisModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    primary_family: KnownFamily | Literal['OTHER', 'MIXED']
    applicable_families: list[KnownFamily]
    basis: str
    observed_document_label: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    source_page_hints: list[int] = Field(default_factory=list)

    @model_validator(mode='after')
    def consistency(self):
        if len(self.applicable_families) != len(set(self.applicable_families)):
            raise ValueError('Document families must be unique')
        if len(self.source_page_hints) != len(set(self.source_page_hints)) or any(p < 1 for p in self.source_page_hints):
            raise ValueError('Page hints must be distinct positive original PDF pages')
        if self.primary_family == 'MIXED' and len(self.applicable_families) < 2:
            raise ValueError('MIXED requires two or more evidenced families, not merely two projects')
        if self.primary_family == 'OTHER' and self.applicable_families:
            raise ValueError('OTHER requires generic routing')
        if self.primary_family not in ('OTHER', 'MIXED') and self.primary_family not in self.applicable_families:
            raise ValueError('The primary family must be included in applicable_families')
        return self


class ClassificationAnalysis(AnalysisModel):
    status: Literal['RUNNING', 'SUCCEEDED', 'FALLBACK', 'FAILED'] = 'RUNNING'
    result: DocumentClassification | None = None
    error: AnalysisFailure | None = None
    selected_modules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_digest: str | None = None
    prompt_identity: str | None = None
    usage: list[UsageRecord] = Field(default_factory=list)
    raw_response: str | None = None


class OutputCorrection(AnalysisModel):
    path: str
    op: Literal['SET', 'REMOVE'] = 'SET'
    value_json: str | None = None


class OutputCorrections(AnalysisModel):
    corrections: list[OutputCorrection]


class PageGroupAnalysis(AnalysisModel):
    id: str
    submission_id: str
    page_numbers: list[int]
    input_digest: str
    status: Literal['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SPLIT'] = 'PENDING'
    attempt: int = 0
    draft: FileDraft | None = None
    error: AnalysisFailure | None = None
    unvalidated_output: str | None = None
    preparation: dict[str, JsonValue] | None = None
    prompt_version: str | None = None
    classification: ClassificationAnalysis | None = None
    prompt_manifest: dict[str, str] = Field(default_factory=dict)
    processing_stage: str | None = None
    response_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    recoveries: list[dict[str, JsonValue]] = Field(default_factory=list)
    previous_attempts: list[dict[str, JsonValue]] = Field(default_factory=list)
    assembled_record_indices: list[int] = Field(default_factory=list)
    repair_state: dict[str, JsonValue] | None = None


class FileAnalysis(AnalysisModel):
    submission_id: str
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"] = "PENDING"
    attempt: int = 0
    draft: FileDraft | None = None
    error: AnalysisFailure | None = None
    unvalidated_output: str | None = None
    preparation: dict[str, JsonValue] | None = None
    prompt_version: str | None = None
    classification: ClassificationAnalysis | None = None
    prompt_manifest: dict[str, str] = Field(default_factory=dict)
    processing_stage: str | None = None
    response_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    recoveries: list[dict[str, JsonValue]] = Field(default_factory=list)
    reconciliation: ReconciliationAnalysis | None = None
    page_groups: list[PageGroupAnalysis] = Field(default_factory=list)
    repair_state: dict[str, JsonValue] | None = None
    reader_metadata: dict[str, JsonValue] | None = None
    reused_from_run_id: str | None = None


class AnalysisRun(AnalysisModel):
    id: str
    model_slot: ModelSlot
    model_id: str
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "INTERRUPTED"] = "PENDING"
    files: list[FileAnalysis]
    proposals: list[ProposedEntity] = Field(default_factory=list)
    observations: list[ToolObservation] = Field(default_factory=list)
    usage: list[UsageRecord] = Field(default_factory=list)
    cross_check: BatchCrossCheck | None = None
    cross_check_error: AnalysisFailure | None = None
    retry_keys: list[str] = Field(default_factory=list)
    previous_attempts: list[dict[str, JsonValue]] = Field(default_factory=list)
    worker_instance_id: str | None = None
    recovery_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    provider_cleanup: dict[str, JsonValue] | None = None
    batch_check_parts: dict[str, BatchCrossCheck] = Field(default_factory=dict)
    batch_check_progress: dict[str, int] = Field(default_factory=dict)
    repair_state: dict[str, JsonValue] | None = None
    retry_submission_ids: list[str] | None = None
    retry_fingerprints: dict[str, str] = Field(default_factory=dict)
    proposal_lineage: dict[str, str] = Field(default_factory=dict)


class AnalysisComparison(AnalysisModel):
    contract_version: Literal["ingestion.analysis.v1"] = "ingestion.analysis.v1"
    id: str
    idempotency_key: str
    request_fingerprint: str
    input_revision: int
    input_digest: str
    manifest: dict[str, JsonValue]
    initial_context: dict[str, JsonValue]
    prompt_version: str
    configuration: dict[str, JsonValue]
    created_at: datetime
    runs: list[AnalysisRun]
    request_aliases: dict[str, str] = Field(default_factory=dict)
