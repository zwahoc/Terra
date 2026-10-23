"""Phase 4 operator review, approval and exact previews; never publication."""
from decimal import Decimal, localcontext
from pydantic import ValidationError
from backend.app.services.analysis_output import PLAIN_DECIMAL
from uuid import uuid4
from backend.app.schemas.analysis import DraftRecord, MaterialProposal, ProjectProposal, ProposedEntity
from backend.app.schemas.review import ReviewState, ReviewRow, ReviewSubmission, ReviewProject, ReviewEntity
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService, now
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.review_calculations import preview_groups, group_id
from terra.quantities import unit as canonical_unit

PROTECTED = ('raw_description', 'raw_quantity', 'raw_unit', 'raw_fields', 'source_locator', 'source_page',
             'source_item_ref', 'additional_source_pages', 'continues_from')
ACTIVE = {'RESERVED', 'IN_TRANSIT', 'RECEIVED'}


def require(condition, code, message):
    if not condition:
        raise IngestionError(code, message, 409)


def audit(review, action, target, actor='Operator'):
    review.audit.append({'action': action, 'target': target, 'at': now().isoformat(), 'actor_label': actor})


def invalidate(review):
    for submission in review.submissions:
        submission.approval_digest, submission.approved_at = None, None
        submission.summary_confirmed = False


class ReviewService:
    def __init__(self, intake=None):
        self.intake = intake if intake is not None else IntakeService()

    @staticmethod
    def state(batch):
        require(batch.review is not None, 'REVIEW_NOT_STARTED', 'Choose an analysis for review or enter data manually.')
        return batch.review

    def edit(self, batch_id, revision, action):
        def change(batch):
            review = self.state(batch)
            self.upgrade_approvals(batch)
            action(batch, review)
        self.intake._edit(batch_id, revision, change)
        return self.get(batch_id)

    def upgrade_approvals(self, batch):
        """Migrate only verifiably current older batch-wide approvals."""
        if batch.review and any(s.approval_digest for s in batch.review.submissions):
            view = self._preview(batch)
            for sub in batch.review.submissions:
                if view['approvals'][sub.id]:
                    sub.approval_digest = view['submission_digests'][sub.id]

    def select(self, batch_id, command):
        def select(batch):
            require(batch.review is None, 'REVIEW_ALREADY_STARTED', 'Existing operator edits are preserved. Continue the working review instead of replacing it.')
            comparison = next((c for c in batch.comparisons if c.id == command.comparison_id), None)
            require(comparison is not None, 'COMPARISON_NOT_FOUND', 'Select an analysis from this batch.')
            from backend.app.services.analysis_service import ComparisonService
            require(comparison.manifest == ComparisonService.manifest(batch)
                    and not batch.context.refresh_required and comparison.configuration.get('context_epoch', 0) == batch.context.epoch,
                    'ANALYSIS_INPUT_CHANGED', 'Analyse current files/context before starting review.')
            run = next((r for r in comparison.runs if r.id == command.run_id), None)
            require(run is not None and self.reviewable(batch, run),
                    'ANALYSIS_INCOMPLETE', 'Choose a complete extraction, project comparison and batch check.')
            require(not ComparisonService._unchecked_pdf_files(batch, run), 'DOCUMENT_COVERAGE_NOT_VERIFIED', 'Analyse this PDF with current coverage checks before review.')
            review = ReviewState(comparison_id=comparison.id, run_id=run.id,
                                 source_digest=digest_json(comparison.manifest), context_epoch=batch.context.epoch,
                                 entities=[ReviewEntity(original=p.model_copy(deep=True), proposal=p.model_copy(deep=True)) for p in run.proposals])
            sources = {s.id: s for s in batch.submissions}
            for file in run.files:
                if sources[file.submission_id].resolution != 'ANALYSE':
                    review.submissions.append(self.resolved_submission(sources[file.submission_id]))
                    continue
                review.submissions.append(ReviewSubmission(id=file.submission_id, kind='FILE', label=sources[file.submission_id].source.display_filename,
                    notes=[*file.draft.assumptions, *file.draft.issues, *(file.reconciliation.result.issues if file.reconciliation and file.reconciliation.result else []),
                           *[finding.explanation for finding in run.cross_check.findings if file.submission_id in finding.submission_ids]],
                    rows=[ReviewRow(id='REV-'+uuid4().hex, original=row.model_copy(deep=True), current=row.model_copy(deep=True)) for row in file.draft.records],
                    projects=[ReviewProject(id='RPR-'+uuid4().hex, original=p.model_copy(deep=True), current=p.model_copy(deep=True)) for p in file.draft.project_info]))
            batch.review = review
            audit(review, 'WORKING_ANALYSIS_SELECTED', run.id)
        self.intake._edit(batch_id, command.expected_revision, select)
        return self.get(batch_id)

    def prepare(self, batch_id, command):
        """Explicit new-review/adoption action. Never rewrite a published review."""
        batch = self.intake.get(batch_id)
        require(batch.state != 'PUBLISHED', 'BATCH_PUBLISHED', 'Published evidence is read-only.')
        if batch.review is None:
            self.select(batch_id, command)
            revision = self.intake.get(batch_id).revision
        else:
            require(batch.revision == command.expected_revision, 'STALE_REVISION', 'Reload the review before preparing it.')
            require(batch.review.run_id == command.run_id, 'MODEL_REVIEW_MISMATCH', 'Keep the current working model review.')
            revision = command.expected_revision
        def preparing(batch, review):
            from backend.app.services.review_preparation import prepare
            prepare(self, batch)
            audit(review, 'RECOMMENDATIONS_PREPARED', batch.id, 'Terra')
        self.edit(batch_id, revision, preparing)
        return self.get(batch_id)

    def manual(self, batch_id, command):
        require(bool(command.records), 'MANUAL_RECORD_REQUIRED', 'Enter at least one manual record.')
        require(not command.conversions or len(command.conversions) == len(command.records),
                'MANUAL_CONVERSIONS_INVALID', 'Conversions must correspond to the manual records.')
        def add(batch):
            if batch.review is None:
                batch.review = ReviewState(context_epoch=batch.context.epoch, prepared=command.prepared)
            review = batch.review
            self.upgrade_approvals(batch)
            submission = ReviewSubmission(id='MAN-'+uuid4().hex, kind='MANUAL', label=command.label)
            if command.replaces_submission_id:
                source = next((s for s in batch.submissions if s.id == command.replaces_submission_id), None)
                require(source is not None and source.resolution == 'ANALYSE', 'FILE_RESOLUTION_INVALID', 'Choose an unresolved failed file for manual replacement.')
                self.require_failed(batch, source.id, command.analysis_run_id)
                require(not any(s.id == source.id for s in review.submissions), 'FILE_ALREADY_REVIEWED', 'Keep the existing review; manual replacement applies to failed files only.')
                source.resolution, source.manual_submission_id = 'MANUAL', submission.id
                review.submissions.append(self.resolved_submission(source))
            for index, record in enumerate(command.records):
                self.manual_source(record)
                conversion = command.conversions[index] if command.conversions else None
                if conversion:
                    conversion = conversion.model_copy(update={'confirmed': False})
                submission.rows.append(ReviewRow(id='REV-'+uuid4().hex, current=record, conversion=conversion,
                                                provenance='OPERATOR_MANUAL', edited_by_operator=True))
            review.submissions.append(submission)
            self.clear_scopes(review, submission.rows)
            audit(review, 'MANUAL_SUBMISSION_ADDED', submission.id)
        self.intake._edit(batch_id, command.expected_revision, add)
        return self.get(batch_id)

    @staticmethod
    def reviewable(batch, run):
        active = {s.id for s in batch.submissions if s.resolution == 'ANALYSE'}
        files = {f.submission_id: f for f in run.files}
        if not active:
            return run.status not in ('RUNNING', 'PENDING', 'INTERRUPTED')
        return (run.status not in ('RUNNING', 'PENDING', 'INTERRUPTED') and run.cross_check is not None
                and run.cross_check_error is None and active <= set(files)
                and all(files[sid].status == 'SUCCEEDED' and files[sid].draft is not None
                        and files[sid].reconciliation is not None and files[sid].reconciliation.status == 'SUCCEEDED'
                        for sid in active))

    @staticmethod
    def resolved_submission(source):
        return ReviewSubmission(id=source.id, kind='FILE', label=source.source.display_filename,
            resolution='SKIPPED' if source.resolution == 'SKIPPED' else 'MANUAL_REPLACEMENT',
            notes=['Operator skipped this file; it contributes no document records.' if source.resolution == 'SKIPPED' else
                   'Operator replaced failed extraction with manual information. Manual values are not document-supported evidence.'])

    def require_failed(self, batch, submission_id, run_id):
        from backend.app.services.analysis_service import ComparisonService
        candidates = [r for c in batch.comparisons if c.manifest == ComparisonService.manifest(batch) for r in c.runs if r.id == run_id]
        require(bool(candidates), 'ANALYSIS_REQUIRED', 'Choose the current model run before resolving a failed file.')
        latest = candidates[0]
        if batch.review and batch.review.run_id:
            selected = next(r for c in batch.comparisons for r in c.runs if r.id == batch.review.run_id)
            require(latest.model_slot == selected.model_slot and latest.model_id == selected.model_id,
                    'MODEL_REVIEW_MISMATCH', 'Resolve failures from the working review model only.')
        file = next((f for f in latest.files if f.submission_id == submission_id), None)
        from backend.app.services.analysis_service import WORKER_INSTANCE_ID
        from filelock import FileLock, Timeout
        active = False
        try:
            with FileLock(str(self.intake.store.root / 'locks' / f'worker-{latest.id}.lock'), timeout=0):
                pass
        except Timeout:
            active = True
        pending = latest.status == 'PENDING' and latest.worker_instance_id == WORKER_INSTANCE_ID
        require(not active and not pending and file is not None and
                (file.status != 'SUCCEEDED' or file.reconciliation is None or file.reconciliation.status != 'SUCCEEDED'),
                'FILE_NOT_FAILED', 'This file is not an unresolved failure in the selected analysis.')
        if latest.status in ('RUNNING', 'PENDING'):
            latest.status = 'PARTIAL' if any(f.status == 'SUCCEEDED' for f in latest.files) else 'FAILED'

    def resolve_file(self, batch_id, submission_id, command):
        def change(batch):
            source = next((s for s in batch.submissions if s.id == submission_id), None)
            require(source is not None, 'SUBMISSION_NOT_FOUND', 'The file is not part of this batch.')
            if command.resolution == 'SKIPPED':
                self.require_failed(batch, source.id, command.analysis_run_id)
            else:
                require(source.resolution in ('SKIPPED', 'MANUAL'), 'FILE_RESOLUTION_INVALID', 'Only a skipped or manually replaced file can be restored for analysis.')
                if source.resolution == 'MANUAL' and batch.review:
                    manual = next((s for s in batch.review.submissions if s.id == source.manual_submission_id), None)
                    if manual:
                        self.clear_scopes(batch.review, manual.rows)
                        for row in manual.rows:
                            row.decision, row.assumptions_confirmed = 'PENDING', False
                        manual.notes.append('Document analysis was restored. These manual values are retained; resolve overlap with the new document result before approval.')
            source.resolution, source.manual_submission_id = command.resolution, None
            if batch.review is None and all(s.resolution != 'ANALYSE' for s in batch.submissions):
                batch.review = ReviewState(context_epoch=batch.context.epoch,
                    submissions=[self.resolved_submission(s) for s in batch.submissions if s.id != source.id])
            if batch.review:
                require(not any(s.id == source.id and s.rows for s in batch.review.submissions), 'FILE_ALREADY_REVIEWED', 'Existing extracted rows cannot be discarded by resolving a failure.')
                batch.review.submissions = [s for s in batch.review.submissions if s.id != source.id]
                if source.resolution != 'ANALYSE': batch.review.submissions.append(self.resolved_submission(source))
                audit(batch.review, 'FILE_'+command.resolution, source.id)
        self.intake._edit(batch_id, command.expected_revision, change)
        return self.intake.get(batch_id)

    @staticmethod
    def clear_scopes(review, rows):
        affected = {group_id(r.current.project_ref.id, r.current.material_ref.id,
                            r.conversion.to_unit if r.conversion else r.current.unit)
                    for r in rows if r.current.project_ref and r.current.material_ref}
        review.confirmed_stock_scopes = [key for key in review.confirmed_stock_scopes if key not in affected]

    def rebase(self, batch_id, command):
        from backend.app.services.review_rebase import rebase_review
        self.intake._edit(batch_id, command.expected_revision, lambda batch: rebase_review(self, batch, command))
        return self.get(batch_id)

    def refresh_manual_context(self, batch_id, command):
        def refresh(batch):
            review = self.state(batch)
            require(not any(s.resolution == 'ANALYSE' for s in batch.submissions), 'ANALYSIS_REQUIRED', 'Document extraction needs current analysis before review can be updated.')
            invalidate(review)
            review.confirmed_stock_scopes = []
            review.context_epoch = batch.context.epoch
            batch.context.refresh_required = False
            from backend.app.services.analysis_service import ComparisonService
            review.source_digest = digest_json(ComparisonService.manifest(batch))
            audit(review, 'MANUAL_CONTEXT_REFRESHED', batch.id)
        self.intake._edit(batch_id, command.expected_revision, refresh)
        return self.get(batch_id)

    @staticmethod
    def manual_source(row):
        require(not any(getattr(row, key) for key in ('source_page', 'source_locator', 'source_item_ref', 'additional_source_pages', 'continues_from')),
                'MANUAL_SOURCE_INVALID', 'Manual values have no documentary source. Leave source page/locator empty.')

    @staticmethod
    def submission(review, submission_id):
        submission = next((s for s in review.submissions if s.id == submission_id), None)
        require(submission is not None, 'SUBMISSION_NOT_FOUND', 'Review submission not found.')
        return submission

    def row(self, batch_id, submission_id, row_id, command):
        def update(batch, review):
            submission = self.submission(review, submission_id)
            row = next((r for r in submission.rows if r.id == row_id), None)
            require(row is not None, 'ROW_NOT_FOUND', 'Review row not found.')
            if row.original:
                require(all(getattr(command.current, key) == getattr(row.original, key) for key in PROTECTED),
                        'SOURCE_IMMUTABLE', 'Original document fields cannot be overwritten. Edit interpreted values instead.')
            else:
                self.manual_source(command.current)
            identity_changed = (row.current.project_ref != command.current.project_ref or row.current.material_ref != command.current.material_ref
                                or row.current.specifications != command.current.specifications or row.current.unit != command.current.unit)
            require(not identity_changed or command.conversion is None or command.conversion != row.conversion,
                    'CONVERSION_STALE', 'Changed material/unit/specification needs a newly confirmed conversion basis.')
            if row.current != command.current or row.conversion != command.conversion or row.decision != command.decision:
                self.clear_scopes(review, [row, ReviewRow(id='new', current=command.current, conversion=command.conversion)])
            row.current = command.current
            row.decision, row.assumptions_confirmed, row.conversion = command.decision, command.assumptions_confirmed, command.conversion
            row.release_confirmed = command.release_confirmed and not identity_changed
            row.edited_by_operator = row.original is None or row.current != row.original or row.conversion is not None
            if review.prepared:
                # Preparation is not an operator edit. An explicit changed review is.
                row.edited_by_operator = row.original is None or row.current.model_dump(mode='json') != row.preparation.get('snapshot', {})
                if row.current.application != 'UNDECIDED':
                    row.preparation['questions'] = []
            audit(review, 'EDITED_BY_OPERATOR' if row.edited_by_operator else 'ROW_REVIEWED', row.id)
        return self.edit(batch_id, command.expected_revision, update)

    def bulk(self, batch_id, submission_id, command):
        def update(batch, review):
            submission = self.submission(review, submission_id)
            rows = {r.id: r for r in submission.rows}
            require(set(command.row_ids) <= set(rows), 'ROW_NOT_FOUND', 'One of the selected rows is not in this submission.')
            self.clear_scopes(review, [rows[rid] for rid in command.row_ids])
            for rid in command.row_ids:
                row = rows[rid]
                row.decision, row.assumptions_confirmed = command.decision, command.assumptions_confirmed
                row.current.application, row.current.replaces_record_ids = command.application, []
                row.edited_by_operator = row.original is None or row.current != row.original
            audit(review, 'BULK_OPERATOR_REVIEW', submission_id)
        return self.edit(batch_id, command.expected_revision, update)

    def project(self, batch_id, submission_id, project_id, command):
        def update(batch, review):
            project = next((p for p in self.submission(review, submission_id).projects if p.id == project_id), None)
            require(project is not None, 'PROJECT_NOT_FOUND', 'Project review not found.')
            if project.original:
                require(project.original.source_page == command.current.source_page and project.original.source_locator == command.current.source_locator,
                        'SOURCE_IMMUTABLE', 'Project source locations are immutable.')
            require(not command.current.start_date or not command.current.end_date or command.current.start_date <= command.current.end_date,
                    'PROJECT_DATES_INVALID', 'Project end date precedes start date.')
            project.current, project.confirmed = command.current, command.confirmed
            allowed={'name','code','township','managing_organisation','start_date','target_end_date','address'}
            require(set(command.master_updates)<=allowed,'PROJECT_FIELDS_INVALID','Unsupported project correction field.')
            require(all(v.strip() for v in command.master_updates.values()),'PROJECT_FIELDS_INVALID','A correction cannot erase project information.')
            from datetime import date
            for key in ('start_date','target_end_date'):
                if key in command.master_updates:
                    try: valid=date.fromisoformat(command.master_updates[key]).isoformat()==command.master_updates[key]
                    except ValueError:valid=False
                    require(valid, 'PROJECT_DATES_INVALID','Use an ISO project date.')
            project.master_updates=dict(command.master_updates)
            project.edited_by_operator = True
            audit(review, 'PROJECT_REVIEWED', project.id)
        return self.edit(batch_id, command.expected_revision, update)

    def entity(self, batch_id, entity_id, command):
        def update(batch, review):
            model = ProjectProposal if command.kind == 'PROJECT' else MaterialProposal
            try:
                attributes = model.model_validate(command.attributes).model_dump(mode='json')
            except ValidationError as exc:
                raise IngestionError('PROPOSAL_INVALID', 'Check the proposal name, dates and text-valued specifications.', 422) from exc
            if command.confirmed and command.kind == 'MATERIAL':
                require(attributes.get('category_code') and attributes.get('standard_unit'), 'PROPOSAL_INCOMPLETE', 'A confirmed material needs a category and standard unit.')
            require(not attributes.get('start_date') or not attributes.get('target_end_date') or attributes['start_date'] <= attributes['target_end_date'],
                    'PROJECT_DATES_INVALID', 'Project end date precedes start date.')
            entity = next((e for e in review.entities if e.proposal.id == entity_id), None)
            if entity_id == 'new':
                entity = ReviewEntity(proposal=ProposedEntity(id='DRAFT-'+command.kind+'-'+uuid4().hex, kind=command.kind, attributes=attributes))
                review.entities.append(entity)
            require(entity is not None and entity.proposal.kind == command.kind, 'PROPOSAL_NOT_FOUND', 'Draft entity not found.')
            if entity.proposal.attributes != attributes:
                affected = [r for s in review.submissions for r in s.rows if any(
                    ref and ref.kind == 'PROPOSED' and ref.id == entity.proposal.id
                    for ref in (r.current.project_ref,r.current.material_ref))]
                self.clear_scopes(review, affected)
                for submission in review.submissions:
                    for row in submission.rows:
                        if any(ref and ref.kind == 'PROPOSED' and ref.id == entity.proposal.id
                               for ref in (row.current.project_ref, row.current.material_ref)):
                            row.decision, row.assumptions_confirmed, row.conversion = 'PENDING', False, None
                            row.release_confirmed = False
            entity.proposal.attributes, entity.confirmed = attributes, command.confirmed
            entity.edited_by_operator = True
            audit(review, 'ENTITY_REVIEWED', entity.proposal.id)
        return self.edit(batch_id, command.expected_revision, update)

    def scopes(self, batch_id, command):
        known = {g['id'] for g in self.get(batch_id)['groups']}
        require(set(command.scopes) <= known, 'SCOPE_INVALID', 'A stock scope must match a displayed calculation group.')
        def update(batch, review):
            review.confirmed_stock_scopes = command.scopes
            audit(review, 'STOCK_SCOPE_CONFIRMED', batch.id)
        return self.edit(batch_id, command.expected_revision, update)

    def _preview(self, batch):
        if not batch.review.prepared:
            return self._preview_raw(batch)
        from backend.app.services.review_preparation import candidate
        proposed = candidate(batch)
        initial = self._preview_raw(proposed)
        proposed.review.confirmed_stock_scopes = [g['id'] for g in initial['groups']]
        view = self._preview_raw(proposed)
        for sub in batch.review.submissions:
            for row in sub.rows:
                if row.decision != 'EXCLUDED' and row.preparation.get('questions'):
                    view['blockers'][sub.id].append({'row_id':row.id, 'messages':row.preparation['questions']})
                if (row.decision != 'EXCLUDED' and row.current.application != 'HISTORY_ONLY'
                        and row.current.record_kind == 'OUTSTANDING_DEMAND'
                        and (not row.current.needed_from or not row.current.required_by)):
                    view['blockers'][sub.id].append({'row_id':row.id,
                        'messages':['Outstanding demand needs a source-supported or operator-provided start date and deadline.']})
        # Show stored choices/provenance, not virtual human confirmations.
        view['review'] = batch.review.model_dump(mode='json')
        view['prepared'] = True
        view['effective_rows'] = {}
        for sub in proposed.review.submissions:
            for row in sub.rows:
                quantity = row.current.quantity
                if quantity is not None and row.conversion:
                    with localcontext() as ctx:
                        ctx.prec = 1000
                        quantity = format(Decimal(quantity) * Decimal(row.conversion.factor), 'f')
                view['effective_rows'][row.id] = {'quantity':quantity,
                    'unit':canonical_unit(row.conversion.to_unit if row.conversion else row.current.unit or '')}
        view['confirmation_summary'] = [
            'Accept the displayed project/material identities, interpreted values and evidence treatments.',
            'Confirm displayed conversions and current stock inputs are complete and non-overlapping where used.',
            'For released material, confirm unused condition and ownership for release; transfer suitability remains a later decision.']
        view['publication_available'] = all(view['approvals'].values()) and not view['warnings'] and not any(view['blockers'].values())
        return view

    def _preview_raw(self, batch):
        review = self.state(batch)
        contexts, entities, material_cache = {}, {e.proposal.id: e for e in review.entities}, {}
        errors = {s.id: [] for s in review.submissions}
        records, seen_targets = [], set()
        existing = {}
        for submission in review.submissions:
            refs = [row.current.project_ref for row in submission.rows if row.decision != 'EXCLUDED']
            refs += [project.current.project_ref for project in submission.projects] if not submission.rows else []
            for ref in refs:
                if ref and ref.kind == 'EXISTING' and ref.id not in contexts:
                    contexts[ref.id] = self.intake.reads.project_context(ref.id)
        stock_heads = {}
        superseded = set()
        for project, context in contexts.items():
            superseded.update(row['id'] for row in context['collections'].get('superseded_records', []))
            for head in context['collections'].get('stock_heads', []):
                stock_heads[(project, head['material_id'], canonical_unit(head['unit']))] = head
            for row in context['collections'].get('extracted_rows', []):
                if row['id'] not in superseded: existing[row['id']] = (project, row)
            for row in context['collections'].get('published_records', []):
                if row['id'] not in superseded and row['application'] != 'HISTORY_ONLY':
                    existing[row['id']] = (project, {'id': row['id'], 'document_id': row['source'].get('document_id', row['source']['submission_id']),
                        'review_status': 'ACCEPTED', 'suggested_material_id': row['material_id'],
                        'parsed_fields': {'record_kind':row['record_kind'],'quantity':row['quantity'],'unit':row['unit']},
                        'projection_id':row.get('projection_id')})

        replacements = set()
        working_rows = {row.id: row for submission in review.submissions for row in submission.rows}
        def cycles(start, targets, visited=None):
            visited = set() if visited is None else visited
            for target in targets:
                if target == start: return True
                if target in visited: continue
                visited.add(target)
                prior = working_rows.get(target)
                if prior and prior.current.application == 'REPLACE' and cycles(start, prior.current.replaces_record_ids, visited): return True
            return False
        for submission in review.submissions:
            for row in submission.rows:
                if row.decision == 'EXCLUDED': continue
                record = row.current
                blockers = []
                valid_targets = set()
                def resolve(ref, kind):
                    if ref is None:
                        blockers.append(f'{kind.title()} is unresolved.'); return None
                    if ref.kind == 'PROPOSED':
                        entity = entities.get(ref.id)
                        if not entity or entity.proposal.kind != kind or not entity.confirmed:
                            blockers.append(f'{kind.title()} proposal needs confirmation.'); return None
                        return entity.proposal.attributes
                    if kind == 'PROJECT':
                        return contexts.get(ref.id, {}).get('project')
                    if ref.id not in material_cache:
                        material_cache[ref.id] = self.intake.reads.get_entity('materials', ref.id)
                    if material_cache[ref.id] is None: blockers.append('Existing material not found.')
                    return material_cache[ref.id]
                project, material = resolve(record.project_ref, 'PROJECT'), resolve(record.material_ref, 'MATERIAL')
                if row.decision == 'PENDING': blockers.append('Accept or exclude this record.')
                if not row.assumptions_confirmed: blockers.append('Confirm the interpreted values, assumptions and issues.')
                if record.application == 'UNDECIDED': blockers.append('Choose add, replace or history only.')
                quantity, unit = record.quantity, record.unit
                standard = material.get('standard_unit') if material else None
                known_specs = material.get('specifications', {}) if material else {}
                conflicts = [key for key, value in record.specifications.items() if key in known_specs and known_specs[key] is not None
                             and str(known_specs[key]).casefold().strip() != str(value).casefold().strip()]
                if conflicts: blockers.append('Specifications differ from the selected catalogue identity: ' + ', '.join(conflicts))
                if row.conversion:
                    if not row.conversion.confirmed: blockers.append('Confirm the conversion basis.')
                    if quantity is not None:
                        with localcontext() as ctx:
                            ctx.prec = max(1000, len(quantity) + len(row.conversion.factor) + 20)
                            quantity = format(Decimal(quantity)*Decimal(row.conversion.factor), 'f')
                    unit = row.conversion.to_unit
                if record.application != 'HISTORY_ONLY':
                    if record.quantity_basis != 'MATERIAL' or quantity is None or not unit:
                        blockers.append('An effective record needs a known material quantity and unit; use history only for context.')
                    if quantity is not None and not PLAIN_DECIMAL.fullmatch(quantity): blockers.append('Use a plain nonnegative decimal quantity.')
                    if record.record_kind == 'UNKNOWN': blockers.append('Unknown business meaning must be resolved or history only.')
                    from terra.quantities import unit as normal_unit
                    unit=normal_unit(unit) if unit else unit
                    standard=normal_unit(standard) if standard else standard
                    if standard and unit != standard: blockers.append('Catalogue unit differs. Supply a confirmed conversion or use history only.')
                if record.available_from and record.available_until and record.available_from > record.available_until:
                    blockers.append('Availability dates are reversed.')
                if record.needed_from and record.required_by and record.needed_from > record.required_by:
                    blockers.append('Demand dates are reversed.')
                if record.record_kind == 'CONFIRMED_SURPLUS' and not record.available_from:
                    blockers.append('Confirmed surplus needs an operator-confirmed availability date.')
                if record.application != 'REPLACE' and record.replaces_record_ids:
                    blockers.append('Replacement targets require REPLACE treatment.')
                if record.application == 'REPLACE':
                    if not record.replaces_record_ids: blockers.append('Select exact prior record IDs to replace.')
                    if cycles(row.id, record.replaces_record_ids): blockers.append('Replacement links contain a cycle or self-reference.')
                    for target in record.replaces_record_ids:
                        if target in working_rows:
                            prior_row = working_rows[target]
                            if (prior_row.decision != 'ACCEPTED' or prior_row.current.project_ref != record.project_ref
                                    or prior_row.current.application == 'HISTORY_ONLY'):
                                blockers.append('Same-batch predecessor must be accepted effective evidence for the same project.')
                            if target in seen_targets: blockers.append('Another row already replaces this target.')
                            seen_targets.add(target); valid_targets.add(target)
                            continue
                        prior = existing.get(target)
                        if not prior or not record.project_ref or prior[0] != record.project_ref.id:
                            blockers.append('Replacement target is not a record in this project.'); continue
                        if target in seen_targets: blockers.append('Another row already replaces this target.')
                        seen_targets.add(target); valid_targets.add(target)
                        original_material = prior[1].get('suggested_material_id')
                        context = contexts[prior[0]]['collections']
                        offers = {o['id']: o for o in context.get('supply_offers', [])}
                        allocations = {a['id']: a for a in context.get('allocation_proposals', [])}
                        protected = any((t['status'] in ACTIVE or t.get('reserved_quantity', 0) > 0) and
                            offers.get(allocations.get(t['proposal_id'], {}).get('supply_offer_id'), {}).get('material_id') == original_material
                            for t in context.get('transfers', []))
                        if protected: blockers.append('This stock has an active transfer. Resolve it in Transfer Management before making corrections.')
                if blockers:
                    errors[submission.id].append({'row_id': row.id, 'messages': blockers})
                if not blockers and record.application != 'HISTORY_ONLY':
                    replacements.update(valid_targets)
                    records.append({'id': row.id, 'project': record.project_ref.id, 'material': record.material_ref.id,
                        'unit': unit, 'quantity': quantity, 'kind': record.record_kind, 'source': submission.id,
                        'provenance': row.provenance, 'treatment': record.application})
        # Legacy rows are only included for supported, accepted observation meanings.
        # Offers are never added to stock. Overlap/incomplete-ledger risks remain visible.
        for rid, (project, row) in existing.items():
            if rid in replacements or row['review_status'] not in ('ACCEPTED', 'CORRECTED'): continue
            fields = row['parsed_fields']; kind = fields.get('record_kind')
            if kind not in ('ON_HAND_INVENTORY', 'REMAINING_LOCAL_REQUIREMENT', 'OUTSTANDING_DEMAND'): continue
            if kind == 'ON_HAND_INVENTORY' and (project, row.get('suggested_material_id'), canonical_unit(fields.get('unit'))) in stock_heads: continue
            value = fields.get('quantity'); unit = fields.get('unit'); mid = row.get('suggested_material_id')
            if kind == 'OUTSTANDING_DEMAND':
                linked_demands = [d for d in contexts[project]['collections'].get('demand_requests', [])
                                  if d.get('origin_document_row_id') == rid or d['id'] == row.get('projection_id')]
                if linked_demands:
                    value = sum(max(Decimal(str(d['required_quantity'])) - Decimal(str(d['fulfilled_quantity'])), Decimal(0))
                                for d in linked_demands if d['request_status'] == 'OPEN' and d.get('is_outstanding_need_confirmed'))

            if value is None or not mid or not unit: continue
            records.append({'id': rid, 'project': project, 'material': mid, 'unit': unit, 'quantity': str(value),
                            'kind': kind, 'source': row['document_id'], 'provenance': 'STORED_RECORD', 'treatment': 'EXISTING'})
        represented_demands = {row.get('projection_id') for _, row in existing.values()}
        represented_origins = set(existing)
        for project, context in contexts.items():
            for demand in context['collections'].get('demand_requests', []):
                if demand['id'] in represented_demands or demand.get('origin_document_row_id') in represented_origins:
                    continue
                if demand['request_status'] != 'OPEN' or not demand['is_outstanding_need_confirmed']:
                    continue
                quantity=max(Decimal(str(demand['required_quantity']))-Decimal(str(demand['fulfilled_quantity'])),Decimal(0))
                records.append({'id':demand['id'],'project':project,'material':demand['material_id'],'unit':demand['unit'],
                    'quantity':format(quantity,'f'),'kind':'OUTSTANDING_DEMAND','source':demand['id'],
                    'provenance':'STORED_DEMAND','treatment':'EXISTING'})
        for (project, material, unit), head in stock_heads.items():
            stock = Decimal(head['quantity'])
            offers = contexts[project]['collections']['supply_offers']
            changed = sum(max(Decimal(str(offer['transferred_out_quantity'])) - Decimal(str(head['outgoing_baseline'].get(offer['id'], 0))), Decimal(0))
                          for offer in offers if offer['material_id'] == material and canonical_unit(offer['unit']) == canonical_unit(unit))
            stock -= changed
            replaced_members = set(head['members']) & replacements
            if replaced_members:
                if replaced_members == set(head['members']): stock = Decimal(0)
                elif changed:
                    for submission in review.submissions:
                        errors[submission.id].append({'messages':['Partial replacement of a stock scope with later transfer effects requires a full reviewed stock reconciliation.']})
                else:
                    stock -= sum(Decimal(str(head['members'][rid])) for rid in replaced_members)
            if stock < 0:
                for submission in review.submissions:
                    errors[submission.id].append({'messages':['Transfer effects exceed verified stock. Reconcile current physical stock before publication.']})
            records.append({'id':head['id'],'project':project,'material':material,'unit':unit,'quantity':format(max(stock,Decimal(0)),'f'),
                            'kind':'ON_HAND_INVENTORY','source':head['publication_id'],'provenance':'STORED_STOCK_SCOPE','treatment':'EXISTING'})
        records = [record for record in records if record['id'] not in replacements]
        groups = preview_groups(records, contexts, review.confirmed_stock_scopes)
        for group in groups:
            if group['declared_confirmed_surplus'] is not None:
                declared = Decimal(group['declared_confirmed_surplus'])
                available = group['available_stock']
                unsafe = available is None or declared > Decimal(available) or (
                    group['calculated_potential_surplus'] is not None and declared > Decimal(group['calculated_potential_surplus']))
                if unsafe:
                    for entry in group['inputs']:
                        if entry['source'] in errors and entry['kind'] == 'CONFIRMED_SURPLUS':
                            errors[entry['source']].append({'row_id': entry['id'], 'messages': ['Confirmed surplus requires verified complete stock and must not exceed unreserved stock remaining after local need.']})
        for submission in review.submissions:
            used = {(r.current.project_ref.kind, r.current.project_ref.id) for r in submission.rows
                    if r.decision != 'EXCLUDED' and r.current.project_ref}
            for project in submission.projects:
                if not submission.rows and project.current.project_ref and project.current.project_ref.kind == 'PROPOSED':
                    proposal = entities.get(project.current.project_ref.id)
                    if not proposal or proposal.proposal.kind != 'PROJECT' or not proposal.confirmed:
                        errors[submission.id].append({'project_id': project.id, 'messages': ['Confirm the proposed project identity.']})
                if not submission.rows and project.current.project_ref is None:
                    errors[submission.id].append({'project_id': project.id, 'messages': ['Resolve this project association before approval.']})
                if not project.confirmed and (not submission.rows or project.current.project_ref and (project.current.project_ref.kind, project.current.project_ref.id) in used):
                    errors[submission.id].append({'project_id': project.id, 'messages': ['Confirm project details and association.']})
        warnings = []
        if review.context_epoch != batch.context.epoch or batch.context.refresh_required:
            warnings.append('Database context was restored or changed. Start a current review after revalidation.')
        current_files = {s.id for s in batch.submissions}
        reviewed_files = {s.id for s in review.submissions if s.kind == 'FILE'}
        if current_files != reviewed_files:
            warnings.append('Some uploaded files are not included in this working review. Complete analysis/review before publication.')
        for source in batch.submissions:
            item = next((s for s in review.submissions if s.id == source.id), None)
            if source.resolution == 'MANUAL' and not any(s.id == source.manual_submission_id and s.kind == 'MANUAL' and s.rows for s in review.submissions):
                warnings.append('A failed file needs its linked manual replacement before publication.')
            expected = {'SKIPPED': 'SKIPPED', 'MANUAL': 'MANUAL_REPLACEMENT'}.get(source.resolution, 'EXTRACTED')
            if item and item.resolution != expected:
                warnings.append('A file resolution changed. Update the working review before approval.')
        if review.source_digest:
            from backend.app.services.analysis_service import ComparisonService
            if review.source_digest != digest_json(ComparisonService.manifest(batch)):
                warnings.append('Upload/context inputs changed since the working analysis. Existing edits remain saved; review needs explicit reconciliation before approval.')
        context_digest = digest_json({'projects': contexts, 'materials': material_cache})
        content = review.model_dump(mode='json')
        content.pop('audit')
        # Additive preparation metadata must not invalidate untouched legacy approvals.
        if not content['prepared']:
            content.pop('prepared')
        for entity in content['entities']:
            entity.pop('edited_by_operator', None)
        for submission in content['submissions']:
            for field in ('approval_digest', 'approved_at', 'summary_confirmed'): submission.pop(field)
            for project in submission['projects']:
                project.pop('edited_by_operator', None)
            for row in submission['rows']:
                if not row['preparation']:
                    row.pop('preparation')
        digest = digest_json({'content': content, 'context': context_digest, 'groups': groups, 'errors': errors, 'warnings': warnings})
        legacy_content = {**content, 'submissions': [{key:value for key,value in sub.items() if key != 'resolution'} for sub in content['submissions']]}
        legacy_digest = digest_json({'content':legacy_content, 'context':context_digest, 'groups':groups, 'errors':errors, 'warnings':warnings})
        # Per-project dependencies retain unrelated file approvals. The batch
        # digest still guards every publication input and every approval request.
        submission_digests = {}
        for sub in review.submissions:
            project_ids = {r.current.project_ref.id for r in sub.rows if r.current.project_ref}
            project_ids.update(p.current.project_ref.id for p in sub.projects if p.current.project_ref)
            related = [s for s in review.submissions if s.id == sub.id or
                       any(r.current.project_ref and r.current.project_ref.id in project_ids for r in s.rows) or
                       any(p.current.project_ref and p.current.project_ref.id in project_ids for p in s.projects)]
            refs = {ref.id for s in related for r in s.rows for ref in (r.current.project_ref, r.current.material_ref) if ref}
            refs.update(p.current.project_ref.id for s in related for p in s.projects if p.current.project_ref)
            material_ids = {r.current.material_ref.id for s in related for r in s.rows if r.current.material_ref}
            bodies = []
            for item in related:
                body = item.model_dump(mode='json', exclude={'approval_digest', 'approved_at', 'summary_confirmed'})
                for project in body['projects']:
                    project.pop('edited_by_operator', None)
                for row in body['rows']:
                    if not row['preparation']:
                        row.pop('preparation')
                bodies.append(body)
            submission_digests[sub.id] = digest_json({'submissions': bodies,
                'entities': [e.model_dump(mode='json', exclude={'edited_by_operator'}) for e in review.entities if e.proposal.id in refs],
                'contexts': {pid: contexts.get(pid) for pid in sorted(project_ids)},
                'materials': {mid: material_cache.get(mid) for mid in sorted(material_ids)},
                'groups': [g for g in groups if g['project'] in project_ids],
                'errors': {s.id: errors[s.id] for s in related}, 'epoch': review.context_epoch})
        approvals = {s.id: bool(s.approval_digest and s.approval_digest in (digest, legacy_digest, submission_digests[s.id])) for s in review.submissions}
        return {'batch_id': batch.id, 'revision': batch.revision, 'review': review.model_dump(mode='json'),
                'groups': groups, 'blockers': errors, 'warnings': warnings, 'preview_digest': digest,
                'context_digest': context_digest, 'operational_writes': False,
                'publication_available': bool(approvals) and all(approvals.values()) and not warnings and not any(errors.values()),
                'approvals': approvals, 'submission_digests': submission_digests}

    def get(self, batch_id):
        batch=self.intake.get(batch_id)
        if batch.state == 'PUBLISHED':
            from backend.app.services.publication_service import PublicationService
            receipt=PublicationService(self.intake).get_receipt(batch_id)
            require(receipt is not None,'PUBLICATION_RECEIPT_MISSING','This published batch has no receipt in the current database. Do not replay it.')
            return {'batch_id':batch.id,'revision':batch.revision,'review':batch.review.model_dump(mode='json'),
                    'groups':receipt['groups'],'blockers':{s.id:[] for s in batch.review.submissions},
                    'warnings':receipt['warnings'],'preview_digest':receipt['review_digest'],'context_digest':receipt['context_digest'],
                    'approvals':{s.id:True for s in batch.review.submissions},'operational_writes':False,
                    'publication_available':False,'published':True}
        return self._preview(batch)

    def approve(self, batch_id, submission_id, command):
        def approve(batch):
            review = self.state(batch)
            submission = self.submission(review, submission_id)
            preview = self._preview(batch)
            require(command.preview_digest == preview['preview_digest'], 'PREVIEW_STALE', 'Values or database context changed. Review the refreshed preview.')
            require(command.summary_confirmed and not preview['blockers'][submission_id], 'REVIEW_UNRESOLVED', 'Resolve every included row and confirm this file summary before approval.')
            require(not preview['warnings'], 'REVIEW_CONTEXT_STALE', 'Revalidate changed batch/context before approval.')
            if review.prepared:
                require(command.accept_recommendations, 'PREPARED_CONFIRMATION_REQUIRED', 'Approve the displayed recommendations and physical-input summary explicitly.')
                from backend.app.services.review_preparation import candidate
                proposed = candidate(batch).review
                refs = {ref.id for row in submission.rows if row.decision != 'EXCLUDED'
                        for ref in (row.current.project_ref, row.current.material_ref) if ref}
                refs.update(p.current.project_ref.id for p in submission.projects if p.current.project_ref)
                for entity in review.entities:
                    if entity.proposal.id in refs:
                        entity.confirmed = next(e for e in proposed.entities if e.proposal.id == entity.proposal.id).confirmed
                for project in submission.projects:
                    project.confirmed = next(p for s in proposed.submissions for p in s.projects if p.id == project.id).confirmed
                for row in submission.rows:
                    if row.decision != 'EXCLUDED':
                        row.decision, row.assumptions_confirmed = 'ACCEPTED', True
                        row.release_confirmed = row.current.record_kind == 'CONFIRMED_SURPLUS'
                        if row.conversion: row.conversion.confirmed = True
                scopes = {g['id'] for g in preview['groups'] if any(
                    row.decision != 'EXCLUDED' and row.current.application != 'HISTORY_ONLY'
                    and row.current.project_ref and row.current.material_ref
                    and row.current.project_ref.id == g['project'] and row.current.material_ref.id == g['material']
                    and canonical_unit(row.conversion.to_unit if row.conversion else row.current.unit or '') == g['unit']
                    for row in submission.rows)}
                review.confirmed_stock_scopes = sorted(set(review.confirmed_stock_scopes) | scopes)
            submission.summary_confirmed, submission.approval_digest, submission.approved_at = True, preview['submission_digests'][submission.id], now()
            audit(review, 'SUBMISSION_APPROVED', submission.id)
        self.intake._edit(batch_id, command.expected_revision, approve)
        return self.get(batch_id)
