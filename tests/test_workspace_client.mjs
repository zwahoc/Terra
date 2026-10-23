import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {transformWithOxc} from '../frontend/node_modules/vite/dist/node/index.js';
async function moduleUrl(path,replacements=[]) {
 const {code}=await transformWithOxc(readFileSync(new URL(path,import.meta.url),'utf8'),path);
 let output=code;
 for(const [pattern,value] of replacements)output=output.replace(pattern,value);
 return 'data:text/javascript;base64,'+Buffer.from(output).toString('base64');
}
const amounts=await moduleUrl('../frontend/src/lib/quantities.ts');
const commands=await moduleUrl('../frontend/src/lib/action-request.ts');
const react=new URL('../frontend/node_modules/react/index.js',import.meta.url).href;
const store=await import(await moduleUrl('../frontend/src/data/terra.ts',[
 [/from ["']react["']/g,`from '${react}'`],
 [/from ["']\.\.\/lib\/quantities["']/g,`from '${amounts}'`],
 [/from ["']\.\.\/lib\/action-request["']/g,`from '${commands}'`],
]));
function environment() {
 const saved={fetch:globalThis.fetch,sessionStorage:globalThis.sessionStorage,location:globalThis.location,history:globalThis.history};
 const values=new Map();let current='http://127.0.0.1:5173/?intake=BAT-new';
 globalThis.sessionStorage={get length(){return values.size;},key:i=>[...values.keys()][i],getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 globalThis.location={get href(){return current;}};
 globalThis.history={replaceState:(_a,_b,url)=>{current=new URL(url,current).href;}};
 return {values,url:()=>current,restore:()=>{Object.assign(globalThis,saved);}};
}
test('workspace quantities keep decimal precision and failed refresh keeps the last snapshot',async()=>{
 const env=environment();
 try {
  const data={terra:{metadata:{workspace_epoch:'WORKSPACE-a'},projects:[],materials:[]},supply_views:[],demand_views:[],transfer_views:[],candidate_matches:[],dashboard:{},matching:{state:'READY',materials:[]}};
  globalThis.fetch=async()=>({ok:true,json:async()=>({data})});
  await store.refreshWorkspace();assert.equal(store.terra,data.terra);
  globalThis.fetch=async()=>{throw Error('Temporary read failure');};
  await assert.rejects(store.refreshWorkspace(),/Temporary read failure/);assert.equal(store.terra,data.terra);
  assert.equal(store.formatUnits({m:'1000000000000.000001',pcs:300}),'1,000,000,000,000.000001 m · 300 pcs');
 } finally {env.restore();}
});
test('workspace switch clears old selections but preserves explicit first-visit links and same-workspace edits',()=>{
 const env=environment();
 try {
  env.values.set('terra.upload.batch','BAT-old');env.values.set('terra.active_optimisation_run_id','RUN-old');
  store.syncWorkspaceEpoch('WORKSPACE-a');
  assert.equal(env.values.has('terra.upload.batch'),false);assert.match(env.url(),/intake=BAT-new/);
  env.values.set('terra.upload.batch','BAT-new');store.syncWorkspaceEpoch('WORKSPACE-a');assert.equal(env.values.get('terra.upload.batch'),'BAT-new');
  env.values.set('terra.pending-command.old','old-key');store.syncWorkspaceEpoch('WORKSPACE-b');
  assert.equal(env.values.has('terra.upload.batch'),false);assert.equal(env.values.has('terra.pending-command.old'),false);assert.doesNotMatch(env.url(),/intake=/);
 } finally {env.restore();}
});

const presentation=await import(await moduleUrl('../frontend/src/lib/matching-presentation.ts'));
const allocation=(s,d,q='1',unit='pcs',start='2026-10-23')=>({supply_offer_id:s,demand_request_id:d,material_id:'M',proposed_quantity:q,unit,earliest_dispatch_date:start,earliest_delivery_date:'2026-10-25',required_by:'2026-11-01',reason_codes:[]});
function materialScope(id,allocations,status='CURRENT') {return {material_id:id,material_name:'Material '+id,unit:'pcs',status,generation:{alternatives:[{run_id:'run-'+id,plan:{objective:'MAX_REUSE',allocations}},{run_id:'deadline-'+id,plan:{objective:'EARLIEST_DEADLINE',allocations}}]}};}
test('matching list preserves access to every result with search, status filters and clamped pages',()=>{
 const materials=Array.from({length:120},(_,i)=>materialScope(String(i).padStart(3,'0'),[allocation('S'+i,'D'+i)]));
 const describe=m=>({reference:m.material_id,search:m.material_id==='119'?'Last project special product':''});
 const options={query:'',filter:'all',sort:'reference',on:'2026-10-23'};
 const filtered=presentation.filterMatchingMaterials(materials,options,describe);
 const ids=[];for(let p=1;p<=12;p++)ids.push(...presentation.pageItems(filtered,p,10).items.map(m=>m.material_id));
 assert.equal(new Set(ids).size,120);assert.equal(ids.at(-1),'119');
 assert.deepEqual(presentation.filterMatchingMaterials(materials,{...options,query:'Last project'},describe).map(m=>m.material_id),['119']);
 assert.equal(presentation.pageItems(filtered,999,10).page,12);
 const pending=materialScope('P',[allocation('SP','DP')],'PENDING'),empty=materialScope('E',[]),future=materialScope('F',[allocation('SF','DF','1','pcs','2026-10-28')]);
 assert.equal(presentation.hasOpportunity(pending),false);
 assert.deepEqual(presentation.filterMatchingMaterials([pending,empty,future],{...options,filter:'attention'},describe).map(m=>m.material_id),['P']);
 assert.deepEqual(presentation.filterMatchingMaterials([pending,empty,future],{...options,filter:'none'},describe).map(m=>m.material_id),['E']);
 assert.deepEqual(presentation.filterMatchingMaterials([pending,empty,future],{...options,filter:'upcoming'},describe).map(m=>m.material_id),['F']);
});
test('matching totals are exact within one unit and never combine incompatible units',()=>{
 assert.equal(presentation.sumAllocationQuantity([allocation('A','X','1000000000000.000001','m'),allocation('B','Y','0.000001','m')],'m'),'1000000000000.000002');
 assert.equal(presentation.sumAllocationQuantity([allocation('A','X','1','m'),allocation('B','Y','1','pcs')],'m'),null);
 assert.equal(presentation.sameAllocations([allocation('A','X','1')],[allocation('A','X','2')]),false);
 assert.equal(presentation.sameTransfer(allocation('A','X'),allocation('A','Y')),false);
 assert.equal(presentation.timingState(allocation('A','X'),undefined),'UNKNOWN');
});

const reportApi=await import(await moduleUrl('../frontend/src/lib/terra-api.ts',[
 [/import \{ refreshWorkspace \} from ["']\.\.\/data\/terra["'];?/g,"const refreshWorkspace=async()=>{throw Error('Report must not mutate workspace');};"],
 [/from ["']\.\/action-request["']/g,`from '${commands}'`],
]));
test('Excel report download keeps project scope, readable server filename and no writes',async()=>{
 const saved={fetch:globalThis.fetch,document:globalThis.document,setTimeout:globalThis.setTimeout};
 const create=URL.createObjectURL,revoke=URL.revokeObjectURL;const calls=[];let clicked=false,removed=false,filename='';
 try {
  const anchor={href:'',set download(v){filename=v;},click:()=>{clicked=true;},remove:()=>{removed=true;}};
  globalThis.document={createElement:()=>anchor,body:{appendChild:()=>{}}};
  globalThis.setTimeout=()=>0;URL.createObjectURL=()=> 'blob:test';URL.revokeObjectURL=()=>{};
  globalThis.fetch=async(path,init)=>{calls.push([path,init]);return new Response(new Uint8Array([80,75]),{headers:{'content-type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','content-disposition':'attachment; filename="terra-LG-EW-P1-reuse-2026-10-24.xlsx"'}});};
  await reportApi.downloadReuseExcel({projectId:'project with spaces'});
  const url=new URL(calls[0][0],'http://local');
  assert.equal(url.searchParams.get('project_id'),'project with spaces');assert.equal(url.searchParams.get('format'),'xlsx');
  assert.equal(url.searchParams.get('basis'),'ACTUAL_CONFIRMED_USE');assert.equal(calls[0][1].cache,'no-store');
  assert.equal(calls[0][1].method,undefined);assert.equal(clicked,true);assert.equal(removed,true);
  assert.equal(filename,'terra-LG-EW-P1-reuse-2026-10-24.xlsx');
  await reportApi.downloadReuseExcel();assert.equal(new URL(calls[1][0],'http://local').searchParams.has('project_id'),false);
 } finally {Object.assign(globalThis,saved);URL.createObjectURL=create;URL.revokeObjectURL=revoke;}
});
test('Report download exposes backend errors and refuses a wrong-format response',async()=>{
 const original=globalThis.fetch;
 try {
  globalThis.fetch=async()=>new Response(JSON.stringify({error:{message:'Terra changed while exporting. Please retry.'}}),{status:409,headers:{'content-type':'application/json'}});
  await assert.rejects(reportApi.downloadReuseExcel(),/Terra changed/);
  globalThis.fetch=async()=>new Response('{}',{headers:{'content-type':'application/json'}});
  await assert.rejects(reportApi.downloadReuseExcel(),/unexpected report format/);
 } finally {globalThis.fetch=original;}
});
