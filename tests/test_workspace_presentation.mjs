import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {transformWithOxc} from '../frontend/node_modules/vite/dist/node/index.js';
const path='../frontend/src/lib/workspace-presentation.ts';
const {code}=await transformWithOxc(readFileSync(new URL(path,import.meta.url),'utf8'),path);
const ui=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('fresh sidebar destinations remove intake context while direct and contextual destinations survive reload',()=>{
 const old='http://127.0.0.1:5173/?intake=BAT-existing#/upload?resume=1';
 const fresh=ui.pageUrl({page:'upload'},old);
 assert.equal(fresh,'/#/upload');assert.equal(ui.readPageTarget('http://local'+fresh).resume,false);
 assert.equal(ui.readPageTarget('http://local/?intake=BAT-existing').resume,true);
 for(const target of [{page:'matching',materialId:'MAT-a'},{page:'approvals',runId:'RUN-a',supplyId:'S-a',demandId:'D-a'},{page:'transfers',transferId:'T-a'},{page:'impact',projectId:'P-a',transferId:'T-a'}]){
  const resolved=ui.readPageTarget('http://local'+ui.pageUrl(target,old));
  for(const key of Object.keys(target))assert.equal(resolved[key],target[key]);
  assert.doesNotMatch(ui.pageUrl(target,old),/intake=/);
 }
});
test('missing factor aliases produce one readable requirement without inventing values',()=>{
 assert.deepEqual(ui.missingInputLabels(['PRODUCTION_FACTOR','MISSING_NEW_MATERIAL_PRODUCTION_FACTOR','ROUTE_DISTANCE','MISSING_TRANSPORT_FACTOR','TRANSPORT_FACTOR']),['Material production factor','Route distance','Transport factor']);
 assert.deepEqual(ui.missingInputLabels(['NEW_UNKNOWN_INPUT']),['new unknown input']);
 assert.equal(ui.statusLabel('IN_TRANSIT'),'On the way');assert.equal(ui.meaningLabel('UNKNOWN'),'Technical information');
});
test('uncertain outcomes and stale inputs retain actionable warnings while generated identifiers leave normal error copy',()=>{
 assert.match(ui.displayError(new Error('Confirmation could not be verified; timeout')),/Check the saved result/);
 assert.match(ui.displayError('Stale generation'),/Refresh and review/);
 assert.doesNotMatch(ui.displayError('Stock SUP-1234567890abcdef is reserved'),/1234567890abcdef/);
 assert.match(ui.displayError('Supply quantity exceeds available stock'),/exceeds available stock/);
});
