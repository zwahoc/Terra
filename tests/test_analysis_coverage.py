"""Regression checks for a valid-looking first-row-only PDF extraction."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.schemas.analysis import FileDraft
from backend.app.services.analysis_budget import BudgetLedger
from backend.app.services.analysis_providers import ProviderAdapter, provider_error_details, RequestPacer
from backend.app.services.ingestion_errors import IngestionError
from tests.test_analysis import ScriptedTransport, settings
from tests import test_analysis as analysis_fixtures
from backend.app.schemas.analysis import AnalyseRequest, SelectPrimaryRequest


class PdfCoverageRegressionTests(unittest.TestCase):
    def test_pacing_spaces_generation_without_replaying_any_request(self):
        with tempfile.TemporaryDirectory() as directory:
            pacer=RequestPacer(Path(directory))
            with patch('backend.app.services.analysis_providers.time.time',return_value=100), patch('backend.app.services.analysis_providers.time.sleep') as sleep:
                pacer.wait('gemini_flash',15)
                pacer.wait('gemini_flash',15)
                self.assertEqual([call.args[0] for call in sleep.call_args_list],[0,15])
    def test_saved_unchecked_pdf_result_is_not_still_advertised_complete(self):
        fixture=analysis_fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        value=fixture.start()
        batch=fixture.repo.rows[fixture.batch_id]
        batch.submissions[0].source.display_filename='legacy.pdf'
        for comparison in batch.comparisons:
            for item in comparison.manifest['files']:
                if item['submission_id']==batch.submissions[0].id:
                    item['display_filename']='legacy.pdf'
        updated=fixture.service.get(fixture.batch_id,value['id'])
        self.assertEqual(updated['runs'][0]['status'],'PARTIAL')
        self.assertTrue(updated['runs'][0]['coverage_verification_required'])
        with self.assertRaises(IngestionError) as caught:
            fixture.service.select_primary(fixture.batch_id,SelectPrimaryRequest(
                expected_revision=batch.revision,expected_preference_revision=0,
                comparison_id=value['id'],run_id=value['runs'][0]['id']))
        self.assertEqual(caught.exception.code,'DOCUMENT_COVERAGE_NOT_VERIFIED')
        # The historical stored result remains immutable.
        self.assertEqual(fixture.repo.rows[fixture.batch_id].comparisons[0].runs[0].status,'SUCCEEDED')

    def test_complete_numbered_rows_pass_and_missing_pages_do_not(self):
        from backend.app.services.analysis_coverage import validate_pdf_coverage, numbered_table_references
        refs = numbered_table_references('ITEM DESCRIPTION UNIT QTY\nX01 First\nX02 Second\nX03 Third\n')
        self.assertEqual(refs, ['X01', 'X02', 'X03'])
        self.assertEqual(numbered_table_references('Document X01\nX02 date\nX03 other'), [])
        draft = FileDraft.model_validate({'document_type':'BOQ','summary':'Complete', 'page_coverage':[1,2],
            'records':[{'raw_description':ref,'source_page':2,'source_item_ref':ref} for ref in refs]})
        coverage = validate_pdf_coverage(draft, {2:refs}, [1,2])
        self.assertEqual(coverage['numbered_source_items'], 3)
        draft.page_coverage = [2]
        with self.assertRaises(IngestionError):
            validate_pdf_coverage(draft, {2:refs}, [1,2])

    def test_a_single_record_cannot_pass_a_numbered_multirow_source(self):
        from backend.app.services.analysis_coverage import validate_pdf_coverage
        draft = FileDraft.model_validate({"document_type": "BOQ", "summary": "One-row-only candidate", "records": [
            {"raw_description": "Generic row one", "source_page": 1, "source_item_ref": "X01"}], "page_coverage": [1]})
        with self.assertRaises(IngestionError) as caught:
            validate_pdf_coverage(draft, {1: ["X01", "X02", "X03"]}, [1])
        self.assertEqual(caught.exception.code, "DOCUMENT_COVERAGE_INCOMPLETE")

    def test_length_finish_reason_preserves_a_specific_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            config = settings()
            response = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": '{"records":[', "reasoning_content": "private"}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 8192}}
            adapter = ProviderAdapter(config.models[2], config, BudgetLedger(config, Path(directory)), ScriptedTransport([response]))
            with self.assertRaises(IngestionError) as caught:
                adapter.session("Test", "Test", [], [], {}).step()
            self.assertEqual(caught.exception.code, "MODEL_OUTPUT_LIMIT")
            self.assertEqual(caught.exception.details["finish_reason"], "length")
            self.assertEqual(caught.exception.final_output, '{"records":[')
            self.assertNotIn("private", str(caught.exception.details))

    def test_quota_diagnostics_whitelist_retry_and_limit_without_raw_messages(self):
        payload={'error':{'message':'Echoed sensitive input must not be retained', 'details':[
            {'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'32.2s'},
            {'@type':'type.googleapis.com/google.rpc.QuotaFailure','violations':[
                {'quotaMetric':'generate_content_requests','quotaId':'RequestsPerMinute','quotaValue':'5','description':'private data'}]}]}}
        value=provider_error_details(payload,429)
        self.assertGreaterEqual(value['retry_after_seconds'],32)
        self.assertEqual(value['quota_violations'][0]['quotaId'],'RequestsPerMinute')
        self.assertNotIn('sensitive',str(value))
        self.assertNotIn('private',str(value))
