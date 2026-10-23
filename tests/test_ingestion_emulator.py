"""Phase 1 REST proof against a fresh demo emulator, opt-in only."""

import asyncio
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.app.main import app
from backend.app.repositories.ingestion_repository import IngestionRepository, TerraReadRepository
from backend.app.routes.ingestion import get_intake_service
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore
from terra.local_adapter import AdapterError, LocalDataConnect, equivalent
from terra.seeding import seed_local, verify
from terra.validation import load
from tests.test_ingestion import http_request, json_request, multipart
from tests.test_analysis import ScriptedAdapter, settings
from backend.app.routes.analysis import get_comparison_service
from backend.app.services.analysis_budget import BudgetLedger
from backend.app.services.analysis_service import ComparisonService
from backend.app.services.analysis_tools import FrozenTerraReads, ToolExecutor
from backend.app.services.analysis_providers import ToolCall
from backend.app.schemas.analysis import AnalysisRun
from backend.app.repositories.model_preference_repository import ModelPreferenceRepository
from tests.pdf_test_helpers import diagnostic_pdf


@unittest.skipUnless(os.environ.get("TERRA_RUN_EMULATOR_TESTS") == "1", "Use npm run test:integration for isolated emulator tests")
class IngestionEmulatorTests(unittest.TestCase):
    def test_connected_group_retry_persists_success_without_reextraction(self):
        import io
        import json
        from dataclasses import replace
        from unittest.mock import patch
        from backend.app.services.analysis_providers import ProviderTurn, ProviderError
        from tests.test_analysis import usage
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation='demo-terra-local')
        before = adapter.snapshot()
        with tempfile.TemporaryDirectory(prefix='terra group retry ') as directory:
            intake = IntakeService(IngestionRepository(adapter), TerraReadRepository(adapter), SourceStore(Path(directory)/'intake'))
            batch = intake.create()
            intake.add_files(batch.id, 1, [('diagnostic.pdf', io.BytesIO(diagnostic_pdf()))])
            calls, failure = [], [True]
            class Adapter(ScriptedAdapter):
                def session(self, system, instruction, attachments, tools, output_schema):
                    task = json.loads(instruction)['task']
                    if task['stage'] != 'INTERPRET_FILE':
                        return super().session(system, instruction, attachments, tools, output_schema)
                    pages = task['page_group']['owned_pages']
                    calls.append(pages)
                    if pages == [2] and failure[0]:
                        failure[0] = False
                        raise ProviderError('PROVIDER_UNAVAILABLE', 'Scripted failed group', 502)
                    value = {'extraction_version': 'MATERIAL_V2', 'document_type': 'OTHER', 'summary': 'Diagnostic',
                             'page_coverage': pages, 'records': []}
                    class Session:
                        def step(self, results=None): return ProviderTurn([], json.dumps(value), usage())
                    return Session()
            config = replace(settings(), models=(settings().models[2],))
            service = ComparisonService(intake, config, BudgetLedger(config, Path(directory)/'budget'),
                provider_factory=lambda spec: Adapter(spec, []), schedule=lambda fn,*args: fn(*args),
                preferences=ModelPreferenceRepository(Path(directory)/'preference'))
            app.dependency_overrides[get_intake_service] = lambda: intake
            app.dependency_overrides[get_comparison_service] = lambda: service
            try:
                with patch('backend.app.services.document_analysis.plan_pages', return_value=[[1], [2]]):
                    status, value = json_request('POST', f'/api/ingestion/batches/{batch.id}/analyse',
                        {'expected_revision': 2, 'idempotency_key': 'group-sql-proof'})
                    self.assertEqual(status, 202, value)
                    comparison = value['data']
                    run = comparison['runs'][0]
                    self.assertEqual(run['status'], 'FAILED')
                    reopened = IngestionRepository(LocalDataConnect()).get(batch.id)
                    self.assertEqual(reopened.comparisons[0].runs[0].files[0].page_groups[0].status, 'SUCCEEDED')
                    status, value = json_request('POST', f'/api/ingestion/batches/{batch.id}/comparisons/{comparison["id"]}/runs/{run["id"]}/retry',
                        {'expected_revision': reopened.revision, 'idempotency_key': 'retry-sql-group'})
                    self.assertEqual(status, 202, value)
                    self.assertEqual(value['data']['runs'][0]['status'], 'SUCCEEDED', value)
                self.assertEqual(calls, [[1], [2], [2]])
                final = IngestionRepository(LocalDataConnect()).get(batch.id)
                self.assertEqual(final.comparisons[0].runs[0].files[0].draft.page_coverage, [1, 2])
            finally:
                app.dependency_overrides.clear()
        self.assertTrue(equivalent(before, adapter.snapshot()))
        verify(adapter, baseline)

    def test_project_material_extraction_then_stored_record_reconciliation(self):
        import io
        import json
        from backend.app.services.analysis_providers import ProviderTurn
        from tests.test_analysis import usage
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation='demo-terra-local')
        before = adapter.snapshot()
        snapshots = []
        with tempfile.TemporaryDirectory(prefix='terra project comparison ') as directory:
            intake = IntakeService(IngestionRepository(adapter), TerraReadRepository(adapter), SourceStore(Path(directory) / 'intake'))
            batch = intake.create('PRJ-001')
            intake.add_files(batch.id, 1, [('diagnostic.txt', io.BytesIO(b'Generic existing-project material linkage diagnostic'))])
            class Adapter(ScriptedAdapter):
                def session(self, system, instruction, attachments, tools, output_schema):
                    task = json.loads(instruction)['task']
                    if task['stage'] == 'INTERPRET_FILE':
                        answer = {'extraction_version': 'MATERIAL_V2', 'document_type': 'OTHER', 'summary': 'Scripted linkage proof',
                            'project_refs': [{'kind': 'EXISTING', 'id': 'PRJ-001'}],
                            'project_info': [{'project_ref': {'kind': 'EXISTING', 'id': 'PRJ-001'},
                                'name': 'Elmina Demo Phase A', 'location': 'Elmina', 'association_explanation': 'Synthetic identity proof'}],
                            'records': [{'material_name': 'Concrete paving block', 'raw_description': 'Generic diagnostic material',
                                'quantity_basis': 'MATERIAL', 'quantity': '20', 'unit': 'pcs', 'record_kind': 'RECEIPT',
                                'project_ref': {'kind': 'EXISTING', 'id': 'PRJ-001'}, 'material_ref': {'kind': 'EXISTING', 'id': 'MAT-001'}}]}
                    elif task['stage'] == 'RECONCILE_FILE':
                        context = task['current_project_context']['PRJ-001']['collections']
                        if not any(m['id'] == 'MAT-001' for m in context['materials']):
                            raise AssertionError('Current context must include the project material')
                        snapshots.append(IngestionRepository(adapter).get(batch.id))
                        answer = {'summary': 'New receipt evidence, no balance calculated',
                            'projects': [{'project_info_index': 0, 'explanation': 'Project identity agrees with current stored facts'}],
                            'materials': [{'record_index': 0, 'relationship': 'ADDITIONAL_EVIDENCE',
                                'existing_records': [{'project_id': 'PRJ-001', 'collection': 'supply_offers', 'record_id': 'SUP-001'}],
                                'explanation': 'Same project and material; additional evidence requires duplicate checks before applying',
                                'suggested_treatment': 'UNDECIDED'}]}
                    else:
                        return super().session(system, instruction, attachments, tools, output_schema)
                    class Session:
                        def step(self, results=None): return ProviderTurn([], json.dumps(answer), usage())
                    return Session()
            service = ComparisonService(intake, settings(), BudgetLedger(settings(), Path(directory) / 'budget'),
                provider_factory=lambda spec: Adapter(spec, []), schedule=lambda fn, *args: fn(*args),
                preferences=ModelPreferenceRepository(Path(directory) / 'preference'))
            app.dependency_overrides[get_intake_service] = lambda: intake
            app.dependency_overrides[get_comparison_service] = lambda: service
            try:
                status, value = json_request('POST', f'/api/ingestion/batches/{batch.id}/analyse',
                    {'expected_revision': 2, 'idempotency_key': 'project-material-proof', 'mode': 'COMPARE'})
                self.assertEqual(status, 202, value)
                self.assertTrue(all(run['status'] == 'SUCCEEDED' for run in value['data']['runs']))
                reopened = IngestionRepository(LocalDataConnect()).get(batch.id)
                self.assertEqual(reopened.comparisons[0].runs[0].files[0].reconciliation.result.materials[0].existing_records[0].record_id, 'SUP-001')
                self.assertTrue(all(any(f.draft and f.reconciliation.status == 'RUNNING' for r in state.comparisons[0].runs for f in r.files) for state in snapshots))
            finally:
                app.dependency_overrides.clear()
        self.assertTrue(equivalent(before, adapter.snapshot()))
        verify(adapter, baseline)

    def test_flexible_material_search_reads_full_specs_and_leaves_baseline_intact(self):
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation='demo-terra-local')
        before = adapter.snapshot()
        run = AnalysisRun(id='AIR-flexible-search', model_slot='deepseek_flash', model_id='deepseek-flash', files=[])
        executor = ToolExecutor(run, FrozenTerraReads(TerraReadRepository(adapter)), lambda _: None)
        response = executor.execute(ToolCall('bulk', 'search_materials_bulk', {'queries': [
            {'query_id': 'pavers', 'terms': ['paver', 'paving'], 'match_mode': 'ANY', 'limit': 2},
            {'query_id': 'dimensions', 'terms': ['200', '100', '60', 'grey'], 'match_mode': 'ALL'},
            {'query_id': 'category', 'terms': ['paving_block'], 'search_fields': ['category']}
        ]}))['result']['results']
        ids = [row['id'] for row in response[0]['records']]
        cursor = response[0]['next_cursor']
        while cursor is not None:
            page = executor.execute(ToolCall('continue', 'search_materials_bulk', {'queries': [
                {'query_id': 'pavers', 'terms': ['paver', 'paving'], 'match_mode': 'ANY', 'limit': 2, 'after': cursor}
            ]}))['result']['results'][0]
            ids.extend(row['id'] for row in page['records'])
            cursor = page['next_cursor']
        expected = sorted(row['id'] for row in baseline['materials'] if row['category'] == 'PAVING_BLOCK')
        self.assertEqual(ids, expected)
        exact = next(row for row in response[1]['records'] if row['id'] == 'MAT-001')
        self.assertEqual(exact['specifications']['thickness_mm'], 60)
        self.assertEqual([row['id'] for row in response[2]['records']], expected)
        self.assertEqual(run.proposals, [])
        self.assertTrue(equivalent(before, adapter.snapshot()))
        verify(adapter, baseline)

    def test_numbered_pdf_first_row_only_is_not_marked_complete(self):
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation="demo-terra-local")
        before=adapter.snapshot()
        with tempfile.TemporaryDirectory(prefix='terra coverage emulator ') as directory:
            intake=IntakeService(IngestionRepository(adapter),TerraReadRepository(adapter),SourceStore(Path(directory)/'intake'))
            service=ComparisonService(intake,settings(),BudgetLedger(settings(),Path(directory)/'budget'),
                provider_factory=lambda spec:ScriptedAdapter(spec,[]),schedule=lambda fn,*args:fn(*args),
                preferences=ModelPreferenceRepository(Path(directory)/'preference'))
            app.dependency_overrides[get_intake_service]=lambda:intake
            app.dependency_overrides[get_comparison_service]=lambda:service
            try:
                status,created=json_request('POST','/api/ingestion/batches',{})
                self.assertEqual(status,200)
                bid=created['data']['id']
                body,headers=multipart(1,[('numbered-diagnostic.pdf',diagnostic_pdf(numbered=True))])
                status,_,_=asyncio.run(http_request('POST',f'/api/ingestion/batches/{bid}/files',body,headers))
                self.assertEqual(status,200)
                status,value=json_request('POST',f'/api/ingestion/batches/{bid}/analyse',{'expected_revision':2,'idempotency_key':'coverage-proof','mode':'COMPARE'})
                self.assertEqual(status,202)
                for run in value['data']['runs']:
                    self.assertEqual(run['status'],'FAILED')
                    self.assertEqual(run['files'][0]['error']['code'],'DOCUMENT_COVERAGE_INCOMPLETE')
                    self.assertEqual(len(run['files'][0]['error']['details']['missing_source_items']),3)
                saved=IngestionRepository(LocalDataConnect()).get(bid)
                self.assertEqual(saved.comparisons[0].runs[1].status,'FAILED')
            finally:app.dependency_overrides.clear()
        self.assertTrue(equivalent(before,adapter.snapshot()))
        verify(adapter,baseline)

    def test_deepseek_pdf_upload_preparation_and_original_sql_read_back(self):
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation="demo-terra-local")
        before = adapter.snapshot()
        with tempfile.TemporaryDirectory(prefix="terra PDF emulator ") as directory:
            intake = IntakeService(IngestionRepository(adapter), TerraReadRepository(adapter), SourceStore(Path(directory) / "intake"))
            service = ComparisonService(intake, settings(), BudgetLedger(settings(), Path(directory) / "budget"),
                provider_factory=lambda spec: ScriptedAdapter(spec, []), schedule=lambda fn, *args: fn(*args),
                preferences=ModelPreferenceRepository(Path(directory) / "preference"))
            app.dependency_overrides[get_intake_service] = lambda: intake
            app.dependency_overrides[get_comparison_service] = lambda: service
            try:
                status, created = json_request("POST", "/api/ingestion/batches", {})
                self.assertEqual(status, 200)
                batch_id = created["data"]["id"]
                original = diagnostic_pdf()
                body, headers = multipart(1, [("diagnostic.pdf", original)])
                status, _, _ = asyncio.run(http_request("POST", f"/api/ingestion/batches/{batch_id}/files", body, headers))
                self.assertEqual(status, 200)
                status, result = json_request("POST", f"/api/ingestion/batches/{batch_id}/analyse", {
                    "expected_revision": 2, "idempotency_key": "pdf-emulator-proof", "mode": "COMPARE"})
                self.assertEqual(status, 202, result)
                self.assertEqual([run["status"] for run in result["data"]["runs"]], ["SUCCEEDED"] * 3)
                prepared = result["data"]["runs"][2]["files"][0]["preparation"]
                self.assertEqual(prepared["page_numbers"], [1, 2])
                self.assertEqual(prepared["pages_with_text"], 1)
                reloaded = IngestionRepository(LocalDataConnect()).get(batch_id)
                self.assertEqual(reloaded.comparisons[0].runs[2].files[0].preparation, prepared)
                source_id = reloaded.submissions[0].id
                status, headers, downloaded = asyncio.run(http_request("GET", f"/api/ingestion/batches/{batch_id}/files/{source_id}/source?preview=true"))
                self.assertEqual(status, 200)
                self.assertEqual(headers[b"content-type"], b"application/pdf")
                self.assertEqual(downloaded, original)
            finally:
                app.dependency_overrides.clear()
        self.assertTrue(equivalent(before, adapter.snapshot()))
        verify(adapter, baseline)

    def test_three_model_orchestration_with_concurrent_sql_draft_progress(self):
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation="demo-terra-local")
        before = adapter.snapshot()
        with tempfile.TemporaryDirectory(prefix="terra analysis emulator ") as directory:
            service = IntakeService(IngestionRepository(adapter), TerraReadRepository(adapter), SourceStore(Path(directory) / "intake"))
            batch = service.create("PRJ-001")
            import io
            service.add_files(batch.id, 1, [("hello.txt", io.BytesIO(b"Generic test input"))])
            log, futures = [], []
            with ThreadPoolExecutor(max_workers=3) as pool:
                def schedule(fn, *args):
                    future = pool.submit(fn, *args)
                    futures.append(future)
                    return future
                comparison_service = ComparisonService(service, settings(), BudgetLedger(settings(), Path(directory) / "budget"),
                    provider_factory=lambda spec: ScriptedAdapter(spec, log), schedule=schedule,
                    preferences=ModelPreferenceRepository(Path(directory) / "model-choice"))
                app.dependency_overrides[get_comparison_service] = lambda: comparison_service
                try:
                    status, value = json_request("POST", f"/api/ingestion/batches/{batch.id}/analyse", {"expected_revision": 2, "idempotency_key": "emulator-three-models"})
                    self.assertEqual(status, 202, value)
                    comparison_id = value["data"]["id"]
                    for future in futures:
                        future.result(timeout=30)
                    status, value = json_request("GET", f"/api/ingestion/batches/{batch.id}/comparisons/{comparison_id}")
                    self.assertEqual(status, 200, value)
                    self.assertEqual([r["status"] for r in value["data"]["runs"]], ["SUCCEEDED"] * 3)
                    self.assertEqual(len({r["proposals"][0]["id"] for r in value["data"]["runs"]}), 3)
                    reopened = IngestionRepository(LocalDataConnect()).get(batch.id)
                    self.assertEqual(len(reopened.comparisons[0].runs), 3)
                    self.assertEqual([len(r.observations) for r in reopened.comparisons[0].runs], [3, 3, 3])
                    status, chosen = json_request("POST", f"/api/ingestion/batches/{batch.id}/primary-model", {
                        "expected_revision": reopened.revision, "expected_preference_revision": 0,
                        "comparison_id": comparison_id, "run_id": value["data"]["runs"][1]["id"]})
                    self.assertEqual(status, 200, chosen)
                    self.assertEqual(chosen["data"]["primary_model_slot"], "gemini_flash_lite")
                    status, primary_run = json_request("POST", f"/api/ingestion/batches/{batch.id}/analyse", {
                        "expected_revision": service.get(batch.id).revision, "idempotency_key": "primary-emulator"})
                    self.assertEqual(status, 202, primary_run)
                    self.assertEqual(len(primary_run["data"]["runs"]), 1)
                    for future in futures:
                        future.result(timeout=30)
                finally:
                    app.dependency_overrides.clear()
        self.assertTrue(equivalent(before, adapter.snapshot()))
        verify(adapter, baseline)

    def test_real_intake_context_reopen_and_seed_unchanged(self):
        adapter, baseline = LocalDataConnect(), load()
        seed_local(baseline, adapter, reset_confirmation="demo-terra-local")
        before = adapter.snapshot()
        with tempfile.TemporaryDirectory(prefix="terra emulator intake ") as directory:
            service = IntakeService(IngestionRepository(adapter), TerraReadRepository(adapter), SourceStore(Path(directory)))
            app.dependency_overrides[get_intake_service] = lambda: service
            try:
                status, response = json_request("POST", "/api/ingestion/batches", {"selected_project_id": "PRJ-001"})
                self.assertEqual(status, 200, response)
                batch_id = response["data"]["id"]
                payload, headers = multipart(1, [("notes.txt", "Hello 材料".encode()), ("table.csv", b"a,b\n1,2")])
                status, _, response = asyncio.run(http_request("POST", f"/api/ingestion/batches/{batch_id}/files", payload, headers))
                self.assertEqual(status, 200, response)
                status, response = json_request("PATCH", f"/api/ingestion/batches/{batch_id}/context", {"expected_revision": 2, "operator_notes": "Resume here", "operator_input": {"comment": "unapproved"}})
                self.assertEqual(status, 200, response)
                status, response = json_request("POST", f"/api/ingestion/batches/{batch_id}/context/projects", {"expected_revision": 3, "project_id": "PRJ-001"})
                self.assertEqual(status, 200, response)
                facts = response["data"]["context"]["project_observations"][0]["facts"]
                self.assertEqual(len(facts["collections"]["documents"]), len([r for r in baseline["documents"] if r["project_id"] == "PRJ-001"]))
                self.assertGreater(len(facts["collections"]["transfers"]), 0)
                fresh = IntakeService(IngestionRepository(LocalDataConnect()), TerraReadRepository(LocalDataConnect()), SourceStore(Path(directory)))
                batch = fresh.get(batch_id)
                self.assertEqual(batch.revision, 4)
                self.assertEqual(batch.context.operator_notes, "Resume here")
                self.assertEqual(len(batch.submissions), 2)
                source_id = batch.submissions[0].id
                status, _, original = asyncio.run(http_request("GET", f"/api/ingestion/batches/{batch_id}/files/{source_id}/source"))
                self.assertEqual((status, original), (200, "Hello 材料".encode()))
                # Named mutation itself rejects a stale write, beyond service checks.
                with self.assertRaises(IngestionError) as caught:
                    fresh.repository.save(batch, expected_revision=1)
                self.assertEqual(caught.exception.code, "STALE_REVISION")
                self.assertEqual(fresh.get(batch_id).revision, 4)
                # Ordinary connector execution cannot bypass NO_ACCESS.
                with self.assertRaises(AdapterError):
                    adapter.execute("GetIngestionBatch", {"id": batch_id}, admin=False)
                projects = fresh.reads.page("projects", limit=2)
                next_projects = fresh.reads.page("projects", limit=2, after=projects["next_cursor"])
                self.assertEqual([r["id"] for r in projects["records"] + next_projects["records"]], ["PRJ-001", "PRJ-002", "PRJ-003", "PRJ-004"])
                self.assertEqual(fresh.reads.get_entity("materials", "MAT-001"), baseline["materials"][0])
                # Explicit seed reset preserves intake rows but refresh is still a separate observation.
                seed_local(baseline, adapter, reset_confirmation="demo-terra-local")
                self.assertEqual(fresh.get(batch_id).revision, 4)
            finally:
                app.dependency_overrides.clear()
        self.assertTrue(equivalent(before, adapter.snapshot()))
        verify(adapter, baseline)
