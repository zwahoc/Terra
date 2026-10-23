import type { Quantity } from './quantities';
import { refreshWorkspace } from '../data/terra';
import { commandRequest } from './action-request';
export type OptimisationObjective = "MAX_REUSE" | "EARLIEST_DEADLINE" | "MAX_NET_CO2E_AVOIDED";

/**
 * A preview must be evaluated at or after every timestamp in the live emulator
 * snapshot.  The seed's as_of_date is only appropriate before any lifecycle
 * action has been performed.  Use the operator's local business date instead
 * of silently pinning every new preview to the seed date.
 */
export function currentPlanningDate(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kuala_Lumpur",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export type OptimisationPreview = {
  preview: true;
  persisted: false;
  plan: {
    objective: OptimisationObjective;
    solver_status: string;
    total_proposed_quantity: Quantity;
    remaining_newly_allocatable_quantity_by_demand: Record<string, Quantity>;
    allocations: Array<{
      supply_offer_id: string;
      demand_request_id: string;
      material_id: string;
      proposed_quantity: Quantity;
      unit: string;
      earliest_delivery_date: string;
      required_by: string;
      distance_km: string | null;
      reason_codes: string[];
    }>;
    incomplete_carbon?: boolean;
    carbon_scoring_available?: boolean | null;
  };
  forecast_summary: {
    net_avoided_kgco2e: string | null;
    known_net_subtotal_kgco2e: string;
    complete_for_selected_allocations: boolean;
    incomplete_allocations: Array<[string, string]>;
    candidate_scoring_incomplete: boolean;
    carbon_scoring_available: boolean | null;
  };
  matching_coverage_by_demand: Record<string, {
    required_quantity: Quantity;
    proposed_quantity: Quantity;
    committed_quantity: Quantity;
    uncovered_quantity: Quantity;
    status: "COVERED" | "PARTIALLY_COVERED" | "NOT_COVERED" | "ALREADY_COMMITTED";
  }>;
  forecast_previews: Array<{
    supply_offer_id: string;
    demand_request_id: string;
    quantity_assessed: Quantity;
    unit: string;
    net_avoided_kgco2e: string | null;
    calculation_status: "DEMO" | "PRELIMINARY" | "INSUFFICIENT_DATA";
    missing_data: string[];
  }>;
};

export type PersistedAllocationProposal = {
  id: string;
  run_id: string;
  supply_offer_id: string;
  demand_request_id: string;
  proposed_quantity: Quantity;
  unit: string;
  compatibility_result: "ELIGIBLE" | string;
  status: "SELECTED" | string;
  reason_codes: string[];
  created_at: string;
};

export type PersistedOptimisationRun = {
  id: string;
  created_at: string;
  objective: OptimisationObjective;
  inputs_snapshot_hash: string;
  input_snapshot: Record<string, unknown>;
  factor_dataset_version: string;
  solver_status: string;
  assumptions: Record<string, unknown>;
};

type PersistedRunData = {
  run: PersistedOptimisationRun;
  proposals: PersistedAllocationProposal[];
  idempotency_key?: string;
  replayed?: boolean;
};

type PersistedEnvelope = { data: PersistedRunData | null; error: { code: string; message: string } | null };
const activeRunStorageKey = "terra.active_optimisation_run_id";


async function persistedRequest(path: string, init?: RequestInit): Promise<PersistedRunData> {
  const response = await fetch(path, init);
  const rawPayload = await response.text();
  let payload: PersistedEnvelope | null = null;
  try {
    payload = rawPayload ? JSON.parse(rawPayload) as PersistedEnvelope : null;
  } catch {
    throw new Error("The Matching API returned an invalid response.");
  }
  if (!response.ok || !payload?.data) {
    throw new Error(payload?.error?.message ?? `The Matching API returned HTTP ${response.status}.`);
  }
  return payload.data;
}

export async function persistOptimisationRun(
  objective: OptimisationObjective,
  planningDate: string,
  destinationProjectId?: string,
) {
  const result = await commandRequest<PersistedRunData>("/api/optimisation-runs", {
    objective, planning_date: planningDate, factor_dataset_version: "demo-v1",
    ...(destinationProjectId ? { destination_project_id: destinationProjectId } : {}), actor_label: "Demo operator",
  });
  await refreshWorkspace().catch(() => {});
  return result;
}

export const getPersistedOptimisationRun = (runId: string) => persistedRequest(`/api/optimisation-runs/${runId}`);

export function rememberActiveOptimisationRun(runId: string) {
  window.sessionStorage.setItem(activeRunStorageKey, runId);
}

export function rememberedActiveOptimisationRun() {
  return window.sessionStorage.getItem(activeRunStorageKey) ?? "";
}

type Envelope = { data: OptimisationPreview | null; error: { code: string; message: string } | null };

export async function getOptimisationPreview(
  objective: OptimisationObjective,
  planningDate: string,
  destinationProjectId?: string,
) {
  const response = await fetch("/api/optimisation-runs/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      objective,
      planning_date: planningDate,
      factor_dataset_version: "demo-v1",
      ...(destinationProjectId ? { destination_project_id: destinationProjectId } : {}),
    }),
  });
  const rawPayload = await response.text();
  let payload: Envelope | null = null;

  if (rawPayload) {
    try {
      payload = JSON.parse(rawPayload) as Envelope;
    } catch {
      throw new Error("The Matching API returned an invalid response. Make sure the FastAPI backend is running on port 8000.");
    }
  }

  if (!response.ok) {
    throw new Error(payload?.error?.message ?? `The Matching API returned HTTP ${response.status}.`);
  }
  if (!payload?.data) {
    throw new Error("The Matching API returned no preview. Start the emulator, seed data, and FastAPI backend, then try again.");
  }
  return payload.data;
}
