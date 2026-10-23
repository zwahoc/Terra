import { formatQuantity, type Quantity } from '../lib/quantities';
import { resetPendingCommands } from '../lib/action-request';
import type { CurrentMatching } from '../lib/current-matching';
import { useSyncExternalStore } from 'react';
import type { Transfer, ImpactAssessment } from '../lib/terra-api';

export type SupplyStatus = 'POTENTIAL' | 'CONFIRMED' | 'SUSPENDED' | 'CLOSED';
export type TransferStatus = Transfer['status'];
export interface Project { id: string; name: string; code: string; township: string }
export interface Material { id: string; canonical_name: string; standard_unit: string; category: string; reference_code: string | null; specifications: Record<string, unknown>; mass_kg_per_unit: number | null }
export interface Supply { id: string; source_project_id: string; material_id: string; unit: string; surplus_status: SupplyStatus; condition: string; declared_quantity: Quantity; confirmed_quantity: Quantity | null; reserved_active_quantity: Quantity; transferred_out_quantity: Quantity; available_from: string; available_until: string | null }
export interface Demand { id: string; destination_project_id: string; material_id: string; required_quantity: Quantity; fulfilled_quantity: Quantity; unit: string; needed_from: string; required_by: string; request_status: string }
export interface Proposal { id: string; run_id: string; supply_offer_id: string; demand_request_id: string; proposed_quantity: Quantity; unit: string; compatibility_result: string; status: string }
export interface Observation { id: string; project_id: string; material_id: string; quantity: string | null; unit: string | null; record_kind: string; application: string; is_effective: boolean; superseded_by: string | null; source: { kind: string; label: string } }
export interface Workspace {
 terra: { metadata: { as_of_date: string; observed_at: string; workspace_epoch: string }; projects: Project[]; materials: Material[]; supply_offers: Supply[]; demand_requests: Demand[]; allocation_proposals: Proposal[]; transfers: Transfer[]; impact_assessments: ImpactAssessment[]; published_records: Observation[] };
 supply_views: (Supply & { project_name: string; material_name: string; reservable_quantity: Quantity })[];
 demand_views: (Demand & { project_name: string; material_name: string; remaining_unfulfilled_quantity: Quantity; newly_allocatable_quantity: Quantity })[];
 transfer_views: (Transfer & { source_project_id:string; destination_project_id:string; unit: string; received_but_unused_quantity: Quantity; material_name: string; source_project_name: string; destination_project_name: string })[];
 candidate_matches: (Proposal & { source_project_id:string; destination_project_id:string; material_name: string; source_project_name: string; destination_project_name: string; maximum_preview_quantity: Quantity })[];
 matching: CurrentMatching;
 dashboard: { by_project:Record<string,{confirmed_by_unit:Record<string,Quantity>;demand_by_unit:Record<string,Quantity>;actual_reuse_tonnes:number|null}>; confirmed_by_unit: Record<string, Quantity>; demand_by_unit: Record<string, Quantity>; actual_reuse_tonnes: number | null; known_reuse_tonnes: number; unknown_mass_transfer_ids: string[] };
}
let snapshot: Workspace | null = null;
let failure = '';
let revision = 0;
let pending: Promise<void> | null = null;
const listeners = new Set<() => void>();
export let terra: Workspace['terra'];
export let supplyViews: Workspace['supply_views'];
export let demandViews: Workspace['demand_views'];
export let transferViews: Workspace['transfer_views'];
export let candidateMatches: Workspace['candidate_matches'];
export let dashboard: Workspace['dashboard'];
export let matching: Workspace['matching'];
const notify = () => { revision++; listeners.forEach(fn => fn()); };
export function refreshWorkspace(): Promise<void> {
 if (pending) return pending;
 pending = (async () => {
  try {
   const response = await fetch('/api/workspace'); const result = await response.json();
   if (!response.ok || !result.data) throw new Error(result.error?.message ?? 'Current Terra data is unavailable.');
   snapshot = result.data as Workspace;
   syncWorkspaceEpoch(snapshot.terra.metadata.workspace_epoch);
   ({ terra, supply_views: supplyViews, demand_views: demandViews, transfer_views: transferViews, candidate_matches: candidateMatches, dashboard, matching } = snapshot);
   failure = '';
  } catch (error) { failure = error instanceof Error ? error.message : 'Current data could not be loaded.'; throw error; }
  finally { pending = null; notify(); }
 })();
 return pending;
}
export function useWorkspaceState() {
 useSyncExternalStore(fn => { listeners.add(fn); return () => { listeners.delete(fn); }; }, () => revision);
 return { ready: snapshot !== null, error: failure, epoch: snapshot?.terra.metadata.workspace_epoch };
}
export const projectName = (id: string) => terra.projects.find(p => p.id === id)?.name ?? id;
export const materialName = (id: string) => terra.materials.find(m => m.id === id)?.canonical_name ?? id;
export const transferStages: TransferStatus[] = ['REQUESTED', 'APPROVED', 'RESERVED', 'IN_TRANSIT', 'RECEIVED', 'REUSED'];
export const formatUnits = (values: Record<string, Quantity>) => Object.entries(values).map(([unit,value]) => `${formatQuantity(value)} ${unit}`).join(' · ') || '0';

export function syncWorkspaceEpoch(epoch: string) {
 if (!epoch || epoch === 'legacy' || epoch === 'unassigned') return;
 try {
  const key = 'terra.workspace.epoch';
  const previousEpoch=sessionStorage.getItem(key);
  if (previousEpoch === epoch) return;
  resetPendingCommands();
  const oldBatch = sessionStorage.getItem('terra.upload.batch');
  if (oldBatch) sessionStorage.setItem('terra.history.previous-batch',oldBatch);
  for (let i=sessionStorage.length-1;i>=0;i--) {
   const name=sessionStorage.key(i);
   if (name && (name==='terra.upload.batch' || name==='terra.active_optimisation_run_id' || name.startsWith('terra.publish.') || name.startsWith('terra.pending-command.'))) sessionStorage.removeItem(name);
  }
  const url = new URL(location.href);
  if (previousEpoch !== null) {
   url.searchParams.delete('intake');
   history.replaceState(null,'',url.pathname+url.search+url.hash);
  }
  sessionStorage.setItem(key,epoch);
 } catch { /* Database generation and command guards remain authoritative. */ }
}
