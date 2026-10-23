import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transformWithOxc } from '../frontend/node_modules/vite/dist/node/index.js';
async function load(path) {
 const { code } = await transformWithOxc(readFileSync(new URL(path,import.meta.url),'utf8'),path);
 return import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
}
const { materialGroups, issueSummary, canReview, visibleStockScopes } = await load('../frontend/src/app/ingestion/review-groups.ts');
const row = (id,item,project='P1',material=item) => ({id,current:{source_item_ref:item,project_ref:{kind:'EXISTING',id:project},material_ref:{kind:'EXISTING',id:material},material_name:item,raw_description:item}});
test('51 values for 18 materials retain every source record while grouped for review',()=>{
 const rows=[];
 for(let i=0;i<18;i++) { rows.push(row(`${i}-stock`,String(i)),row(`${i}-need`,String(i))); if(i<6) rows.push(row(`${i}-excess`,String(i))); if(i>=9) rows.push(row(`${i}-demand`,String(i))); }
 const groups=materialGroups(rows);
 assert.equal(rows.length,51);assert.equal(groups.length,18);
 assert.deepEqual(groups.flatMap(g=>g.rows).map(r=>r.id).sort(),rows.map(r=>r.id).sort());
});
test('same source item in different projects or for different materials stays separate',()=>{
 assert.equal(materialGroups([row('1','item','A','cement'),row('2','item','B','cement'),row('3','item','A','sand')]).length,3);
});
test('file summary deduplicates repeated requirements and counts affected records',()=>{
 const view={blockers:{file:[{row_id:'1',messages:['Confirm identity','Accept value']},{row_id:'2',messages:['Confirm identity']},{row_id:'1',messages:['Confirm identity']}]}};
 assert.deepEqual(issueSummary(view,'file'),[{message:'Confirm identity',count:2},{message:'Accept value',count:1}]);
});
test('partial extraction or failed reconciliation cannot become a working review',()=>{
 const complete={status:'SUCCEEDED',cross_check:{},cross_check_error:null,files:[{status:'SUCCEEDED',draft:{},reconciliation:{status:'SUCCEEDED'}}]};
 assert.equal(canReview(complete),true);
 assert.equal(canReview({...complete,status:'INTERRUPTED'}),false);
 assert.equal(canReview({...complete,coverage_verification_required:true}),false);
 assert.equal(canReview({...complete,files:[{...complete.files[0],reconciliation:{status:'RUNNING'}}]}),false);
});
const { api } = await load('../frontend/src/api.ts');
test('upload sends original bytes for every file with the current revision',async()=>{
 const old=globalThis.fetch;let form;
 globalThis.fetch=async(_url,options)=>{form=options.body;return {ok:true,json:async()=>({data:{batch:{id:'B1'},files:[]},error:null})};};
 try {
  await api.upload('B1',17,[new File(['%PDF-original'],'one.pdf'),new File(['source text'],'two.txt')]);
  assert.equal(form.get('expected_revision'),'17');
  assert.deepEqual(await Promise.all(form.getAll('files').map(file=>file.text())),['%PDF-original','source text']);
 } finally {globalThis.fetch=old;}
});

test('filtered stock confirmation cannot acknowledge hidden projects or materials',()=>{
 const scopes=[{id:'visible',project:'A',material:'cement'},{id:'other-project',project:'B',material:'cement'},{id:'hidden-material',project:'A',material:'sand'}];
 const groups=materialGroups([row('1','item','A','cement')]);
 assert.deepEqual(visibleStockScopes(scopes,groups).map(scope=>scope.id),['visible']);
});

test('different inferred materials from one work item stay distinct before catalogue resolution',()=>{
 const concrete=row('1','work-item');concrete.current.material_ref=null;concrete.current.material_name='Concrete';
 const reinforcement=row('2','work-item');reinforcement.current.material_ref=null;reinforcement.current.material_name='Reinforcement';
 assert.equal(materialGroups([concrete,reinforcement]).length,2);
});

test('server review readiness allows resolved failed files while retaining conservative legacy checks',()=>{
 assert.equal(canReview({status:'PARTIAL',review_ready:true}),true);
 assert.equal(canReview({status:'SUCCEEDED',review_ready:false}),false);
});
