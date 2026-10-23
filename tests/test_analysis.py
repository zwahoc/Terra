"""Phase 2 orchestration and provider-boundary checks without external API calls."""

import copy
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

from backend.app.schemas.analysis import AnalyseRequest, RetryAnalysisRequest, SelectPrimaryRequest, UsageRecord
from backend.app.repositories.model_preference_repository import ModelPreferenceRepository
from backend.app.schemas.ingestion import ContextPatch
from backend.app.main import app
from backend.app.routes.analysis import get_comparison_service
from backend.app.services.analysis_budget import BudgetLedger
from backend.app.services.analysis_providers import ProviderAdapter, ProviderError, ProviderTurn, ToolCall
from backend.app.services.analysis_service import ComparisonService
from backend.app.services.analysis_settings import AnalysisSettings, ModelSpec
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore
from tests.test_ingestion import FakeReads, MemoryDraftRepository, json_request


def settings():
    key = SecretStr("test-only-key")
    return AnalysisSettings(True, (
        ModelSpec("gemini_flash", "gemini-3.8-flash", "gemini", Decimal("1.50"), Decimal("7.50"), key),
        ModelSpec("gemini_flash_lite", "gemini-3.5-flash-lite", "gemini", Decimal("0.30"), Decimal("2.50"), key),
        ModelSpec("deepseek_flash", "deepseek-flash", "deepseek", Decimal("0.30"), Decimal("1.20"), key)), gemini_min_interval_seconds=0)


def usage():
    return UsageRecord(input_tokens=100, output_tokens=20, estimated_cost_myr="0.001", latency_ms=1, pricing_version="TEST_ONLY")


class ModelReads(FakeReads):
    def page(self, entity, **kwargs):
        return {"records": [{"id": "PRJ-001", "name": "Test project"}] if entity == "projects" else [],
                "next_cursor": None, "consistency": "OBSERVED_READS"}


class ScriptedAdapter:
    def __init__(self, spec, log, failures=None):
        self.spec, self.log, self.failures = spec, log, failures if failures is not None else set()

    def check_availability(self):
        return {"available": True}

    def session(self, system, instruction, attachments, tools, output_schema):
        task = json.loads(instruction)["task"]
        self.log.append({"slot": self.spec.slot, "task": copy.deepcopy(task)})
        fail_key = (self.spec.slot, task.get("submission_id"))
        if fail_key in self.failures:
            self.failures.remove(fail_key)
            raise ProviderError("PROVIDER_RATE_LIMIT", "Test provider rate limit", 502)

        class Session:
            def step(inner, results=None):
                if task['stage'] == 'CLASSIFY_FILE':
                    value = {'primary_family':'OTHER','applicable_families':[], 'basis':'Generic diagnostic'}
                    return ProviderTurn([], json.dumps(value), usage())
                if task["stage"] == "RECONCILE_FILE":
                    extraction = task['extraction']
                    value = {'summary': 'Scripted provisional comparison',
                        'projects': [{'project_info_index': i, 'explanation': 'Test project context'} for i, _ in enumerate(extraction['project_info'])],
                        'materials': [{'record_index': i, 'relationship': 'NEW_INFORMATION', 'explanation': 'Test-only new evidence'} for i, _ in enumerate(extraction['records'])]}
                    return ProviderTurn([], json.dumps(value), usage())
                if task["stage"] == "CROSS_CHECK_BATCH":
                    value = {"summary": "Cross-checked all file outcomes", "findings": []}
                    return ProviderTurn([], json.dumps(value), usage())
                if results is None:
                    return ProviderTurn([
                        ToolCall("c1", "search_projects", {"query": "Test"}),
                        ToolCall("c2", "get_project_context", {"project_id": "PRJ-001"}),
                        ToolCall("c3", "propose_material", {"canonical_name": "Provisional test entry", "category_code": "OTHER", "standard_unit": "bag"}),
                    ], "", usage())
                proposal_id = results[2]["result"]["proposal"]["id"]
                value = {"extraction_version": "MATERIAL_V2", "document_type": "OTHER", "summary": "Test-only proposed interpretation", "records": [
                    {"raw_description": "Test input", "raw_quantity": "1.25", "raw_unit": "bag", "quantity_basis": "MATERIAL", "quantity": "1.25", "unit": "bag",
                     "project_ref": {"kind": "EXISTING", "id": "PRJ-001"},
                     "material_ref": {"kind": "PROPOSED", "id": proposal_id}, "record_kind": "UNKNOWN"}],
                    'project_refs': [{'kind': 'EXISTING', 'id': 'PRJ-001'}],
                    'project_info': [{'project_ref': {'kind': 'EXISTING', 'id': 'PRJ-001'}, 'name': 'Test project', 'association_explanation': 'Matched stored test project'}]}
                preparation = task.get("content_preparation")
                if task.get('reader_metadata'):
                    value['records'][0]['source_locator'] = task['reader_metadata']['locators'][0]
                if preparation:
                    value["page_coverage"] = preparation["page_numbers"]
                return ProviderTurn([], json.dumps(value), usage())
        return Session()


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="terra analysis 材料 ")
        self.addCleanup(self.directory.cleanup)
        self.repo = MemoryDraftRepository()
        self.intake = IntakeService(self.repo, ModelReads(), SourceStore(Path(self.directory.name) / "intake"))
        batch = self.intake.create("PRJ-001")
        self.batch_id = batch.id
        self.intake.add_files(batch.id, 1, [("a.txt", io.BytesIO(b"hello")), ("b.csv", io.BytesIO(b"a,b\n1,2"))])
        self.log, self.failures = [], set()
        self.service = ComparisonService(self.intake, settings(), BudgetLedger(settings(), Path(self.directory.name) / "budget"),
            provider_factory=lambda spec: ScriptedAdapter(spec, self.log, self.failures),
            schedule=lambda fn, *args: fn(*args),
            preferences=ModelPreferenceRepository(Path(self.directory.name) / "model-choice"))

    def start(self, key="first", **kwargs):
        return self.service.start(self.batch_id, AnalyseRequest(expected_revision=self.intake.get(self.batch_id).revision, idempotency_key=key, **kwargs))

    def test_all_three_models_tools_isolation_and_persistent_results(self):
        value = self.start()
        self.assertEqual([run["status"] for run in value["runs"]], ["SUCCEEDED"] * 3)
        self.assertTrue(value["input_manifest_current"])
        self.assertEqual(len({run["proposals"][0]["id"] for run in value["runs"]}), 3)
        for run in value["runs"]:
            self.assertEqual(len(run["usage"]), 9)
            self.assertEqual(len(run["observations"]), 6)
            for file in run["files"]:
                self.assertEqual(file["draft"]["records"][0]["material_ref"]["id"], run["proposals"][0]["id"])
                self.assertTrue(file["draft"]["records"][0]["requires_operator_confirmation"])
        contexts = [entry["task"]["initial_terra_context"] for entry in self.log if entry["task"]["stage"] == "INTERPRET_FILE"]
        self.assertTrue(all(context == contexts[0] for context in contexts))
        self.assertNotIn("test-only-key", json.dumps(value))
        reopened = IntakeService(self.repo, ModelReads(), SourceStore(Path(self.directory.name) / "intake"))
        self.assertEqual(reopened.get(self.batch_id).comparisons[0].id, value["id"])

    def test_retry_failed_file_retains_success_and_other_models(self):
        batch = self.intake.get(self.batch_id)
        self.failures.add(("deepseek_flash", batch.submissions[0].id))
        value = self.start()
        failed = value["runs"][2]
        self.assertEqual(failed["status"], "PARTIAL")
        untouched = copy.deepcopy(value["runs"][:2])
        successful_draft = copy.deepcopy(failed["files"][1]["draft"])
        result = self.service.retry(self.batch_id, value["id"], failed["id"], RetryAnalysisRequest(
            expected_revision=self.intake.get(self.batch_id).revision, idempotency_key="retry-one"))
        self.assertEqual(result["runs"][:2], untouched)
        self.assertEqual(result["runs"][2]["status"], "SUCCEEDED")
        self.assertEqual(result["runs"][2]["files"][1]["draft"], successful_draft)
        self.assertEqual(result["runs"][2]["files"][1]["attempt"], 1)
        self.assertEqual(len(result["runs"][2]["previous_attempts"]), 1)

    def test_idempotency_duplicate_reuse_and_explicit_reanalysis(self):
        value = self.start()
        calls = len(self.log)
        request = AnalyseRequest(expected_revision=2, idempotency_key="first")
        self.assertEqual(self.service.start(self.batch_id, request)["id"], value["id"])
        self.assertEqual(self.start("another-key")["id"], value["id"])
        self.assertEqual(len(self.log), calls)
        with self.assertRaises(IngestionError) as caught:
            self.start("another-key", reanalyse=True)
        self.assertEqual(caught.exception.code, "IDEMPOTENCY_KEY_REUSED")
        self.assertNotEqual(self.start("explicit", reanalyse=True)["id"], value["id"])

    def test_operator_edits_survive_background_analysis(self):
        jobs = []
        self.service.schedule = lambda fn, *args: jobs.append((fn, args))
        value = self.start()
        batch = self.intake.get(self.batch_id)
        self.intake.patch_context(self.batch_id, ContextPatch(expected_revision=batch.revision, operator_notes="new operator input"))
        for fn, args in jobs:
            fn(*args)
        self.assertEqual(self.intake.get(self.batch_id).context.operator_notes, "new operator input")
        self.assertFalse(self.service.get(self.batch_id, value["id"])["input_manifest_current"])

    def test_disabled_and_cross_run_references_cannot_bypass_rules(self):
        self.service.settings = replace(settings(), enabled=False)
        with self.assertRaises(IngestionError) as caught:
            self.start()
        self.assertEqual(caught.exception.code, "MODELS_DISABLED")
        self.assertEqual(self.log, [])

    def test_interrupted_pending_run_is_reported_and_can_retry(self):
        jobs = []
        self.service.schedule = lambda fn, *args: jobs.append((fn, args))
        value = self.start()
        run_id = value["runs"][0]["id"]
        request = RetryAnalysisRequest(expected_revision=self.intake.get(self.batch_id).revision, idempotency_key="resume")
        with self.assertRaises(IngestionError) as caught:
            self.service.retry(self.batch_id, value["id"], run_id, request)
        self.assertEqual(caught.exception.code, "ANALYSIS_ALREADY_RUNNING")
        with patch("backend.app.services.analysis_service.WORKER_INSTANCE_ID", "another-process"):
            interrupted = self.service.get(self.batch_id, value["id"])
            self.assertEqual(interrupted["runs"][0]["status"], "INTERRUPTED")
            result = self.service.retry(self.batch_id, value["id"], run_id, request)
            self.assertEqual(result["runs"][0]["status"], "PENDING")

    def test_model_cannot_reference_another_runs_proposed_material(self):
        from backend.app.schemas.analysis import AnalysisRun, FileDraft
        from backend.app.services.analysis_tools import FrozenTerraReads, ToolExecutor
        run = AnalysisRun(id="AIR-test", model_slot="gemini_flash", model_id="gemini-3.8-flash", files=[])
        executor = ToolExecutor(run, FrozenTerraReads(ModelReads()), lambda _: None)
        rejected = executor.execute(ToolCall("untrusted", "publish_stock", {"quantity_basis": "MATERIAL", "quantity": 999}))
        self.assertEqual(rejected["result"]["error"]["code"], "TOOL_NOT_ALLOWED")
        draft = FileDraft.model_validate({"extraction_version": "MATERIAL_V2", "document_type": "OTHER", "summary": "Proposed test record", "records": [
            {"raw_description": "test", "material_ref": {"kind": "PROPOSED", "id": "DRAFT-MATERIAL-other-run"}}]})
        with self.assertRaises(IngestionError) as caught:
            executor.validate_references(draft)
        self.assertEqual(caught.exception.code, "DRAFT_REFERENCE_INVALID")

    def test_analysis_http_envelope_and_model_labels(self):
        app.dependency_overrides[get_comparison_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.clear)
        status, value = json_request("POST", f"/api/ingestion/batches/{self.batch_id}/analyse",
                                     {"expected_revision": 2, "idempotency_key": "http-test"})
        self.assertEqual(status, 202, value)
        self.assertEqual(value["meta"]["stage"], "DRAFT_ANALYSIS")
        self.assertFalse(value["meta"]["operational_writes"])
        self.assertEqual(len(value["data"]["runs"]), 3)
        comparison_id = value["data"]["id"]
        status, value = json_request("GET", f"/api/ingestion/batches/{self.batch_id}/comparisons/{comparison_id}")
        self.assertEqual(status, 200)
        self.assertEqual([r["model_id"] for r in value["data"]["runs"]], [m.model_id for m in settings().models])

    def test_primary_choice_persists_and_default_analysis_uses_one_model(self):
        value = self.start()
        choice = SelectPrimaryRequest(expected_revision=self.intake.get(self.batch_id).revision,
            expected_preference_revision=0, comparison_id=value["id"], run_id=value["runs"][1]["id"])
        selected = self.service.select_primary(self.batch_id, choice)
        self.assertEqual(selected.primary_model_slot, "gemini_flash_lite")
        self.assertEqual(self.service.preferences.get(), selected)
        first = self.start("primary-default")
        self.assertEqual([r["model_slot"] for r in first["runs"]], ["gemini_flash_lite"])
        explicit = self.start("compare-explicit", mode="COMPARE")
        self.assertEqual(len(explicit["runs"]), 3)
        self.assertEqual(self.service.status()["preference"]["primary_model_slot"], "gemini_flash_lite")
        self.assertNotIn("test-only-key", json.dumps(self.service.status()))
        with self.assertRaises(IngestionError) as caught:
            self.service.select_primary(self.batch_id, choice)
        self.assertEqual(caught.exception.code, "STALE_MODEL_PREFERENCE")

    def test_incomplete_old_input_and_restored_results_cannot_choose_primary(self):
        batch = self.intake.get(self.batch_id)
        self.failures.add(("deepseek_flash", batch.submissions[0].id))
        value = self.start()
        def choose(run):
            return self.service.select_primary(self.batch_id, SelectPrimaryRequest(
                expected_revision=self.intake.get(self.batch_id).revision, expected_preference_revision=0,
                comparison_id=value["id"], run_id=run["id"]))
        with self.assertRaises(IngestionError) as caught:
            choose(value["runs"][2])
        self.assertEqual(caught.exception.code, "MODEL_RESULT_INCOMPLETE")
        self.intake.patch_context(self.batch_id, ContextPatch(expected_revision=self.intake.get(self.batch_id).revision, operator_notes="Changed input"))
        with self.assertRaises(IngestionError) as caught:
            choose(value["runs"][0])
        self.assertEqual(caught.exception.code, "ANALYSIS_INPUT_CHANGED")
        self.intake.patch_context(self.batch_id, ContextPatch(expected_revision=self.intake.get(self.batch_id).revision))
        self.repo.rows.clear()
        restored = self.intake.restore(self.batch_id)
        self.assertGreater(restored.context.epoch, 0)
        self.assertTrue(self.service.get(self.batch_id, value["id"])["database_context_requires_refresh"])
        with self.assertRaises(IngestionError) as caught:
            choose(value["runs"][0])
        self.assertEqual(caught.exception.code, "ANALYSIS_INPUT_CHANGED")
        fresh = self.start("fresh-context")
        self.assertNotEqual(fresh["id"], value["id"])
        self.assertFalse(fresh["database_context_requires_refresh"])
        self.assertTrue(self.service.get(self.batch_id, value["id"])["database_context_requires_refresh"])

    def test_primary_choice_http_records_only_a_model_preference(self):
        value = self.start()
        app.dependency_overrides[get_comparison_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.clear)
        before = self.intake.get(self.batch_id).model_dump(mode="json")
        status, result = json_request("POST", f"/api/ingestion/batches/{self.batch_id}/primary-model", {
            "expected_revision": before["revision"], "expected_preference_revision": 0,
            "comparison_id": value["id"], "run_id": value["runs"][0]["id"],
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["data"]["primary_model_slot"], "gemini_flash")
        self.assertEqual(self.intake.get(self.batch_id).model_dump(mode="json"), before)


class BudgetTests(unittest.TestCase):
    def test_tracking_continues_past_rm10_and_preserves_concurrent_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            config = settings()
            ledger = BudgetLedger(config, Path(directory))
            spec = config.models[0]
            first = ledger.reserve(spec, 100, 1000)
            reopened = BudgetLedger(config, Path(directory))
            self.assertEqual(reopened.summary()["uncertain_calls"], 1)
            reopened.settle(first, spec, 100, 20)
            self.assertEqual(ledger.summary()["uncertain_calls"], 0)
            # Exceed the former RM10 ceiling, then accept every concurrent call.
            ledger.reserve(spec, 1_000_000, 8192)
            ledger.reserve(spec, 1_000_000, 8192)
            with ThreadPoolExecutor(max_workers=4) as pool:
                accepted = list(pool.map(lambda _: ledger.reserve(spec, 0, 1000), range(4)))
            self.assertEqual(len(set(accepted)), 4)
            summary = reopened.summary()
            self.assertGreater(Decimal(summary["spent_or_reserved_estimate_myr"]), 10)
            self.assertFalse(summary["enforcement_enabled"])
            self.assertIsNone(summary["remaining_estimate_myr"])
            self.assertEqual(summary["calls"], 7)

    def test_free_gemini_usage_costs_zero_and_legacy_paid_references_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            config = settings()
            spec = replace(config.models[0], billing_mode="FREE_TIER")
            ledger = BudgetLedger(config, Path(directory))
            historical = {"version": 1, "entries": [
                {"id": "old-gemini", "model_id": spec.model_id, "charged_estimate_myr": "20", "status": "RESERVED_OR_UNCERTAIN"},
                {"id": "old-deepseek", "model_id": "deepseek-flash", "charged_estimate_myr": "0.02", "status": "USAGE_REPORTED"}]}
            ledger.path.write_text(json.dumps(historical), encoding="utf-8")
            before = ledger.path.read_bytes()
            summary = ledger.summary()
            self.assertEqual(ledger.path.read_bytes(), before)
            self.assertEqual(summary["legacy_gemini_paid_rate_reference_myr"], "20")
            call = ledger.reserve(spec, 1_000_000, 32768)
            self.assertEqual(ledger.settle(call, spec, 50000, 20000), "0")
            summary = ledger.summary()
            self.assertEqual(summary["reported_usage_estimate_myr"], "0.02")
            self.assertEqual(summary["spent_or_reserved_estimate_myr"], "0.02")
            self.assertEqual(json.loads(ledger.path.read_text())["entries"][:2], historical["entries"])

    def test_default_settings_ignore_retired_budget_and_use_free_gemini(self):
        with patch('backend.app.services.analysis_settings.dotenv_values', return_value={
            'TERRA_LLM_BUDGET_MYR': '10', 'TERRA_GEMINI_BILLING_MODE': 'FREE_TIER'}), patch.dict('os.environ', {}, clear=True):
            config = AnalysisSettings.load()
        self.assertEqual([spec.billing_mode for spec in config.models], ['FREE_TIER', 'FREE_TIER', 'PAID'])
        self.assertTrue(config.public()['usage_tracking_only'])
        self.assertNotIn('budget_myr', config.public())


class ScriptedTransport:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def request(self, method, url, headers, payload=None, timeout=180):
        self.requests.append({"method": method, "url": url, "payload": copy.deepcopy(payload)})
        return self.responses.pop(0)


class ProviderTests(unittest.TestCase):
    def test_gemini_preserves_signatures_and_bills_thinking_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            config = settings()
            signature = {"functionCall": {"id": "call", "name": "search_projects", "args": {}}, "thoughtSignature": "opaque-test-signature"}
            first = {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [signature]}}],
                     "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10, "thoughtsTokenCount": 5}}
            final = {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [{"text": '{"ok":true}'}]}}],
                     "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 8}}
            transport = ScriptedTransport([{"totalTokens": 100}, first, {"totalTokens": 120}, final])
            adapter = ProviderAdapter(config.models[0], config, BudgetLedger(config, Path(directory)), transport)
            session = adapter.session("system", "instruction", [], [{"name": "search_projects", "description": "read", "parameters": {"type": "object"}}], {"type": "object"})
            turn = session.step()
            self.assertEqual(turn.usage.output_tokens, 15)
            self.assertEqual(turn.calls[0].name, "search_projects")
            session.step([{"id": "call", "name": "search_projects", "result": {"records": []}}])
            self.assertEqual(transport.requests[-1]["payload"]["generationConfig"]["responseFormat"]["text"]["mimeType"], "APPLICATION_JSON")
            history = transport.requests[-1]["payload"]["contents"]
            self.assertEqual(history[1]["parts"][0], signature)

    def test_deepseek_replays_reasoning_ephemerally_and_rejects_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            config = settings()
            first = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "reasoning_content": "private-test-reasoning", "tool_calls": [{"id": "call", "type": "function", "function": {"name": "search_projects", "arguments": "{}"}}]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
            final = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok":true}'}}], "usage": {"prompt_tokens": 120, "completion_tokens": 10}}
            transport = ScriptedTransport([first, final])
            adapter = ProviderAdapter(config.models[2], config, BudgetLedger(config, Path(directory)), transport)
            session = adapter.session("system", "instruction", [], [{"name": "search_projects", "description": "read", "parameters": {"type": "object"}}], {})
            turn = session.step()
            self.assertNotIn("private-test-reasoning", repr(turn))
            session.step([{"id": "call", "name": "search_projects", "result": {"records": []}}])
            self.assertEqual(transport.requests[-1]["payload"]["messages"][2]["reasoning_content"], "private-test-reasoning")
            with self.assertRaises(ProviderError):
                adapter.session("system", "instruction", [{"media_type": "application/pdf", "data": b"test"}], [], {})
