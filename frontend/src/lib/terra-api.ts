import type { Quantity } from './quantities';
import { refreshWorkspace } from '../data/terra';
import { commandRequest } from './action-request';
export type TransferStatus = "REQUESTED" | "APPROVED" | "RESERVED" | "IN_TRANSIT" | "RECEIVED" | "REUSED" | "CANCELLED";

export type Transfer = {
  id: string; proposal_id: string; approved_quantity: Quantity; reserved_quantity: Quantity;
  dispatched_quantity: Quantity; received_quantity: Quantity; actually_used_quantity: Quantity;
  status: TransferStatus; source_confirmation_status: string; destination_confirmation_status: string;
  requested_at: string; delivered_at: string | null; reuse_confirmed_at: string | null; notes: string | null;
};

export type ImpactAssessment = {
  id: string; basis: "PROPOSAL_FORECAST" | "ACTUAL_CONFIRMED_USE";
  proposal_id: string | null; transfer_id: string | null; quantity_assessed: Quantity; unit: string;
  baseline_description: string; avoided_production_kgco2e: number | null;
  additional_transport_kgco2e: number | null; additional_processing_kgco2e: number | null;
  net_avoided_kgco2e: number | null; factor_ids: string[]; assumptions: Record<string, unknown>;
  calculation_status: string; calculated_at: string;
};

type Envelope<T> = { data: T | null; error: { message: string } | null };



async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const raw = await response.text();
  let payload: Envelope<T> | null = null;
  try { payload = raw ? JSON.parse(raw) as Envelope<T> : null; } catch { throw new Error("Terra returned an invalid API response."); }
  if (!response.ok || !payload?.data) throw new Error(payload?.error?.message ?? `Terra API returned HTTP ${response.status}.`);
  return payload.data;
}

const post = async <T>(path: string, body: Record<string, unknown>): Promise<T> => {
 const result = await commandRequest<T>(path, body);
 // A successful write is not reported as failed merely because refresh fails.
 await refreshWorkspace().catch(() => {});
 return result;
};
const actor_label = "Operator";

export const listTransfers = () => request<Transfer[]>("/api/transfers");
export const listImpactAssessments = () => request<ImpactAssessment[]>("/api/impact-assessments?current_only=true");

export function advanceTransfer(transfer: Transfer, action: "approve" | "reserve" | "dispatch" | "receive" | "confirm-use" | "cancel", quantity?: Quantity, reason?: string) {
  const base = { actor_label, evidence_ref: "Operator confirmation in Terra" };
  if (action === "approve") return post(`/api/transfers/${transfer.id}/approve`, { ...base, approved_quantity: quantity, source_confirmation_status: "CONFIRMED", destination_confirmation_status: "CONFIRMED" });
  if (action === "confirm-use") return post(`/api/transfers/${transfer.id}/confirm-use`, { ...base, quantity });
  if (action === "cancel") return post(`/api/transfers/${transfer.id}/cancel`, { ...base, reason });
  return post(`/api/transfers/${transfer.id}/${action}`, base);
}

export async function approveAllocationProposal(proposalId: string) {
  const result = await post<{ transfer: Transfer }>(`/api/allocation-proposals/${proposalId}/approve`, {
    actor_label,
    evidence_ref: "Operator confirmation in Terra",
  });
  return result.transfer;
}

export function calculateActualImpact(transferId: string) {
  return post(`/api/impact-assessments/transfers/${transferId}/calculate`, { actor_label, revision_reason: "Calculate confirmed actual-use result" });
}

export type ReportScope = { projectId?: string; transferId?: string };
export type ReuseReportSummary = {
 scope: { project_id: string | null; project_name: string; project_code: string };
 generated_at: string;
 summary: { transfers: number; used_transfers: number; complete_estimates: number; missing_estimates: number;
  unknown_mass_transfers: number; known_reuse_tonnes: Quantity; known_net_kgco2e: Quantity | null; demonstration_estimates: number };
};
export const readReuseReportSummary = (projectId?: string) => request<ReuseReportSummary>(
 `/api/reports/reuse${projectId ? `?${new URLSearchParams({project_id:projectId})}` : ''}`);

export async function downloadImpactFile(format: 'xlsx' | 'csv' | 'json', scope: ReportScope = {}) {
 const query = new URLSearchParams({ basis: 'ACTUAL_CONFIRMED_USE', format });
 if (scope.projectId) query.set('project_id', scope.projectId);
 if (scope.transferId) query.set('transfer_id', scope.transferId);
 const response = await fetch(`/api/exports/impact?${query}`, {cache:'no-store'});
 if (!response.ok) {
  const error = await response.json().catch(() => null);
  throw new Error(error?.error?.message ?? `Terra API returned HTTP ${response.status}.`);
 }
 const expected = format === 'xlsx' ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' : format === 'csv' ? 'text/csv' : 'application/json';
 if (!response.headers.get('content-type')?.includes(expected)) throw new Error('Terra returned an unexpected report format. Please retry.');
 const filename=response.headers.get('content-disposition')?.match(/filename="([A-Za-z0-9_.-]+)"/)?.[1];
 const blob = await response.blob();
 const url = URL.createObjectURL(blob);
 const anchor = document.createElement('a');
 anchor.href = url; anchor.download = filename ?? `terra-reuse-report.${format}`;
 document.body.appendChild(anchor);anchor.click();anchor.remove();
 setTimeout(() => URL.revokeObjectURL(url),1000);
}
export const downloadImpactCsv = (scope:ReportScope={}) => downloadImpactFile('csv',scope);
export const downloadReuseExcel = (scope:ReportScope={}) => downloadImpactFile('xlsx',scope);

export type ConfirmationPreview = {
 proposal_id: string; generation_id: string; expected_revision: number; chosen_quantity: Quantity; original_quantity: Quantity; unit: string;
 confirmable: boolean; earliest_start: string; arrival_date: string;
 forecast: { net_avoided_kgco2e: string | null; calculation_status: string; missing_data: string[] };
};
export const previewTransferConfirmation = (id: string, quantity: string, generation: string) =>
 request<ConfirmationPreview>(`/api/allocation-proposals/${id}/confirmation-preview?${new URLSearchParams({quantity, generation_id: generation})}`);
export const confirmTransferReservation = (preview: ConfirmationPreview) =>
 post<{ transfer: Transfer }>(`/api/allocation-proposals/${preview.proposal_id}/confirm`, {
 actor_label, quantity: String(preview.chosen_quantity), generation_id: preview.generation_id, expected_revision: preview.expected_revision,
 });
export type ImpactIntent = { id: string; status: string; payload: { error?: string; calculation_status?: string; assessment_id?: string } };
export const listImpactIntents = () => request<ImpactIntent[]>('/api/impact-refresh');
export const retryImpactUpdates = () => request('/api/impact-refresh/retry', {method: 'POST'});
