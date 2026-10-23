import { useState } from 'react';
import type { Batch } from '../../api';
import type { ReviewView } from '../../reviewApi';
import AnalysisPreview from './AnalysisPreview';

type Archive = {id:string;label:string;created_at:string;batches:{id:string;state:string;revision:number;files:string[]}[]};
async function read<T>(path:string):Promise<T> {
 const response=await fetch('/api/history'+path);const result=await response.json();
 if(!response.ok || result.error)throw new Error(result.error?.message || 'Historical analyses could not be loaded.');
 return result.data as T;
}
export default function HistoricalAnalyses() {
 const [archives,setArchives]=useState<Archive[]|null>(null);const [saved,setSaved]=useState<Batch|null>(null);
 const [archive,setArchive]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const [runId,setRunId]=useState('');const [query,setQuery]=useState('');
 const comparison=saved?.comparisons.find(c=>c.runs.some(r=>r.id===runId)) ?? saved?.comparisons.at(-1);
 const review=saved?.review as ReviewView['review'] | undefined;
 const run=comparison?.runs.find(r=>r.id===runId) ?? comparison?.runs.at(-1);
 return <details onToggle={e=>{if(e.currentTarget.open && archives===null)void read<Archive[]>('').then(setArchives).catch(e=>setError(e.message));}}>
  <summary>Historical analyses from earlier workspaces</summary>
  <p>Original files, AI results and saved review decisions remain available here. They cannot be published into the current workspace. Start a new batch to analyse new evidence.</p>
  {error&&<p role="alert">{error}</p>}
  <label>Find historical analysis<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Filename or batch ID" /></label>
  {archives?.map(a=><div key={a.id}><h3>{a.label} · {new Date(a.created_at).toLocaleString()}</h3>{a.batches.filter(b=>(b.id+' '+b.files.join(' ')).toLowerCase().includes(query.toLowerCase())).map(b=><p key={b.id}>{b.files.join(', ') || 'Manual batch'} · {b.id} · {b.state.toLowerCase()} <button type="button" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{setSaved(await read<Batch>(`/${a.id}/batches/${b.id}`));setArchive(a.id);setRunId('');}catch(e){setError(e instanceof Error?e.message:'Historical analysis unavailable.');}finally{setBusy(false);}}}>View saved analysis</button></p>)}</div>)}
  {archives?.length===0&&<p>No earlier workspace has been archived.</p>}
  {busy&&<p role="status">Opening historical analysis…</p>}
  {saved&&<section aria-label="Read-only historical batch"><h3>Historical batch {saved.id}</h3><p>Original state: {(saved.state || 'draft').toLowerCase()} · saved revision {saved.revision}</p>
   <label>Saved model run<select value={run?.id || ''} onChange={e=>setRunId(e.target.value)}>{saved.comparisons.flatMap(c=>c.runs.map(r=><option key={r.id} value={r.id}>{r.model_slot} · {r.id}</option>))}</select></label>
   {comparison&&<AnalysisPreview key={run?.id} batch={saved} comparison={comparison} run={run} historical sourceUrl={sid=>`/api/history/${archive}/batches/${saved.id}/files/${sid}/source`}/>}
   {review&&<details><summary>Saved human review</summary>{review.submissions.map(sub=><section key={sub.id}><h4>{sub.label}</h4><p>{sub.summary_confirmed?'Review summary confirmed in the previous workspace':'Historical review summary not confirmed'}</p><div className="intake-table-wrap"><table><thead><tr><th>Material</th><th>Meaning</th><th>Saved quantity</th><th>Decision</th></tr></thead><tbody>{sub.rows.map(row=><tr key={row.id}><td>{row.current.material_name || row.current.raw_description}{row.edited_by_operator?' · edited by operator':''}</td><td>{row.current.record_kind}</td><td>{row.current.quantity} {row.current.unit}</td><td>{row.decision}</td></tr>)}</tbody></table></div></section>)}</details>}
  </section>}
 </details>;
}
