export type ModelSlot = 'gemini_flash' | 'gemini_flash_lite' | 'deepseek_flash';
export const modelNames: Record<ModelSlot, string> = {
  gemini_flash: 'Gemini 3.8 Flash',
  gemini_flash_lite: 'Gemini 3.5 Flash-Lite',
  deepseek_flash: 'DeepSeek V4.1 Flash',
};

export interface PrimaryPreference {
  revision: number;
  primary_model_slot: ModelSlot | null;
  model_id: string | null;
  selected_at: string | null;
  batch_id: string | null;
  comparison_id: string | null;
  run_id: string | null;
}
export interface Providers {
  enabled: boolean;
  models: { slot: ModelSlot; model_id: string; key_configured: boolean; billing_mode: 'FREE_TIER' | 'PAID' }[];
  preference: PrimaryPreference;
  budget: { enforcement_enabled: false; ceiling_myr: null; remaining_estimate_myr: null;
    spent_or_reserved_estimate_myr: string; reported_usage_estimate_myr: string;
    uncertain_reservation_estimate_myr: string; legacy_gemini_paid_rate_reference_myr: string; uncertain_calls: number };
}
export interface Project { id: string; name: string; township: string }
export interface EntityRef { kind: 'EXISTING' | 'PROPOSED'; id: string }
export interface DraftRecord {
  material_name?: string | null;
  evidence_basis?: 'EXPLICIT' | 'INFERRED';
  inferred_fields?: string[];
  inference_explanation?: string | null;
  quantity_basis?: 'MATERIAL' | 'SOURCE_WORK' | 'UNKNOWN';
  project_ref: EntityRef | null;
  material_ref: EntityRef | null;
  raw_description: string;
  raw_quantity: string | null;
  raw_unit: string | null;
  raw_fields: Record<string, string>;
  specifications: Record<string, string>;
  quantity: string | null;
  unit: string | null;
  record_kind: string;
  effective_date: string | null;
  available_from: string | null;
  available_until: string | null;
  needed_from: string | null;
  required_by: string | null;
  application: string;
  replaces_record_ids: string[];
  source_locator: string | null;
  source_page?: number | null;
  additional_source_pages?: number[];
  continues_from?: string | null;
  source_item_ref?: string | null;
  assumptions: string[];
  issues: string[];
}
export interface FileDraft {
  extraction_version?: 'LEGACY' | 'MATERIAL_V2';
  project_info?: { project_ref: EntityRef | null; name: string | null; reference: string | null;
    location: string | null; managing_organisation: string | null; start_date: string | null; end_date: string | null;
    source_page: number | null; source_locator: string | null; association_explanation: string;
    inferred_fields: string[]; assumptions: string[]; issues: string[] }[];
  source_items?: { source_page: number | null; source_item_ref: string; disposition: string; explanation: string; record_indices: number[] }[];
  page_coverage?: number[];
  document_type: string;
  summary: string;
  project_refs: EntityRef[];
  records: DraftRecord[];
  assumptions: string[];
  issues: string[];
}
export interface FileResult {
  reader_metadata?: { format: string; coverage: string; formulas_without_cached_values?: string[] } | null;
  reused_from_run_id?: string | null;
  page_groups?: { id: string; page_numbers: number[]; status: string; attempt: number;
    draft: FileDraft | null; error: { code: string; message: string } | null;
    classification?: { result: { primary_family: string } | null } | null;
    response_history?: { stage: string; text: string }[] }[];
  reconciliation?: { status: string; attempt: number; observed_at: string | null; context_digest: string | null;
    error: { code: string; message: string } | null;
    result: { summary: string; issues: string[];
      projects: { project_info_index: number; explanation: string; issues: string[] }[];
      materials: { record_index: number; relationship: string; explanation: string; suggested_treatment: string;
        existing_records: { project_id: string; collection: string; record_id: string }[]; assumptions: string[]; issues: string[] }[] } | null } | null;
  submission_id: string;
  status: string;
  attempt: number;
  prompt_version?: string | null;
  processing_stage?: string | null;
  classification?: { status: string; result: { primary_family: string; applicable_families: string[]; basis: string; uncertainties: string[] } | null;
    selected_modules: string[]; warnings: string[]; error: { code: string; message: string } | null; prompt_identity: string | null } | null;
  recoveries?: Record<string, unknown>[];
  response_history?: { stage: string; text: string }[];
  draft: FileDraft | null;
  error: { code: string; message: string; validation_errors: { location: (string | number)[]; message: string }[]; details?: Record<string, unknown> } | null;
  unvalidated_output: string | null;
  preparation: { version: string; strategy: string; page_count: number; pages_with_text: number;
    pages_prepared?: number; images_uploaded_in_run?: number;
    pages: { page_number: number; resized_to_limit: boolean }[]; local_ocr: boolean; all_pages_included: boolean;
    coverage_check?: { page_count: number; numbered_source_items: number; numbered_items_accounted_for: boolean } } | null;
}
export interface AnalysisRun {
  review_ready?: boolean;
  id: string;
  model_slot: ModelSlot;
  model_id: string;
  status: string;
  coverage_verification_required?: boolean;
  files: FileResult[];
  proposals: { id: string; kind: string; attributes: Record<string, unknown> }[];
  observations: { tool: string; arguments: Record<string, unknown>; result: Record<string, unknown>; observed_at: string }[];
  usage: { input_tokens: number; output_tokens: number; thinking_tokens: number; estimated_cost_myr: string;
    billing_mode?: 'PAID' | 'FREE_TIER' | 'LEGACY_PAID_RATE_REFERENCE'; latency_ms: number; stage?: string | null }[];
  cross_check: { summary: string; findings: { kind: string; explanation: string; submission_ids: string[] }[] } | null;
  cross_check_error: { code: string; message: string } | null;
}
export interface Comparison {
  id: string;
  created_at: string;
  input_revision: number;
  prompt_version: string;
  configuration: { mode?: string };
  runs: AnalysisRun[];
  input_manifest_current: boolean;
  database_context_requires_refresh: boolean;
  batch_revision?: number;
}
export interface Submission {
  id: string;
  added_at: string;
  analysis_status: string;
  resolution?: 'ANALYSE' | 'SKIPPED' | 'MANUAL';
  manual_submission_id?: string | null;
  source: { id: string; display_filename: string; byte_size: number; sha256: string };
}
export interface Batch {
  id: string;
  revision: number;
  state?: string;
  publication_id?: string | null;
  selected_project_id: string | null;
  created_at: string;
  submissions: Submission[];
  context: { operator_notes: string; operator_input: Record<string, unknown>; refresh_required: boolean; project_observations: unknown[] };
  comparisons: Comparison[];
  review?: import('./reviewApi').ReviewView['review'] | null;
}

interface Envelope<T> {
  data: T;
  error: { code: string; message: string } | null;
}
export class ApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/ingestion${path}`, { cache: 'no-store', ...options });
  } catch {
    throw new ApiError('CONNECTION_UNAVAILABLE', 'Cannot reach Terra. Start the backend and local emulator, then refresh.');
  }
  let body: Envelope<T>;
  try { body = await response.json(); }
  catch { throw new ApiError('INVALID_RESPONSE', 'Terra did not return an API response. Check the backend connection, then refresh.'); }
  if (!response.ok || body.error) {
    throw new ApiError(body.error?.code ?? 'REQUEST_FAILED', body.error?.message ?? 'The request failed. Refresh and try again.');
  }
  return body.data;
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
const part = encodeURIComponent;
export const api = {
  providers: () => request<Providers>('/providers'),
  async projects(): Promise<Project[]> {
    const projects: Project[] = [];
    let after = '';
    do {
      const page = await request<{ records: Project[]; next_cursor: string | null }>(`/projects?limit=200&after=${part(after)}`);
      projects.push(...page.records);
      const next = page.next_cursor ?? '';
      if (next && next <= after) throw new ApiError('INVALID_CURSOR', 'Project loading stopped unexpectedly. Refresh and try again.');
      after = next;
    } while (after);
    return projects;
  },
  create: (projectId: string) => request<Batch>('/batches', json('POST', { selected_project_id: projectId || null })),
  batch: (id: string) => request<Batch>(`/batches/${part(id)}`),
  duplicates: (id: string) => request<{matches:{submission_id:string;batch_id:string;state:string;source_filename:string;has_saved_analysis:boolean}[]}>(`/batches/${part(id)}/duplicates`),
  upload: (id: string, revision: number, files: File[]) => {
    const body = new FormData();
    body.append('expected_revision', String(revision));
    for (const file of files) body.append('files', file);
    return request<{ batch: Batch; files: { duplicate_in_batch: boolean }[] }>(`/batches/${part(id)}/files`, { method: 'POST', body });
  },
  notes: (batch: Batch, notes: string) => request<Batch>(`/batches/${part(batch.id)}/context`, json('PATCH', {
    expected_revision: batch.revision, operator_notes: notes, operator_input: batch.context.operator_input,
  })),
  restore: (id: string) => request<Batch>(`/batches/${part(id)}/restore`, json('POST', {})),
  analyse: (batch: Batch, mode: 'DEFAULT' | 'COMPARE', reanalyse: boolean) => request<Comparison>(`/batches/${part(batch.id)}/analyse`, json('POST', {
    expected_revision: batch.revision, idempotency_key: crypto.randomUUID(), mode, reanalyse,
  })),
  comparison: (batchId: string, id: string) => request<Comparison>(`/batches/${part(batchId)}/comparisons/${part(id)}`),
  selectPrimary: (batch: Batch, comparison: Comparison, run: AnalysisRun, preference: PrimaryPreference) => request<PrimaryPreference>(`/batches/${part(batch.id)}/primary-model`, json('POST', {
    expected_revision: batch.revision, expected_preference_revision: preference.revision,
    comparison_id: comparison.id, run_id: run.id,
  })),
  retry: (batch: Batch, comparison: Comparison, run: AnalysisRun) => request<Comparison>(`/batches/${part(batch.id)}/comparisons/${part(comparison.id)}/runs/${part(run.id)}/retry`, json('POST', {
    expected_revision: batch.revision, idempotency_key: crypto.randomUUID(),
  })),
  source: (batchId: string, submissionId: string) => `/api/ingestion/batches/${part(batchId)}/files/${part(submissionId)}/source?preview=true`,
};
