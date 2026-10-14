import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.main import app
from backend.app.repositories.transfer_repository import (
    TransferRepositoryError,
    TransferRepositoryUnavailable,
)
from backend.app.services import transfer_read_service


async def request(
    method: str, path: str, json_body: dict | None = None
) -> tuple[int, dict]:
    messages = []
    request_sent = False
    encoded_body = json.dumps(json_body).encode("utf-8") if json_body is not None else b""

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": encoded_body,
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": (
            [(b"content-type", b"application/json")] if json_body is not None else []
        ),
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    await app(scope, receive, send)

    status = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(body)


class FakeRepository:
    def __init__(self, records=None, error=None):
        self.records = records or []
        self.error = error

    def list(self):
        if self.error:
            raise self.error
        return self.records

    def get(self, transfer_id):
        if self.error:
            raise self.error
        return next((row for row in self.records if row["id"] == transfer_id), None)


class TransferApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_path = Path(__file__).resolve().parents[1] / "data" / "terra_seed.json"
        cls.seed = json.loads(seed_path.read_text(encoding="utf-8"))
        cls.meta = {
            "dataset_version": cls.seed["metadata"]["version"],
            "synthetic": cls.seed["metadata"]["synthetic"],
            "as_of_date": cls.seed["metadata"]["as_of_date"],
        }

    def test_service_list_uses_repository_records_and_baseline_metadata(self):
        emulator_records = [{**self.seed["transfers"][0], "notes": "runtime value"}]

        response = transfer_read_service.list_transfers(
            FakeRepository(records=emulator_records)
        )

        self.assertEqual(response["data"], emulator_records)
        self.assertEqual(response["meta"], self.meta)
        self.assertNotEqual(response["data"], self.seed["transfers"])
        self.assertIsNone(response["error"])

    def test_service_get_returns_one_complete_repository_record(self):
        response = transfer_read_service.get_transfer(
            "TRF-001", FakeRepository(records=self.seed["transfers"])
        )

        self.assertEqual(response["data"], self.seed["transfers"][0])
        self.assertEqual(response["meta"], self.meta)

    def test_unknown_transfer_returns_404_envelope(self):
        not_found = transfer_read_service.TransferNotFound("TRF-999")
        with patch(
            "backend.app.routes.transfers.get_transfer", side_effect=not_found
        ):
            status, response = asyncio.run(request("GET", "/api/transfers/TRF-999"))

        self.assertEqual(status, 404)
        self.assertIsNone(response["data"])
        self.assertIsNone(response["meta"])
        self.assertEqual(response["error"]["code"], "TRANSFER_NOT_FOUND")
        self.assertEqual(response["error"]["details"]["transfer_id"], "TRF-999")

    def test_emulator_unavailability_returns_503_without_fallback(self):
        repository = FakeRepository(
            error=TransferRepositoryUnavailable("emulator unavailable")
        )

        with self.assertRaises(transfer_read_service.TransferReadUnavailable):
            transfer_read_service.list_transfers(repository)

        unavailable = transfer_read_service.TransferReadUnavailable(
            "TRANSFER_DATA_UNAVAILABLE",
            "The local SQL Connect emulator is unavailable.",
        )
        with patch(
            "backend.app.routes.transfers.list_transfers", side_effect=unavailable
        ):
            status, response = asyncio.run(request("GET", "/api/transfers"))

        self.assertEqual(status, 503)
        self.assertIsNone(response["data"])
        self.assertEqual(response["error"]["code"], "TRANSFER_DATA_UNAVAILABLE")

    def test_provider_error_is_500_not_503(self):
        repository = FakeRepository(error=TransferRepositoryError("bad data"))

        with self.assertRaises(transfer_read_service.TransferReadError) as raised:
            transfer_read_service.list_transfers(repository)

        self.assertNotIsInstance(
            raised.exception, transfer_read_service.TransferReadUnavailable
        )
        with patch(
            "backend.app.routes.transfers.list_transfers",
            side_effect=raised.exception,
        ):
            status, response = asyncio.run(request("GET", "/api/transfers"))

        self.assertEqual(status, 500)
        self.assertEqual(response["error"]["code"], "TRANSFER_DATA_ERROR")

    def test_post_transfers_is_not_allowed(self):
        status, response = asyncio.run(request("POST", "/api/transfers"))

        self.assertEqual(status, 405)
        self.assertEqual(response["detail"], "Method Not Allowed")

    def test_dispatch_quantity_field_is_explicitly_rejected(self):
        status, response = asyncio.run(request(
            "POST", "/api/transfers/TRF-001/dispatch",
            {"actor_label": "Demo operator", "idempotency_key": "dto-reject",
             "quantity": 100},
        ))

        self.assertEqual(status, 422)
        self.assertEqual(response["error"]["code"], "REQUEST_VALIDATION_ERROR")
        self.assertTrue(any(
            detail["loc"][-1] == "quantity" and detail["type"] == "extra_forbidden"
            for detail in response["error"]["details"]["validation_errors"]
        ))

    def test_receive_quantity_field_is_explicitly_rejected(self):
        status, response = asyncio.run(request(
            "POST", "/api/transfers/TRF-001/receive",
            {"actor_label": "Demo operator", "idempotency_key": "dto-receive-reject",
             "quantity": 100},
        ))

        self.assertEqual(status, 422)
        self.assertEqual(response["error"]["code"], "REQUEST_VALIDATION_ERROR")
        self.assertTrue(any(
            detail["loc"][-1] == "quantity" and detail["type"] == "extra_forbidden"
            for detail in response["error"]["details"]["validation_errors"]
        ))


if __name__ == "__main__":
    unittest.main()
