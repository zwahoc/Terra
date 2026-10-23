import { useState } from 'react';
import { api, modelNames } from '../../api';
import type { AnalysisRun, Batch, Comparison } from '../../api';
import { materialGroups, readable } from './review-groups';

export default function AnalysisPreview({batch,comparison,run,historical=false,sourceUrl}: {batch:Batch;comparison:Comparison;run:AnalysisRun | undefined;historical?:boolean;sourceUrl?:(submissionId:string)=>string}) {
 const [fileId,setFileId] = useState('');
 const file = run?.files.find(f => f.submission_id === fileId) ?? run?.files[0];
 const submission = batch.submissions.find(s => s.id === file?.submission_id);
 const partial = !file?.draft;
 const draft = file?.draft ?? file?.page_groups?.filter(g => g.status === 'SUCCEEDED').at(-1)?.draft;
 const groups = materialGroups((draft?.records ?? []).map((record,index) => ({id:String(index),original:record,current:record,decision:'PENDING',assumptions_confirmed:false,conversion:null,edited_by_operator:false,provenance:'AI_DOCUMENT'})));
 return <section className="intake-analysis" aria-label="Document analysis"><header><h2>Document analysis</h2><p role="status">{run ? `${modelNames[run.model_slot]} · ${readable(run.status)} · ${run.files.filter(f => f.status === 'SUCCEEDED').length} of ${run.files.length} files extracted` : 'Choose analysed model results below.'}</p></header>
 <div className="intake-file-tabs" aria-label="Uploaded files">{batch.submissions.map(source => <button type="button" key={source.id} aria-pressed={file?.submission_id === source.id} onClick={() => setFileId(source.id)}>{source.source.display_filename}<small>{readable(source.resolution && source.resolution !== 'ANALYSE' ? source.resolution === 'MANUAL' ? 'manual replacement' : source.resolution : run?.files.find(f => f.submission_id === source.id)?.status ?? 'saved')}</small></button>)}</div>
 {submission && <div className="intake-heading"><h3>{submission.source.display_filename}</h3><a href={sourceUrl ? sourceUrl(submission.id) : api.source(batch.id,submission.id)} target="_blank" rel="noreferrer">View whole source</a></div>}
 {file && <><p>{readable(file.processing_stage ?? file.status)}{file.preparation ? ` · ${file.preparation.pages_with_text} pages with extracted text / ${file.preparation.page_count} source pages` : ''}</p>{file.error && (!submission?.resolution || submission.resolution === 'ANALYSE') && <p className="intake-error" role="alert">{readable(file.error.code)}: {file.error.message}</p>}
 {file.reused_from_run_id && <p>Saved extraction reused. Current project context and batch relationships are checked again.</p>}
 {file.reader_metadata && <p>{file.reader_metadata.format} prepared locally. {file.reader_metadata.coverage}{!!file.reader_metadata.formulas_without_cached_values?.length && ' Some formulas have no cached value; Terra does not calculate them.'}</p>}
 {draft && <><p>{historical ? 'Historical extraction preserved from the previous workspace. Read only.' : partial ? 'Saved partial extraction, still provisional.' : 'Extraction saved. Human review is required before publication.'}</p>{draft.project_info?.map((project,index) => <div className="intake-project-preview" key={index}><h3>{project.name || 'Unidentified project'}</h3><p>{project.location || 'Location not stated'}</p><p>{project.association_explanation}</p></div>)}
 <details open={run?.status !== 'SUCCEEDED'}><summary>{groups.length} material groups extracted{partial ? ' in the latest saved page group' : ''}</summary><div className="intake-table-wrap"><table><thead><tr><th>Material</th><th>Information found</th></tr></thead><tbody>{groups.map(group => <tr key={group.id}><td>{group.name}</td><td>{group.rows.map(r => <div key={r.id}>{readable(r.current.record_kind)}: {r.current.quantity ?? 'Unknown'} {r.current.unit}</div>)}</td></tr>)}</tbody></table></div></details></>}
 {file.reconciliation && <p>Project-record comparison: {readable(file.reconciliation.status)}{file.reconciliation.error ? ` · ${file.reconciliation.error.message}` : ''}</p>}
 {file.reconciliation?.result && <details><summary>What this document means for existing project records</summary><p>{file.reconciliation.result.summary}</p>{file.reconciliation.result.issues.map((v,i) => <p key={i}>{v}</p>)}</details>}
 </>}
 {run?.cross_check_error && <p className="intake-error">Batch check: {run.cross_check_error.message}</p>}
 {run?.cross_check && <details><summary>Batch check completed</summary><p>{run.cross_check.summary}</p>{run.cross_check.findings.map((finding,index) => <p key={index}>{finding.explanation}</p>)}</details>}
 {!historical && (!comparison.input_manifest_current || comparison.database_context_requires_refresh) && <p className="intake-error">These results belong to earlier files or context. Analyse the current inputs before starting review. Existing review edits remain saved.</p>}
 </section>;
}
