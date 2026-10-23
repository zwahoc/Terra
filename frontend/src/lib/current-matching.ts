import { commandRequest } from './action-request';
export type Objective = 'MAX_REUSE' | 'EARLIEST_DEADLINE' | 'MAX_NET_CO2E_AVOIDED';
export type Allocation = { supply_offer_id:string; demand_request_id:string; material_id:string; proposed_quantity:string|number; unit:string; earliest_dispatch_date:string; earliest_delivery_date:string; required_by:string; reason_codes:string[] };
export type Alternative = { run_id:string; plan:{ objective:Objective; allocations:Allocation[] }; forecast_summary:{ net_avoided_kgco2e:string|null; candidate_scoring_incomplete:boolean; carbon_scoring_available?:boolean|null }; forecast_previews?:{calculation_status:string;missing_data?:string[]}[] };
export type MatchingMaterial = { material_id:string; material_name:string; unit:string; status:string; error:{ message?:string }|null; generation:{ generation_id:string; planning_date:string; alternatives:Alternative[] }|null };
export type CurrentMatching = { state:string; materials:MatchingMaterial[]; observed_on?:string };
export async function matchingRequest<T>(path:string,method='GET',body?:unknown):Promise<T> {
 if(method==='POST'&&path==='/inputs') return commandRequest<T>('/api/matching/inputs',body as Record<string,unknown>);
 const response=await fetch(`/api/matching${path}`,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
 const result=await response.json();
 if(!response.ok||result.error)throw new Error(result.error?.message||'Matching is unavailable. Check the local database and retry.');
 return result.data as T;
}
