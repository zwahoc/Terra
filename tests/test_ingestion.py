"""Focused Phase 1 checks. Generic temporary files are not construction fixtures."""

import asyncio
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.app.main import app
from backend.app.repositories.ingestion_repository import TerraReadRepository
from backend.app.routes.ingestion import get_intake_service
from backend.app.schemas.ingestion import CaptureProjectContext, ContextPatch
from backend.app.services.ingestion_content import InitialContentReader
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore


async def http_request(method, url, body=b"", headers=None, client="127.0.0.1"):
    """ASGI test client, including multipart and whole-file responses, without httpx."""
    parts, messages, sent = urlsplit(url), [], False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
               "http_version": "1.1", "method": method, "scheme": "http",
               "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
               "root_path": "", "headers": headers or [], "client": (client, 50100),
               "server": ("127.0.0.1", 8000)}, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")


def json_request(method, url, value=None, **kwargs):
    status, headers, data = asyncio.run(http_request(method, url,
        body=json.dumps(value).encode() if value is not None else b"",
        headers=[(b"content-type", b"application/json")], **kwargs))
    return status, json.loads(data)


def multipart(revision, files):
    boundary = b"terra-test-boundary"
    chunks = [b"--" + boundary + b'\r\nContent-Disposition: form-data; name="expected_revision"\r\n\r\n' + str(revision).encode() + b"\r\n"]
    for filename, content in files:
        chunks.append(b"--" + boundary + b'\r\nContent-Disposition: form-data; name="files"; filename="' + filename.encode() + b'"\r\nContent-Type: application/octet-stream\r\n\r\n' + content + b"\r\n")
    chunks.append(b"--" + boundary + b"--\r\n")
    return b"".join(chunks), [(b"content-type", b"multipart/form-data; boundary=" + boundary)]


class MemoryDraftRepository:
    """Test double only. Production always uses the SQL Connect adapter."""
    def __init__(self):
        self.rows, self.history = {}, []

    def get(self, batch_id):
        return copy.deepcopy(self.rows.get(batch_id))

    def save(self, batch, expected_revision=None):
        current = self.rows.get(batch.id)
        if (expected_revision is None and current is not None) or (expected_revision is not None and (current is None or current.revision != expected_revision)):
            raise IngestionError("STALE_REVISION", "Stale batch")
        self.rows[batch.id] = copy.deepcopy(batch)
        self.history.append(copy.deepcopy(batch))


class FakeReads:
    def get_entity(self, entity, entity_id):
        return {"id": entity_id} if entity_id == "PRJ-001" else None

    def project_context(self, project_id):
        return {"project": {"id": project_id}, "collections": {"supply_offers": []}, "consistency": "OBSERVED_READS"}


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="terra intake 材料 ")
        self.addCleanup(self.temporary.cleanup)
        self.repo = MemoryDraftRepository()
        self.store = SourceStore(Path(self.temporary.name))
        self.service = IntakeService(self.repo, FakeReads(), self.store)

    def test_cross_batch_duplicate_hints_require_current_sql_records(self):
        first=self.service.create();second=self.service.create()
        self.service.add_files(first.id,1,[('original.txt',io.BytesIO(b'identical diagnostic'))])
        self.service.add_files(second.id,1,[('renamed.txt',io.BytesIO(b'identical diagnostic'))])
        matches=self.service.duplicates(second.id)['matches']
        self.assertEqual([m['batch_id'] for m in matches],[first.id])
        del self.repo.rows[first.id]
        # Disk checkpoint alone must not be advertised as a live database batch.
        self.assertEqual(self.service.duplicates(second.id)['matches'],[])

    def test_upload_reopen_context_and_explicit_restore(self):
        batch = self.service.create("PRJ-001")
        result = self.service.add_files(batch.id, 1, [("notes.txt", io.BytesIO("Hello 材料".encode())),
                                                     ("table.csv", io.BytesIO(b"a,b\n1,2\n"))])
        self.assertEqual(len(result["batch"]["submissions"]), 2)
        reopened = IntakeService(self.repo, FakeReads(), SourceStore(Path(self.temporary.name)))
        batch = reopened.patch_context(batch.id, ContextPatch(expected_revision=2, operator_notes="Keep this", operator_input={"stage": "intake"}))
        batch = reopened.capture_project(batch.id, CaptureProjectContext(expected_revision=3, project_id="PRJ-001"))
        self.assertEqual(batch.revision, 4)
        self.assertEqual(len(batch.context.project_observations), 1)
        self.repo.rows.clear()  # Equivalent missing-state branch; real restart proof runs separately.
        with self.assertRaisesRegex(IngestionError, "Explicitly restore"):
            reopened.get(batch.id)
        restored = reopened.restore(batch.id)
        self.assertEqual(restored.revision, 5)
        self.assertEqual(restored.context.operator_notes, "Keep this")
        self.assertTrue(restored.context.refresh_required)
        self.assertEqual(restored.context.project_observations, [])
        source, path = reopened.source(batch.id, restored.submissions[0].id)
        self.assertEqual(path.read_bytes(), "Hello 材料".encode())
        self.assertEqual(source.byte_size, len(path.read_bytes()))

    def test_duplicates_and_stale_edits_do_not_add_submissions(self):
        batch = self.service.create()
        result = self.service.add_files(batch.id, 1, [("a.txt", io.BytesIO(b"hello")), ("copy.txt", io.BytesIO(b"hello"))])
        self.assertEqual(len(result["batch"]["submissions"]), 1)
        self.assertEqual([row["duplicate_in_batch"] for row in result["files"]], [False, True])
        with self.assertRaisesRegex(IngestionError, "changed"):
            self.service.patch_context(batch.id, ContextPatch(expected_revision=1))
        self.assertEqual(self.repo.get(batch.id).revision, 2)

    def test_original_integrity_and_portable_display_names(self):
        source = self.store.put(io.BytesIO(b"original"), "C:\\fakepath\\材料.txt")
        self.assertEqual(source.display_filename, "材料.txt")
        self.store.path(source).write_bytes(b"changed")
        with self.assertRaisesRegex(IngestionError, "changed"):
            self.store.path(source)
        with self.assertRaises(IngestionError):
            self.store.recoverable("../escape")

    def test_content_preparation_preserves_utf8_and_csv_cells(self):
        for name, data, kind in (("材料.txt", "Hello 材料".encode(), "TEXT"),
                                 ("table.csv", b'column,value\r\n"a,b",2\r\n', "CELLS"),
                                 ("table.tsv", b'column\tvalue\r\n"a,b"\t2\r\n', "CELLS"),
                                 ("unknown.bin", b"\x00\xff", "UNSUPPORTED")):
            source = self.store.put(io.BytesIO(data), name)
            prepared = InitialContentReader().prepare(source, self.store.path(source))
            self.assertEqual(prepared.kind, kind)
            if kind == "CELLS":
                self.assertEqual(prepared.cells[1], ["a,b", "2"])
        source = self.store.put(io.BytesIO(b"%PDF-generic-signature-only"), "sample.pdf")
        self.assertEqual(InitialContentReader().prepare(source, self.store.path(source)).kind, "NATIVE_CANDIDATE")

    def test_http_upload_whole_source_and_local_write_boundary(self):
        app.dependency_overrides[get_intake_service] = lambda: self.service
        self.addCleanup(app.dependency_overrides.clear)
        status, value = json_request("POST", "/api/ingestion/batches", {})
        self.assertEqual(status, 200)
        batch_id = value["data"]["id"]
        payload, headers = multipart(1, [("notes.txt", b"hello"), ("table.csv", b"a,b\n1,2")])
        status, _, data = asyncio.run(http_request("POST", f"/api/ingestion/batches/{batch_id}/files", payload, headers))
        self.assertEqual(status, 200, data)
        batch = json.loads(data)["data"]["batch"]
        submission_id = batch["submissions"][0]["id"]
        status, headers, original = asyncio.run(http_request("GET", f"/api/ingestion/batches/{batch_id}/files/{submission_id}/source"))
        self.assertEqual((status, original), (200, b"hello"))
        self.assertIn(b"attachment", headers[b"content-disposition"])
        status, result = json_request("POST", "/api/ingestion/batches", {}, client="192.168.1.9")
        self.assertEqual((status, result["error"]["code"]), (403, "LOCAL_ONLY"))
        status, _, _ = asyncio.run(http_request("POST", "/api/ingestion/batches", b"{}", [(b"origin", b"https://untrusted.example"), (b"content-type", b"application/json")]))
        self.assertEqual(status, 403)

    def test_no_checkpoint_fallback_when_provider_unavailable(self):
        batch = self.service.create()
        with patch.object(self.repo, "get", side_effect=IngestionError("INGESTION_UNAVAILABLE", "Unavailable", 503)):
            with self.assertRaisesRegex(IngestionError, "Unavailable"):
                self.service.get(batch.id)


class PaginationTests(unittest.TestCase):
    def test_context_follows_every_page_beyond_snapshot_limit(self):
        repository = TerraReadRepository(adapter=object())
        with patch.object(repository, "get_entity", return_value={"id": "PRJ-001"}), patch.object(repository, "page") as page:
            def fetch(entity, **kwargs):
                if entity != "documents":
                    return {"records": [], "next_cursor": None}
                start = int(kwargs["after"] or "0")
                end = min(start + 100, 1105)
                return {"records": [{"id": f"DOC-{i}"} for i in range(start, end)],
                        "next_cursor": str(end) if end < 1105 else None}
            # Numeric test cursors are padded so key ordering agrees with the provider.
            def padded(entity, **kwargs):
                value = fetch(entity, **kwargs)
                if value["next_cursor"]:
                    value["next_cursor"] = value["next_cursor"].zfill(5)
                return value
            page.side_effect = padded
            context = repository.project_context("PRJ-001")
        self.assertEqual(len(context["collections"]["documents"]), 1105)
        self.assertEqual(context["coverage"], "ALL_PAGES_OBSERVED")
