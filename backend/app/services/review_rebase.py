"""Explicit adoption of current same-model analysis without discarding edits."""
from uuid import uuid4

from backend.app.schemas.review import ReviewState, ReviewSubmission, ReviewRow, ReviewProject, ReviewEntity
from backend.app.services.ingestion_storage import digest_json


def rebase_review(service, batch, command):
    from backend.app.services.analysis_service import ComparisonService
    from backend.app.services.review_service import require, audit, invalidate

    review = service.state(batch)
    comparison = next((c for c in batch.comparisons if c.id == command.comparison_id), None)
    require(comparison is not None and comparison.manifest == ComparisonService.manifest(batch)
            and comparison.configuration.get('context_epoch', 0) == batch.context.epoch and not batch.context.refresh_required,
            'ANALYSIS_INPUT_CHANGED', 'Analyse the current files and context before updating review.')
    run = next((r for r in comparison.runs if r.id == command.run_id), None)
    require(run is not None and service.reviewable(batch, run) and not ComparisonService._unchecked_pdf_files(batch, run),
            'ANALYSIS_INCOMPLETE', 'Resolve failures and finish the current batch check first.')
    if review.run_id:
        previous = next(r for c in batch.comparisons for r in c.runs if r.id == review.run_id)
        require((previous.model_slot, previous.model_id) == (run.model_slot, run.model_id),
                'MODEL_REVIEW_MISMATCH', 'An existing review can only be updated from its own model. Other comparisons remain isolated.')
    from backend.app.services.analysis_reuse import review_namespace
    run, id_mapping = review_namespace(batch,run,review)
    old = review.model_dump(mode='json', exclude={'audit'})
    sources = {s.id: s for s in batch.submissions}
    existing = {s.id: s for s in review.submissions}
    for proposal in run.proposals:
        entity = next((e for e in review.entities if e.proposal.id == proposal.id), None)
        if entity is None:
            review.entities.append(ReviewEntity(original=proposal.model_copy(deep=True), proposal=proposal.model_copy(deep=True)))
        elif entity.original != proposal:
            # Preserve operator attributes; changed AI evidence needs renewed confirmation.
            entity.original = proposal.model_copy(deep=True)
            entity.confirmed = False
    for file in run.files:
        source = sources[file.submission_id]
        if source.resolution != 'ANALYSE':
            if file.submission_id not in existing:
                review.submissions.append(service.resolved_submission(source))
            continue
        draft = file.draft
        sub = existing.get(file.submission_id)
        if sub is None:
            sub = ReviewSubmission(id=file.submission_id, kind='FILE', label=source.source.display_filename)
            review.submissions.append(sub)
        if sub.resolution != 'EXTRACTED':
            sub.resolution = 'EXTRACTED'
        unused_rows = list(sub.rows)
        for record in draft.records:
            matched = next((row for row in unused_rows if row.original == record), None)
            if matched is not None:
                unused_rows.remove(matched)
            else:
                row = ReviewRow(id='REV-'+uuid4().hex, original=record.model_copy(deep=True), current=record.model_copy(deep=True))
                sub.rows.append(row)
                service.clear_scopes(review, [row])
        if unused_rows:
            # Changed/removed source interpretation cannot silently erase an edited row.
            # Retain it for explicit exclusion/replacement and save the prior overlay below.
            service.clear_scopes(review, unused_rows)
            for row in unused_rows:
                row.decision, row.assumptions_confirmed = 'PENDING', False
        for info in draft.project_info:
            if not any(p.original == info for p in sub.projects):
                sub.projects.append(ReviewProject(id='RPR-'+uuid4().hex, original=info.model_copy(deep=True), current=info.model_copy(deep=True)))
        sub.notes = list(dict.fromkeys([*draft.assumptions, *draft.issues,
            *(file.reconciliation.result.issues if file.reconciliation and file.reconciliation.result else []),
            *[f.explanation for f in run.cross_check.findings if sub.id in f.submission_ids],
            *(['New extraction differs from prior rows. Prior values and operator edits are retained; resolve retained and new observations before approval.'] if unused_rows else [])]))
    if review.context_epoch != batch.context.epoch:
        invalidate(review)
        review.confirmed_stock_scopes = []
    review.context_epoch = batch.context.epoch
    review.comparison_id, review.run_id = comparison.id, run.id
    review.source_digest = digest_json(comparison.manifest)
    audit(review, 'WORKING_REVIEW_UPDATED', run.id)
    review.audit[-1]['previous_review'] = old
    review.audit[-1]['analysis_to_review_proposal_ids'] = id_mapping
