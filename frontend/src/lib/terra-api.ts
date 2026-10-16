export type TransferStatus = "REQUESTED" | "APPROVED" | "RESERVED" | "IN_TRANSIT" | "RECEIVED" | "REUSED" | "CANCELLED";

export type Transfer = {
  id: string; proposal_id: string; approved_quantity: number; reserved_quantity: number;
  dispatched_quantity: number; received_quantity: number; actually_used_quantity: number;
  status: TransferStatus; source_confirmation_status: string; destination_confirmation_status: string;
  requested_at: string; delivered_at: string | null; reuse_confirmed_at: string | null; notes: string | null;
};

export type ImpactAssessment = {
  id: string; basis: "PROPOSAL_FORECAST" | "ACTUAL_CONFIRMED_USE";
  proposal_id: string | null; transfer_id: string | null; quantity_assessed: number; unit: string;
  baseline_description: string; avoided_production_kgco2e: number | null;
  additional_transport_kgco2e: number | null; additional_processing_kgco2e: number | null;
  net_avoided_kgco2e: number | null; factor_ids: string[]; assumptions: Record<string, unknown>;
  calculation_status: string; calculated_at: string;
};

type Envelope<T> = { data: T | null; error: { message: string } | null };

const key = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const raw = await response.text();
  let payload: Envelope<T> | null = null;
  try { payload = raw ? JSON.parse(raw) as Envelope<T> : null; } catch { throw new Error("Terra returned an invalid API response."); }
  if (!response.ok || !payload?.data) throw new Error(payload?.error?.message ?? `Terra API returned HTTP ${response.status}.`);
  return payload.data;
}

const post = <T>(path: string, body: Record<string, unknown>) => request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const actor_label = "Demo operator";

export const listTransfers = () => request<Transfer[]>("/api/transfers");
export const listImpactAssessments = () => request<ImpactAssessment[]>("/api/impact-assessments?current_only=true");

export function advanceTransfer(transfer: Transfer, action: "approve" | "reserve" | "dispatch" | "receive" | "confirm-use" | "cancel", quantity?: number, reason?: string) {
  const base = { actor_label, idempotency_key: key(`${transfer.id}-${action}`), evidence_ref: "Synthetic demo operator review" };
  if (action === "approve") return post(`/api/transfers/${transfer.id}/approve`, { ...base, approved_quantity: quantity, source_confirmation_status: "CONFIRMED", destination_confirmation_status: "CONFIRMED" });
  if (action === "confirm-use") return post(`/api/transfers/${transfer.id}/confirm-use`, { ...base, quantity });
  if (action === "cancel") return post(`/api/transfers/${transfer.id}/cancel`, { ...base, reason });
  return post(`/api/transfers/${transfer.id}/${action}`, base);
}

export function approveAllocationProposal(proposalId: string) {
  return post<Transfer>(`/api/allocation-proposals/${proposalId}/approve`, {
    actor_label,
    idempotency_key: key(`${proposalId}-proposal-approval`),
    evidence_ref: "Synthetic demo operator review",
  });
}

export function calculateActualImpact(transferId: string) {
  return post(`/api/impact-assessments/transfers/${transferId}/calculate`, { actor_label, idempotency_key: key(`${transferId}-actual-impact`), revision_reason: "Calculate confirmed actual-use result" });
}

export async function downloadImpactCsv(scope: { projectId?: string; transferId?: string } = {}) {
  const query = new URLSearchParams({ basis: "ACTUAL_CONFIRMED_USE", format: "csv" });
  if (scope.projectId) query.set("project_id", scope.projectId);
  if (scope.transferId) query.set("transfer_id", scope.transferId);
  const response = await fetch(`/api/exports/impact?${query}`);
  if (!response.ok) throw new Error(`Terra API returned HTTP ${response.status}.`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = scope.transferId ? `terra-transfer-${scope.transferId}-impact.csv` : scope.projectId ? `terra-project-${scope.projectId}-impact.csv` : "terra-actual-use-impact.csv"; anchor.click();
  URL.revokeObjectURL(url);
}
