"""Batched source-link correction and durable repair retry, without live models."""
import json
import unittest

from backend.app.schemas.analysis import AnalysisRun, FileAnalysis, FileDraft
from backend.app.services.analysis_providers import ProviderError, ProviderTurn
from backend.app.services.analysis_reconciliation import validate_material_extraction
from backend.app.services.analysis_tools import FrozenTerraReads, ToolExecutor
from backend.app.services.ingestion_errors import IngestionError
from tests import test_analysis as fixtures


def candidate(count=3):
    records = [{'raw_description': f'Generic item {i}', 'quantity_basis': 'MATERIAL',
                'raw_quantity': str(i+1), 'quantity': str(i+1), 'unit': 'pcs',
                'source_page': page, 'source_item_ref': f'X{i:02d}'}
               for page in (1, 2) for i in range(count)]
    ledger = [{'source_page': page, 'source_item_ref': f'X{i:02d}', 'disposition': 'MATERIAL',
               'record_indices': [i, count+i] if page == 1 else [count+i],
               'explanation': f'Generic page {page} item {i}'}
              for page in (1, 2) for i in range(count)]
    return {'extraction_version': 'MATERIAL_V2', 'document_type': 'OTHER', 'summary': 'Generic diagnostic',
            'records': records, 'source_items': ledger, 'page_coverage': [1, 2]}


def task():
    return {'stage': 'INTERPRET_FILE', 'submission_id': 'SUB-diagnostic',
            'extraction_contract': 'MATERIAL_V2', 'text': 'Generic diagnostic source',
            'cells': None, 'batch_manifest': {}, 'own_proposals': [],
            'content_preparation': {'page_numbers': [1, 2], 'page_count': 2},
            'numbered_source_items_by_page': {}}


def patches(paths):
    return {'corrections': [{'path': path, 'op': 'SET',
                            'value_json': json.dumps([int(path.split('/')[2])])} for path in paths]}


def office_candidate():
    # One document item can supply both released stock and retained local need.
    records = [{'raw_description': f'Diagnostic material observation {i}',
                'quantity_basis': 'MATERIAL', 'raw_quantity': str(i+1),
                'quantity': str(i+1), 'unit': 'pcs', 'source_page': None,
                'source_locator': 'word/document.xml#paragraph-1'} for i in range(3)]
    return {'extraction_version': 'MATERIAL_V2', 'document_type': 'OTHER',
            'summary': 'Generic unpaginated diagnostic', 'records': records,
            'source_items': [
                {'source_page': None, 'source_item_ref': 'SR-01', 'disposition': 'MATERIAL',
                 'record_indices': [0, 1], 'explanation': 'Two meanings from one source item'},
                {'source_page': None, 'source_item_ref': 'SR-02', 'disposition': 'MATERIAL',
                 'record_indices': [2], 'explanation': 'Another material item'}]}


def office_task():
    return {**task(), 'content_preparation': None, 'numbered_source_items_by_page': {},
            'reader_metadata': {'format': 'DOCX', 'locators': ['word/document.xml#paragraph-1'],
                                'embedded_images': []}}


class BatchedRepairTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AnalysisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service
        self.file = FileAnalysis(submission_id='SUB-diagnostic')
        self.run = AnalysisRun(id='AIR-diagnostic', model_slot='deepseek_flash', model_id='deepseek-flash', files=[self.file])
        self.executor = ToolExecutor(self.run, FrozenTerraReads(fixtures.ModelReads()), lambda _: None)

    def converse(self, adapter, instruction=None):
        return self.service._conversation(adapter, instruction or task(), [], FileDraft,
            self.run, self.executor, lambda _: None, file=self.file,
            system=self.service.prompts.compose('INTERPRET_FILE', ['families/generic.md']))

    def test_collects_all_source_link_errors_in_one_validation(self):
        with self.assertRaises(IngestionError) as caught:
            validate_material_extraction(FileDraft.model_validate(candidate(15)))
        self.assertEqual(set(caught.exception.allowed_paths),
                         {f'/source_items/{i}/record_indices' for i in range(15)})
        self.assertEqual(len(caught.exception.validation_errors), 15)

    def test_missing_office_row_references_authorise_only_affected_source_fields(self):
        with self.assertRaises(IngestionError) as caught:
            validate_material_extraction(FileDraft.model_validate(office_candidate()))
        paths = set(caught.exception.allowed_paths)
        self.assertEqual(paths, {'/source_items/0/record_indices', '/source_items/1/record_indices',
                                '/records/0/source_item_ref', '/records/1/source_item_ref',
                                '/records/2/source_item_ref'})

    def test_office_reference_repair_preserves_all_other_evidence_and_shared_item(self):
        original = office_candidate()
        seen = []
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; seen.append(value)
                answer = original
                if value['stage'] == 'REPAIR_OUTPUT':
                    self.assertFalse(tools)
                    answer = {'corrections': [
                        {'op': 'SET', 'path': f'/records/{i}/source_item_ref',
                         'value_json': json.dumps(item['source_item_ref'])}
                        for item in original['source_items'] for i in item['record_indices']]}
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        result = self.converse(Adapter(), office_task())
        self.assertEqual(sum(value['stage'] == 'REPAIR_OUTPUT' for value in seen), 1)
        expected = FileDraft.model_validate(original).model_dump(mode='json')
        expected['records'][0]['source_item_ref'] = 'SR-01'
        expected['records'][1]['source_item_ref'] = 'SR-01'
        expected['records'][2]['source_item_ref'] = 'SR-02'
        self.assertEqual(result.model_dump(mode='json'), expected)
        self.assertIsNone(self.file.repair_state)

    def test_office_reference_repair_cannot_change_quantity_or_original_locator(self):
        original = office_candidate()
        for field, value_json in [('quantity', '"999"'), ('source_locator', '"invented"')]:
            with self.subTest(field=field):
                class Adapter:
                    def session(inner, system, instruction, attachments, tools, schema):
                        value = json.loads(instruction)['task']
                        answer = original if value['stage'] == 'INTERPRET_FILE' else {
                            'corrections': [{'path': f'/records/0/{field}', 'value_json': value_json}]}
                        class Session:
                            def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                        return Session()
                with self.assertRaises(IngestionError) as caught:
                    self.converse(Adapter(), office_task())
                self.assertEqual(caught.exception.code, 'MODEL_REPAIR_NO_PROGRESS')
                self.assertEqual(self.file.repair_state['candidate'], original)
                self.assertIsNone(self.file.draft)

    def test_office_reference_correction_is_fully_revalidated(self):
        original = office_candidate()
        repairs = []
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']
                answer = original
                if value['stage'] == 'REPAIR_OUTPUT':
                    repairs.append(value)
                    answer = {'corrections': [] if len(repairs) > 1 else [
                        {'op': 'SET', 'path': '/records/0/source_item_ref', 'value_json': '"WRONG-ITEM"'}]}
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        with self.assertRaises(IngestionError):
            self.converse(Adapter(), office_task())
        self.assertEqual(len(repairs), 2, 'A changed reference is not accepted without full validation')
        self.assertIsNone(self.file.draft)
        self.assertIsNotNone(self.file.repair_state)

    def test_targeted_office_retry_preserves_other_successes_and_original_failure(self):
        import io
        from dataclasses import replace
        from backend.app.schemas.analysis import AnalyseRequest, RetryAnalysisRequest
        from tests.test_office_readers import package, word_parts, excel_parts
        fixture = self.fixture
        fixture.service.settings = replace(fixture.service.settings, models=(fixture.service.settings.models[-1],))
        batch = fixture.intake.create('PRJ-001')
        release_parts = word_parts()
        release_parts['word/document.xml'] = release_parts['word/document.xml'].replace('Diagnostic title', 'Different diagnostic title')
        fixture.intake.add_files(batch.id, batch.revision, [
            ('technical.docx', io.BytesIO(package(word_parts()))),
            ('release.docx', io.BytesIO(package(release_parts))),
            ('requirements.xlsx', io.BytesIO(package(excel_parts())))])
        source = fixture.intake.get(batch.id).submissions[1]
        original, seen, retrying = office_candidate(), [], [False]
        class Adapter(fixtures.ScriptedAdapter):
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; seen.append(value)
                source_task = value.get('source_task', value)
                if source_task.get('submission_id') != source.id or value['stage'] not in ('INTERPRET_FILE', 'REPAIR_OUTPUT'):
                    return super().session(system, instruction, attachments, tools, schema)
                answer = original
                if value['stage'] == 'REPAIR_OUTPUT':
                    answer = {'corrections': [] if not retrying[0] else [
                        {'op': 'SET', 'path': f'/records/{i}/source_item_ref',
                         'value_json': json.dumps(item['source_item_ref'])}
                        for item in original['source_items'] for i in item['record_indices']]}
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        first = fixture.service.start(batch.id, AnalyseRequest(expected_revision=2, idempotency_key='office-start'))
        run = first['runs'][0]
        self.assertEqual([f['status'] for f in run['files']], ['SUCCEEDED', 'FAILED', 'SUCCEEDED'])
        before_retry = len(seen)
        retrying[0] = True
        final = fixture.service.retry(batch.id, first['id'], run['id'], RetryAnalysisRequest(
            expected_revision=fixture.intake.get(batch.id).revision, idempotency_key='office-retry',
            submission_ids=[source.id]))
        result = final['runs'][0]
        self.assertEqual(result['status'], 'SUCCEEDED', result['files'][1]['error'])
        for index in (0, 2):
            self.assertEqual(result['files'][index], run['files'][index])
        for value in seen[before_retry:]:
            if value['stage'] in ('CLASSIFY_FILE', 'INTERPRET_FILE', 'RECONCILE_FILE'):
                self.assertEqual(value['submission_id'], source.id)
        historical = result['previous_attempts'][-1]['files'][1]
        self.assertEqual(historical['repair_state']['candidate'], original)
        self.assertEqual(historical['response_history'][-1]['text'], '{"corrections": []}')
        self.assertIsNone(result['files'][1]['repair_state'])

    def test_all_fifteen_repairs_share_one_request_and_preserve_source_records(self):
        original = candidate(15)
        seen = []
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']
                seen.append(value)
                answer = original if value['stage'] == 'INTERPRET_FILE' else patches(value['allowed_paths'])
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        value = self.converse(Adapter())
        repairs = [v for v in seen if v['stage'] == 'REPAIR_OUTPUT']
        self.assertEqual(len(repairs), 1)
        self.assertEqual(len(repairs[0]['allowed_paths']), 15)
        self.assertEqual(len(repairs[0]['validation_errors']), 15)
        self.assertEqual([r.model_dump(mode='json') for r in value.records],
                         [r.model_dump(mode='json') for r in FileDraft.model_validate(original).records])
        for old, new in zip(original['source_items'], value.source_items):
            self.assertEqual(old['source_item_ref'], new.source_item_ref)
            self.assertEqual(old['explanation'], new.explanation)
            self.assertEqual(old['source_page'], new.source_page)

    def test_transport_failure_resumes_corrected_candidate_without_reextracting(self):
        seen, failure = [], [True]
        original = candidate()
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; seen.append(value)
                if value['stage'] == 'INTERPRET_FILE':
                    answer = original
                elif failure[0] and len([v for v in seen if v['stage'] == 'REPAIR_OUTPUT']) == 1:
                    answer = patches(value['allowed_paths'][:1])
                elif failure[0]:
                    failure[0] = False
                    raise ProviderError('PROVIDER_TRANSPORT_ERROR', 'Diagnostic timeout', 502)
                else:
                    answer = patches(value['allowed_paths'])
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        with self.assertRaises(ProviderError): self.converse(Adapter())
        saved = FileAnalysis.model_validate(self.file.model_dump(mode='json'))
        self.assertIsNotNone(saved.repair_state)
        self.assertEqual(saved.repair_state['candidate']['source_items'][0]['record_indices'], [0])
        self.file = saved; self.run.files = [saved]
        value = self.converse(Adapter())
        self.assertEqual(sum(v['stage'] == 'INTERPRET_FILE' for v in seen), 1)
        last = seen[-1]
        self.assertNotIn('/source_items/0/record_indices', last['allowed_paths'])
        self.assertIsNone(self.file.repair_state)
        validate_material_extraction(value)

    def test_wrong_links_and_missing_entries_are_repaired_together(self):
        original = candidate(15)
        original['source_items'] = original['source_items'][:15]
        seen = []
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; seen.append(value)
                answer = original
                if value['stage'] == 'REPAIR_OUTPUT':
                    answer = patches([path for path in value['allowed_paths'] if not path.endswith('/-')])
                    for item in value['error']['details']['missing_source_items']:
                        row_index = next(i for i, row in enumerate(original['records'])
                                         if row['source_page'] == item['page'] and row['source_item_ref'] == item['item_reference'])
                        entry = {'source_page': item['page'], 'source_item_ref': item['item_reference'],
                                 'disposition': 'MATERIAL', 'record_indices': [row_index], 'explanation': 'Original source location'}
                        answer['corrections'].append({'op': 'SET', 'path': '/source_items/-', 'value_json': json.dumps(entry)})
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        result = self.converse(Adapter())
        self.assertEqual(sum(t['stage'] == 'REPAIR_OUTPUT' for t in seen), 1)
        self.assertEqual(len(result.source_items), 30)
        validate_material_extraction(result)
        self.assertEqual(len(result.records), 30)
        self.assertEqual([r.raw_quantity for r in result.records], [r['raw_quantity'] for r in original['records']])

    def test_unsafe_patch_does_not_change_candidate_or_lose_resume_state(self):
        original = candidate()
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']
                answer = original if value['stage'] == 'INTERPRET_FILE' else {
                    'corrections': [{'path': '/records/0/quantity', 'value_json': '"999"'}]}
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        with self.assertRaises(IngestionError): self.converse(Adapter())
        self.assertEqual(self.file.repair_state['candidate'], original)
        self.assertIsNone(self.file.draft)

    def test_page_group_retry_keeps_completed_correction_and_skips_classification_extraction(self):
        import io
        from dataclasses import replace
        from tests.pdf_test_helpers import diagnostic_pdf
        from backend.app.schemas.analysis import AnalyseRequest, RetryAnalysisRequest
        fixture = self.fixture
        fixture.service.settings = replace(fixture.service.settings, models=(fixture.service.settings.models[2],))
        batch = fixture.intake.create()
        fixture.intake.add_files(batch.id, 1, [('diagnostic.pdf', io.BytesIO(diagnostic_pdf()))])
        seen, fail = [], [True]
        original = candidate()
        class Adapter(fixtures.ScriptedAdapter):
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; seen.append(value)
                if value['stage'] == 'INTERPRET_FILE':
                    answer = original
                elif value['stage'] == 'REPAIR_OUTPUT':
                    if fail[0] and sum(t['stage'] == 'REPAIR_OUTPUT' for t in seen) == 1:
                        answer = patches(value['allowed_paths'][:1])
                    elif fail[0]:
                        fail[0] = False
                        raise ProviderError('PROVIDER_TRANSPORT_ERROR', 'Diagnostic transport failure', 502)
                    else:
                        answer = patches(value['allowed_paths'])
                else:
                    return super().session(system, instruction, attachments, tools, schema)
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(answer), fixtures.usage())
                return Session()
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        first = fixture.service.start(batch.id, AnalyseRequest(expected_revision=2, idempotency_key='repair-start'))
        run = first['runs'][0]; group = run['files'][0]['page_groups'][0]
        self.assertEqual(run['status'], 'FAILED')
        self.assertEqual(group['repair_state']['candidate']['source_items'][0]['record_indices'], [0])
        reopened = fixture.intake.store.recoverable(batch.id)
        self.assertEqual(reopened.comparisons[-1].runs[0].files[0].page_groups[0].repair_state,
                         group['repair_state'], 'Private on-disk checkpoint retains completed corrections')
        fixture.repo.rows[batch.id] = reopened
        second = fixture.service.retry(batch.id, first['id'], run['id'], RetryAnalysisRequest(
            expected_revision=fixture.intake.get(batch.id).revision, idempotency_key='repair-retry'))
        self.assertEqual(second['runs'][0]['status'], 'SUCCEEDED', second['runs'][0]['files'][0]['error'])
        self.assertEqual(sum(t['stage'] == 'CLASSIFY_FILE' for t in seen), 1)
        self.assertEqual(sum(t['stage'] == 'INTERPRET_FILE' for t in seen), 1)
        group = second['runs'][0]['files'][0]['page_groups'][0]
        self.assertEqual(group['attempt'], 2)
        self.assertIsNone(group['repair_state'])
        self.assertEqual(len(group['recoveries']), 2)
        self.assertTrue(group['previous_attempts'][0]['repair_state'])

    def test_semantic_coverage_and_reference_defects_are_collected_together(self):
        value = candidate(2)
        value['page_coverage'] = [1]
        value['records'][0]['material_ref'] = {'kind': 'PROPOSED', 'id': 'DRAFT-unknown'}
        with self.assertRaises(IngestionError) as caught:
            self.service._validate_output(value, FileDraft, task(), self.executor)
        paths = caught.exception.allowed_paths
        self.assertIn('/page_coverage', paths)
        self.assertIn('/records/0/material_ref', paths)
        self.assertIn('/source_items/0/record_indices', paths)
        self.assertIn('/source_items/1/record_indices', paths)

    def test_changed_evidence_does_not_resume_old_candidate(self):
        calls = []
        class Adapter:
            def session(inner, system, instruction, attachments, tools, schema):
                value = json.loads(instruction)['task']; calls.append(value)
                if value['stage'] == 'REPAIR_OUTPUT':
                    raise ProviderError('PROVIDER_TRANSPORT_ERROR', 'Diagnostic timeout', 502)
                class Session:
                    def step(inner, results=None): return ProviderTurn([], json.dumps(candidate()), fixtures.usage())
                return Session()
        with self.assertRaises(ProviderError): self.converse(Adapter())
        changed = {**task(), 'text': 'Changed diagnostic evidence'}
        with self.assertRaises(ProviderError): self.converse(Adapter(), changed)
        self.assertEqual(sum(v['stage'] == 'INTERPRET_FILE' for v in calls), 2)
