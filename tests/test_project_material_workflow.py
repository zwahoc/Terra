"""Material-only extraction, fresh read-only comparison and independent recovery."""

import copy
import json
import unittest

from backend.app.schemas.analysis import FileDraft, ReconciliationResult, RetryAnalysisRequest
from backend.app.services.analysis_coverage import validate_pdf_coverage
from backend.app.services.analysis_providers import ProviderError, ProviderTurn, ToolCall
from backend.app.services.analysis_reconciliation import validate_material_extraction, validate_reconciliation
from backend.app.services.analysis_tools import FrozenTerraReads
from backend.app.services.ingestion_errors import IngestionError
from tests import test_analysis as fixtures


def extracted():
    return {'extraction_version': 'MATERIAL_V2', 'document_type': 'BOQ', 'summary': 'Project and material information',
        'project_info': [{'name': 'Test project', 'location': 'Test location',
            'project_ref': {'kind': 'EXISTING', 'id': 'PRJ-001'}, 'association_explanation': 'Name and location agree'}],
        'project_refs': [{'kind': 'EXISTING', 'id': 'PRJ-001'}], 'page_coverage': [1, 2],
        'source_items': [
            {'source_page': 2, 'source_item_ref': 'A01', 'disposition': 'CONTEXT', 'record_indices': [], 'explanation': 'Mobilisation service'},
            {'source_page': 2, 'source_item_ref': 'A02', 'disposition': 'MATERIAL', 'record_indices': [0, 1], 'explanation': 'Reinforced concrete implies two materials'},
            {'source_page': 2, 'source_item_ref': 'A03', 'disposition': 'CONTEXT', 'record_indices': [], 'explanation': 'Office rental'}],
        'records': [{'material_name': name, 'raw_description': 'Reinforced concrete walkway, 120 m2',
            'raw_quantity': '120', 'raw_unit': 'm2', 'quantity_basis': 'SOURCE_WORK', 'quantity': None, 'unit': None,
            'evidence_basis': 'INFERRED', 'inferred_fields': ['material_name'], 'inference_explanation': explanation,
            'source_page': 2, 'source_item_ref': 'A02', 'record_kind': 'PLANNED_REQUIREMENT',
            'project_ref': {'kind': 'EXISTING', 'id': 'PRJ-001'}} for name, explanation in (
                ('Concrete', 'Concrete named within reinforced concrete work; volume not specified'),
                ('Reinforcement', 'Reinforcement inferred from reinforced concrete; type and mass unknown'))]}


def compared(task):
    return {'summary': 'Provisional new information, not stock changes',
        'projects': [{'project_info_index': i, 'explanation': 'Compared extracted project details with current context'}
                     for i in range(len(task['extraction']['project_info']))],
        'materials': [{'record_index': i, 'relationship': 'NEW_INFORMATION', 'explanation': 'Planned evidence only'}
                      for i in range(len(task['extraction']['records']))]}


class ProjectMaterialWorkflowTests(unittest.TestCase):
    def test_model_read_tools_keep_business_evidence_without_fixture_provenance(self):
        material = {'id': 'MAT-001', 'canonical_name': 'Grey paver', 'is_synthetic': True,
                    'standard_unit': 'pcs', 'mass_source': 'SYNTHETIC_ASSUMPTION',
                    'specifications': {'thickness_mm': 80}}
        document = {'id': 'DOC-001', 'is_simulated': True, 'processing_status': 'SIMULATED',
                    'source_availability': 'METADATA_ONLY', 'file_uri': None,
                    'recorded_at': '2026-10-10T09:00:00+08:00'}
        row = {'id': 'ROW-001', 'review_status': 'ACCEPTED', 'review_mode': 'DEMO_PREAPPROVED',
               'is_simulated': True, 'raw_quantity': 'Not recorded',
               'parsed_fields': {'quantity': None, 'synthetic_test_fixture': True}}
        context = {'project': {'id': 'PRJ-001'}, 'synthetic_baseline': True,
                   'baseline_as_of_date': '2026-10-12', 'stock_coverage': 'NO_COMPLETE_PHYSICAL_STOCK_LEDGER',
                   'collections': {'materials': [material], 'documents': [document], 'extracted_rows': [row]}}
        original = copy.deepcopy(context)

        class Reads:
            def page(self, entity, **kwargs):
                return {'records': context['collections'][entity], 'next_cursor': None}
            def get_entity(self, entity, entity_id):
                return material if entity == 'materials' else context['project']
            def project_context(self, project_id):
                return context

        reads = FrozenTerraReads(Reads())
        operations = [('get_project_context', {'project_id': 'PRJ-001'}),
                      ('get_material_context', {'material_id': 'MAT-001'}),
                      ('search_materials', {}),
                      ('search_materials_flexible', {'terms': ['paver'], 'match_mode': 'ANY',
                         'search_fields': ['canonical_name']}),
                      ('find_related_documents', {'project_id': 'PRJ-001'}),
                      ('get_record_context', {'project_id': 'PRJ-001', 'collection': 'extracted_rows', 'record_id': 'ROW-001'})]
        for name, arguments in operations:
            with self.subTest(tool=name):
                result = reads.call(name, arguments)
                text = json.dumps(result)
                for removed in ('is_simulated', 'is_synthetic', 'synthetic_test_fixture',
                                'synthetic_baseline', 'baseline_as_of_date', 'SIMULATED', 'DEMO_PREAPPROVED'):
                    self.assertNotIn(removed, text)
                self.assertEqual(result, reads.call(name, arguments), 'Cached results keep the same projection')
        projected = reads.call('get_project_context', {'project_id': 'PRJ-001'})
        self.assertEqual(projected['collections']['documents'][0]['source_availability'], 'METADATA_ONLY')
        self.assertIsNone(projected['collections']['documents'][0]['file_uri'])
        self.assertIsNone(projected['collections']['extracted_rows'][0]['parsed_fields']['quantity'])
        self.assertEqual(projected['collections']['extracted_rows'][0]['review_status'], 'ACCEPTED')
        self.assertEqual(projected['collections']['materials'][0]['mass_source'], 'SYNTHETIC_ASSUMPTION')
        self.assertEqual(projected['stock_coverage'], 'NO_COMPLETE_PHYSICAL_STOCK_LEDGER')
        self.assertEqual(context, original, 'Stored facts and audit provenance are not mutated')

    def test_starting_extraction_and_reconciliation_contexts_use_business_projection(self):
        fixture = self.fixture()
        raw = {'project': {'id': 'PRJ-001'}, 'synthetic_baseline': True, 'baseline_as_of_date': '2026-10-12',
               'collections': {'supply_offers': [], 'documents': [
                   {'id': 'DOC-001', 'is_simulated': True, 'processing_status': 'SIMULATED',
                    'source_availability': 'METADATA_ONLY'}]}}
        original = copy.deepcopy(raw)
        fixture.intake.reads.project_context = lambda project_id: raw
        value = fixture.start()
        self.assertTrue(all(run['status'] == 'SUCCEEDED' for run in value['runs']))
        for entry in fixture.log:
            task = entry['task']
            if task['stage'] in ('INTERPRET_FILE', 'RECONCILE_FILE', 'CROSS_CHECK_BATCH'):
                text = json.dumps(task)
                for removed in ('is_simulated', 'synthetic_baseline', 'baseline_as_of_date', 'SIMULATED'):
                    self.assertNotIn(removed, text)
        self.assertEqual(raw, original)

    def test_deepseek_provider_ceiling_reserves_allowance_without_forcing_low_reasoning(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from backend.app.services.analysis_budget import BudgetLedger
        from backend.app.services.analysis_providers import ProviderAdapter
        with tempfile.TemporaryDirectory() as directory:
            config = fixtures.settings()
            ledger = BudgetLedger(config, Path(directory))
            transport = fixtures.ScriptedTransport([{'choices': [{'finish_reason': 'length', 'message': {'content': '{"records":['}}],
                                                   'usage': {'prompt_tokens': 100, 'completion_tokens': 393216}}])
            adapter = ProviderAdapter(config.models[2], config, ledger, transport)
            with patch.object(ledger, 'reserve', wraps=ledger.reserve) as reserve:
                with self.assertRaises(IngestionError) as caught:
                    adapter.session('System', 'Instruction', [], [], {}).step()
            self.assertEqual(reserve.call_args.args[2], 393216)
            self.assertEqual(transport.requests[0]['payload']['max_tokens'], 393216)
            self.assertEqual(transport.requests[0]['payload']['reasoning_effort'], 'high')
            self.assertEqual(transport.requests[0]['payload']['thinking'], {'type': 'enabled'})
            self.assertEqual(caught.exception.code, 'MODEL_OUTPUT_LIMIT')
            self.assertEqual(caught.exception.details['output_token_limit'], 393216)
            self.assertEqual(config.max_output_tokens, 32768, 'Gemini allowance stays unchanged')

    def fixture(self):
        fixture = fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_services_accounted_internally_and_two_inferred_materials_share_work_quantity(self):
        draft = FileDraft.model_validate(extracted())
        validate_material_extraction(draft)
        coverage = validate_pdf_coverage(draft, {2: ['A01', 'A02', 'A03']}, [1, 2])
        self.assertTrue(coverage['numbered_items_accounted_for'])
        self.assertEqual(len(draft.records), 2)
        self.assertTrue(all(row.quantity is None for row in draft.records))
        self.assertEqual(draft.records[0].raw_quantity, '120')

    def test_work_quantity_and_unexplained_inference_cannot_be_accepted(self):
        for changes in ({'quantity': '120', 'unit': 'm2'}, {'inference_explanation': None}):
            value = extracted()
            value['records'][0].update(changes)
            with self.assertRaises(IngestionError):
                validate_material_extraction(FileDraft.model_validate(value))

    def test_ledger_cannot_hide_missing_items_or_link_nonmaterial_to_records(self):
        value = extracted()
        value['source_items'].pop()
        with self.assertRaises(IngestionError):
            validate_pdf_coverage(FileDraft.model_validate(value), {2: ['A01', 'A02', 'A03']}, [1, 2])
        value = extracted()
        value['source_items'][0]['record_indices'] = [0]
        with self.assertRaises(IngestionError):
            validate_material_extraction(FileDraft.model_validate(value))

    def test_project_only_document_and_old_payload_defaults(self):
        value = extracted()
        value.update(records=[], source_items=[])
        validate_material_extraction(FileDraft.model_validate(value))
        legacy = FileDraft.model_validate({'document_type': 'OTHER', 'summary': 'Old result', 'records': []})
        self.assertEqual(legacy.extraction_version, 'LEGACY')
        with self.assertRaises(IngestionError):
            validate_material_extraction(legacy)

    def test_saved_extraction_visible_before_fresh_reconciliation_and_no_mutation(self):
        fixture = self.fixture()
        snapshots = []
        reads = fixture.intake.reads
        original = reads.project_context
        calls = []
        def context(project_id):
            calls.append(project_id)
            return {**original(project_id), 'read_number': len(calls)}
        reads.project_context = context

        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                if task['stage'] == 'INTERPRET_FILE':
                    value = extracted()
                elif task['stage'] == 'RECONCILE_FILE':
                    saved = fixture.intake.get(fixture.batch_id)
                    snapshots.append(copy.deepcopy(saved.comparisons[-1].runs))
                    if any(tool['name'].startswith('propose_') for tool in tools):
                        raise AssertionError('Comparison exposes read tools only')
                    if task['current_project_context']['PRJ-001']['read_number'] <= 1:
                        raise AssertionError('Comparison must refresh extraction context')
                    value = compared(task)
                else:
                    return super().session(system, instruction, attachments, tools, output_schema)
                class Session:
                    def step(self, results=None): return ProviderTurn([], json.dumps(value), fixtures.usage())
                return Session()
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        comparison = fixture.start()
        self.assertTrue(all(run['status'] == 'SUCCEEDED' for run in comparison['runs']))
        self.assertEqual(len(snapshots), 6)
        self.assertTrue(any(file.draft and file.reconciliation.status == 'RUNNING' for runs in snapshots for run in runs for file in run.files))
        for run in comparison['runs']:
            self.assertEqual(run['proposals'], [])
            self.assertTrue(all(file['status'] == 'SUCCEEDED' and file['reconciliation']['status'] == 'SUCCEEDED' for file in run['files']))

    def test_failed_reconciliation_retries_without_extraction_and_preserves_attempt(self):
        fixture = self.fixture()
        stages, failures = [], {'deepseek_flash'}
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                stages.append((self.spec.slot, task['stage']))
                if task['stage'] == 'RECONCILE_FILE' and self.spec.slot in failures:
                    failures.remove(self.spec.slot)
                    raise ProviderError('PROVIDER_UNAVAILABLE', 'Test comparison outage', 502)
                return super().session(system, instruction, attachments, tools, output_schema)
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        first = fixture.start()
        run = first['runs'][2]
        self.assertEqual(run['status'], 'PARTIAL')
        self.assertTrue(all(file['draft'] and file['status'] == 'SUCCEEDED' for file in run['files']))
        drafts = [file['draft'] for file in run['files']]
        previous = len(stages)
        second = fixture.service.retry(fixture.batch_id, first['id'], run['id'], RetryAnalysisRequest(
            expected_revision=fixture.intake.get(fixture.batch_id).revision, idempotency_key='reconcile-only'))
        run = second['runs'][2]
        self.assertEqual(run['status'], 'SUCCEEDED')
        self.assertEqual([file['draft'] for file in run['files']], drafts)
        self.assertEqual([stage for _, stage in stages[previous:]], ['RECONCILE_FILE', 'CROSS_CHECK_BATCH'])
        self.assertEqual(run['files'][0]['reconciliation']['attempt'], 2)
        self.assertEqual(run['files'][0]['reconciliation']['previous_attempts'][0]['status'], 'FAILED')

    def test_reconciliation_cannot_call_proposal_tools(self):
        fixture = self.fixture()
        class Adapter(fixtures.ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)['task']
                if task['stage'] != 'RECONCILE_FILE':
                    return super().session(system, instruction, attachments, tools, output_schema)
                class Session:
                    def step(self, results=None):
                        return ProviderTurn([ToolCall('bad', 'propose_material', {'canonical_name': 'Unauthorized'})], '', fixtures.usage())
                return Session()
        fixture.service.provider_factory = lambda spec: Adapter(spec, [])
        value = fixture.start()
        for run in value['runs']:
            self.assertEqual(run['status'], 'PARTIAL')
            self.assertEqual(len(run['proposals']), 1)  # Extraction proposal only.
            self.assertTrue(all(file['reconciliation']['error']['code'] == 'TOOL_NOT_ALLOWED' for file in run['files']))

    def test_reconciliation_rejects_invented_and_cross_project_record_references(self):
        draft = FileDraft.model_validate(extracted())
        task = {'extraction': draft.model_dump(mode='json')}
        for project_id in ('PRJ-001', 'PRJ-other'):
            value = compared(task)
            value['materials'][0].update(relationship='POSSIBLE_DUPLICATE', existing_records=[
                {'project_id': project_id, 'collection': 'documents', 'record_id': 'DOC-missing'}])
            class Reads(fixtures.ModelReads):
                def page(self, *args, **kwargs): return {'records': [], 'next_cursor': None}
            with self.assertRaises(IngestionError):
                validate_reconciliation(ReconciliationResult.model_validate(value), draft, FrozenTerraReads(Reads()))


if __name__ == '__main__':
    unittest.main()
