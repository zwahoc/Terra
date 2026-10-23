import type { AnalysisRun, Batch, Comparison } from '../../api';
import { reviewApi } from '../../reviewApi';
import { commandRequest } from '../../lib/action-request';

type Props = { batch: Batch; comparison: Comparison; run: AnalysisRun; disabled: boolean;
  onAction: (label: string, work: () => Promise<unknown>) => Promise<void>;
  onManual: (submissionId: string, runId: string, label: string) => void };

export default function FileRecovery({ batch, comparison, run, disabled, onAction, onManual }: Props) {
  const failed = run.files.filter(file => {
    const source = batch.submissions.find(s => s.id === file.submission_id);
    return source && (source.resolution && source.resolution !== 'ANALYSE' ||
      file.status === 'FAILED' || file.reconciliation?.status === 'FAILED' ||
      file.status === 'PENDING' && !['PENDING','RUNNING'].includes(run.status) ||
      run.status === 'INTERRUPTED' && file.status !== 'SUCCEEDED');
  });
  if (!failed.length && run.status !== 'INTERRUPTED' && !run.cross_check_error) return null;
  return <section className="intake-file-recovery" aria-label="Resolve unfinished files">
    <h3>Unfinished files</h3>
    {run.status === 'INTERRUPTED' && <p role="status">Analysis stopped when its worker ended. Saved results remain available. Retrying is an explicit action and may send new model requests.</p>}
    {run.cross_check_error && <p>The batch check needs attention: {run.cross_check_error.message}. Retry unfinished analysis after resolving the files.</p>}
    {failed.map(file => {
      const source = batch.submissions.find(s => s.id === file.submission_id)!;
      const resolution = source.resolution ?? 'ANALYSE';
      return <div className="intake-failed-file" key={source.id}><strong>{source.source.display_filename}</strong>
        <p>{resolution === 'SKIPPED' ? 'Skipped by operator. This file will contribute no records.' : resolution === 'MANUAL' ? 'Replaced with linked manual information. The manual entry needs its own review and approval.' : file.error?.message ?? file.reconciliation?.error?.message ?? 'Processing was interrupted. Completed work remains saved.'}</p>
        {resolution === 'ANALYSE' ? <div className="intake-actions">
          <button disabled={disabled} onClick={() => void onAction('Retrying this file', () => commandRequest(`/api/ingestion/batches/${batch.id}/comparisons/${comparison.id}/runs/${run.id}/retry`, {expected_revision:batch.revision,submission_ids:[source.id]}))}>Retry this file</button>
          <button disabled={disabled} onClick={() => void onAction('Skipping failed file', () => reviewApi.resolveFile(batch.id,source.id,batch.revision,'SKIPPED',run.id))}>Skip this file</button>
          <button disabled={disabled} onClick={() => onManual(source.id,run.id,source.source.display_filename)}>Replace with manual information</button>
        </div> : <><button disabled={disabled} onClick={() => void onAction('Restoring file for analysis', () => reviewApi.resolveFile(batch.id,source.id,batch.revision,'ANALYSE'))}>Restore file for analysis</button>{resolution === 'MANUAL' && <p>The manual entry will remain saved and will need review for overlap with the retried document.</p>}</>}
      </div>;
    })}
  </section>;
}
