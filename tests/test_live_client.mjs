import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transformWithOxc } from '../frontend/node_modules/vite/dist/node/index.js';
const source = readFileSync(new URL('../frontend/src/lib/action-request.ts', import.meta.url), 'utf8');
const { code } = await transformWithOxc(source, 'action-request.ts');
const { commandRequest } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

test('uncertain response retains command identity; confirmed next action gets a new key', async () => {
 const originalFetch = globalThis.fetch;
 const originalStorage = globalThis.sessionStorage;
 const values = new Map();
 globalThis.sessionStorage = { getItem: key => values.get(key) ?? null, setItem: (key,value) => values.set(key,value), removeItem: key => values.delete(key) };
 const keys=[];
 globalThis.fetch=async (_url,init) => {
  keys.push(JSON.parse(init.body).idempotency_key);
  if(keys.length===1) throw new Error('Lost acknowledgement');
  return {ok:true,json:async()=>({data:{transfer:{id:'TRF-new'}},error:null})};
 };
 try {
  await assert.rejects(commandRequest('/api/test',{quantity:10}),/Lost acknowledgement/);
  assert.equal((await commandRequest('/api/test',{quantity:10})).transfer.id,'TRF-new');
  await commandRequest('/api/test',{quantity:10});
  assert.equal(keys[0],keys[1]);assert.notEqual(keys[1],keys[2]);
 } finally {globalThis.fetch=originalFetch;globalThis.sessionStorage=originalStorage;}
});

test('team application data module has no runtime seed import', () => {
 const source=readFileSync(new URL('../frontend/src/data/terra.ts',import.meta.url),'utf8');
 assert.doesNotMatch(source,/terra_seed|candidateMatches\s*=.*flatMap/s);
});
