"""Connected page-group interpretation using the existing provisional pipeline."""

from backend.app.schemas.analysis import PageGroupAnalysis, FileDraft
from backend.app.services.analysis_coverage import numbered_table_references, validate_pdf_coverage
from backend.app.services.analysis_reconciliation import validate_material_extraction
from backend.app.services.analysis_tools import tool_definitions
from backend.app.services.document_groups import plan_pages, input_size, assemble, CONTEXT_TOKENS, OUTPUT_TOKENS
from backend.app.services.document_preparation import prepare_document
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_storage import digest_json


CAPACITY_ERRORS = {'MODEL_INPUT_TOO_LARGE', 'MODEL_OUTPUT_LIMIT', 'PROVIDER_REQUEST_TOO_LARGE'}


def analyse_document(service, adapter, run, file, source, path, comparison, executor, persist):
    from backend.app.services.analysis_service import _failure, PROMPT_VERSION
    def progress(value):
        file.preparation = {'version': 'deepseek-disk-pages.v2', 'strategy': 'DISK_PAGES_WITH_FILE_REFERENCES',
                            'pages': [], 'page_numbers': [], 'pages_with_text': 0, 'all_pages_included': False, **value}
        persist(run)
    document = prepare_document(path, progress=progress)
    file.preparation = document.evidence()
    def uploaded(event):
        file.processing_stage = 'UPLOADING_PAGE_IMAGES' if event['uploading'] else 'READING_PAGE_GROUP'
        if 'uploaded_in_run' in event:
            file.preparation['images_uploaded_in_run'] = event['uploaded_in_run']
        persist(run)
    adapter.file_progress = uploaded
    persist(run)
    common = {'stage': 'INTERPRET_FILE', 'submission_id': file.submission_id,
              'extraction_contract': 'MATERIAL_V2', 'source': source.model_dump(mode='json'),
              'batch_manifest': comparison.manifest, 'initial_terra_context': comparison.initial_context,
              'previous_successful_file_drafts': [{'submission_id': f.submission_id, 'summary': f.draft.summary,
                  'project_info': [p.model_dump(mode='json') for p in f.draft.project_info],
                  'material_count': len(f.draft.records)} for f in run.files if f.status == 'SUCCEEDED'],
              'context_delivery': 'Other accepted file records and all run proposals remain accessible through get_run_draft_context.'}
    overhead = input_size(common) + input_size(tool_definitions()) + input_size(FileDraft.model_json_schema()) + sum(len(t.encode()) for t in service.prompts.texts.values())
    if overhead + OUTPUT_TOKENS >= CONTEXT_TOKENS:
        common['initial_terra_context'] = {key: {**{k:v for k,v in value.items() if k != 'collections'},
            'collection_counts': {name:len(rows) for name,rows in value.get('collections', {}).items()},
            'delivery': 'Full records available through paginated Terra read tools; not a ranked shortlist.'}
            for key,value in comparison.initial_context.items()}
        overhead = input_size(common) + input_size(tool_definitions()) + input_size(FileDraft.model_json_schema()) + sum(len(t.encode()) for t in service.prompts.texts.values())
    identity = digest_json({'source': source.sha256, 'prompt': service.prompts.identity, 'settings': service.settings.public(), 'comparison_input': comparison.input_digest})
    planned = plan_pages(document, overhead=overhead)
    prior = {g.id: g for g in file.page_groups}
    def group(numbers):
        key = f'PG-{numbers[0]:06}-{numbers[-1]:06}'
        saved = prior.get(key)
        expected = digest_json({'document': identity, 'pages': numbers})
        if saved and saved.input_digest == expected:
            return saved
        fresh = PageGroupAnalysis(id=key, submission_id=file.submission_id, page_numbers=numbers, input_digest=expected)
        if saved:
            fresh.previous_attempts = [saved.model_dump(mode='json', exclude={'previous_attempts'}), *saved.previous_attempts]
        return fresh
    if not file.page_groups or any(g.input_digest != digest_json({'document': identity, 'pages': g.page_numbers}) for g in file.page_groups):
        file.page_groups = [group(numbers) for numbers in planned]
    index = 0
    accepted = []
    while index < len(file.page_groups):
        part = file.page_groups[index]
        if part.status == 'SPLIT':
            index += 1
            continue
        if part.status == 'SUCCEEDED':
            accepted.append(part)
            file.classification = file.classification or part.classification
            index += 1
            continue
        if part.attempt:
            part.previous_attempts.append(part.model_dump(mode='json', exclude={'previous_attempts'}))
        part.attempt += 1
        part.status, part.error, part.draft, part.unvalidated_output = 'RUNNING', None, None, None
        if not part.repair_state:
            part.response_history, part.recoveries = [], []
        part.prompt_version, part.prompt_manifest = PROMPT_VERSION, dict(service.prompts.manifest)
        file.processing_stage = 'READING_PAGE_GROUP'
        part.processing_stage = 'CLASSIFYING'
        numbers = part.page_numbers
        context_pages = [numbers[0] - 1] if numbers[0] > 1 else []
        views = [*context_pages, *numbers]
        # If overlap itself breaches real request constraints, omit the image overlap,
        # while retaining the preceding saved boundary records and source text.
        attachments = document.attachments(views)
        if len(attachments) > 600 or sum(a['byte_size'] for a in attachments) > 200 * 1024 * 1024:
            attachments = document.attachments(numbers)
        part.preparation = {'page_count': len(document.pages), 'page_numbers': numbers,
                            'context_page_numbers': context_pages, 'version': file.preparation['version']}
        previous = accepted[-1] if accepted else None
        boundary = [] if previous is None else [
            {'record_ref': f'{previous.id}:{i}', 'record': row.model_dump(mode='json')}
            for i, row in enumerate(previous.draft.records) if row.source_page == previous.page_numbers[-1]]
        project_info = [p.model_dump(mode='json') for saved in accepted for p in saved.draft.project_info]
        projects = list({digest_json(p): p for p in project_info}.values())
        proposals = [p.model_dump(mode='json') for p in run.proposals]
        if overhead + input_size(proposals) > CONTEXT_TOKENS - OUTPUT_TOKENS:
            proposals = []
        task = {**common, 'text': document.text_for(views), 'cells': None, 'content_preparation': part.preparation,
                'numbered_source_items_by_page': {n: numbered_table_references(document.text(n)) for n in numbers},
                'own_proposals': proposals, 'document_projects': projects, 'boundary_records': boundary,
                'page_group': {'id': part.id, 'owned_pages': numbers, 'context_pages': context_pages},
                'saved_terra_observations': []}
        request_overhead = input_size(tool_definitions()) + input_size(FileDraft.model_json_schema()) + sum(len(t.encode()) for t in service.prompts.texts.values())
        if input_size(task) + len(attachments)*1024 + request_overhead + OUTPUT_TOKENS > CONTEXT_TOKENS:
            task['own_proposals'] = []
            task['draft_context_delivery'] = 'Full own-run proposal evidence is available with get_run_draft_context.'
        persist(run)
        try:
            if service._resumable_output(part, task, FileDraft) and part.classification:
                modules = part.classification.selected_modules
            else:
                modules = service._classify(adapter, task, attachments, run, executor, persist, part)
            file.classification = file.classification or part.classification
            task['classification'] = part.classification.model_dump(mode='json', exclude={'usage', 'raw_response'})
            part.processing_stage = 'EXTRACTING'
            executor.start_file()
            draft = service._conversation(adapter, task, attachments, FileDraft, run, executor, persist,
                system=service.prompts.compose('INTERPRET_FILE', modules), file=part)
            part.draft, part.status, part.processing_stage = draft, 'SUCCEEDED', 'COMPLETE'
            accepted.append(part)
            if getattr(adapter, 'files', None):
                adapter.files.retain([item['path'] for item in document.attachments([numbers[-1]])])
        except IngestionError as exc:
            part.error, part.status = _failure(exc), 'FAILED'
            part.unvalidated_output = getattr(exc, 'final_output', None)
            part.processing_stage = 'NEEDS_ATTENTION'
            if exc.code in CAPACITY_ERRORS and len(numbers) > 1:
                middle = len(numbers) // 2
                part.status = 'SPLIT'
                file.page_groups[index+1:index+1] = [group(numbers[:middle]), group(numbers[middle:])]
            else:
                persist(run)
                raise
        persist(run)
        index += 1
    result = assemble(accepted)
    if file.classification and len(accepted) > 1:
        warning = 'Classification is per page group. The complete-file document type is assembled from material-bearing groups; inspect group classifications for mixed content.'
        if warning not in file.classification.warnings:
            file.classification.warnings.append(warning)
    validate_material_extraction(result)
    executor.validate_references(result)
    file.preparation['coverage_check'] = validate_pdf_coverage(result,
        {p['page_number']: numbered_table_references(document.text(p['page_number'])) for p in document.pages},
        list(range(1, len(document.pages)+1)))
    file.preparation['groups_complete'] = len(accepted)
    persist(run)
    return result

