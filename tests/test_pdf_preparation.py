"""Automatic DeepSeek PDF evidence preparation and no-partial-input checks."""

import base64
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.app.services.analysis_budget import BudgetLedger
from backend.app.services.analysis_providers import ProviderAdapter
from backend.app.services.analysis_service import ComparisonService
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.pdf_preparation import PdfPreparer, _prepare_document
from backend.app.schemas.analysis import AnalyseRequest
from tests.pdf_test_helpers import diagnostic_pdf
from tests import test_analysis as analysis_fixtures
from tests.test_analysis import ScriptedAdapter, ScriptedTransport, settings


class PdfPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="terra PDF 材料 ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "diagnostic.pdf"
        self.path.write_bytes(diagnostic_pdf())
        self.preparer = PdfPreparer(self.root / "preparation")

    def test_real_text_and_image_pages_are_included_with_page_provenance(self):
        original = self.path.read_bytes()
        result = self.preparer.prepare(self.path)
        self.assertEqual(result.evidence["page_count"], 2)
        self.assertEqual(result.evidence["pages_with_text"], 1)
        self.assertEqual(result.evidence["page_numbers"], [1, 2])
        self.assertTrue(result.evidence["all_pages_included"])
        self.assertFalse(result.evidence["local_ocr"])
        self.assertIn("TEXT PAGE ONE", result.text)
        self.assertIn("PDF page 2 of 2", result.text)
        self.assertIn("No extractable text", result.text)
        self.assertEqual(len(result.attachments), 2)
        for attachment in result.attachments:
            with Image.open(io.BytesIO(attachment["data"])) as image:
                self.assertEqual(image.size, (600, 400))
                # Each page has actual visible marks rather than a blank conversion.
                self.assertLess(image.convert("L").getextrema()[0], 100)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list((self.root / "preparation").iterdir()), [])

    def test_unreadable_pdf_fails_without_partial_evidence_or_temp_files(self):
        self.path.write_bytes(b"%PDF-broken")
        with self.assertRaises(IngestionError) as caught:
            self.preparer.prepare(self.path)
        self.assertEqual(caught.exception.code, "PDF_INVALID")
        self.assertEqual(list((self.root / "preparation").iterdir()), [])

    def test_limits_and_timeout_are_explicit_and_do_not_return_first_pages(self):
        with patch("backend.app.services.pdf_preparation.MAX_SOURCE_BYTES", 1):
            with self.assertRaises(IngestionError) as caught:
                self.preparer.prepare(self.path)
            self.assertEqual(caught.exception.code, "PDF_PREPARATION_LIMIT")
        with patch("backend.app.services.pdf_preparation.MAX_PREPARED_BYTES", 1):
            with self.assertRaises(IngestionError) as caught:
                _prepare_document(self.path, self.root)
            self.assertEqual(caught.exception.code, "PDF_PREPARATION_LIMIT")
        with patch("backend.app.services.pdf_preparation.subprocess.run", side_effect=subprocess.TimeoutExpired("pdf", 90)):
            with self.assertRaises(IngestionError) as caught:
                self.preparer.prepare(self.path)
            self.assertEqual(caught.exception.code, "PDF_PREPARATION_TIMEOUT")
        self.assertEqual(list((self.root / "preparation").iterdir()), [])

    def test_deepseek_receives_labelled_png_pages_through_existing_budget_guard(self):
        result = self.preparer.prepare(self.path)
        config = settings()
        transport = ScriptedTransport([{"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 20}}])
        ledger = BudgetLedger(config, self.root / "budget")
        adapter = ProviderAdapter(config.models[2], config, ledger, transport)
        adapter.session("Prepare evidence only", result.text, result.attachments, [], {}).step()
        content = transport.requests[0]["payload"]["messages"][1]["content"]
        self.assertIn("TEXT PAGE ONE", content[0]["text"])
        self.assertIn("PDF page 1 of 2", content[1]["text"])
        self.assertIn("PDF page 2 of 2", content[3]["text"])
        for block in (content[2], content[4]):
            url = block["image_url"]["url"]
            self.assertTrue(base64.b64decode(url.split(",", 1)[1]).startswith(b"\x89PNG"))
        self.assertEqual(ledger.summary()["uncertain_calls"], 0)


class PdfOrchestrationTests(unittest.TestCase):
    def test_pdf_is_prepared_for_deepseek_and_stays_native_for_gemini(self):
        # Reuse the isolated SQL-repository double and preference store, not real keys.
        fixture = analysis_fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        intake = fixture.intake
        batch = intake.create()
        intake.add_files(batch.id, 1, [("diagnostic.pdf", io.BytesIO(diagnostic_pdf()))])
        seen = []

        class CapturingAdapter(ScriptedAdapter):
            def session(self, system, instruction, attachments, tools, output_schema):
                task = json.loads(instruction)["task"]
                if task["stage"] == "INTERPRET_FILE":
                    seen.append({"slot": self.spec.slot, "task": task, "attachments": attachments})
                    self_test = output_schema['$defs']['DraftRecord']['required']
                    if not {'source_page', 'source_item_ref', 'project_ref'}.issubset(self_test):
                        raise AssertionError('PDF provenance must be required by the provider schema')
                    if 'page_coverage' not in output_schema['required']:
                        raise AssertionError('PDF page acknowledgement must be required')
                return super().session(system, instruction, attachments, tools, output_schema)

        service = ComparisonService(intake, settings(), fixture.service.ledger,
            provider_factory=lambda spec: CapturingAdapter(spec, []), schedule=lambda fn, *args: fn(*args),
            preferences=fixture.service.preferences)
        result = service.start(batch.id, AnalyseRequest(expected_revision=2, idempotency_key="pdf-comparison", mode="COMPARE"))
        self.assertEqual([run["status"] for run in result["runs"]], ["SUCCEEDED"] * 3)
        deepseek = next(item for item in seen if item["slot"] == "deepseek_flash")
        self.assertEqual(len(deepseek["attachments"]), 2)
        self.assertTrue(all(item["media_type"] == "image/png" for item in deepseek["attachments"]))
        self.assertEqual(deepseek["task"]["content_preparation"]["page_count"], 2)
        for item in seen:
            if item["slot"].startswith("gemini"):
                self.assertEqual(len(item["attachments"]), 1)
                self.assertEqual(item["attachments"][0]["media_type"], "application/pdf")
        reopened = intake.get(batch.id)
        prepared = reopened.comparisons[0].runs[2].files[0].preparation
        self.assertEqual(prepared["page_numbers"], [1, 2])
        self.assertNotIn("TEXT PAGE ONE", json.dumps(prepared))
        source, path = intake.source(batch.id, reopened.submissions[0].id)
        self.assertEqual(path.read_bytes(), diagnostic_pdf())
