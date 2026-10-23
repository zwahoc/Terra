import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, modelNames } from '../../api';
import type { Batch, Comparison, Project, Providers } from '../../api';
import { reviewApi } from '../../reviewApi';
import type { Catalogue, ReviewView } from '../../reviewApi';
import { commandRequest } from '../../lib/action-request';
import { refreshWorkspace } from '../../data/terra';
import Publication from '../../Publication';
import DocumentReview from '../ingestion/DocumentReview';
import PreparedReview from '../ingestion/PreparedReview';
import './prepared-intake.css';
import AnalysisPreview from '../ingestion/AnalysisPreview';
import HistoricalAnalyses from '../ingestion/HistoricalAnalyses';
import FileRecovery from '../ingestion/FileRecovery';
import { canReview, readable } from '../ingestion/review-groups';
import './intake-workflow.css';
import { ErrorNotice, Feedback, PageHeader, TechnicalDetails } from '../components-workspace';

const initialBatch = () => { try { return new URLSearchParams(location.search).get('intake') ?? sessionStorage.getItem('terra.upload.batch') ?? ''; } catch { return ''; } };
export default function UploadPage({resume=false,onMatching}:{resume?:boolean;onMatching?:()=>void}) {
  const [id, setId] = useState(()=>resume?initialBatch():'');
  const [resumeId,setResumeId]=useState(()=>{try{return sessionStorage.getItem('terra.upload.batch')||'';}catch{return '';}});
  const [batch, setBatch] = useState<Batch | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [review, setReview] = useState<ReviewView | null>(null);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [catalogue, setCatalogue] = useState<Catalogue[]>([]);
  const [selectedProject, setSelectedProject] = useState('');
  const [notes, setNotes] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState('');
  const [publicationBusy, setPublicationBusy] = useState(false);
  const [connectionError,setConnectionError]=useState<Error|null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState('');
  const [openId, setOpenId] = useState('');
  const [selectedRun, setSelectedRun] = useState('');
  const [manual, setManual] = useState(false);
  const [manualReplacement, setManualReplacement] = useState<{submissionId:string;runId:string;label:string} | null>(null);
  const [reviewEditing, setReviewEditing] = useState(false);
  const [phase,setPhase] = useState(1);
  useEffect(()=>{if(batch?.state==='PUBLISHED')setPhase(3);else if(batch?.review)setPhase(2);},[batch?.id,!!batch?.review,batch?.state]);
  const [reanalyse, setReanalyse] = useState(false);
  const [duplicates, setDuplicates] = useState<Awaited<ReturnType<typeof api.duplicates>>['matches']>([]);
  const generation = useRef(0); const actionLock = useRef(false); const latestRevision = useRef(0);
  const primary = providers?.preference.primary_model_slot;
  const run = comparison?.runs.find(r => r.id === selectedRun)
    ?? comparison?.runs.find(r => r.model_slot === primary)
    ?? (comparison?.runs.length === 1 ? comparison.runs[0] : undefined);
  const running = comparison?.runs.some(r => ['RUNNING', 'PENDING'].includes(r.status)) ?? false;
  const locked = batch?.state === 'PUBLISHED';
  const disabled = !!busy || publicationBusy || running;
  const inputLocked = disabled || locked || reviewEditing || manual;

  const load = useCallback(async (batchId: string, restoreNotes = false) => {
    const ticket = generation.current;
    const value = await api.batch(batchId);
    const working = value.review ? await reviewApi.get(batchId) : null;
    const comparisonId = value.comparisons.at(-1)?.id ?? working?.review.comparison_id;
    const result = comparisonId ? await api.comparison(batchId, comparisonId) : null;
    if (ticket !== generation.current || value.revision < latestRevision.current) return;
    latestRevision.current = Math.max(value.revision, working?.revision ?? 0);
    setConnectionError(null);setBatch({ ...value, revision: latestRevision.current }); setReview(working); setComparison(result);
    if (restoreNotes) { setNotes(value.context.operator_notes); setSelectedProject(value.selected_project_id ?? ''); }
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([api.providers(), api.projects(), reviewApi.catalogue()]).then(([p, projects, materials]) => {
      if (active) { setProviders(p); setProjects(projects); setCatalogue(materials); }
    }).catch(reason => { if (active) setError(reason); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    generation.current++; latestRevision.current = 0;
    setBatch(null); setReview(null); setComparison(null); setSelectedRun('');
    if (!id) return;
    const ticket = generation.current;
    setBusy('Loading batch'); setError(null);
    load(id, true).catch(reason => { if (ticket === generation.current) setError(reason); })
      .finally(() => { if (ticket === generation.current) setBusy(''); });
    try { sessionStorage.setItem('terra.upload.batch', id); } catch { /* Server persistence remains. */ }
    return () => { generation.current++; };
  }, [id, load]);
  useEffect(() => {
    if (!id || !running) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await load(id); } catch (reason) { if (active) setConnectionError(reason as Error); }
      if (active) timer = setTimeout(poll, 2200);
    };
    timer = setTimeout(poll, 1000);
    return () => { active = false; clearTimeout(timer); };
  }, [id, running, load]);
  async function action(label: string, task: () => Promise<void>) {
    if (actionLock.current) return;
    actionLock.current = true; const ticket = generation.current;
    setBusy(label); setError(null); setNotice('');
    try { await task(); } catch (reason) { if (ticket === generation.current) setError(reason as Error); if (id) await load(id).catch(() => {}); }
    finally { actionLock.current = false; if (ticket === generation.current) setBusy(''); }
  }
  function open(batchId: string) {
    if(!window.dispatchEvent(new Event('terra:before-editor-navigation',{cancelable:true})))return;
    setFiles([]); setManual(false); setManualReplacement(null); setDuplicates([]); setError(null); setNotice(''); setId(batchId.trim());
    const url = new URL(location.href);
    if (batchId) url.searchParams.set('intake', batchId.trim()); else url.searchParams.delete('intake');
    url.hash=batchId?'/upload?resume=1':'/upload';
    history.replaceState(null, '', url.pathname + url.search+url.hash);
    if(batchId)setResumeId(batchId.trim());
    else {setNotes('');setSelectedProject('');setPhase(1);}
  }
  async function refresh() {
    if (!batch) return;
    await load(batch.id);
    if ((await api.batch(batch.id)).state === 'PUBLISHED') {
      await refreshWorkspace().catch(() => {});
      const [p, c] = await Promise.all([api.projects(), reviewApi.catalogue()]); setProjects(p); setCatalogue(c);
    }
  }
  async function upload() {
    await action('Uploading files', async () => {
      let value = batch ? await api.batch(batch.id) : await api.create(selectedProject);
      const result = await api.upload(value.id, value.revision, files); value = result.batch;
      if (notes !== value.context.operator_notes) value = await api.notes(value, notes);
      setFiles([]); if (id !== value.id) open(value.id); else await load(value.id);
      setNotice(result.files.every(f => f.duplicate_in_batch) ? 'These files are already in this batch.' : 'Files saved.');
    });
  }
  async function analyse() {
    if (!primary) return;
    await action('Saving files and starting analysis', async () => {
      let value = batch ? await api.batch(batch.id) : await api.create(selectedProject);
      if(files.length){const uploaded=await api.upload(value.id,value.revision,files);value=uploaded.batch;setFiles([]);}
      if (value.context.operator_notes !== notes) value = await api.notes(value, notes);
      const runAgain = reanalyse; setReanalyse(false);
      await commandRequest(`/api/ingestion/batches/${value.id}/analyse`, { expected_revision: value.revision, mode: 'DEFAULT', reanalyse: runAgain });
      if(id!==value.id)open(value.id);else await load(value.id);
      setPhase(1);
    });
  }
  async function startReview(){if(!batch||!run||!comparison)return;
    await action('Preparing recommendations',async()=>{const value=await api.batch(batch.id);
      if(value.review&&value.review.run_id!==run.id){await reviewApi.rebase(id,value.revision,comparison.id,run.id);const latest=await api.batch(id);await reviewApi.prepare(id,latest.revision,comparison.id,run.id);}
      else await reviewApi.prepare(id,value.revision,comparison.id,run.id);
      await load(id);setPhase(2);
    });
  }
  return <div className="terra-intake ingestion-flow">
    <PageHeader title="Document intake" actions={<>{phase===1&&!locked&&<button disabled={disabled} onClick={()=>void action('Opening manual entry',async()=>{const value=batch??await api.create(selectedProject);if(!batch)open(value.id);setManualReplacement(null);setManual(true);})}>Enter information manually</button>}{!id&&resumeId&&<button disabled={disabled} onClick={()=>open(resumeId)}>Resume saved batch</button>}{id&&<button disabled={disabled||reviewEditing} onClick={()=>{open('');setPhase(1);}}>New batch</button>}</>}/>
    <nav className="intake-phases" aria-label="Ingestion phases">{['Upload & analyse','Review','Publish'].map((label,i)=><button key={label} aria-current={phase===i+1?'step':undefined} disabled={disabled||reviewEditing||i>0&&!review} onClick={()=>setPhase(i+1)}><span>{i+1}</span>{label}</button>)}</nav>
    {connectionError&&<ErrorNotice error={connectionError}><button disabled={disabled} onClick={()=>void load(id).catch(setConnectionError)}>Retry connection</button></ErrorNotice>}
    {error&&<ErrorNotice error={error}>{error instanceof ApiError&&error.code==='DRAFT_RESTORE_REQUIRED'?<button disabled={disabled} onClick={()=>void action('Restoring draft',async()=>{await api.restore(id);await load(id,true);})}>Restore saved draft</button>:<button disabled={disabled} onClick={()=>void action('Refreshing connection',async()=>{const [p,c,m]=await Promise.all([api.providers(),api.projects(),reviewApi.catalogue()]);setProviders(p);setProjects(c);setCatalogue(m);if(id)await load(id);})}>Refresh connection</button>}</ErrorNotice>}
    {notice&&<Feedback>{notice}</Feedback>}{busy&&<p role="status">{busy}…</p>}
    {phase===1&&<>
      <div className="flow-upload-layout"><section className="flow-upload-paper"><div className="review-section"><h2>{running?'Terra is connecting the evidence':canReview(run)?'Your documents are ready to review':'Start with your documents'}</h2>
      {!locked&&<label className="flow-file-picker">Choose documents<input type="file" multiple disabled={inputLocked} onChange={e=>{const selected=Array.from(e.target.files??[]);setFiles(current=>[...current,...selected]);e.target.value='';}}/><small>PDF, supported images, Word DOCX, Excel XLSX/XLSM and UTF-8 text/CSV.</small></label>}
      {files.map((file,index)=><div className="flow-upload-file" key={`${file.name}-${index}`}><div><strong>{file.name}</strong><small>Selected · not uploaded yet</small></div><button disabled={disabled} onClick={()=>setFiles(current=>current.filter((_,i)=>i!==index))}>Remove</button></div>)}
      {batch?.submissions.map(source=>{const result=run?.files.find(f=>f.submission_id===source.id);const resolution=source.resolution;const status=resolution==='SKIPPED'?'Skipped':resolution==='MANUAL'?'Manual replacement':result?.error?'Needs attention':result?.status==='SUCCEEDED'?result.reconciliation?.status==='SUCCEEDED'?'Extraction and comparison complete':'Extraction saved · comparing project records':readable(result?.processing_stage??result?.status??'uploaded');return <div className="flow-upload-file" key={source.id}><div><strong>{source.source.display_filename}</strong><small role="status">{status}</small></div><a href={api.source(batch.id,source.id)} target="_blank" rel="noreferrer">View source</a></div>;})}


      {run&&batch&&comparison&&!locked&&<FileRecovery batch={batch} comparison={comparison} run={run} disabled={disabled||reviewEditing||manual||!comparison.input_manifest_current||comparison.database_context_requires_refresh} onAction={(label,task)=>action(label,async()=>{await task();await load(id);})} onManual={(submissionId,runId,label)=>{setManualReplacement({submissionId,runId,label});setManual(true);}}/>}
      {comparison&&batch&&<details className="flow-analysis-detail"><summary>Inspect saved results and processing details</summary><AnalysisPreview batch={batch} comparison={comparison} run={run}/>{comparison.runs.length>1&&<label>Analysis to review<select value={run?.id??''} disabled={disabled} onChange={e=>setSelectedRun(e.target.value)}>{comparison.runs.map(r=><option key={r.id} value={r.id}>{modelNames[r.model_slot]} · {readable(r.status)}</option>)}</select></label>}</details>}
      {batch?.context.refresh_required&&<p className="intake-error">Context was restored or changed. Analyse against current records, then explicitly update review. Saved edits remain.</p>}
            {!locked&&<div className="flow-extra-actions">{batch&&<details><summary>File options</summary><div className="workspace-actions"><button disabled={disabled||!files.length} onClick={()=>void upload()}>Save selected files without analysing</button>{comparison&&<><label className="intake-check"><input type="checkbox" disabled={disabled} checked={reanalyse} onChange={e=>setReanalyse(e.target.checked)}/>Run again instead of reusing saved extraction</label><button disabled={disabled} onClick={()=>void analyse()}>Analyse added files / run again</button></>}<button disabled={disabled} onClick={()=>void action('Checking identical uploads',async()=>{const result=await api.duplicates(batch.id);setDuplicates(result.matches);setNotice(result.matches.length?'Earlier identical uploads found.':'No identical files found in other current batches.');})}>Find earlier uploads</button>{duplicates.map(match=><p key={`${match.batch_id}:${match.submission_id}`}>{match.source_filename} · {match.state.toLowerCase()}<button disabled={disabled} onClick={()=>open(match.batch_id)}>Open earlier batch</button></p>)}</div></details>}</div>}</div><footer className="flow-upload-footer"><small>{batch?`${batch.submissions.length} saved file${batch.submissions.length===1?'':'s'}`:files.length?`${files.length} selected file${files.length===1?'':'s'}`:''}</small><div>{canReview(run)&&comparison?.input_manifest_current&&!comparison.database_context_requires_refresh&&!files.length&&notes===batch?.context.operator_notes?<button className="review-primary" disabled={disabled||reviewEditing||manual} onClick={()=>review?.review.prepared&&review.review.run_id===run?.id?setPhase(2):void startReview()}>{review?'Continue working review':'Review proposed changes'}</button>:<button className="review-primary" disabled={inputLocked||!providers?.enabled||!primary||!files.length&&!batch?.submissions.length} onClick={()=>void analyse()}>{running?'Analysing…':'Analyse documents'}</button>}</div></footer></section>
      <aside className="flow-context-paper"><div className="review-section"><h3>Project context</h3><label>Associate with<select disabled={!!batch||disabled} value={selectedProject} onChange={e=>setSelectedProject(e.target.value)}><option value="">Let Terra identify projects</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>Additional context <small>Optional</small><textarea rows={4} disabled={inputLocked} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Anything Terra should know about these files?"/></label></div><div className="review-section"><details><summary>Analysis settings</summary><small>{primary?`Using ${modelNames[primary]}.`:'Choose your primary model in the sandbox before analysing.'}</small>{providers&&!providers.enabled&&<p>Analysis is disabled in local configuration. Saved evidence and reviews remain available.</p>}</details></div></aside></div>

    </>}
    {(phase===2||manual)&&batch&&(review?.review.prepared||locked||manual?<PreparedReview onPublication={()=>setPhase(3)} onEditingChange={setReviewEditing} batch={batch} view={review} projects={projects} catalogue={catalogue} disabled={disabled} manual={manual} manualReplacement={manualReplacement} onManualClose={()=>{setManual(false);setManualReplacement(null);}} onManualOpen={()=>setManual(true)} onAction={(label,fn)=>action(label,async()=>{await fn();setManual(false);setManualReplacement(null);await load(id);})}/>:<><div className="review-notice"><h3>Saved review preserved</h3><p>This review uses the previous controls. Upgrade explicitly to prepare recommendations without discarding your edits.</p><button disabled={disabled||!run||!canReview(run)} onClick={()=>void startReview()}>Prepare this working review</button></div><DocumentReview onEditingChange={setReviewEditing} batch={batch} analysis={batch.comparisons.flatMap(c=>c.runs).find(r=>r.id===review?.review.run_id)} view={review} projects={projects} catalogue={catalogue} disabled={disabled} manual={manual} onManualClose={()=>setManual(false)} onManualOpen={()=>setManual(true)} onAction={(label,fn)=>action(label,async()=>{await fn();await load(id);})}/></>)}
    {phase===3&&batch?.review&&<Publication fileApprovals={review?.approvals} disabled={!!busy||reviewEditing||manual} batch={batch} onChanged={refresh} onBusyChange={setPublicationBusy} onMatching={onMatching} onReview={()=>setPhase(2)}/>}
    <details className="flow-history"><summary>Earlier analyses</summary><details><summary>Open by reference</summary><form onSubmit={e=>{e.preventDefault();if(openId.trim())open(openId);}}><label>Batch ID<input value={openId} onChange={e=>setOpenId(e.target.value)} placeholder="BAT-…"/></label><button disabled={!openId.trim()||disabled}>Open batch</button></form></details><HistoricalAnalyses/></details>
    {batch&&<TechnicalDetails values={{'Batch ID':batch.id,Revision:batch.revision,State:batch.state}}/>}
  </div>;
}
