import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, modelNames } from './api';
import type { AnalysisRun, Batch, Comparison, Project, Providers } from './api';
import Results from './Results';
import Review from './Review';
import Publication from './Publication';

function Icon({ name }: { name: 'upload' | 'file' | 'close' | 'arrow' }) {
  const paths = {
    upload: <path d="M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4" />,
    file: <path d="M14 3H6v18h12V7l-4-4Zm0 0v5h4M9 12h6m-6 4h6" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  };
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function size(bytes: number): string { return bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`; }
function storedBatch(): string {
  const hash = new URLSearchParams(location.hash.slice(1)).get('batch');
  if (hash) return hash;
  try { return localStorage.getItem('terra.sandbox.batch') ?? ''; } catch { return ''; }
}
function recentBatches(): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem('terra.sandbox.recent') ?? '[]'); return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []; } catch { return []; }
}

export default function App() {
  const [batchId, setBatchId] = useState(storedBatch);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [comparisonId, setComparisonId] = useState('');
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [notes, setNotes] = useState('');
  const [openId, setOpenId] = useState('');
  const [recent, setRecent] = useState(recentBatches);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [reanalyse, setReanalyse] = useState(false);
  const [manualFocus, setManualFocus] = useState(false);
  const generation = useRef(0);
  const batchRevision = useRef(0);
  const selectedComparison = useRef('');
  const notesDirty = notes !== (batch?.context.operator_notes ?? '');
  const running = comparison?.runs.some(run => ['RUNNING', 'PENDING'].includes(run.status)) ?? false;
  const locked = batch?.state === 'PUBLISHED';
  const primary = providers?.preference.primary_model_slot;
  useEffect(() => { if (manualFocus && batch) { document.getElementById('review')?.scrollIntoView({ behavior: 'smooth' }); setManualFocus(false); } }, [manualFocus, batch]);

  const remember = useCallback((id: string) => {
    const values = [id, ...recentBatches().filter(value => value !== id)].slice(0, 12);
    setRecent(values);
    try { localStorage.setItem('terra.sandbox.batch', id); localStorage.setItem('terra.sandbox.recent', JSON.stringify(values)); } catch { /* Server persistence still works. */ }
    history.replaceState(null, '', `#batch=${encodeURIComponent(id)}`);
  }, []);
  function applyBatch(value: Batch) {
    if (value.revision >= batchRevision.current) { batchRevision.current = value.revision; setBatch(value); }
  }
  const refresh = useCallback(async (id: string, restoreNotes = false) => {
    const ticket = generation.current;
    const [value, status] = await Promise.all([api.batch(id), api.providers()]);
    if (ticket !== generation.current) return;
    if (value.revision >= batchRevision.current) { batchRevision.current = value.revision; setBatch(value); }
    setProviders(current => current && current.preference.revision > status.preference.revision
      ? { ...status, preference: current.preference } : status);
    if (restoreNotes) { setNotes(value.context.operator_notes); setSelectedProject(value.selected_project_id ?? ''); }
    const comparisonId = selectedComparison.current || value.comparisons.at(-1)?.id;
    if (comparisonId) {
      const detail = await api.comparison(id, comparisonId);
      if (ticket !== generation.current || (selectedComparison.current && selectedComparison.current !== comparisonId)) return;
      selectedComparison.current = comparisonId;
      setComparisonId(comparisonId);
      setComparison(detail);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([api.providers(), api.projects()]).then(([status, projects]) => {
      if (alive) { setProviders(status); setProjects(projects); }
    }).catch(reason => { if (alive) setError(reason instanceof ApiError ? reason : new ApiError('REQUEST_FAILED', 'Cannot load Terra. Start the backend and seeded emulator, then refresh.')); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!batchId) return;
    const ticket = ++generation.current;
    batchRevision.current = 0;
    setLoading(true);
    refresh(batchId, true).then(() => { if (ticket === generation.current) { remember(batchId); setError(null); } })
      .catch(reason => { if (ticket === generation.current) setError(reason); })
      .finally(() => { if (ticket === generation.current) setLoading(false); });
    return () => { generation.current++; };
  }, [batchId, refresh, remember]);
  useEffect(() => {
    if (!batchId || !running) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { await refresh(batchId); }
      catch (reason) { if (!disposed) setError(reason as ApiError); }
      if (!disposed) timer = setTimeout(poll, 2500);
    }
    timer = setTimeout(poll, 1500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [batchId, running, refresh]);

  async function action(label: string, task: () => Promise<void>) {
    setBusy(label); setError(null); setNotice('');
    try { await task(); }
    catch (reason) { setError(reason instanceof ApiError ? reason : new ApiError('REQUEST_FAILED', 'The action could not finish. Refresh before trying again.')); }
    finally { setBusy(''); }
  }
  function openBatch(id: string) {
    if (!id.trim()) return;
    selectedComparison.current = ''; setComparisonId(''); setComparison(null); setBatch(null); setFiles([]); setError(null); setNotice('');
    if (id.trim() === batchId) void action('Opening batch', () => refresh(batchId, true));
    else setBatchId(id.trim());
  }
  function newBatch() {
    generation.current++; selectedComparison.current = ''; batchRevision.current = 0;
    setBatchId(''); setBatch(null); setComparisonId(''); setComparison(null); setFiles([]); setNotes(''); setSelectedProject(''); setError(null); setNotice('');
    try { localStorage.removeItem('terra.sandbox.batch'); } catch { /* Server drafts are retained. */ }
    history.replaceState(null, '', location.pathname + location.search);
  }
  async function upload() {
    await action('Uploading files', async () => {
      let current = batch ? await api.batch(batch.id) : await api.create(selectedProject);
      const result = await api.upload(current.id, current.revision, files);
      current = result.batch;
      if (notes !== current.context.operator_notes) current = await api.notes(current, notes);
      setFiles([]); applyBatch(current); remember(current.id);
      if (batchId !== current.id) setBatchId(current.id);
      else await refresh(current.id);
      const duplicates = result.files.filter(file => file.duplicate_in_batch).length;
      setNotice(`${result.files.length - duplicates} file${result.files.length - duplicates === 1 ? '' : 's'} added.${duplicates ? ` ${duplicates} identical upload${duplicates === 1 ? '' : 's'} already in this batch.` : ''}`);
    });
  }
  async function analyse(mode: 'DEFAULT' | 'COMPARE') {
    if (!batch) return;
    await action(mode === 'COMPARE' || !primary ? 'Starting comparison' : 'Starting analysis', async () => {
      let current = await api.batch(batch.id);
      if (notes !== current.context.operator_notes) current = await api.notes(current, notes);
      const result = await api.analyse(current, mode, reanalyse);
      selectedComparison.current = result.id; setComparisonId(result.id); setComparison(result); setReanalyse(false);
      await refresh(batch.id);
    });
  }
  async function choosePrimary(run: AnalysisRun) {
    if (!batch || !comparison || !providers) return;
    await action('Saving model choice', async () => {
      const [current, latest] = await Promise.all([api.batch(batch.id), api.providers()]);
      await api.selectPrimary(current, comparison, run, latest.preference);
      setProviders(await api.providers());
      setNotice(`${modelNames[run.model_slot]} is your primary model. Future Analyse actions will use it.`);
    });
  }

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">Skip to documents</a>
    <header className="topbar"><div className="brand"><svg width="27" height="27" viewBox="0 0 28 28" aria-hidden="true"><path d="M3 4h22v6H3zm0 9h9v11H3zm12 0h10v11H15z" fill="currentColor" /></svg><span>Terra</span><span className="sandbox-tag">Sandbox</span></div>
      <div className="budget">{providers ? <><span className="budget-dot" />RM{Number(providers.budget.reported_usage_estimate_myr).toFixed(2)} usage estimate <span className="muted">· no spending cap{providers.models.filter(model => model.slot.startsWith('gemini')).every(model => model.billing_mode === 'FREE_TIER') ? ' · Gemini free tier' : ''}</span></> : 'Connecting to Terra…'}</div>
    </header>
    <main id="workspace">
      <div className="page-heading"><div><h1>Document sandbox</h1><p>Analyse documents, review the evidence and preview quantities.</p></div><button className="button secondary" disabled={!!busy || running || locked} onClick={() => void action('Opening manual entry', async () => { const value = batch ?? await api.create(selectedProject); applyBatch(value); remember(value.id); setBatchId(value.id); setManualFocus(true); })}>Enter manually</button><button className="button secondary" onClick={newBatch} disabled={!!busy || running}>New batch</button></div>
      {error && <div className="notice error" role="alert"><strong>{error.message}</strong>{error.code === 'DRAFT_RESTORE_REQUIRED' ? <button className="button secondary" disabled={!!busy} onClick={() => void action('Restoring batch', async () => { const restored = await api.restore(batchId); setNotes(restored.context.operator_notes); await refresh(batchId, true); })}>Restore saved draft</button>
        : <button className="text-link" disabled={!!busy} onClick={() => void action('Refreshing', async () => { setProviders(await api.providers()); setProjects(await api.projects()); if (batchId) await refresh(batchId); })}>Refresh connection</button>}</div>}
      {notice && <p className="notice success" role="status">{notice}</p>}
      <div className="workspace-grid">
        <aside className="intake-panel" aria-label="Upload and batch context">
          <div className="section-heading"><h2>Your documents</h2>{batch && <span className="count">{batch.submissions.length}</span>}</div>
          <label htmlFor="project">Project context <span className="optional">optional</span></label><select id="project" value={batch?.selected_project_id ?? selectedProject} disabled={!!batch || !!busy || loading} onChange={event => setSelectedProject(event.target.value)}><option value="">Identify projects from the documents</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select><p className="field-hint">Files can mention more than one project.</p>
          <label className={`dropzone ${dragging ? 'dragging' : ''} ${busy || running ? 'unavailable' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy && !running) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); const incoming = Array.from(event.dataTransfer.files); if (!busy && !running) setFiles(current => [...current, ...incoming]); }}>
            <input className="sr-only" type="file" multiple aria-label="Choose documents" disabled={!!busy || running || locked} onChange={event => { const incoming = Array.from(event.target.files ?? []); setFiles(current => [...current, ...incoming]); event.target.value = ''; }} /><Icon name="upload" /><strong>Choose files</strong><span>or drag them here</span>
          </label>
          {!!files.length && <><ul className="file-list pending-files">{files.map((file, index) => <li key={`${file.name}-${index}`}><Icon name="file" /><div><strong>{file.name}</strong><span>{size(file.size)} · ready to upload</span></div><button className="icon-button" aria-label={`Remove ${file.name}`} disabled={!!busy} onClick={() => setFiles(current => current.filter((_, i) => index !== i))}><Icon name="close" /></button></li>)}</ul><button className="button secondary full-width" disabled={!!busy || running || locked} onClick={() => void upload()}>{busy === 'Uploading files' ? 'Uploading…' : `Upload ${files.length} file${files.length === 1 ? '' : 's'}`}</button></>}
          {!!batch?.submissions.length && <ul className="file-list uploaded-files">{batch.submissions.map(submission => <li key={submission.id}><Icon name="file" /><div><strong>{submission.source.display_filename}</strong><span>{size(submission.source.byte_size)} · uploaded</span></div><a className="text-link source-link" href={api.source(batch.id, submission.id)} target="_blank" rel="noreferrer" aria-label={`View source ${submission.source.display_filename}`}>Source</a></li>)}</ul>}
          <details className="format-help"><summary>Which files can I try?</summary><p>Try UTF-8 text, CSV, TSV, PDFs or images. Terra automatically prepares PDF pages and available text for DeepSeek; Gemini receives the original PDF. Word/Excel readers and real layout accuracy are still pending. Every upload remains available as its original source.</p></details>
          <div className="context-input"><label htmlFor="operator-notes">Additional context <span className="optional">optional</span></label><textarea id="operator-notes" rows={3} value={notes} disabled={!!busy || running || locked} placeholder="Explain how the files relate, or add a project reference." onChange={event => setNotes(event.target.value)} />{batch && notesDirty && <button className="text-link" disabled={!!busy || running || locked} onClick={() => void action('Saving context', async () => { const current = await api.batch(batch.id); applyBatch(await api.notes(current, notes)); await refresh(batch.id); setNotice('Context saved. Analyse again to include these changes.'); })}>Save context</button>}</div>
          <div className="analysis-actions"><button className="button primary full-width" disabled={!batch?.submissions.length || !!busy || running || locked || !!files.length || !providers?.enabled} onClick={() => void analyse(primary ? 'DEFAULT' : 'COMPARE')}><span>{running ? 'Analysis in progress' : primary ? `Analyse with ${modelNames[primary]}` : 'Compare all 3 models'}</span><Icon name="arrow" /></button>
            {primary && <button className="button secondary full-width" disabled={!batch?.submissions.length || !!busy || running || locked || !!files.length || !providers?.enabled} onClick={() => void analyse('COMPARE')}>Compare all 3 models</button>}
            {batch && !!batch.comparisons.length && <label className="checkbox-label"><input type="checkbox" checked={reanalyse} disabled={!!busy || running || locked} onChange={event => setReanalyse(event.target.checked)} />Run again instead of reusing results</label>}
            <p className="field-hint">{files.length ? 'Upload your selected files before analysing.' : providers && !providers.enabled ? 'Model calls are disabled. Enable them in your local .env.' : primary ? 'Ordinary analysis uses your primary. Comparison runs all three.' : 'One action, three separate interpretations. You choose the primary.'}</p>
          </div>
          <details className="resume"><summary>Open a saved batch</summary><label htmlFor="batch-id">Batch ID</label><div className="inline-form"><input id="batch-id" value={openId} placeholder="BAT-…" onChange={event => setOpenId(event.target.value)} /><button className="button secondary" disabled={!openId.trim() || !!busy || running} onClick={() => openBatch(openId)}>Open</button></div>{!!recent.length && <ul>{recent.map(id => <li key={id}><button className="text-link batch-reference" disabled={!!busy || running || locked} onClick={() => openBatch(id)}>{id}</button></li>)}</ul>}</details>
          {batch && <p className="batch-reference muted">{batch.id}<br />Revision {batch.revision}</p>}
        </aside>
        <section className="results-panel" aria-label="Analysis results"><div className="section-heading results-heading"><h2>Model outputs</h2>{batch && batch.comparisons.length > 0 && <label className="history-select"><span className="sr-only">Saved analysis</span><select aria-label="Saved analysis" value={comparisonId} disabled={!!busy} onChange={event => {
          const id = event.target.value; selectedComparison.current = id; setComparisonId(id); setComparison(null); void action('Loading results', async () => { if (batchId) { const value = await api.comparison(batchId, id); if (selectedComparison.current === id) setComparison(value); } });
        }}>{batch.comparisons.map((item, index) => <option key={item.id} value={item.id}>Run {index + 1} · {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kuala_Lumpur' })} MYT · {item.runs.length > 1 ? 'Comparison' : 'Single model'}</option>)}</select></label>}</div>
          {comparison && batch ? <Results batch={batch} comparison={comparison} providers={providers} projects={projects} busy={busy} notesDirty={notesDirty} onSelectPrimary={run => void choosePrimary(run)} onRetry={run => void action('Retrying model', async () => { const current = await api.batch(batch.id); await api.retry(current, comparison, run); await refresh(batch.id); })} />
            : loading || busy === 'Loading results' ? <div className="result-placeholder" role="status"><div className="skeleton-line wide" /><div className="skeleton-line" /><p>Loading saved context…</p></div>
              : <div className="result-placeholder"><div className="empty-mark" aria-hidden="true"><Icon name="file" /></div><h3>Start with your documents</h3><p>Upload the files you want to analyse together, then compare the models. Their interpretations will appear here.</p><p className="muted">Read the assumptions, open the source, and decide which model you prefer.</p></div>}
        </section>
      </div>
      {batch && !running && <div id="review"><Review batch={batch} comparison={comparison} projects={projects} onChanged={() => refresh(batch.id)} /></div>}
      {batch && !!batch.review && !running && <Publication key={batch.id} batch={batch} onChanged={() => refresh(batch.id)} />}
      <footer><span>Local prototype · synthetic Terra baseline</span><span>Review first. Publish the approved batch once; matching handoff is recorded separately.</span><span className="sr-only" role="status">{busy}</span></footer>
    </main>
  </div>;
}
