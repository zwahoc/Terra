import asyncio
import json
import unittest
from unittest.mock import patch

from backend.app.main import app
from backend.app.services.impact_service import ImpactConflict


async def request(method, path, query="", body=None):
    messages = []
    encoded = json.dumps(body).encode() if body is not None else b""
    sent = False
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": encoded, "more_body": False}
        return {"type": "http.disconnect"}
    async def send(message):
        messages.append(message)
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": query.encode(), "root_path": "",
        "headers": [(b"content-type", b"application/json")] if body is not None else [],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }
    await app(scope, receive, send)
    status = next(item["status"] for item in messages if item["type"] == "http.response.start")
    headers = dict(next(item["headers"] for item in messages if item["type"] == "http.response.start"))
    content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return status, headers, content


class ImpactApiTests(unittest.TestCase):
    def test_calculation_endpoint_uses_consistent_envelope(self):
        expected = {"data": {"assessment": {"id": "IMP-X"}, "current": True, "replayed": False}, "meta": {}, "error": None}
        with patch("backend.app.routes.impact.calculate_impact", return_value=expected) as calculate:
            status, _, content = asyncio.run(request(
                "POST", "/api/impact-assessments/proposals/ALC-001/calculate",
                body={"idempotency_key": "k", "revision_reason": "reason", "actor_label": "Demo operator"},
            ))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content), expected)
        self.assertEqual(calculate.call_args.args[:2], ("PROPOSAL_FORECAST", "ALC-001"))

    def test_stale_calculation_maps_to_409(self):
        error = ImpactConflict("IMPACT_INPUT_STALE", "stale")
        with patch("backend.app.routes.impact.calculate_impact", side_effect=error):
            status, _, content = asyncio.run(request(
                "POST", "/api/impact-assessments/transfers/TRF-007/calculate",
                body={"idempotency_key": "k", "revision_reason": "reason", "actor_label": "Demo operator"},
            ))
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(content)["error"]["code"], "IMPACT_INPUT_STALE")

    def test_export_contract_requires_basis_and_format_and_returns_csv(self):
        with patch("backend.app.routes.impact.export_csv", return_value="a,b\r\n1,2\r\n"):
            status, headers, content = asyncio.run(request(
                "GET", "/api/exports/impact",
                query="basis=ACTUAL_CONFIRMED_USE&format=csv",
            ))
        self.assertEqual(status, 200)
        self.assertIn(b"text/csv", headers[b"content-type"])
        self.assertEqual(content, b"a,b\r\n1,2\r\n")

    def test_invalid_export_basis_is_422_envelope(self):
        status, _, content = asyncio.run(request(
            "GET", "/api/exports/impact", query="basis=BOTH&format=json"
        ))
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(content)["error"]["code"], "REQUEST_VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
