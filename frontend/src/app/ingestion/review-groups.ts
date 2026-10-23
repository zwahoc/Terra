import type { ReviewRow, ReviewView } from '../../reviewApi';
const refKey = (ref: ReviewRow['current']['project_ref']) => ref ? `${ref.kind}:${ref.id}` : '';

export function materialGroups(rows: ReviewRow[]) {
  const groups = new Map<string, { id: string; name: string; rows: ReviewRow[] }>();
  for (const row of rows) {
    const value = row.current;
    // Display grouping only. All original row IDs, meanings and source items survive.
    const key = JSON.stringify([refKey(value.project_ref), refKey(value.material_ref) || value.material_name || value.raw_description,
      value.source_item_ref ?? value.material_name ?? value.raw_description]);
    const group = groups.get(key) ?? { id: key, name: value.material_name || value.raw_description, rows: [] };
    group.rows.push(row); groups.set(key, group);
  }
  return [...groups.values()];
}

export function issueSummary(view: ReviewView, submissionId: string) {
  const issues = new Map<string, Set<string>>();
  for (const blocker of view.blockers[submissionId] ?? []) {
    for (const message of blocker.messages) {
      const ids = issues.get(message) ?? new Set<string>();
      ids.add(blocker.row_id ?? blocker.project_id ?? submissionId); issues.set(message, ids);
    }
  }
  return [...issues].map(([message, ids]) => ({ message, count: ids.size }));
}
export const readable = (value: string) => value.replaceAll('_', ' ').toLowerCase();
export function canReview(run: { status: string; cross_check: unknown; cross_check_error: unknown; coverage_verification_required?: boolean; review_ready?: boolean; files: { status: string; draft: unknown; reconciliation?: { status: string } | null }[] } | undefined) {
  if (run?.review_ready !== undefined) return run.review_ready;
  return !!run && run.status === 'SUCCEEDED' && !!run.cross_check && !run.cross_check_error
    && !run.coverage_verification_required && run.files.length > 0
    && run.files.every(file => file.status === 'SUCCEEDED' && !!file.draft && file.reconciliation?.status === 'SUCCEEDED');
}

export function visibleStockScopes(scopes: ReviewView['groups'], groups: ReturnType<typeof materialGroups>) {
  return scopes.filter(scope => groups.some(group => group.rows.some(row =>
    row.current.material_ref?.id === scope.material && row.current.project_ref?.id === scope.project)));
}
