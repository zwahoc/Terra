"""Local intake orchestration independent of FastAPI and model providers."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.app.repositories.ingestion_repository import IngestionRepository, TerraReadRepository
from backend.app.schemas.ingestion import ContextObservation, FileSubmission, IngestionBatch
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_storage import SourceStore, digest_json


def now():
    return datetime.now(timezone(timedelta(hours=8)))


class IntakeService:
    def __init__(self, repository=None, reads=None, store=None):
        self.repository = repository if repository is not None else IngestionRepository()
        self.reads = reads if reads is not None else TerraReadRepository(self.repository.adapter)
        self.store = store if store is not None else SourceStore()

    def create(self, selected_project_id=None):
        if selected_project_id and self.reads.get_entity("projects", selected_project_id) is None:
            raise IngestionError("PROJECT_NOT_FOUND", "The selected project does not exist.", 404)
        timestamp = now()
        batch = IngestionBatch(id=f"BAT-{uuid4().hex}", revision=1,
                               selected_project_id=selected_project_id,
                               created_at=timestamp, updated_at=timestamp)
        with self.store.batch_lock(batch.id):
            self.repository.save(batch)
            self.store.checkpoint(batch)
        return batch

    def get(self, batch_id):
        batch = self.repository.get(batch_id)
        if batch is None:
            if self.store.recoverable(batch_id):
                raise IngestionError("DRAFT_RESTORE_REQUIRED", "The emulator has no batch. Explicitly restore its local draft checkpoint.")
            raise IngestionError("BATCH_NOT_FOUND", "The intake batch does not exist.", 404)
        self.store.checkpoint(batch)
        return batch

    def _edit(self, batch_id, expected_revision, edit):
        with self.store.batch_lock(batch_id):
            batch = self.get(batch_id)
            if expected_revision is not None and batch.revision != expected_revision:
                raise IngestionError("STALE_REVISION", "The batch changed. Reload it before editing.")
            if batch.state == "PUBLISHED":
                raise IngestionError("BATCH_PUBLISHED", "This batch is published and immutable. Start a new batch for corrections.")
            previous_revision = batch.revision
            result = edit(batch)
            batch.revision += 1
            batch.updated_at = now()
            self.repository.save(batch, previous_revision)
            self.store.checkpoint(batch)
            return batch, result

    def update_analysis(self, batch_id, edit):
        """Server-owned merge under the same lock/CAS as operator edits."""
        return self._edit(batch_id, None, edit)

    def add_files(self, batch_id, expected_revision, files):
        if not files:
            raise IngestionError("FILES_REQUIRED", "Select at least one file.", 422)

        def edit(batch):
            if batch.review:
                from backend.app.services.review_service import ReviewService
                ReviewService(self).upgrade_approvals(batch)
            results = []
            for filename, stream in files:
                source = self.store.put(stream, filename)
                prior = next((s for s in batch.submissions if s.source.sha256 == source.sha256), None)
                if prior is None:
                    prior = FileSubmission(id=f"SUB-{uuid4().hex}", source=source, added_at=now())
                    batch.submissions.append(prior)
                    duplicate = False
                else:
                    duplicate = True
                results.append({"submission_id": prior.id, "source_id": prior.source.id,
                                "duplicate_in_batch": duplicate, "uploaded_filename": source.display_filename})
            return results

        batch, results = self._edit(batch_id, expected_revision, edit)
        return {"batch": batch.model_dump(mode="json"), "files": results}

    def patch_context(self, batch_id, request):
        def edit(batch):
            batch.context.operator_notes = request.operator_notes
            batch.context.operator_input = request.operator_input
        return self._edit(batch_id, request.expected_revision, edit)[0]

    def capture_project(self, batch_id, request):
        def edit(batch):
            facts = self.reads.project_context(request.project_id)
            observation = ContextObservation(project_id=request.project_id, observed_at=now(),
                                             read_token=digest_json(facts), facts=facts)
            batch.context.project_observations = [o for o in batch.context.project_observations if o.project_id != request.project_id]
            batch.context.project_observations.append(observation)
            batch.context.refresh_required = False
        return self._edit(batch_id, request.expected_revision, edit)[0]

    def source(self, batch_id, submission_id):
        batch = self.get(batch_id)
        submission = next((s for s in batch.submissions if s.id == submission_id), None)
        if submission is None:
            raise IngestionError("SUBMISSION_NOT_FOUND", "The file is not part of this batch.", 404)
        return submission.source, self.store.path(submission.source)

    def duplicates(self, batch_id):
        batch = self.get(batch_id)
        matches = []
        for submission in batch.submissions:
            for candidate_id in self.store.candidate_batches(submission.source.sha256):
                if candidate_id == batch.id: continue
                candidate = self.repository.get(candidate_id)
                if candidate is None: continue
                original = next((s for s in candidate.submissions if s.source.sha256 == submission.source.sha256), None)
                if original is None: continue
                matches.append({'submission_id':submission.id, 'batch_id':candidate.id,
                                'state':candidate.state, 'source_filename':original.source.display_filename,
                                'has_saved_analysis':bool(candidate.comparisons)})
        return {'matches':matches, 'authority':'SQL_VERIFIED_IDENTICAL_BYTES_ONLY'}

    def restore(self, batch_id):
        with self.store.batch_lock(batch_id):
            if self.repository.get(batch_id) is not None:
                raise IngestionError("BATCH_EXISTS", "Restore only applies to a missing emulator batch.")
            batch = self.store.recoverable(batch_id)
            if batch is None:
                raise IngestionError("CHECKPOINT_NOT_FOUND", "No local draft checkpoint exists.", 404)
            batch.restored_from_revision = batch.revision
            batch.revision += 1
            batch.updated_at = now()
            # Cached database facts cannot survive a database reset as current truth.
            batch.context.project_observations = []
            batch.context.refresh_required = True
            batch.context.epoch += 1
            if batch.review:
                from backend.app.services.review_service import invalidate
                invalidate(batch.review)
                batch.review.confirmed_stock_scopes = []
            from backend.app.schemas.analysis import AnalysisFailure
            for comparison in batch.comparisons:
                for run in comparison.runs:
                    if run.status in ('PENDING', 'RUNNING'):
                        run.status = 'INTERRUPTED'
                        run.worker_instance_id = None
                    for file in run.files:
                        if file.status == 'RUNNING':
                            file.status = 'FAILED'
                            file.error = AnalysisFailure(code='ANALYSIS_INTERRUPTED', message='The process stopped. Saved groups and candidates are retained; retry explicitly after refreshing database context.')
                        if file.reconciliation and file.reconciliation.status == 'RUNNING':
                            file.reconciliation.status = 'FAILED'
                            file.reconciliation.error = AnalysisFailure(code='ANALYSIS_INTERRUPTED', message='The project comparison stopped. Saved extraction remains available.')
            self.repository.save(batch)
            self.store.checkpoint(batch)
            return batch
