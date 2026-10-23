"""Three-model comparison orchestration. Results remain draft-only and isolated."""

import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import ValidationError

from backend.app.schemas.analysis import (
    AnalysisComparison, AnalysisFailure, AnalysisRun, BatchCrossCheck, FileAnalysis, FileDraft, ModelPreference,
    DocumentClassification, ClassificationAnalysis, OutputCorrections, ReconciliationAnalysis, ReconciliationResult,
)
from backend.app.repositories.model_preference_repository import ModelPreferenceRepository
from backend.app.services.analysis_budget import BudgetLedger
from backend.app.services.analysis_providers import ProviderAdapter, ProviderError, encode
from backend.app.services.analysis_settings import AnalysisSettings
from backend.app.services.analysis_tools import FrozenTerraReads, ToolExecutor, tool_definitions
from backend.app.services.ingestion_content import InitialContentReader
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService, now
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.pdf_preparation import PdfPreparer
from backend.app.services.analysis_coverage import numbered_table_references, validate_pdf_coverage
from backend.app.services.analysis_prompts import PromptBundle, PIPELINE_VERSION
from backend.app.services.analysis_output import AmbiguousJSON, parse_object, normalise_quantities, apply_corrections, pointer, PLAIN_DECIMAL, recoverable_record_prefix
from backend.app.services.analysis_reconciliation import validate_material_extraction, validate_reconciliation, combine_validation_errors


PROMPT_VERSION = PIPELINE_VERSION
WORKER_INSTANCE_ID = uuid4().hex
POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="terra-analysis")


def _failure(error):
    if isinstance(error, IngestionError):
        return AnalysisFailure(code=error.code, message=error.message,
                               validation_errors=getattr(error, "validation_errors", []),
                               details=getattr(error, "details", {}))
    return AnalysisFailure(code="ANALYSIS_INTERNAL_ERROR", message="Analysis stopped unexpectedly; successful drafts are retained. Inspect local development diagnostics before retrying.")


class ComparisonService:
    def __init__(self, intake=None, settings=None, ledger=None, provider_factory=None, schedule=None, preferences=None, prompts=None):
        self.intake = intake if intake is not None else IntakeService()
        self.settings = settings if settings is not None else AnalysisSettings.load()
        self.ledger = ledger if ledger is not None else BudgetLedger(self.settings)
        self.provider_factory = provider_factory or (lambda spec: ProviderAdapter(spec, self.settings, self.ledger))
        self.schedule = schedule or POOL.submit
        self.preferences = preferences if preferences is not None else ModelPreferenceRepository()
        self.prompts = prompts if prompts is not None else PromptBundle()

    @staticmethod
    def manifest(batch):
        return {"selected_project_id": batch.selected_project_id,
                "files": [{"submission_id": s.id, **s.source.model_dump(mode="json")} for s in batch.submissions],
                "operator_notes": batch.context.operator_notes, "operator_input": batch.context.operator_input}

    def status(self):
        return {**self.settings.public(), "budget": self.ledger.summary(),
                "preference": self.preferences.get().model_dump(mode="json")}

    def select_primary(self, batch_id, request):
        # This records a model preference, never a file approval or working review draft.
        with self.preferences.lock, self.intake.store.batch_lock(batch_id):
            preference = self.preferences.get()
            if preference.revision != request.expected_preference_revision:
                raise IngestionError("STALE_MODEL_PREFERENCE", "The model choice changed in another session. Refresh before choosing.")
            batch = self.intake.get(batch_id)
            if batch.revision != request.expected_revision:
                raise IngestionError("STALE_REVISION", "The batch changed. Refresh before choosing a model.")
            comparison = self._find(batch, request.comparison_id)
            candidate = next((run for run in comparison.runs if run.id == request.run_id), None)
            if candidate is None:
                raise IngestionError("ANALYSIS_RUN_NOT_FOUND", "The selected run does not belong to this comparison.", 404)
            if (candidate.status != "SUCCEEDED" or candidate.cross_check is None or candidate.cross_check_error is not None
                    or not candidate.files or any(file.status != "SUCCEEDED" or file.draft is None for file in candidate.files)):
                raise IngestionError("MODEL_RESULT_INCOMPLETE", "Choose a model with complete file results and a successful cross-file check.")
            if self._unchecked_pdf_files(batch, candidate):
                raise IngestionError("DOCUMENT_COVERAGE_NOT_VERIFIED", "This saved PDF result predates coverage validation. Run analysis again before choosing it as primary.")
            if (self.manifest(batch) != comparison.manifest or batch.context.refresh_required
                    or comparison.configuration.get("context_epoch", 0) != batch.context.epoch):
                raise IngestionError("ANALYSIS_INPUT_CHANGED", "This result belongs to older input or restored context. Refresh and analyse the current files before choosing.")
            spec = next((spec for spec in self.settings.models if spec.slot == candidate.model_slot and spec.model_id == candidate.model_id), None)
            if spec is None:
                raise IngestionError("MODEL_CONFIGURATION_CHANGED", "The selected model is no longer configured. No substitute was selected.")
            selected = ModelPreference(revision=preference.revision + 1,
                primary_model_slot=candidate.model_slot, model_id=candidate.model_id, selected_at=now(),
                batch_id=batch.id, comparison_id=comparison.id, run_id=candidate.id, input_digest=comparison.input_digest)
            self.preferences.save(selected)
        return selected

    def check_providers(self):
        results = []
        for spec in self.settings.models:
            try:
                results.append(self.provider_factory(spec).check_availability())
            except IngestionError as exc:
                results.append({"slot": spec.slot, "model_id": spec.model_id, "available": False,
                                "error": {"code": exc.code, "message": exc.message}})
        return {"models": results, "generation_tested": False}

    def start(self, batch_id, request):
        fingerprint = digest_json(request.model_dump(mode="json"))
        batch = self.intake.get(batch_id)
        prior = next((c for c in batch.comparisons if c.idempotency_key == request.idempotency_key or request.idempotency_key in c.request_aliases), None)
        if prior:
            prior_fingerprint = prior.request_aliases.get(request.idempotency_key, prior.request_fingerprint)
            if prior_fingerprint != fingerprint:
                raise IngestionError("IDEMPOTENCY_KEY_REUSED", "This analysis key was already used with different input.")
            return self.get(batch_id, prior.id)
        if not self.settings.enabled:
            raise IngestionError("MODELS_DISABLED", "Add provider keys and set TERRA_LLM_ENABLED=true in .env before analysis.", 503)
        if not batch.submissions or not any(s.resolution == 'ANALYSE' for s in batch.submissions):
            raise IngestionError("FILES_REQUIRED", "Upload at least one file before model comparison.", 422)
        preference = self.preferences.get()
        selected_models = self.settings.models
        if request.mode == "DEFAULT" and preference.primary_model_slot is not None:
            selected_models = tuple(spec for spec in self.settings.models
                                    if spec.slot == preference.primary_model_slot and spec.model_id == preference.model_id)
            if not selected_models:
                raise IngestionError("MODEL_CONFIGURATION_CHANGED", "The saved primary model is no longer configured. Choose again; no substitute was selected.")
        # Freeze a common starting view from current records, not cached old observations.
        reads = FrozenTerraReads(self.intake.reads)
        project_ids = {o.project_id for o in batch.context.project_observations}
        if batch.selected_project_id:
            project_ids.add(batch.selected_project_id)
        initial = {project_id: reads.call("get_project_context", {"project_id": project_id}) for project_id in sorted(project_ids)}
        manifest = self.manifest(batch)
        digest = digest_json({"manifest": manifest, "context": initial, "context_epoch": batch.context.epoch,
                              "prompt_identity": self.prompts.identity,
                              "model_configuration": self.settings.public()})
        resolutions = {s.id: s.resolution for s in batch.submissions if s.resolution != 'ANALYSE'}
        if not request.reanalyse:
            reusable = next((c for c in reversed(batch.comparisons) if c.input_digest == digest and c.prompt_version == PROMPT_VERSION
                             and c.configuration.get('file_resolutions', {}) == resolutions
                             and [(r.model_slot, r.model_id) for r in c.runs] == [(spec.slot, spec.model_id) for spec in selected_models]), None)
            if reusable:
                def alias(current):
                    self._find(current, reusable.id).request_aliases[request.idempotency_key] = fingerprint
                self.intake._edit(batch_id, request.expected_revision, alias)
                return self.get(batch_id, reusable.id)
        if any((r.status == "PENDING" and r.worker_instance_id == WORKER_INSTANCE_ID) or (r.status == "RUNNING" and self.worker_active(r.id)) for c in batch.comparisons for r in c.runs):
            raise IngestionError("ANALYSIS_ALREADY_RUNNING", "This batch already has pending/active analysis. Wait or explicitly retry interrupted work.")
        comparison = AnalysisComparison(id=f"CMP-{uuid4().hex}", idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint, input_revision=batch.revision, input_digest=digest,
            manifest=manifest, initial_context=initial, prompt_version=PROMPT_VERSION,
            configuration={**{k: v for k, v in self.settings.public().items() if k != "models"},
                           "mode": request.mode, "preference_revision": preference.revision,
                           "context_epoch": batch.context.epoch,
                           'file_resolutions': resolutions,
                           "prompt_manifest": self.prompts.manifest, "prompt_identity": self.prompts.identity}, created_at=now(),
            runs=[AnalysisRun(id=f"AIR-{uuid4().hex}", model_slot=spec.slot, model_id=spec.model_id,
                             worker_instance_id=WORKER_INSTANCE_ID,
                             files=[FileAnalysis(submission_id=s.id) for s in batch.submissions]) for spec in selected_models])

        if not request.reanalyse:
            for run in comparison.runs:
                self._reuse_files(batch, comparison, run)

        def attach(current):
            current.comparisons.append(comparison)
            current.context.refresh_required = False
            for submission in current.submissions:
                submission.analysis_status = "ANALYSING"
        self.intake._edit(batch_id, request.expected_revision, attach)
        for spec, run in zip(selected_models, comparison.runs):
            self.schedule(self._worker, batch_id, comparison.id, run.id, spec, reads)
        return self.get(batch_id, comparison.id)

    def _reuse_files(self, batch, comparison, run):
        """Copy compatible evidence into a new isolated run, retaining its lineage.

        Fresh database reconciliation and the complete batch check still run.
        Changed notes/configuration/epoch invalidate extraction reuse.
        """
        for previous in reversed(batch.comparisons):
            if (previous.prompt_version != PROMPT_VERSION or previous.configuration.get('prompt_identity') != self.prompts.identity
                    or previous.configuration.get('context_epoch', 0) != batch.context.epoch
                    or any(previous.manifest.get(key) != comparison.manifest.get(key) for key in
                           ('selected_project_id', 'operator_notes', 'operator_input'))):
                continue
            if any(previous.configuration.get(key) != comparison.configuration.get(key) for key in
                   ('deepseek_reasoning_effort', 'deepseek_max_output_tokens', 'max_output_tokens')):
                continue
            prior = next((r for r in previous.runs if (r.model_slot, r.model_id) == (run.model_slot, run.model_id)), None)
            if prior is None:
                continue
            hashes = {f['submission_id']: f['sha256'] for f in previous.manifest['files']}
            sources = {s.id: s for s in batch.submissions}
            from backend.app.services.analysis_reuse import remap_refs
            mapping = {p.id:f'DRAFT-{p.kind}-{uuid4().hex}' for p in prior.proposals}
            def project_file(old):
                copied = old.model_copy(deep=True)
                copied.reused_from_run_id = prior.id
                if copied.draft:
                    copied.draft = FileDraft.model_validate(remap_refs(copied.draft.model_dump(mode='json'),mapping))
                for group in copied.page_groups:
                    if group.draft:
                        group.draft = FileDraft.model_validate(remap_refs(group.draft.model_dump(mode='json'),mapping))
                    group.repair_state = None
                copied.repair_state = None
                return copied
            inherited = False
            for index, file in enumerate(run.files):
                old = next((f for f in prior.files if f.submission_id == file.submission_id), None)
                if old is not None and sources[file.submission_id].resolution != 'ANALYSE':
                    copied = project_file(old)
                    run.files[index] = copied
                    continue
                if old is None or old.status != 'SUCCEEDED' or old.draft is None or old.draft.extraction_version != 'MATERIAL_V2' or hashes.get(file.submission_id) != sources[file.submission_id].source.sha256:
                    continue
                if self._unchecked_pdf_files(batch, prior) and file.submission_id in self._unchecked_pdf_files(batch, prior):
                    continue
                copied = project_file(old)
                if copied.reconciliation:
                    copied.reconciliation.status = 'PENDING'
                    # Renaming only owned provisional IDs changes no evidence.
                    # Fresh context comparison remains mandatory in _reconcile.
                    copied.reconciliation.extraction_digest = digest_json(copied.draft.model_dump(mode='json'))
                run.files[index] = copied
                inherited = True
            if inherited:
                # These become this run's own detached provisional copies. No
                # other model's IDs, edits or approvals are imported.
                run.proposals = [p.model_copy(update={'id':mapping[p.id]},deep=True) for p in prior.proposals]
                run.proposal_lineage = {new:old for old,new in mapping.items()}
            return

    def _job_lock(self, run_id):
        self.intake.store._id(run_id)
        return FileLock(str(self.intake.store.root / "locks" / f"worker-{run_id}.lock"), timeout=0)

    def worker_active(self, run_id):
        try:
            with self._job_lock(run_id):
                return False
        except Timeout:
            return True

    def _find(self, batch, comparison_id):
        comparison = next((c for c in batch.comparisons if c.id == comparison_id), None)
        if comparison is None:
            raise IngestionError("COMPARISON_NOT_FOUND", "This comparison does not belong to the batch.", 404)
        return comparison

    @staticmethod
    def _unchecked_pdf_files(batch, run):
        # Historical outputs stay immutable. Mark unchecked older PDF results in the view.
        pdf_ids = {s.id for s in batch.submissions if s.source.display_filename.lower().endswith('.pdf')}
        return [file.submission_id for file in run.files if file.status == "SUCCEEDED" and
                (file.submission_id in pdf_ids or file.preparation is not None) and
                not (file.preparation or {}).get("coverage_check")]

    def get(self, batch_id, comparison_id):
        batch = self.intake.get(batch_id)
        comparison = self._find(batch, comparison_id)
        value = comparison.model_dump(mode="json")
        value["batch_revision"] = batch.revision
        value["input_manifest_current"] = self.manifest(batch) == comparison.manifest
        value["database_context_requires_refresh"] = (batch.context.refresh_required or
            comparison.configuration.get("context_epoch", 0) != batch.context.epoch)
        value["worker_active"] = {run.id: self.worker_active(run.id) for run in comparison.runs}
        for run in value["runs"]:
            original = next(r for r in comparison.runs if r.id == run["id"])
            run["coverage_verification_required"] = bool(self._unchecked_pdf_files(batch, original))
            if run["coverage_verification_required"] and run["status"] == "SUCCEEDED":
                run["status"] = "PARTIAL"
            if ((run["status"] == "RUNNING" and not value["worker_active"][run["id"]]) or
                    (run["status"] == "PENDING" and run["worker_instance_id"] != WORKER_INSTANCE_ID and not value["worker_active"][run["id"]])):
                run["status"] = "INTERRUPTED"
            from backend.app.services.review_service import ReviewService
            run['review_ready'] = (run['status'] != 'INTERRUPTED' and ReviewService.reviewable(batch, original)
                                   and not run['coverage_verification_required'])
        value["operational_writes"] = False
        return value

    def _persist(self, batch_id, comparison_id, run):
        frozen = run.model_copy(deep=True)
        def edit(batch):
            comparison = self._find(batch, comparison_id)
            comparison.runs = [frozen if current.id == frozen.id else current for current in comparison.runs]
            if comparison.id == batch.comparisons[-1].id:
                for submission in batch.submissions:
                    statuses = [f.status for r in comparison.runs for f in r.files if f.submission_id == submission.id]
                    if not statuses:
                        continue
                    file_results = [f for r in comparison.runs for f in r.files if f.submission_id == submission.id]
                    if any(status in ("PENDING", "RUNNING") for status in statuses) or any(
                            f.reconciliation and f.reconciliation.status in ('PENDING', 'RUNNING') for f in file_results):
                        submission.analysis_status = "ANALYSING"
                    elif all(status == "SUCCEEDED" for status in statuses) and not any(
                            f.reconciliation and f.reconciliation.status == 'FAILED' for f in file_results):
                        submission.analysis_status = "COMPLETE"
                    elif any(status == "SUCCEEDED" for status in statuses):
                        submission.analysis_status = "PARTIAL"
                    else:
                        submission.analysis_status = "FAILED"
        self.intake.update_analysis(batch_id, edit)

    @staticmethod
    def _file_context(file):
        # Audit originals are stored for inspection, not repeatedly fed back as
        # duplicate evidence or accepted facts in every subsequent stage.
        value = file.model_dump(mode='json', exclude={'response_history', 'recoveries', 'prompt_manifest', 'unvalidated_output', 'repair_state'})
        value.pop('page_groups', None)
        if file.classification is not None:
            value['classification'] = file.classification.model_dump(mode='json', exclude={'usage','raw_response'})
        if file.reconciliation is not None:
            value['reconciliation'] = file.reconciliation.model_dump(mode='json', exclude={
                'project_context', 'response_history', 'recoveries', 'previous_attempts', 'group_results', 'repair_state'})
        return value

    def _classify(self, adapter, task, attachments, run, executor, persist, file):
        file.processing_stage = 'CLASSIFYING'
        # Classification sees file evidence and operator hints, not other models or proposals.
        input_task = {key: task[key] for key in ('submission_id', 'source', 'text', 'cells', 'content_preparation', 'batch_manifest')}
        input_task['reader_metadata'] = task.get('reader_metadata')
        input_task['stage'] = 'CLASSIFY_FILE'
        evidence_digest = digest_json({'source': task['source'], 'text': task['text'], 'cells': task['cells'],
            'manifest': task['batch_manifest'], 'model': run.model_id,
            'preparation': task['content_preparation'], 'prompt_identity': self.prompts.identity,
            'model_configuration': self.settings.public()})
        metadata = ClassificationAnalysis(evidence_digest=evidence_digest, prompt_identity=self.prompts.identity)
        file.classification = metadata
        persist(run)
        before = len(run.usage)
        try:
            result = self._conversation(adapter, input_task, attachments, DocumentClassification,
                run, executor, persist, tools=False, file=file)
            pages = [*(file.preparation or {}).get('page_numbers', []), *(file.preparation or {}).get('context_page_numbers', [])]
            if not set(result.source_page_hints) <= set(pages):
                raise IngestionError('CLASSIFICATION_PAGE_INVALID', 'Classification referenced pages that were not supplied.')
            metadata.result = result
            metadata.selected_modules = self.prompts.route(result)
            metadata.warnings = list(result.uncertainties)
            if result.primary_family == 'OTHER':
                metadata.warnings.append('Unknown document family; using generic extraction guidance.')
            metadata.status = 'FALLBACK' if result.primary_family == 'OTHER' else 'SUCCEEDED'
        except IngestionError as exc:
            metadata.error = _failure(exc)
            # Invalid interpretation can fall back; an unavailable provider must not
            # receive an automatic second paid generation after transport/quota failure.
            if exc.code.startswith(('PROVIDER_', 'TOKEN_', 'MODELS_', 'MODEL_INPUT', 'PROMPT_')):
                metadata.status = 'FAILED'
                raise
            metadata.status = 'FALLBACK'
            metadata.selected_modules = self.prompts.route(None)
            metadata.warnings = ['Classification was invalid or incomplete; using generic guidance.']
        finally:
            metadata.usage = [u.model_copy(deep=True) for u in run.usage[before:]]
            metadata.raw_response = next((h['text'] for h in reversed(file.response_history) if h['stage'] == 'CLASSIFY_FILE'), None)
            persist(run)
        return metadata.selected_modules

    def _conversation(self, adapter, instruction, attachments, schema_model, run, executor, persist,
                      tools=True, system=None, file=None, read_only=False):
        schema = schema_model.model_json_schema()
        if schema_model is FileDraft and instruction.get('extraction_contract') == 'MATERIAL_V2':
            schema['required'] = list(dict.fromkeys(schema.get('required', []) + ['extraction_version', 'project_info', 'source_items']))
            schema['properties']['extraction_version'] = {'type': 'string', 'const': 'MATERIAL_V2'}
            record_schema = schema['$defs']['DraftRecord']
            record_schema['required'] = list(dict.fromkeys(record_schema.get('required', []) +
                ['material_name', 'evidence_basis', 'inferred_fields', 'inference_explanation', 'quantity_basis']))
        if schema_model is FileDraft and instruction.get("content_preparation"):
            # Provider output must include provenance rather than silently taking DTO defaults.
            schema["required"] = list(dict.fromkeys(schema.get("required", []) + ["page_coverage"]))
            record_schema = schema.get("$defs", {}).get("DraftRecord", {})
            record_schema["required"] = list(dict.fromkeys(record_schema.get("required", []) + ["source_page", "source_item_ref", "project_ref"]))
            page_numbers = instruction["content_preparation"]["page_numbers"]
            schema["properties"]["page_coverage"].update({"minItems": len(page_numbers), "maxItems": len(page_numbers)})
            if instruction.get('extraction_contract') == 'MATERIAL_V2':
                schema['properties']['source_items']['minItems'] = sum(len(refs) for refs in instruction.get('numbered_source_items_by_page', {}).values())
        if schema_model is FileDraft and instruction.get('reader_metadata'):
            record_schema = schema['$defs']['DraftRecord']
            record_schema['required'] = list(dict.fromkeys(record_schema.get('required', []) + ['source_locator']))
            record_schema['properties']['source_locator'] = {'type':'string', 'minLength':1,
                'description':'Use a supplied exact paragraph, sheet/cell or embedded-image package locator. Office source_page must be null.'}
        stage = instruction['stage']
        system = system or self.prompts.compose(stage)
        declared_tools = [tool for tool in tool_definitions() if not read_only or not tool['name'].startswith('propose_')]
        resume = self._resumable_output(file or run, instruction, schema_model)
        if resume:
            return self._accept_output(adapter, instruction, attachments, schema_model, schema,
                resume['original_response'], run, executor, persist, file, resume=resume)
        session = adapter.session(system, encode({'task': instruction, 'required_json_schema': schema}),
                                  attachments, declared_tools if tools else [], schema)
        results = None
        stalled, final_requested = 0, False
        history = file.response_history if file is not None else run.recovery_history
        while True:
            try:
                turn = session.step(results)
            except ProviderError as exc:
                if hasattr(exc, "usage"):
                    exc.usage.stage = stage
                    exc.usage.submission_id = instruction.get('submission_id')
                    run.usage.append(exc.usage)
                    persist(run)
                raise
            turn.usage.stage = stage
            turn.usage.submission_id = instruction.get('submission_id')
            run.usage.append(turn.usage)
            persist(run)
            if turn.calls:
                if not tools:
                    raise IngestionError("MODEL_OUTPUT_INVALID", "A tool-free stage attempted an undeclared tool.")
                if any(call.name not in {tool['name'] for tool in declared_tools} for call in turn.calls):
                    raise IngestionError('TOOL_NOT_ALLOWED', 'This stage attempted an undeclared or proposal-writing tool.')
                before = executor.progress_count
                results = [executor.execute(call) for call in turn.calls]
                stalled = stalled + 1 if executor.progress_count == before else 0
                if stalled >= 3:
                    # Return a final opportunity with connected source/context, rather
                    # than cutting off immediately after executing the last tool.
                    final_requested = True
                    tools = False
                    task = {**instruction, 'own_proposals':[p.model_dump(mode='json') for p in run.proposals],
                            'saved_terra_observations':[o.model_dump(mode='json') for o in run.observations],
                            'completion_instruction': ('Repeated lookups add no new evidence. Return the complete reconciliation object, preserving the saved extraction. Account for every material/project and mark unresolved relationships honestly. No proposals or writes.' if read_only else
                                'Repeated lookups are adding no new evidence. Return useful material candidates and internal source-item coverage now. Use justified existing IDs or actual own proposal IDs. Explain unresolved evidence specifically. Do not invent dimensions, conversions, proposals or IDs.')}
                    session = adapter.session(system, encode({'task':task, 'required_json_schema':schema}), attachments, [], schema)
                    results = None
                continue
            history.append({'stage':stage, 'text':turn.text, 'final_opportunity':final_requested})
            persist(run)
            return self._accept_output(adapter, instruction, attachments, schema_model, schema, turn.text,
                                       run, executor, persist, file)

    def _validate_output(self, candidate, schema_model, instruction, executor):
        try:
            value = schema_model.model_validate(candidate)
        except ValidationError as exc:
            error = IngestionError('MODEL_OUTPUT_INVALID', 'Model output did not match the typed JSON contract. The candidate is retained for repair or inspection.')
            error.validation_errors = [{'location':list(item['loc']), 'type':item['type'], 'message':item['msg']}
                for item in exc.errors(include_input=False, include_context=False)]
            error.allowed_paths = [pointer(item['location']) for item in error.validation_errors if item['location']]
            raise error from None
        if schema_model is FileDraft:
            errors = []
            metadata = instruction.get('reader_metadata')
            if metadata:
                locators = [*metadata.get('locators', []), *metadata.get('embedded_images', [])]
                bad = [i for i,row in enumerate(value.records) if not row.source_locator or
                       not any(re.search(re.escape(locator)+r'(?![A-Za-z0-9_-])', row.source_locator) for locator in locators)]
                if bad:
                    errors.append(IngestionError('OFFICE_PROVENANCE_INVALID', 'Office records must identify a supplied paragraph, cell or image locator. The candidate is retained; no source link was invented.'))
                pages = [f'/records/{i}/source_page' for i,row in enumerate(value.records) if row.source_page is not None]
                pages += [f'/records/{i}/additional_source_pages' for i,row in enumerate(value.records) if row.additional_source_pages]
                pages += [f'/project_info/{i}/source_page' for i,info in enumerate(value.project_info) if info.source_page is not None]
                pages += [f'/source_items/{i}/source_page' for i,item in enumerate(value.source_items) if item.source_page is not None]
                if pages:
                    error = IngestionError('OFFICE_PROVENANCE_INVALID', 'Unpaginated Office evidence has paragraph/cell locators, not rendered page numbers.')
                    error.allowed_paths = pages
                    errors.append(error)
            if instruction.get('extraction_contract') == 'MATERIAL_V2':
                try:
                    validate_material_extraction(value)
                except IngestionError as error:
                    errors.append(error)
            noncanonical = [i for i, row in enumerate(value.records) if row.quantity is not None and not PLAIN_DECIMAL.fullmatch(row.quantity)]
            if noncanonical:
                error = IngestionError('MODEL_OUTPUT_INVALID', 'Standardised quantities must use plain nonnegative decimal strings. Raw quantities remain unchanged.')
                error.allowed_paths = [f'/records/{i}/quantity' for i in noncanonical]
                errors.append(error)
            try:
                executor.validate_references(value)
            except IngestionError as error:
                if error.status >= 500:
                    raise
                error.allowed_paths = getattr(error, 'details', {}).get('invalid_reference_paths', [])
                errors.append(error)
            preparation = instruction.get('content_preparation')
            if preparation:
                try:
                    coverage = validate_pdf_coverage(value, instruction.get('numbered_source_items_by_page', {}), preparation['page_numbers'],
                        project_pages=list(range(1, preparation.get('page_count', len(preparation['page_numbers']))+1)))
                except IngestionError as error:
                    details = getattr(error, 'details', {})
                    paths = []
                    if 'expected_pages' in details:
                        paths.append('/page_coverage')
                    if details.get('missing_source_items'):
                        paths.append('/source_items/-' if value.extraction_version == 'MATERIAL_V2' else '/records/-')
                    invalid_pages = details.get('invalid_source_pages', [])
                    paths.extend(f'/records/{i}/source_page' for i, row in enumerate(value.records) if row.source_page in invalid_pages)
                    paths.extend(f'/records/{i}/additional_source_pages' for i, row in enumerate(value.records)
                                 if any(page in invalid_pages for page in row.additional_source_pages))
                    paths.extend(f'/source_items/{i}/source_page' for i, item in enumerate(value.source_items) if item.source_page in invalid_pages)
                    paths.extend(f'/project_info/{i}/source_page' for i, info in enumerate(value.project_info) if info.source_page in invalid_pages)
                    error.allowed_paths = paths
                    errors.append(error)
            if errors:
                raise combine_validation_errors(errors)
            if preparation:
                preparation['coverage_check'] = coverage
        elif schema_model is ReconciliationResult:
            validate_reconciliation(value, FileDraft.model_validate(instruction['extraction']), executor.reads)
        elif schema_model is BatchCrossCheck:
            known = {f['submission_id'] for f in instruction['files']}
            if any(set(f.submission_ids) - known for f in value.findings):
                raise IngestionError('MODEL_OUTPUT_INVALID', 'Cross-file findings referenced another batch.')
        return value

    def _repair_identity(self, instruction, schema_model):
        # Volatile observation timestamps and own-run tools/proposals do not
        # change the source. Source/context/configuration changes do.
        task = copy.deepcopy(instruction)
        for key in ('own_proposals', 'saved_terra_observations', 'context_observed_at', 'classification'):
            task.pop(key, None)
        if isinstance(task.get('content_preparation'), dict):
            task['content_preparation'].pop('coverage_check', None)
        return digest_json({'task': task, 'schema': schema_model.model_json_schema(),
                            'prompt': self.prompts.identity, 'settings': self.settings.public()})

    def _resumable_output(self, owner, instruction, schema_model):
        state = owner.repair_state
        if state and state.get('identity') == self._repair_identity(instruction, schema_model):
            return state
        return None

    def _accept_output(self, adapter, instruction, attachments, schema_model, schema, text, run, executor, persist, file, resume=None):
        history = file.response_history if file is not None else run.recovery_history
        recoveries = file.recoveries if file is not None else run.recovery_history
        owner = file or run
        if resume:
            candidate = copy.deepcopy(resume['candidate'])
            syntax_repaired = bool(resume.get('syntax_repaired'))
        else:
            candidate, syntax_repaired = None, False
            try:
                candidate, fenced = parse_object(text, recoveries=recoveries)
                if fenced:
                    recoveries.append({'stage':instruction['stage'], 'action':'REMOVED_JSON_CODE_FENCE'})
            except AmbiguousJSON as exc:
                error = IngestionError('MODEL_OUTPUT_AMBIGUOUS', 'Conflicting duplicate fields or nonfinite values cannot be resolved safely. The original response is retained for inspection.')
                error.final_output = text
                raise error from exc
            except (ValueError, TypeError):
                if schema_model is DocumentClassification:
                    error = IngestionError('MODEL_OUTPUT_INVALID', 'Classification did not return one valid JSON object.')
                    error.final_output = text
                    raise error
                # One syntax recovery opportunity; unchanged/invalid output is no progress.
                repaired = self._repair_call(adapter, {'stage':'REPAIR_OUTPUT', 'original_response':text,
                    'instruction':'Recover JSON syntax only, preserving all facts and records.',
                    'source_task':instruction}, attachments, schema, run, persist, history)
                syntax_repaired = True
                try:
                    candidate, _ = parse_object(repaired, recoveries=recoveries)
                    prefix = recoverable_record_prefix(text) if schema_model is FileDraft else []
                    if prefix and candidate.get('records', [])[:len(prefix)] != prefix:
                        raise ValueError('Syntax recovery changed complete original rows')
                except (ValueError, TypeError):
                    error = IngestionError('MODEL_REPAIR_NO_PROGRESS', 'JSON syntax repair did not produce a usable object. Original responses remain saved.')
                    error.final_output = repaired
                    raise error
        seen_errors = set()
        while True:
            if schema_model is FileDraft:
                evidence = json.dumps({key:instruction.get(key) for key in ('text','cells','batch_manifest')}, ensure_ascii=False)
                candidate, changes = normalise_quantities(candidate, evidence)
                recoveries.extend(changes)
            try:
                value = self._validate_output(candidate, schema_model, instruction, executor)
                if syntax_repaired:
                    recoveries.append({'action':'JSON_SYNTAX_REPAIRED', 'stage':instruction['stage']})
                owner.repair_state = None
                persist(run)
                return value
            except IngestionError as error:
                if schema_model is DocumentClassification:
                    error.final_output = encode(candidate)
                    raise
                paths = getattr(error, 'allowed_paths', [])
                # Raw source values are evidence, never inferred repairs. A malformed
                # raw field requires operator attention rather than rewriting it.
                protected = ('raw_description', 'raw_quantity', 'raw_unit', 'raw_fields', 'source_locator')
                paths = [path for path in paths if not any('/'+field in path for field in protected)]
                # Progress is fewer unresolved field paths / missing references, not
                # the model changing punctuation repeatedly on the same invalid field.
                signature = digest_json({'code':error.code, 'paths':sorted(paths), 'details':getattr(error,'details',{})})
                if not paths or signature in seen_errors:
                    error.final_output = encode(candidate)
                    if signature in seen_errors:
                        error.code = 'MODEL_REPAIR_NO_PROGRESS'
                        error.message = 'Targeted correction is not resolving the remaining defects. The complete candidate and original responses are retained; retry or inspect them.'
                    raise error
                seen_errors.add(signature)
                if file is not None:
                    file.processing_stage = 'REPAIRING'
                owner.repair_state = {'identity': self._repair_identity(instruction, schema_model),
                    'candidate': copy.deepcopy(candidate), 'original_response': text,
                    'syntax_repaired': syntax_repaired, 'stage': instruction['stage']}
                persist(run)
                repair_task = {'stage':'REPAIR_OUTPUT', 'candidate':candidate, 'allowed_paths':paths,
                    'validation_errors':getattr(error,'validation_errors',[]), 'error':_failure(error).model_dump(mode='json'),
                    'source_task':instruction,
                    'known_proposals':[p.model_dump(mode='json') for p in run.proposals]}
                try:
                    repaired = self._repair_call(adapter, repair_task, attachments, OutputCorrections.model_json_schema(), run, persist, history)
                except IngestionError as exc:
                    if exc.code.startswith('PROVIDER_'):
                        exc.final_output = encode(candidate)
                        raise
                    error.details = {**getattr(error, 'details', {}), 'repair_failure':_failure(exc).model_dump(mode='json')}
                    error.final_output = encode(candidate)
                    raise error from exc
                try:
                    patches, _ = parse_object(repaired, recoveries=recoveries)
                    corrections = OutputCorrections.model_validate(patches)
                    updated = apply_corrections(candidate, corrections, paths)
                    if '/records/-' in paths:
                        missing = {(item['page'], item['item_reference']) for item in error.details.get('missing_source_items', [])}
                        additions = updated['records'][len(candidate['records']):]
                        supplied = [(row.get('source_page'), row.get('source_item_ref')) for row in additions]
                        if len(set(supplied)) != len(supplied) or not set(supplied) <= missing:
                            raise ValueError('Only missing source items may be appended')
                    if '/source_items/-' in paths:
                        missing = {(item['page'], item['item_reference']) for item in error.details.get('missing_source_items', [])}
                        supplied = [(item.get('source_page'), item.get('source_item_ref')) for item in updated['source_items'][len(candidate.get('source_items', [])):]]
                        if len(set(supplied)) != len(supplied) or not set(supplied) <= missing:
                            raise ValueError('Only missing coverage entries may be appended')
                    if updated == candidate:
                        raise ValueError('No change')
                except (ValueError, TypeError, IngestionError) as exc:
                    stopped = IngestionError('MODEL_REPAIR_NO_PROGRESS', 'The correction was invalid, unchanged or outside its authorised fields. The candidate is retained.')
                    stopped.final_output = encode(candidate)
                    raise stopped from exc
                recoveries.append({'action':'TARGETED_CORRECTION', 'corrections':corrections.model_dump(mode='json')['corrections'],
                                   'before_digest':digest_json(candidate), 'after_digest':digest_json(updated)})
                candidate = updated
                owner.repair_state['candidate'] = copy.deepcopy(candidate)
                persist(run)

    def _repair_call(self, adapter, task, attachments, schema, run, persist, history):
        session = adapter.session(self.prompts.compose('REPAIR_OUTPUT'),
            encode({'task':task, 'required_json_schema':schema}), attachments, [], schema)
        try:
            turn = session.step()
        except ProviderError as exc:
            if hasattr(exc, 'usage'):
                exc.usage.stage = 'REPAIR_OUTPUT'
                exc.usage.submission_id = task.get('source_task', {}).get('submission_id')
                run.usage.append(exc.usage)
                persist(run)
            raise
        turn.usage.stage = 'REPAIR_OUTPUT'
        turn.usage.submission_id = task.get('source_task', {}).get('submission_id')
        run.usage.append(turn.usage)
        history.append({'stage':'REPAIR_OUTPUT', 'text':turn.text})
        persist(run)
        if turn.calls:
            raise IngestionError('MODEL_OUTPUT_INVALID', 'Response repair attempted an undeclared tool.')
        return turn.text

    def _reconcile(self, adapter, run, file, persist):
        from backend.app.services.document_groups import input_size, partition_records, CONTEXT_TOKENS, OUTPUT_TOKENS
        previous = file.reconciliation
        history = [] if previous is None else [*previous.previous_attempts,
            previous.model_dump(mode='json', exclude={'previous_attempts'})]
        result = ReconciliationAnalysis(attempt=1 if previous is None else previous.attempt + 1,
                                        previous_attempts=history, extraction_digest=digest_json(file.draft.model_dump(mode='json')))
        file.reconciliation = result
        file.processing_stage, result.status = 'RECONCILING', 'RUNNING'
        persist(run)
        reads = FrozenTerraReads(self.intake.reads)
        executor = ToolExecutor(run, reads, persist)
        try:
            refs = [*file.draft.project_refs, *(row.project_ref for row in file.draft.records),
                    *(info.project_ref for info in file.draft.project_info)]
            project_ids = sorted({ref.id for ref in refs if ref and ref.kind == 'EXISTING'})
            result.project_context = {project_id: reads.call('get_project_context', {'project_id': project_id})
                                      for project_id in project_ids}
            result.observed_at = now()
            result.context_digest = digest_json(result.project_context)
            if previous and previous.context_digest == result.context_digest and previous.extraction_digest == result.extraction_digest:
                result.group_results = dict(previous.group_results)
                result.repair_state = copy.deepcopy(previous.repair_state)
                if previous.result is not None and previous.error is None:
                    validate_reconciliation(previous.result, file.draft, reads)
                    result.result = previous.result.model_copy(deep=True)
                    result.status, result.processing_stage = 'SUCCEEDED', 'REUSED_AFTER_CURRENT_CONTEXT_CHECK'
                    file.processing_stage = 'COMPLETE'
                    persist(run)
                    return
            extraction = file.draft.model_dump(mode='json')
            rows = extraction.pop('records')
            extraction['source_items'] = []  # Coverage already verified; no duplicate full-file ledger.
            task = {'stage': 'RECONCILE_FILE', 'submission_id': file.submission_id,
                    'extraction': {**extraction, 'records': []},
                    'current_project_context': result.project_context,
                    'context_observed_at': result.observed_at.isoformat(),
                    'own_proposals': [p.model_dump(mode='json') for p in run.proposals]}
            available = CONTEXT_TOKENS - OUTPUT_TOKENS - 16384 - input_size(tool_definitions()) - input_size(ReconciliationResult.model_json_schema())
            if input_size(task) >= available:
                task['own_proposals'] = []
                task['current_project_context'] = {key: {**{k:v for k,v in value.items() if k != 'collections'},
                    'collection_counts': {collection: len(items) for collection, items in value.get('collections', {}).items()},
                    'delivery': 'Full stored records are available through paginated Terra read tools; no relevance shortlist was applied.'}
                    for key, value in result.project_context.items()}
                task['draft_context_delivery'] = 'All own-run proposals remain accessible through get_run_draft_context.'
            parts = partition_records(rows, available - input_size(task))
            combined = ReconciliationResult(summary='')
            for number, indices in enumerate(parts):
                part_task = {**task, 'extraction': {**extraction, 'records': [rows[i] for i in indices]},
                             'comparison_part': {'number': number+1, 'total': len(parts), 'original_record_indices': indices}}
                key = digest_json({'task': {k:v for k,v in part_task.items() if k != 'context_observed_at'},
                                   'prompt': self.prompts.identity})
                result.processing_stage = f'COMPARING_PART_{number+1}_OF_{len(parts)}'
                persist(run)
                check = result.group_results.get(key)
                if check is None:
                    check = self._conversation(adapter, part_task, [], ReconciliationResult, run, executor, persist,
                                               read_only=True, file=result)
                    result.group_results[key] = check
                    persist(run)
                if check.summary not in combined.summary:
                    combined.summary += ('\n' if combined.summary else '') + check.summary
                if not combined.projects:
                    combined.projects = [p.model_copy(deep=True) for p in check.projects]
                else:
                    for project in check.projects:
                        target = next(p for p in combined.projects if p.project_info_index == project.project_info_index)
                        if project.explanation != target.explanation:
                            target.explanation += '\n' + project.explanation
                        target.issues = list(dict.fromkeys([*target.issues, *project.issues]))
                for relationship in check.materials:
                    copied = relationship.model_copy(deep=True)
                    copied.record_index = indices[copied.record_index]
                    combined.materials.append(copied)
                combined.issues = list(dict.fromkeys([*combined.issues, *check.issues]))
            validate_reconciliation(combined, file.draft, reads)
            result.result, result.status = combined, 'SUCCEEDED'
            file.processing_stage = 'COMPLETE'
        except Exception as exc:
            result.error, result.status = _failure(exc), 'FAILED'
            file.processing_stage = 'RECONCILIATION_NEEDS_ATTENTION'
        persist(run)

    def _batch_check(self, adapter, task, run, executor, persist):
        from itertools import combinations
        from backend.app.services.document_groups import input_size, partition_records, CONTEXT_TOKENS, OUTPUT_TOKENS
        available = CONTEXT_TOKENS - OUTPUT_TOKENS - input_size(BatchCrossCheck.model_json_schema()) - 16384
        if input_size(task) < available:
            run.batch_check_progress = {'completed': 0, 'total': 1}
            value = self._conversation(adapter, task, [], BatchCrossCheck, run, executor, persist, tools=False)
            run.batch_check_progress = {'completed': 1, 'total': 1}
            return value
        base = {key:value for key,value in task.items() if key not in ('files','own_proposals','initial_terra_context')}
        chunks = []
        for source in task['files']:
            view = copy.deepcopy(source)
            draft = view.get('draft')
            if not draft:
                chunks.append(view)
                continue
            records = draft.pop('records')
            draft['source_items'] = []
            if view.get('reconciliation'):
                comparison = view['reconciliation']
                comparison.pop('group_results', None)
                if comparison.get('result'):
                    comparison['result'] = {k:v for k,v in comparison['result'].items() if k != 'materials'}
            capacity = (available - input_size(base)) // 2 - input_size(view) - 1024
            for indices in partition_records(records, capacity):
                part = copy.deepcopy(view)
                part['draft']['records'] = [records[i] for i in indices]
                part['original_record_indices'] = indices
                chunks.append(part)
        pairs = combinations(range(len(chunks)), 2) if len(chunks) > 1 else [(0,)]
        total = len(chunks)*(len(chunks)-1)//2 if len(chunks)>1 else 1
        run.batch_check_progress = {'completed': 0, 'total': total}
        combined = BatchCrossCheck(summary='')
        seen = set()
        for pair in pairs:
            part_task = {**base, 'files': [chunks[i] for i in pair], 'scope': 'Connected exhaustive pairwise evidence portions, not a complete batch in one request. Report supported relationships within supplied evidence.'}
            key = digest_json({'task': part_task, 'prompt': self.prompts.identity})
            checked = run.batch_check_parts.get(key)
            if checked is None:
                checked = self._conversation(adapter, part_task, [], BatchCrossCheck, run, executor, persist, tools=False)
                run.batch_check_parts[key] = checked
            for finding in checked.findings:
                identity = digest_json(finding.model_dump(mode='json'))
                if identity not in seen:
                    combined.findings.append(finding)
                    seen.add(identity)
            run.batch_check_progress['completed'] += 1
            persist(run)
        combined.summary = 'Completed cross-check of all evidence portions; findings remain provisional for human review.'
        return combined

    def _worker(self, batch_id, comparison_id, run_id, spec, reads):
        adapter, run, persist = None, None, None
        try:
            with self._job_lock(run_id):
                batch = self.intake.get(batch_id)
                comparison = self._find(batch, comparison_id)
                run = next(r for r in comparison.runs if r.id == run_id).model_copy(deep=True)
                if run.status != "PENDING":
                    return
                persist = lambda value: self._persist(batch_id, comparison_id, value)
                run.status = "RUNNING"
                persist(run)
                try:
                    adapter = self.provider_factory(spec)
                    adapter.check_availability()
                except Exception as exc:
                    for file in run.files:
                        if file.status != "SUCCEEDED":
                            file.status, file.error = "FAILED", _failure(exc)
                        elif file.reconciliation and file.reconciliation.status != 'SUCCEEDED':
                            file.reconciliation.status, file.reconciliation.error = 'FAILED', _failure(exc)
                    run.status = "FAILED" if not any(f.status == "SUCCEEDED" for f in run.files) else "PARTIAL"
                    persist(run)
                    return
                executor = ToolExecutor(run, reads, persist)
                submissions = {s.id: s for s in batch.submissions}
                for file in run.files:
                    if submissions[file.submission_id].resolution != 'ANALYSE':
                        continue
                    if run.retry_submission_ids is not None and file.submission_id not in run.retry_submission_ids:
                        continue
                    if file.status == "SUCCEEDED":
                        if file.draft and file.draft.extraction_version == 'MATERIAL_V2' and (file.reconciliation is None or file.reconciliation.status != 'SUCCEEDED'):
                            self._reconcile(adapter, run, file, persist)
                        continue
                    file.status, file.error, file.unvalidated_output, file.preparation = "RUNNING", None, None, None
                    executor.start_file()
                    if not file.repair_state:
                        file.classification = None
                        file.response_history, file.recoveries = [], []
                    file.prompt_manifest = dict(self.prompts.manifest)
                    file.processing_stage = "PREPARING"
                    file.prompt_version = PROMPT_VERSION
                    file.attempt += 1
                    persist(run)
                    try:
                        source = submissions[file.submission_id].source
                        path = self.intake.store.path(source)
                        prepared = InitialContentReader().prepare(source, path)
                        attachments = list(prepared.attachments)
                        file.reader_metadata = prepared.metadata or None
                        pdf = None
                        reference_audit = {}
                        if prepared.kind == "UNSUPPORTED":
                            raise IngestionError("UNSUPPORTED_FORMAT", " ".join(prepared.issues))
                        if prepared.kind == 'NATIVE_CANDIDATE' and spec.provider == 'deepseek':
                            from backend.app.services.document_analysis import analyse_document
                            draft = analyse_document(self, adapter, run, file, source, path, comparison, executor, persist)
                            file.draft, file.status, file.processing_stage = draft, 'SUCCEEDED', 'EXTRACTED'
                            persist(run)
                            self._reconcile(adapter, run, file, persist)
                            continue
                        if prepared.kind == "NATIVE_CANDIDATE":
                            if prepared.media_type not in ('application/pdf', 'image/png', 'image/jpeg'):
                                raise IngestionError('PROVIDER_INPUT_UNSUPPORTED', 'This image format is prepared for DeepSeek only; this Gemini input path has not been verified.')
                            if prepared.media_type == "application/pdf":
                                pdf = PdfPreparer().prepare(path)
                                prepared_text = pdf.text
                                reference_audit = {page: numbered_table_references(text) for page, text in pdf.page_texts.items()}
                                attachments.append({"media_type": prepared.media_type, "data": path.read_bytes()})
                                file.preparation = {**pdf.evidence, "strategy": "NATIVE_PDF_WITH_TEXT_COVERAGE_AUDIT"}
                                persist(run)
                            else:
                                attachments.append({"media_type": prepared.media_type, "data": path.read_bytes()})
                                prepared_text = prepared.text
                        else:
                            prepared_text = prepared.text
                        task = {"stage": "INTERPRET_FILE", "submission_id": file.submission_id,
                                'extraction_contract': 'MATERIAL_V2',
                                "source": source.model_dump(mode="json"), "text": prepared_text, "cells": prepared.cells,
                                'reader_metadata': file.reader_metadata,
                                'reader_instruction': 'Local readers supply evidence only. Preserve exact sheet/cell or paragraph/package source locators, with source_page=null for unpaginated Office input. Do not execute formulas or treat formula text/missing caches as numeric quantities. Hidden cells and embedded images are source context, not additional duplicated quantities.',
                                "content_preparation": file.preparation,
                                "numbered_source_items_by_page": reference_audit,
                                "batch_manifest": comparison.manifest, "initial_terra_context": comparison.initial_context,
                                'operator_file_resolutions':comparison.configuration.get('file_resolutions', {}),
                                "own_proposals": [p.model_dump(mode="json") for p in run.proposals],
                                "previous_successful_file_drafts": [self._file_context(f) for f in run.files if f.status == "SUCCEEDED" and submissions[f.submission_id].resolution == 'ANALYSE'],
                                "saved_terra_observations": [o.model_dump(mode="json") for o in run.observations]}
                        if self._resumable_output(file, task, FileDraft) and file.classification:
                            modules = file.classification.selected_modules
                        else:
                            modules = self._classify(adapter, task, attachments, run, executor, persist, file)
                        task['classification'] = file.classification.model_dump(mode='json', exclude={'usage','raw_response'})
                        file.processing_stage = 'EXTRACTING'
                        persist(run)
                        draft = self._conversation(adapter, task, attachments, FileDraft, run, executor, persist,
                            system=self.prompts.compose('INTERPRET_FILE', modules), file=file)
                        if file.classification.result is not None:
                            family = file.classification.result.primary_family
                            expected = family if family in ('BOQ', 'PURCHASE_ORDER', 'INVENTORY', 'DEMAND', 'MIXED') else 'OTHER'
                            if draft.document_type != expected:
                                file.classification.warnings.append(f'Extraction interpreted document_type={draft.document_type}, differing from classification family={family}. Verify the document meaning.')
                        file.draft, file.status, file.processing_stage = draft, "SUCCEEDED", "EXTRACTED"
                    except Exception as exc:
                        file.status, file.error = "FAILED", _failure(exc)
                        file.unvalidated_output = getattr(exc, "final_output", None)
                        file.processing_stage = "NEEDS_ATTENTION"
                    persist(run)
                    if file.status == 'SUCCEEDED':
                        self._reconcile(adapter, run, file, persist)
                try:
                    # Cross-check successful drafts together even when another file failed.
                    task = {"stage": "CROSS_CHECK_BATCH", "instruction": "Flag possible overlaps, revisions/conflicts and shared context. Never merge quantities or change drafts automatically. Include failed-file gaps.",
                            "files": [self._file_context(f) for f in run.files if submissions[f.submission_id].resolution == 'ANALYSE'],
                            'operator_file_resolutions': {s.id:s.resolution for s in batch.submissions if s.resolution != 'ANALYSE'},
                            'operator_review_context': self._review_context(batch),
                            'authority': 'Operator review is provisional context, not accepted database facts. Never overwrite edits or approve values. Manual values have no document provenance.',
                            "own_proposals": [p.model_dump(mode="json") for p in run.proposals],
                            "initial_terra_context": comparison.initial_context, "batch_manifest": comparison.manifest}
                    if any(f.status == "SUCCEEDED" for f in run.files):
                        check = self._batch_check(adapter, task, run, executor, persist)
                        known = {f.submission_id for f in run.files}
                        if any(set(f.submission_ids) - known for f in check.findings):
                            raise IngestionError("MODEL_OUTPUT_INVALID", "Cross-file findings referenced another batch's files.")
                        run.cross_check, run.cross_check_error = check, None
                except Exception as exc:
                    run.cross_check_error = _failure(exc)
                active_files = [f for f in run.files if submissions[f.submission_id].resolution == 'ANALYSE']
                succeeded = sum(f.status == "SUCCEEDED" for f in active_files)
                reconciled = all(f.draft is None or f.draft.extraction_version != 'MATERIAL_V2' or
                                 f.reconciliation is not None and f.reconciliation.status == 'SUCCEEDED' for f in active_files)
                run.status = "SUCCEEDED" if succeeded == len(active_files) and reconciled and run.cross_check is not None and run.cross_check_error is None else "PARTIAL" if succeeded else "FAILED"
                persist(run)
        except Timeout:
            return  # Another process owns this job; never send a second paid request.
        except Exception:
            # No unsafe automatic retry after process/storage failure. Persisted progress remains inspectable.
            return
        finally:
            if adapter is not None and hasattr(adapter, 'close'):
                try:
                    cleanup = adapter.close()
                except Exception:
                    cleanup = {'status': 'RETRY_PENDING', 'expiration_seconds': 86400}
                if run is not None and persist is not None:
                    run.provider_cleanup = cleanup
                    try:
                        persist(run)
                    except Exception:
                        pass  # The private upload journal/expiration still enables cleanup.

    def retry(self, batch_id, comparison_id, run_id, request):
        batch = self.intake.get(batch_id)
        comparison = self._find(batch, comparison_id)
        run = next((r for r in comparison.runs if r.id == run_id), None)
        if run is None:
            raise IngestionError("ANALYSIS_RUN_NOT_FOUND", "This run does not belong to the comparison.", 404)
        if request.idempotency_key in run.retry_keys:
            if run.retry_fingerprints.get(request.idempotency_key, digest_json(request.model_dump(mode='json'))) != digest_json(request.model_dump(mode='json')):
                raise IngestionError('IDEMPOTENCY_KEY_REUSED', 'This retry key was used with different input.')
            return self.get(batch_id, comparison_id)
        if self.worker_active(run_id) or (run.status == "PENDING" and run.worker_instance_id == WORKER_INSTANCE_ID):
            raise IngestionError("ANALYSIS_ALREADY_RUNNING", "This model run still has an active worker.")
        if (self.manifest(batch) != comparison.manifest or batch.context.refresh_required
                or comparison.configuration.get("context_epoch", 0) != batch.context.epoch):
            raise IngestionError("ANALYSIS_INPUT_CHANGED", "Inputs or database context changed. Refresh context and request a new comparison; old drafts are retained.")
        pending = {f.submission_id for f in run.files if f.status != 'SUCCEEDED' or not f.reconciliation or f.reconciliation.status != 'SUCCEEDED'}
        active = {s.id for s in batch.submissions if s.resolution == 'ANALYSE'}
        if run.status == "SUCCEEDED" and not pending & active:
            raise IngestionError("ANALYSIS_ALREADY_SUCCEEDED", "This run has no failed work to retry.")
        if not self.settings.enabled:
            raise IngestionError("MODELS_DISABLED", "Enable models locally before retrying.", 503)
        if request.submission_ids is not None and (len(set(request.submission_ids)) != len(request.submission_ids) or not set(request.submission_ids) <= pending & active):
            raise IngestionError('RETRY_SELECTION_INVALID', 'Choose unresolved files from this model run only.', 422)
        def edit(current):
            target = next(r for r in self._find(current, comparison_id).runs if r.id == run_id)
            target.previous_attempts.append({"files": [f.model_dump(mode="json") for f in target.files],
                "cross_check": target.cross_check.model_dump(mode="json") if target.cross_check else None,
                "cross_check_error": target.cross_check_error.model_dump(mode="json") if target.cross_check_error else None})
            target.status = "PENDING"
            target.worker_instance_id = WORKER_INSTANCE_ID
            target.cross_check, target.cross_check_error = None, None
            target.retry_keys.append(request.idempotency_key)
            target.retry_fingerprints[request.idempotency_key] = digest_json(request.model_dump(mode='json'))
            target.retry_submission_ids = request.submission_ids
            for file in target.files:
                if file.status != "SUCCEEDED" and (request.submission_ids is None or file.submission_id in request.submission_ids):
                    file.status = "PENDING"
        self.intake._edit(batch_id, request.expected_revision, edit)
        reads = FrozenTerraReads(self.intake.reads)
        spec = next(s for s in self.settings.models if s.slot == run.model_slot)
        self.schedule(self._worker, batch_id, comparison_id, run_id, spec, reads)
        return self.get(batch_id, comparison_id)

    @staticmethod
    def _review_context(batch):
        if batch.review is None:
            return None
        return {'submissions': [{'id':s.id, 'kind':s.kind, 'resolution':s.resolution,
                    'projects':[p.current.model_dump(mode='json') for p in s.projects],
                    'rows':[{'id':r.id, 'current':r.current.model_dump(mode='json'), 'decision':r.decision,
                             'edited_by_operator':r.edited_by_operator, 'provenance':r.provenance} for r in s.rows]}
                for s in batch.review.submissions]}
