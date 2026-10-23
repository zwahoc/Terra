"""Large-file, upload ownership and connected-page proofs. No paid model calls."""

import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from backend.app.schemas.analysis import FileDraft, PageGroupAnalysis, RetryAnalysisRequest
from backend.app.services.analysis_budget import BudgetLedger
from backend.app.services.analysis_providers import ProviderAdapter, ProviderTransport, ProviderError, ProviderTurn
from backend.app.services.document_preparation import prepare_document, DiskDocument, save_page
from backend.app.services.document_groups import plan_pages, assemble
from backend.app.services.analysis_coverage import validate_pdf_coverage
from backend.app.services.analysis_reconciliation import validate_material_extraction
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.provider_files import MultipartImage
from tests.pdf_test_helpers import diagnostic_pdf
from tests import test_analysis as fixtures


class FileTransport:
    def __init__(self):
        self.uploads, self.generations, self.deletes = [], [], []
        self.fail_delete = False

    def request(self, method, url, headers, payload=None, timeout=180):
        if url.endswith('/files'):
            chunks = list(payload)
            assert sum(map(len, chunks)) == payload.length
            assert b'name="purpose"\r\n\r\nuser_data' in chunks[0]
            assert b'expires_after[seconds]' in chunks[0]
            assert max(map(len, chunks[1:-1])) <= 1024 * 1024
            self.uploads.append(payload.path)
            return {'id': 'file-api-' + str(len(self.uploads)), 'expires_at': __import__('time').time() + 86400}
        if method == 'DELETE':
            self.deletes.append(url.rsplit('/', 1)[-1])
            if self.fail_delete:
                raise ProviderError('PROVIDER_UNAVAILABLE', 'Test cleanup outage', 502)
            return {'id': self.deletes[-1], 'deleted': True}
        self.generations.append(copy.deepcopy(payload))
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}


class LargeDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='terra large document 材料 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_disk_preparation_accepts_pdf_beyond_old_48mib_limit_and_reuses_completed_pages(self):
        source = self.root / 'large-generic-diagnostic.pdf'
        source.write_bytes(diagnostic_pdf(padding_bytes=49 * 1024 * 1024))
        progress = []
        document = prepare_document(source, root=self.root / 'prepared', progress=progress.append)
        self.assertGreater(source.stat().st_size, 48 * 1024 * 1024)
        self.assertEqual(document.evidence()['page_numbers'], [1, 2])
        self.assertIn('TEXT PAGE ONE', document.text(1))
        self.assertEqual(document.text(2), '')
        attachments = document.attachments([1, 2])
        self.assertTrue(all('path' in item and 'data' not in item for item in attachments))
        old_times = [item['path'].stat().st_mtime_ns for item in attachments]
        again = prepare_document(source, root=self.root / 'prepared')
        self.assertEqual(old_times, [item['path'].stat().st_mtime_ns for item in again.attachments([1, 2])])
        self.assertEqual(progress[-1]['pages_prepared'], 2)

    def test_prepared_scanned_image_can_exceed_old_24mib_total_and_keeps_detail_views(self):
        source = self.root / 'generic-scan.png'
        with Image.frombytes('RGB', (3000, 3000), os.urandom(3000*3000*3)) as image:
            image.save(source)
        document = prepare_document(source, root=self.root / 'scan')
        views = document.attachments([1])
        self.assertGreater(sum(view['byte_size'] for view in views), 24 * 1024 * 1024)
        self.assertGreater(len(views), 1)
        self.assertEqual(views[0]['region'], 'whole page')
        self.assertTrue(any('detail' in view['region'] for view in views))
        self.assertEqual(document.evidence()['page_count'], 1)

    def test_oversized_pdf_retains_full_view_and_native_detail_crops(self):
        source = self.root / 'large-sheet-diagnostic.pdf'
        source.write_bytes(diagnostic_pdf(page_size=(3000, 2000)))
        prepared = prepare_document(source, root=self.root / 'large-sheet')
        views = prepared.attachments([1])
        self.assertEqual(views[0]['region'], 'whole page')
        native = [view for view in views if view['region'].startswith('native detail')]
        self.assertTrue(native)
        visible = False
        for view in native:
            with Image.open(view['path']) as image:
                self.assertLessEqual(max(image.size), 2048)
                visible = visible or image.convert('L').getextrema()[0] < 100
        self.assertTrue(visible, 'Native crops must contain the actual source marks')

    def test_tampered_page_cache_is_rebuilt_and_source_coverage_is_truthful(self):
        source = self.root / 'diagnostic.pdf'
        source.write_bytes(diagnostic_pdf())
        document = prepare_document(source, root=self.root / 'prepared')
        image = document.attachments([2])[0]['path']
        image.write_bytes(b'broken')
        rebuilt = prepare_document(source, root=self.root / 'prepared')
        self.assertTrue(rebuilt.attachments([2])[0]['path'].read_bytes().startswith(b'\x89PNG'))
        self.assertTrue(rebuilt.evidence()['all_pages_included'])

    def test_multipage_tiff_preserves_every_scan_frame(self):
        from backend.app.services.ingestion_content import native_media_type
        source = self.root / 'generic-multipage-scan.tiff'
        with Image.new('RGB', (60, 40), 'white') as first, Image.new('RGB', (60, 40), 'black') as second:
            first.save(source, save_all=True, append_images=[second])
        self.assertEqual(native_media_type(source.read_bytes()[:16]), 'image/tiff')
        document = prepare_document(source, root=self.root / 'tiff')
        self.assertEqual(document.evidence()['page_numbers'], [1, 2])
        self.assertEqual(len(document.attachments([1, 2])), 2)
        with Image.open(document.attachments([2])[0]['path']) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertIn('image page/frame 2', document.attachments([2])[0]['source_label'])

    def test_gif_and_webp_decoders_prepare_all_frames(self):
        from backend.app.services.ingestion_content import native_media_type
        for suffix, media in (('gif', 'image/gif'), ('webp', 'image/webp')):
            with self.subTest(suffix=suffix):
                source = self.root / ('generic.' + suffix)
                with Image.new('RGB', (60, 40), 'white') as first, Image.new('RGB', (60, 40), 'black') as second:
                    first.save(source, save_all=True, append_images=[second], duration=100)
                self.assertEqual(native_media_type(source.read_bytes()[:16]), media)
                prepared = prepare_document(source, root=self.root / suffix)
                self.assertEqual(prepared.evidence()['page_numbers'], [1, 2])

    def test_draft_context_is_paginated_and_limited_to_own_model_run(self):
        from backend.app.schemas.analysis import AnalysisRun, ProposedEntity
        from backend.app.services.analysis_tools import ToolExecutor, FrozenTerraReads
        from backend.app.services.analysis_providers import ToolCall
        run = AnalysisRun(id='AIR-own', model_slot='deepseek_flash', model_id='deepseek-flash', files=[],
            proposals=[ProposedEntity(id=f'DRAFT-MATERIAL-{i}', kind='MATERIAL', attributes={'canonical_name': 'Generic material'}) for i in range(3)])
        executor = ToolExecutor(run, FrozenTerraReads(fixtures.ModelReads()), lambda _: None)
        one = executor.execute(ToolCall('read', 'get_run_draft_context', {'limit': 2}))['result']
        self.assertEqual(len(one['records']), 2)
        self.assertEqual(one['fact_source'], 'THIS_RUN_PROVISIONAL_ONLY')
        two = executor.execute(ToolCall('more', 'get_run_draft_context', {'limit': 2, 'after': one['next_cursor']}))['result']
        self.assertEqual(len(two['records']), 1)
        self.assertIsNone(two['next_cursor'])
        missing = executor.execute(ToolCall('foreign', 'get_run_draft_context', {'collection': 'file_records', 'submission_id': 'SUB-other-model'}))['result']
        self.assertEqual(missing['error']['code'], 'DRAFT_NOT_FOUND')
        self.assertEqual(len(run.proposals), 3)

    def test_files_upload_once_reuse_between_stages_and_delete_only_owned_files(self):
        source = self.root / 'image.png'
        with Image.new('RGB', (30, 20), 'white') as image:
            image.save(source)
        config, transport = fixtures.settings(), FileTransport()
        adapter = ProviderAdapter(config.models[2], config, BudgetLedger(config, self.root / 'budget'), transport)
        attachments = [{'path': source, 'media_type': 'image/png', 'page_number': 1, 'page_count': 1}]
        for stage in ('CLASSIFY_FILE', 'INTERPRET_FILE', 'RECONCILE_FILE'):
            adapter.session('System', stage, attachments, [], {}).step()
        self.assertEqual(len(transport.uploads), 1)
        for payload in transport.generations:
            self.assertEqual(payload['reasoning_effort'], 'high')
            self.assertEqual(payload['max_tokens'], 393216)
            self.assertEqual(payload['messages'][1]['content'][-1], {'type': 'file', 'file_id': 'file-api-1'})
            self.assertNotIn('base64', json.dumps(payload))
        self.assertEqual(adapter.close()['pending_cleanup'], 0)
        self.assertEqual(transport.deletes, ['file-api-1'])
        self.assertTrue(source.exists())

    def test_cleanup_outage_retains_journal_then_next_worker_recovers_it(self):
        source = self.root / 'image.png'
        source.write_bytes(b'generic diagnostic bytes')
        config, transport = fixtures.settings(), FileTransport()
        ledger = BudgetLedger(config, self.root / 'budget')
        adapter = ProviderAdapter(config.models[2], config, ledger, transport)
        adapter.image_file(source)
        transport.fail_delete = True
        self.assertEqual(adapter.close()['pending_cleanup'], 1)
        transport.fail_delete = False
        second = ProviderAdapter(config.models[2], config, ledger, transport)
        second.image_file(source)
        second.close()
        self.assertGreaterEqual(transport.deletes.count('file-api-1'), 2)
        self.assertEqual(list((ledger.root / 'provider-files').rglob('*.json')), [])

    def test_response_body_above_old_16mib_is_not_discarded(self):
        raw = json.dumps({'diagnostic': 'x' * (17*1024*1024)}).encode()
        opener = __import__('unittest.mock', fromlist=['MagicMock']).MagicMock()
        opener.open.return_value = io.BytesIO(raw)
        with patch('backend.app.services.analysis_providers.build_opener', return_value=opener):
            result = ProviderTransport().request('GET', 'https://api.deepseek.com/models', {})
        self.assertEqual(len(result['diagnostic']), 17*1024*1024)

    def test_planner_uses_provider_limits_without_document_page_cutoff(self):
        pages = [{'page_number': i, 'images': [{'bytes': 100}], 'width_pixels': 100, 'height_pixels': 100} for i in range(1, 1202)]
        document = DiskDocument(self.root, {'pages': pages})
        document.text = lambda _: ''
        plan = plan_pages(document)
        self.assertEqual([page for group in plan for page in group], list(range(1, 1202)))
        self.assertTrue(all(len(group) <= 600 for group in plan))
        self.assertGreater(len(plan), 1)

    def test_explicit_cross_page_continuation_does_not_double_count(self):
        def group(name, page, row):
            draft = FileDraft(extraction_version='MATERIAL_V2', document_type='BOQ', summary='Generic diagnostic',
                records=[row], page_coverage=[page], source_items=[{'source_page': page, 'source_item_ref': 'X01',
                    'disposition': 'MATERIAL', 'record_indices': [0], 'explanation': 'Source material'}])
            return PageGroupAnalysis(id=name, submission_id='SUB-test', page_numbers=[page], input_digest=name, status='SUCCEEDED', draft=draft)
        row = {'material_name': 'Generic material', 'raw_description': 'Generic material', 'source_page': 1, 'source_item_ref': 'X01',
               'quantity_basis': 'MATERIAL', 'quantity': None, 'unit': 'pcs'}
        first = group('first', 1, row)
        second = group('second', 2, {**row, 'source_page': 2, 'quantity': '12', 'raw_quantity': '12', 'continues_from': 'first:0'})
        result = assemble([first, second])
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].quantity, '12')
        self.assertEqual(result.records[0].additional_source_pages, [2])
        self.assertEqual(result.source_items[1].record_indices, [0])
        validate_material_extraction(result)
        validate_pdf_coverage(result, {1: ['X01'], 2: ['X01']}, [1, 2])
        first.draft.records[0].quantity = '10'
        conflicted = assemble([first, second])
        self.assertIsNone(conflicted.records[0].quantity)
        self.assertTrue(any('Conflicting cross-page' in issue for issue in conflicted.records[0].issues))
        third = group('third', 3, {**row, 'source_page': 3, 'quantity': '10', 'raw_quantity': '10', 'continues_from': 'second:0'})
        still_conflicted = assemble([first, second, third])
        self.assertIsNone(still_conflicted.records[0].quantity, 'A later fragment cannot silently resolve a previously conflicting amount')
        self.assertEqual(still_conflicted.records[0].quantity_basis, 'UNKNOWN')

    def test_failed_page_group_retries_without_repeating_saved_group(self):
        fixture = fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        batch = fixture.intake.create()
        fixture.intake.add_files(batch.id, 1, [('diagnostic.pdf', io.BytesIO(diagnostic_pdf()))])
        calls, failure = [], [True]
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                if task['stage'] != 'INTERPRET_FILE':
                    return super().session(system, instruction, attachments, tools, output_schema)
                pages = task['page_group']['owned_pages']
                calls.append(pages)
                if pages == [2] and failure[0]:
                    failure[0] = False
                    raise ProviderError('PROVIDER_UNAVAILABLE', 'Test failed group', 502)
                value = {'extraction_version': 'MATERIAL_V2', 'document_type': 'OTHER', 'summary': 'Generic test page',
                         'records': [], 'page_coverage': pages, 'source_items': []}
                class Session:
                    def step(self, results=None): return ProviderTurn([], json.dumps(value), fixtures.usage())
                return Session()
        from dataclasses import replace
        fixture.service.settings = replace(fixture.service.settings, models=(fixture.service.settings.models[2],))
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        with patch('backend.app.services.document_analysis.plan_pages', return_value=[[1], [2]]):
            from backend.app.schemas.analysis import AnalyseRequest
            first = fixture.service.start(batch.id, AnalyseRequest(expected_revision=2, idempotency_key='group-proof'))
            run = first['runs'][0]
            self.assertEqual(run['status'], 'FAILED')
            self.assertEqual([part['status'] for part in run['files'][0]['page_groups']], ['SUCCEEDED', 'FAILED'])
            self.assertIsNone(run['files'][0]['draft'])
            second = fixture.service.retry(batch.id, first['id'], run['id'], RetryAnalysisRequest(
                expected_revision=fixture.intake.get(batch.id).revision, idempotency_key='group-retry'))
        self.assertEqual(second['runs'][0]['status'], 'SUCCEEDED', second['runs'][0]['files'][0]['error'])
        self.assertEqual(calls, [[1], [2], [2]])
        self.assertEqual(second['runs'][0]['files'][0]['page_groups'][1]['attempt'], 2)
        self.assertEqual(second['runs'][0]['files'][0]['draft']['page_coverage'], [1, 2])

    def test_capacity_error_splits_pages_instead_of_dropping_or_clipping_them(self):
        fixture = fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        from dataclasses import replace
        from backend.app.schemas.analysis import AnalyseRequest
        fixture.service.settings = replace(fixture.service.settings, models=(fixture.service.settings.models[2],))
        batch = fixture.intake.create()
        fixture.intake.add_files(batch.id, 1, [('diagnostic.pdf', io.BytesIO(diagnostic_pdf()))])
        calls = []
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                if task['stage'] != 'INTERPRET_FILE':
                    return super().session(system, instruction, attachments, tools, output_schema)
                pages = task['page_group']['owned_pages']
                calls.append(pages)
                if len(pages) > 1:
                    raise ProviderError('MODEL_OUTPUT_LIMIT', 'Test capacity limit', 502)
                value = {'extraction_version': 'MATERIAL_V2', 'document_type': 'OTHER', 'summary': 'Diagnostic',
                         'records': [], 'page_coverage': pages}
                class Session:
                    def step(self, results=None): return ProviderTurn([], json.dumps(value), fixtures.usage())
                return Session()
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        value = fixture.service.start(batch.id, AnalyseRequest(expected_revision=2, idempotency_key='capacity-split'))
        file = value['runs'][0]['files'][0]
        self.assertEqual(value['runs'][0]['status'], 'SUCCEEDED', file['error'])
        self.assertEqual(calls, [[1, 2], [1], [2]])
        self.assertEqual(file['page_groups'][0]['status'], 'SPLIT')
        self.assertEqual(file['draft']['page_coverage'], [1, 2])

    def test_large_reconciliation_preserves_completed_parts_on_retry(self):
        from backend.app.schemas.analysis import AnalysisRun, FileAnalysis
        fixture = fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        file = FileAnalysis(submission_id='SUB-big', status='SUCCEEDED', draft=FileDraft(
            extraction_version='MATERIAL_V2', document_type='OTHER', summary='Diagnostic',
            records=[{'raw_description': str(i) + '-' + 'x'*10000} for i in range(80)]))
        run = AnalysisRun(id='AIR-big', model_slot='deepseek_flash', model_id='deepseek-flash', files=[file])
        seen, fail = [], [True]
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                indices = task['comparison_part']['original_record_indices']
                seen.append(indices)
                if indices[0] > 0 and fail[0]:
                    fail[0] = False
                    raise ProviderError('PROVIDER_UNAVAILABLE', 'Test part failure', 502)
                return super().session(system, instruction, attachments, tools, output_schema)
        adapter = Adapter(fixtures.settings().models[2], [])
        fixture.service._reconcile(adapter, run, file, lambda _: None)
        self.assertEqual(file.reconciliation.status, 'FAILED')
        self.assertEqual(len(file.reconciliation.group_results), 1)
        fixture.service._reconcile(adapter, run, file, lambda _: None)
        self.assertEqual(file.reconciliation.status, 'SUCCEEDED', file.reconciliation.error)
        self.assertEqual([item.record_index for item in file.reconciliation.result.materials], list(range(80)))
        self.assertEqual(sum(indices[0] == 0 for indices in seen), 1)

    def test_large_batch_check_covers_every_pair_of_evidence_without_a_shortlist(self):
        from itertools import combinations
        from backend.app.schemas.analysis import AnalysisRun
        from backend.app.services.analysis_tools import ToolExecutor, FrozenTerraReads
        fixture = fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        run = AnalysisRun(id='AIR-pairs', model_slot='deepseek_flash', model_id='deepseek-flash', files=[])
        task = {'stage': 'CROSS_CHECK_BATCH', 'files': [{'submission_id': name,
            'draft': {'records': [{'raw_description': str(i) + '-' + 'x'*10000} for i in range(80)],
                      'summary': 'Test evidence', 'source_items': []}} for name in ('one', 'two')]}
        observed = set()
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                part = json.loads(instruction)['task']
                identities = [(f['submission_id'], i) for f in part['files'] for i in f['original_record_indices']]
                observed.update(tuple(sorted(pair)) for pair in combinations(identities, 2))
                return super().session(system, instruction, attachments, tools, output_schema)
        executor = ToolExecutor(run, FrozenTerraReads(fixtures.ModelReads()), lambda _: None)
        result = fixture.service._batch_check(Adapter(fixtures.settings().models[2], []), task, run, executor, lambda _: None)
        expected = {tuple(sorted(pair)) for pair in combinations([(name, i) for name in ('one', 'two') for i in range(80)], 2)}
        self.assertEqual(observed, expected)
        self.assertEqual(run.batch_check_progress['completed'], run.batch_check_progress['total'])
        self.assertTrue(result.summary)


if __name__ == '__main__':
    unittest.main()
