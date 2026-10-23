import { useEffect, useState } from 'react';
import { api, modelNames } from './api';
import type { AnalysisRun, Batch, Comparison, DraftRecord, EntityRef, Project, Providers } from './api';

export function readable(value: string): string {
  return value.toLowerCase().split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
export function Status({ value }: { value: string }) {
  const text: Record<string, string> = { PENDING: 'Queued', RUNNING: 'Analysing', SUCCEEDED: 'Complete', PARTIAL: 'Needs attention', FAILED: 'Failed', INTERRUPTED: 'Interrupted' };
  return <span className={`status status-${value.toLowerCase()}`}><span aria-hidden="true" className="status-dot" />{text[value] ?? readable(value)}</span>;
}
function NoteList({ title, values }: { title: string; values: string[] }) {
  if (!values.length) return null;
  return <section className="notes-section"><h4>{title}</h4><ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul></section>;
}

interface Props {
  batch: Batch;
  comparison: Comparison;
  providers: Providers | null;
  projects: Project[];
  busy: string;
  notesDirty: boolean;
  onSelectPrimary: (run: AnalysisRun) => void;
  onRetry: (run: AnalysisRun) => void;
}
export default function Results({ batch, comparison, providers, projects, busy, notesDirty, onSelectPrimary, onRetry }: Props) {
  const [modelId, setModelId] = useState('');
  const [fileId, setFileId] = useState('');
  const run = comparison.runs.find(run => run.id === modelId) ?? comparison.runs[0];
  const file = run?.files.find(file => file.submission_id === fileId) ?? run?.files[0];
  const submission = batch.submissions.find(submission => submission.id === file?.submission_id);
  useEffect(() => { setModelId(''); setFileId(''); }, [comparison.id]);
  if (!run) return <p className="empty-copy">No model runs were returned for this comparison.</p>;
  const current = comparison.input_manifest_current && !comparison.database_context_requires_refresh;
  const isPrimary = providers?.preference.primary_model_slot === run.model_slot;
  function entityName(ref: EntityRef | null, kind: 'PROJECT' | 'MATERIAL'): string {
    if (!ref) return kind === 'PROJECT' ? 'Project not identified' : 'Material not mapped';
    const proposal = run.proposals.find(proposal => proposal.id === ref.id);
    if (proposal) return String(proposal.attributes.name ?? proposal.attributes.canonical_name ?? ref.id);
    if (kind === 'PROJECT') return projects.find(project => project.id === ref.id)?.name ?? ref.id;
    for (const observation of run.observations) {
      const material = observation.result.material as Record<string, unknown> | undefined;
      if (material?.id === ref.id) return String(material.canonical_name ?? ref.id);
      const collections = observation.result.collections as { materials?: { id: string; canonical_name: string }[] } | undefined;
      const match = collections?.materials?.find(material => material.id === ref.id);
      if (match) return match.canonical_name;
    }
    return ref.id;
  }
  const groups = new Map<string, DraftRecord[]>();
  for (const record of file?.draft?.records ?? []) {
    const key = entityName(record.project_ref, 'PROJECT');
    groups.set(key, [...(groups.get(key) ?? []), record]);
  }
  const successful = run.files.filter(file => file.status === 'SUCCEEDED').length;
  const reconciling = run.files.some(file => ['RUNNING', 'PENDING'].includes(file.reconciliation?.status ?? ''));
  const canSelect = run.status === 'SUCCEEDED' && !run.coverage_verification_required && current && !notesDirty && !busy;
  const usage = run.usage.reduce((total, usage) => ({
    input: total.input + usage.input_tokens, output: total.output + usage.output_tokens,
    cost: total.cost + Number(usage.estimated_cost_myr), latency: total.latency + usage.latency_ms,
  }), { input: 0, output: 0, cost: 0, latency: 0 });
  const historicalGeminiPricing = run.model_slot.startsWith('gemini') && run.usage.some(item => !item.billing_mode || item.billing_mode === 'LEGACY_PAID_RATE_REFERENCE');
  return <>
    <div className="model-tabs" role="tablist" aria-label="Model outputs">
      {comparison.runs.map((item, index) => <button key={item.id} id={`tab-${item.id}`} role="tab" aria-selected={item.id === run.id}
        aria-controls="model-output" tabIndex={item.id === run.id ? 0 : -1} onClick={() => setModelId(item.id)}
        onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? comparison.runs.length - 1
            : (index + (event.key === 'ArrowRight' ? 1 : -1) + comparison.runs.length) % comparison.runs.length;
          setModelId(comparison.runs[next].id);
          document.getElementById(`tab-${comparison.runs[next].id}`)?.focus();
        }}><span className="model-name">{modelNames[item.model_slot]}</span><Status value={item.status} /></button>)}
    </div>
    <div id="model-output" role="tabpanel" aria-labelledby={`tab-${run.id}`}>
      <div className="run-heading"><div><h3>{modelNames[run.model_slot]}</h3><p className="muted">{successful} of {run.files.length} files extracted{run.status === 'RUNNING' && reconciling ? ' · Comparing with project records' : run.status === 'RUNNING' && successful === run.files.length ? ' · Checking the batch' : ''}</p></div>
        <button className={isPrimary ? 'button secondary' : 'button primary'} disabled={!canSelect || isPrimary} onClick={() => onSelectPrimary(run)}>{isPrimary ? 'Current primary model' : 'Use as primary model'}</button>
      </div>
      {!current && <p className="notice warning">This output belongs to earlier input or restored context. Run analysis on the current files before choosing a primary model.</p>}
      {run.coverage_verification_required && <p className="notice warning">This saved PDF result was not checked for full document coverage. Select “Run again instead of reusing results” and analyse again. It cannot be chosen as primary yet.</p>}
      {run.status !== 'SUCCEEDED' && <p className="muted selection-hint">Primary selection becomes available when this model finishes every file and its batch check.</p>}
      <div className="file-switcher" aria-label="Files in this model run">{run.files.map(item => <button key={item.submission_id} className={item.submission_id === file?.submission_id ? 'file-switch active' : 'file-switch'}
        aria-pressed={item.submission_id === file?.submission_id} onClick={() => setFileId(item.submission_id)}><span className={`file-state state-${item.status.toLowerCase()}`} aria-hidden="true" />
        {batch.submissions.find(submission => submission.id === item.submission_id)?.source.display_filename ?? item.submission_id}</button>)}</div>
      {file && <section className="file-output" aria-label="Selected file output">
        <div className="file-output-heading"><h4>{submission?.source.display_filename ?? 'File result'}</h4><a className="text-link" href={api.source(batch.id, file.submission_id)} target="_blank" rel="noreferrer">View source</a></div>
        {file.preparation && <p className="field-hint">{file.preparation.all_pages_included === false ? `Preparing pages: ${file.preparation.pages_prepared ?? 0} of ${file.preparation.page_count}` : <>{file.preparation.strategy === 'NATIVE_PDF_WITH_TEXT_COVERAGE_AUDIT' ? 'Original PDF sent to Gemini' : 'Document prepared automatically'} · {file.preparation.page_count} page{file.preparation.page_count === 1 ? '' : 's'}{file.preparation.strategy === 'NATIVE_PDF_WITH_TEXT_COVERAGE_AUDIT' ? '' : ' included as images'} · text on {file.preparation.pages_with_text} page{file.preparation.pages_with_text === 1 ? '' : 's'}.</>}
          {file.preparation.pages.some(page => page.resized_to_limit) ? ' Large pages were resized; verify small print against the original.' : ''}</p>}
        {file.preparation?.coverage_check && <p className="field-hint">Coverage checked: {file.preparation.coverage_check.page_count} pages · {file.preparation.coverage_check.numbered_source_items} numbered source items accounted for. Human review is still required.</p>}
        {file.classification && <details className="technical-details"><summary>{(file.page_groups?.length ?? 0) > 1 ? 'First page-group classification' : 'Document classification'}: {file.classification.result ? readable(file.classification.result.primary_family) : readable(file.classification.status)}</summary>
          {file.classification.result && <p>{file.classification.result.basis}</p>}
          <p>Guidance: {file.classification.selected_modules.join(', ') || 'Not selected yet'}</p>
          <NoteList title="Classification notes" values={file.classification.warnings} />
          {file.classification.error && <p>{file.classification.error.message}</p>}
          <p className="muted">Classification is provisional routing information. It does not approve this document.</p>
        </details>}
        {file.status === 'PENDING' || file.status === 'RUNNING' ? <div className="processing" role="status"><div className="processing-line" /><strong>{file.status === 'PENDING' ? 'Waiting for this model' : readable(file.processing_stage ?? 'Reading the document')}</strong><p>{file.processing_stage === 'CLASSIFYING' ? 'Identifying the document family without tools before extraction.' : 'The model can request Terra context as it works. Results will appear here automatically.'}</p></div> : null}
        {!!file.page_groups?.length && <section className="page-group-progress" aria-label="Document page groups"><p role="status" aria-live="polite">{file.page_groups.filter(group => group.status === 'SUCCEEDED').length} of {file.page_groups.filter(group => group.status !== 'SPLIT').length} page groups saved. {file.draft ? 'Complete-file results are below.' : 'Partial results stay provisional until the whole file finishes.'}</p>
          {file.page_groups.filter(group => group.status !== 'SPLIT').map(group => <details key={group.id}><summary>{group.page_numbers.length === 1 ? `Page ${group.page_numbers[0]}` : `Pages ${group.page_numbers[0]}–${group.page_numbers[group.page_numbers.length - 1]}`} · {({ SUCCEEDED: 'Saved', RUNNING: 'Reading', PENDING: 'Queued', FAILED: 'Needs attention' } as Record<string, string>)[group.status] ?? readable(group.status)}{group.draft ? ` · ${group.draft.records.length} material candidate${group.draft.records.length === 1 ? '' : 's'}` : ''}</summary>
            {group.error && <p className="row-issue">{group.error.message} Completed groups remain saved for retry.</p>}
            {group.classification?.result && <p className="cell-secondary">Document family: {readable(group.classification.result.primary_family)}</p>}
            {group.draft && <><p>{group.draft.summary}</p>{group.draft.project_info?.map((info, i) => <p key={i}>Project: {info.name ?? 'Unresolved'} · {info.location ?? 'Location unknown'}</p>)}<ul>{group.draft.records.map((row, i) => <li key={i}>{row.material_name ?? row.raw_description}{row.evidence_basis === 'INFERRED' ? ' · AI-inferred' : ''} · {row.quantity ?? 'Material quantity unknown'} {row.unit ?? ''}{row.quantity_basis === 'SOURCE_WORK' ? ` · source work: ${row.raw_quantity ?? 'unknown'} ${row.raw_unit ?? ''}` : ''}</li>)}</ul></>}
            {!!group.response_history?.length && <details><summary>Responses for this group</summary>{group.response_history.map((response, index) => <details key={index}><summary>{readable(response.stage)}</summary><pre>{response.text}</pre></details>)}</details>}
          </details>)}</section>}
        {file.error && <div className="notice error"><strong>{readable(file.error.code)}</strong><p>{file.error.message}</p>
          {file.error.details && Object.keys(file.error.details).length > 0 && <details><summary>Failure details</summary><pre>{JSON.stringify(file.error.details, null, 2)}</pre></details>}
          {!!file.error.validation_errors?.length && <details><summary>Validation details</summary><ul>{file.error.validation_errors.map((issue, index) => <li key={index}>{issue.location.join('.')} · {issue.message}</li>)}</ul></details>}</div>}
        {file.draft && <><div className="interpretation"><span className="document-kind">{readable(file.draft.document_type)}</span><p>{file.draft.summary}</p>
          {file.draft.project_refs?.length > 0 && <p className="muted">Projects: {file.draft.project_refs.map(ref => entityName(ref, 'PROJECT')).join(', ')}</p>}</div>
          {file.draft.project_info?.length ? <section className="extracted-projects"><h4>Project information</h4>{file.draft.project_info.map((info, index) => <div className="project-information" key={index}>
            <h5>{info.name ?? 'Project identity unresolved'}</h5><p className="cell-secondary">{info.project_ref ? `${info.project_ref.kind === 'EXISTING' ? 'Existing project' : 'New project proposal'} · ${entityName(info.project_ref, 'PROJECT')}` : 'Association needs confirmation'}</p>
            <dl className="run-details">{([['Reference', info.reference], ['Location', info.location], ['Organisation', info.managing_organisation], ['Start date', info.start_date], ['End date', info.end_date]] as const).filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            <p>{info.association_explanation}</p>{!!info.inferred_fields.length && <p className="row-note">AI-inferred fields: {info.inferred_fields.map(readable).join(', ')}</p>}
            {[...info.assumptions, ...info.issues].map((note, n) => <p className="row-note" key={n}>{note}</p>)}
            {file.reconciliation?.result?.projects.filter(item => item.project_info_index === index).map((item, n) => <p className="project-comparison" key={n}>Compared with project records: {item.explanation}{item.issues.length ? ` ${item.issues.join(' ')}` : ''}</p>)}
          </div>)}</section> : file.draft.extraction_version === 'MATERIAL_V2' ? <p className="empty-copy">No project details could be identified from this document.</p> : null}
          {file.reconciliation && <div className="reconciliation-progress" role="status" aria-live="polite"><strong>Extraction saved.</strong> {file.reconciliation.status === 'RUNNING' || file.reconciliation.status === 'PENDING' ? 'Comparing with current project records. You can inspect the extracted information below.' : file.reconciliation.status === 'FAILED' ? 'Project comparison needs attention. Your extracted information is retained.' : 'Project comparison complete. All suggestions need human review.'}</div>}
          {file.reconciliation?.error && <div className="notice error"><strong>Project comparison failed</strong><p>{file.reconciliation.error.message}</p><p>Use “Retry unfinished work” below to retry comparison without extracting this file again.</p></div>}
          <NoteList title="Assumptions to verify" values={file.draft.assumptions} /><NoteList title="Items needing attention" values={file.draft.issues} />
          <h4 className="material-heading">Material information</h4>
          {groups.size ? <><p className="table-hint">Scroll sideways to see all fields.</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Scrollable material records"><table className="records-table"><caption className="sr-only">Proposed material records, grouped by project. All require human review.</caption>
            <thead><tr><th scope="col">Material & specifications</th><th scope="col">Material quantity</th><th scope="col">Meaning & timing</th><th scope="col">Assumptions & project comparison</th></tr></thead>
            {[...groups.entries()].map(([project, records]) => <tbody key={project}><tr className="project-row"><th colSpan={4} scope="rowgroup">{project}</th></tr>{records.map((record, index) => <tr key={index}>
              <td><strong>{record.material_name ?? record.raw_description}</strong>{record.evidence_basis === 'INFERRED' && <p className="inferred-label">AI-inferred</p>}{record.inference_explanation && <p className="row-note">{record.inference_explanation}</p>}{!!record.inferred_fields?.length && <p className="cell-secondary">Inferred: {record.inferred_fields.map(readable).join(', ')}</p>}{record.material_name && record.material_name !== record.raw_description && <p className="cell-secondary">Source description: {record.raw_description}</p>}<p className="cell-secondary">{entityName(record.material_ref, 'MATERIAL')}</p>{Object.entries(record.specifications ?? {}).map(([key, value]) => <p className="specification" key={key}>{readable(key)}: {value}</p>)}{record.source_locator && <p className="cell-secondary">{record.source_locator}</p>}{(record.source_page || record.source_item_ref) && <p className="cell-secondary">{[record.source_page && `Source page ${[record.source_page, ...(record.additional_source_pages ?? [])].join(", ")}`, record.source_item_ref && `Item ${record.source_item_ref}`].filter(Boolean).join(' · ')}</p>}</td>
              <td className="quantity-cell"><strong>{record.quantity ?? 'Unknown'}</strong> {record.unit ?? ''}{(record.raw_quantity || record.raw_unit) && <p className="cell-secondary">{record.quantity_basis === 'SOURCE_WORK' ? 'Source work quantity, not this material' : 'Source'}: {[record.raw_quantity, record.raw_unit].filter(Boolean).join(' ')}</p>}</td>
              <td><span>{record.record_kind === 'CONFIRMED_SURPLUS' ? 'Reported confirmed surplus' : readable(record.record_kind)}</span>{([['Effective', record.effective_date], ['Available from', record.available_from], ['Available until', record.available_until], ['Needed from', record.needed_from], ['Required by', record.required_by]] as const).filter(([, value]) => value).map(([label, value]) => <p className="cell-secondary" key={label}>{label}: {value}</p>)}</td>
              <td>{file.reconciliation?.result?.materials.filter(item => item.record_index === file.draft!.records.indexOf(record)).map(item => <div key={item.record_index} className="material-comparison"><strong>{readable(item.relationship)}</strong><p>{item.explanation}</p><p className="cell-secondary">Suggested treatment: {readable(item.suggested_treatment)} · requires confirmation</p>{item.existing_records.map(ref => <p className="cell-secondary" key={`${ref.collection}-${ref.record_id}`}>Related {readable(ref.collection)}: {ref.record_id}</p>)}{[...item.assumptions, ...item.issues].map((note, n) => <p className="row-note" key={n}>{note}</p>)}</div>)}{record.assumptions.map((value, index) => <p className="row-note" key={`a${index}`}>{value}</p>)}{record.issues.map((value, index) => <p className="row-issue" key={`i${index}`}>{value}</p>)}</td>
            </tr>)}</tbody>)}
          </table></div></> : <p className="empty-copy">No material rows were proposed for this file.</p>}
          <p className="draft-label">AI interpretation · awaiting human review</p></>}
        {file.reconciliation?.result && <section className="cross-check"><h4>Project comparison</h4><p>{file.reconciliation.result.summary}</p><NoteList title="Comparison notes" values={file.reconciliation.result.issues} /></section>}
        {file.unvalidated_output && <details className="technical-details"><summary>Unvalidated model response</summary><pre>{file.unvalidated_output}</pre></details>}
        {!!file.recoveries?.length && <details className="technical-details"><summary>Formatting recovery & targeted corrections ({file.recoveries.length})</summary><pre>{JSON.stringify(file.recoveries, null, 2)}</pre></details>}
        {!!file.response_history?.length && <details className="technical-details"><summary>Original responses by stage</summary>{file.response_history.map((item, index) => <details key={index}><summary>{readable(item.stage)} · response {index + 1}</summary><pre>{item.text}</pre></details>)}</details>}
      </section>}
      {!!run.proposals.length && <details className="proposals-section"><summary>Proposed catalogue entries</summary><p className="muted">These exist only in this model’s draft.</p><div className="proposal-list">{run.proposals.map(proposal => <div key={proposal.id} className="proposal-row"><div><strong>{String(proposal.attributes.name ?? proposal.attributes.canonical_name ?? proposal.id)}</strong><p className="cell-secondary">{readable(proposal.kind)} proposal</p></div>
        <dl>{Object.entries(proposal.attributes).filter(([key, value]) => value != null && !['name', 'canonical_name'].includes(key)).map(([key, value]) => <div key={key}><dt>{readable(key)}</dt><dd>{typeof value === 'object' ? Object.entries(value as Record<string, unknown>).map(([key, value]) => `${readable(key)}: ${String(value)}`).join(', ') : String(value)}</dd></div>)}</dl></div>)}</div></details>}
      {run.cross_check && <section className="cross-check"><h4>Across the batch</h4><p>{run.cross_check.summary}</p>{run.cross_check.findings.map((finding, index) => <div className="finding" key={index}><strong>{readable(finding.kind)}</strong><p>{finding.explanation}</p><p className="cell-secondary">{finding.submission_ids.map(id => batch.submissions.find(s => s.id === id)?.source.display_filename ?? id).join(', ')}</p></div>)}</section>}
      {run.cross_check_error && <p className="notice error">Batch check: {run.cross_check_error.message}</p>}
      {['FAILED', 'PARTIAL', 'INTERRUPTED'].includes(run.status) && current && <button className="button secondary" disabled={!!busy || notesDirty} onClick={() => onRetry(run)}>Retry unfinished work for this model</button>}
      <details className="technical-details"><summary>Run details & Terra lookups</summary><dl className="run-details"><div><dt>Model</dt><dd>{run.model_id}</dd></div><div><dt>Run</dt><dd>{run.id}</dd></div><div><dt>File attempt prompt</dt><dd>{file?.prompt_version ?? comparison.prompt_version}</dd></div><div><dt>Input / output tokens</dt><dd>{usage.input.toLocaleString()} / {usage.output.toLocaleString()}</dd></div><div><dt>{historicalGeminiPricing ? 'Includes historical paid-rate estimates' : 'Usage estimate, not billing'}</dt><dd>RM{usage.cost.toFixed(4)} across {run.usage.length} calls</dd></div><div><dt>Provider call time</dt><dd>{(usage.latency / 1000).toFixed(1)} seconds total</dd></div></dl>
        {run.observations.length ? <ol className="lookup-list">{run.observations.map((observation, index) => <li key={index}><details><summary>{readable(observation.tool)}</summary><pre>{JSON.stringify({ arguments: observation.arguments, result: observation.result }, null, 2)}</pre></details></li>)}</ol> : <p className="muted">No Terra tool calls recorded.</p>}</details>
    </div>
  </>;
}
