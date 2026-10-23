/** Presentation of complete server results; never eligibility or allocation logic. */
import type { Allocation, MatchingMaterial, Objective } from './current-matching';
export type TransferSelection = { supply_offer_id:string; demand_request_id:string };
export const sameTransfer = (a:TransferSelection,b:TransferSelection) => a.supply_offer_id===b.supply_offer_id&&a.demand_request_id===b.demand_request_id;
export const alternativeFor = (m:MatchingMaterial,objective:Objective) => m.status==='CURRENT'?m.generation?.alternatives.find(a=>a.plan.objective===objective):undefined;
export const opportunityAllocations = (m:MatchingMaterial) => m.status==='CURRENT'?(m.generation?.alternatives.flatMap(a=>a.plan.allocations)??[]):[];
export const hasOpportunity = (m:MatchingMaterial) => opportunityAllocations(m).length>0;
export function timingState(a:Allocation,on?:string){
 if(!on||!/^\d{4}-\d{2}-\d{2}$/.test(a.earliest_dispatch_date))return 'UNKNOWN';
 return a.earliest_dispatch_date>on?'UPCOMING':'READY';
}
export function sumAllocationQuantity(rows:Allocation[],unit:string):string|null{
 try{
  let total=0n;for(const r of rows){if(r.unit!==unit)return null;const m=/^(\d+)(?:\.(\d{1,6}))?$/.exec(String(r.proposed_quantity));if(!m)return null;total+=BigInt(m[1])*1000000n+BigInt((m[2]||'').padEnd(6,'0'));}
  const fraction=String(total%1000000n).padStart(6,'0').replace(/0+$/,'');return String(total/1000000n)+(fraction?'.'+fraction:'');
 }catch{return null;}
}
export function sameAllocations(a:Allocation[],b:Allocation[]){
 const keys=(rows:Allocation[])=>rows.map(r=>JSON.stringify([r.supply_offer_id,r.demand_request_id,String(r.proposed_quantity),r.unit,r.earliest_dispatch_date,r.earliest_delivery_date,r.required_by])).sort();
 return JSON.stringify(keys(a))===JSON.stringify(keys(b));
}
export type MaterialFilter='all'|'ready'|'upcoming'|'none'|'attention';
export type MaterialSort='name'|'reference'|'deadline';
export function filterMatchingMaterials(materials:MatchingMaterial[],options:{query:string;filter:MaterialFilter;sort:MaterialSort;on?:string},describe:(m:MatchingMaterial)=>{reference:string;search:string}){
 const query=options.query.trim().toLocaleLowerCase();
 const result=materials.filter(m=>{
  const rows=opportunityAllocations(m),current=m.status==='CURRENT';
  const includes=options.filter==='attention'?!current:options.filter==='none'?current&&!rows.length:options.filter==='ready'?rows.some(a=>timingState(a,options.on)==='READY'):options.filter==='upcoming'?rows.some(a=>timingState(a,options.on)==='UPCOMING'):rows.length>0;
  return includes&&(!query||`${m.material_name} ${m.material_id} ${describe(m).search}`.toLocaleLowerCase().includes(query));
 });
 const deadline=(m:MatchingMaterial)=>opportunityAllocations(m).map(a=>a.required_by).filter(Boolean).sort()[0]||'9999';
 return result.sort((a,b)=>options.sort==='deadline'?(deadline(a).localeCompare(deadline(b))||a.material_name.localeCompare(b.material_name)):options.sort==='reference'?(describe(a).reference.localeCompare(describe(b).reference)||a.material_id.localeCompare(b.material_id)):a.material_name.localeCompare(b.material_name)||a.material_id.localeCompare(b.material_id));
}
export function pageItems<T>(rows:T[],requested:number,size:number){const pages=Math.max(1,Math.ceil(rows.length/size)),page=Math.min(Math.max(requested,1),pages);return {page,pages,start:rows.length?(page-1)*size+1:0,end:Math.min(page*size,rows.length),items:rows.slice((page-1)*size,page*size)};}
export function matchingDate(value:string){if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return 'Not stated';const date=new Date(value+'T00:00:00Z');return Number.isFinite(date.valueOf())?new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(date):'Not stated';}
