import type { AppPage } from '../app/page-types';

export type PageTarget = { page: AppPage; materialId?: string; transferId?: string; projectId?: string; runId?: string; supplyId?: string; demandId?: string; resume?: boolean };
const paths: Record<AppPage,string> = { overview:'home',materials:'inventory',matching:'matching',approvals:'approvals',transfers:'deliveries',upload:'upload',impact:'report' };
export function readPageTarget(href: string): PageTarget {
 const url=new URL(href),[path,query='']=url.hash.replace(/^#\/?/,'').split('?');
 const page=(Object.keys(paths) as AppPage[]).find(k=>paths[k]===path) ?? (url.searchParams.has('intake')?'upload':'overview');
 const p=new URLSearchParams(query);
 return {page,materialId:p.get('material')||undefined,transferId:p.get('transfer')||undefined,projectId:p.get('project')||undefined,runId:p.get('run')||undefined,supplyId:p.get('supply')||undefined,demandId:p.get('demand')||undefined,resume:p.get('resume')==='1'||(page==='upload'&&url.searchParams.has('intake'))};
}
export function pageUrl(target:PageTarget,href:string) {
 const url=new URL(href),p=new URLSearchParams();
 for(const [key,value] of Object.entries({material:target.materialId,transfer:target.transferId,project:target.projectId,run:target.runId,supply:target.supplyId,demand:target.demandId,resume:target.resume?'1':undefined}))if(value)p.set(key,value);
 if(target.page!=='upload'||!target.resume)url.searchParams.delete('intake');
 url.hash='/'+paths[target.page]+(p.size?'?'+p:'');return url.pathname+url.search+url.hash;
}
export const statusLabel=(status:string)=>({REQUESTED:'Unreserved',APPROVED:'Unreserved',RESERVED:'Reserved',IN_TRANSIT:'On the way',RECEIVED:'Received',REUSED:'Used',CANCELLED:'Cancelled',POTENTIAL:'Potential',CONFIRMED:'Confirmed',SUSPENDED:'On hold',CLOSED:'Closed'}[status]??status.toLowerCase().replaceAll('_',' '));
export const meaningLabel=(kind:string)=>({UNKNOWN:'Technical information',ON_HAND_INVENTORY:'On-hand stock',REMAINING_LOCAL_REQUIREMENT:'Local requirement',OUTSTANDING_DEMAND:'Uncovered need',POTENTIAL_SURPLUS:'Potential excess',CONFIRMED_SURPLUS:'Released surplus',PLANNED_REQUIREMENT:'Planned requirement',PURCHASE_ORDER:'Ordered supply',RECEIPT:'Received quantity'}[kind]??kind.toLowerCase().replaceAll('_',' '));
const missingLabels:Record<string,string>={ROUTE_DISTANCE:'Route distance',MISSING_NEW_MATERIAL_PRODUCTION_FACTOR:'Material production factor',PRODUCTION_FACTOR:'Material production factor',MISSING_TRANSPORT_FACTOR:'Transport factor',TRANSPORT_FACTOR:'Transport factor',MISSING_PROCESSING_FACTOR:'Handling factor',PROCESSING_FACTOR:'Handling factor',MASS_KG_PER_UNIT_FOR_TRANSPORT:'Material weight',MATERIAL_MASS:'Material weight',MASS_KG_PER_UNIT:'Material weight'};
export function missingInputLabels(codes:string[]){return [...new Set(codes.map(code=>missingLabels[code]??code.toLowerCase().replaceAll('_',' ')))];}
export function displayError(error:unknown) {
 const raw=error instanceof Error?error.message:String(error||'');
 if(/uncertain|could not be verified|confirmation response|timed? out|timeout/i.test(raw))return 'The result could not be confirmed. Check the saved result before trying again.';
 if(/stale|no longer current|revision|context.*changed/i.test(raw))return 'The information has changed. Refresh and review the latest values.';
 if(/fetch|network|connection|HTTP 50|unavailable/i.test(raw))return 'Terra could not connect. Your saved work is preserved. Try again.';
 return raw.replace(/\b(?:TRF|SUP|DEM|PRJ|MAT|ALC|DRAFT-MATERIAL|DRAFT-PROJECT|SUB|PUB|BAT)-[A-Za-z0-9-]{12,}\b/g,'the selected record').replaceAll('_',' ');
}
