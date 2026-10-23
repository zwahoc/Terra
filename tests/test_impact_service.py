import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.app.repositories.impact_repository import ImpactPersistenceError, ImpactPersistenceState
from backend.app.services.impact_service import (
    ImpactCalculationInput, ImpactConflict, calculate_impact, list_assessments,
)


class FakeImpactRepository:
    def __init__(self, seed, fail_persist=False):
        self.seed = json.loads(json.dumps(seed))
        self.fail_persist = fail_persist
        self.operations = {}
        current = {}
        for assessment in seed["impact_assessments"]:
            entity_id = assessment["proposal_id"] or assessment["transfer_id"]
            current[f'{assessment["basis"]}:{entity_id}'] = assessment
        self.heads = {}
        for basis, entity in (("PROPOSAL_FORECAST", "allocation_proposals"), ("ACTUAL_CONFIRMED_USE", "transfers")):
            for row in seed[entity]:
                scope = f'{basis}:{row["id"]}'
                assessment = current.get(scope)
                self.heads[scope] = {
                    "id": scope, "basis": basis,
                    "proposal_id": row["id"] if basis == "PROPOSAL_FORECAST" else None,
                    "transfer_id": row["id"] if basis == "ACTUAL_CONFIRMED_USE" else None,
                    "current_assessment_id": assessment["id"] if assessment else None,
                    "revision": 1 if assessment else 0, "input_fingerprint": None,
                    "updated_at": assessment["calculated_at"] if assessment else None,
                }
        self.persisted = []

    def snapshot(self):
        return json.loads(json.dumps({key: value for key, value in self.seed.items() if key != "metadata"}))

    def persistence_state(self, scope_id, operation_id):
        operation = self.operations.get(operation_id)
        assessment = None
        if operation:
            assessment = next(row for row in self.seed["impact_assessments"] if row["id"] == operation["assessment_id"])
        return ImpactPersistenceState(self.heads[scope_id], operation, assessment)

    def persist(self, basis, command):
        if self.fail_persist:
            raise ImpactPersistenceError("stale")
        assessment = json.loads(json.dumps(command["assessment"]))
        self.seed["impact_assessments"].append(assessment)
        head = self.heads[command["scope_id"]]
        head.update(current_assessment_id=assessment["id"], revision=command["new_revision"],
                    input_fingerprint=command["input_fingerprint"], updated_at=assessment["calculated_at"])
        self.operations[command["operation_id"]] = {
            "id": command["operation_id"], "request_fingerprint": command["request_fingerprint"],
            "scope_id": command["scope_id"], "assessment_id": assessment["id"],
        }
        self.persisted.append((basis, command))

    def list_heads(self):
        return list(self.heads.values())


class ImpactServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = json.loads((Path(__file__).parents[1] / "data" / "terra_seed.json").read_text(encoding="utf-8"))
        cls.clock = staticmethod(lambda: datetime(2026, 10, 14, 12, 30, tzinfo=timezone(timedelta(hours=8))))

    def request(self, key="impact-key"):
        return ImpactCalculationInput(key, "Operator requested recalculation", "Demo operator")

    def test_forecast_regression_persists_433_5_as_new_revision(self):
        repository = FakeImpactRepository(self.seed)
        response = calculate_impact("PROPOSAL_FORECAST", "ALC-001", self.request(), repository, self.clock)
        assessment = response["data"]["assessment"]
        self.assertEqual(assessment["avoided_production_kgco2e"], 450.0)
        self.assertEqual(assessment["additional_transport_kgco2e"], 4.5)
        self.assertEqual(assessment["additional_processing_kgco2e"], 12.0)
        self.assertEqual(assessment["net_avoided_kgco2e"], 433.5)
        self.assertEqual(assessment["assumptions"]["revision"]["number"], 2)
        self.assertEqual(assessment["assumptions"]["revision"]["previous_assessment_id"], "IMP-001")
        self.assertEqual(assessment["calculated_at"], "2026-10-14T12:30:00+08:00")

    def test_actual_partial_use_keeps_full_movement_costs(self):
        repository = FakeImpactRepository(self.seed)
        response = calculate_impact("ACTUAL_CONFIRMED_USE", "TRF-006", self.request("partial"), repository, self.clock)
        assessment = response["data"]["assessment"]
        self.assertEqual(assessment["quantity_assessed"], 550)
        self.assertEqual(assessment["assumptions"]["moved_quantity"], 600)
        self.assertEqual(assessment["avoided_production_kgco2e"], 412.5)
        self.assertEqual(assessment["additional_transport_kgco2e"], 4.5)
        self.assertEqual(assessment["additional_processing_kgco2e"], 12.0)
        self.assertEqual(assessment["net_avoided_kgco2e"], 396.0)
        self.assertEqual(assessment["calculation_status"], "DEMO")

    def test_identical_retry_returns_same_revision_without_second_write(self):
        repository = FakeImpactRepository(self.seed)
        first = calculate_impact("PROPOSAL_FORECAST", "ALC-001", self.request(), repository, self.clock)
        second = calculate_impact("PROPOSAL_FORECAST", "ALC-001", self.request(), repository, self.clock)
        self.assertFalse(first["data"]["replayed"])
        self.assertTrue(second["data"]["replayed"])
        self.assertEqual(first["data"]["assessment"]["id"], second["data"]["assessment"]["id"])
        self.assertEqual(len(repository.persisted), 1)

    def test_persistence_failure_is_reported_as_stale_not_current(self):
        repository = FakeImpactRepository(self.seed, fail_persist=True)
        with self.assertRaises(ImpactConflict) as raised:
            calculate_impact("ACTUAL_CONFIRMED_USE", "TRF-007", self.request(), repository, self.clock)
        self.assertEqual(raised.exception.code, "IMPACT_INPUT_STALE")
        self.assertEqual(repository.heads["ACTUAL_CONFIRMED_USE:TRF-007"]["current_assessment_id"], "IMP-006")

    def test_current_selection_returns_one_revision_per_scope(self):
        repository = FakeImpactRepository(self.seed)
        new = calculate_impact("PROPOSAL_FORECAST", "ALC-001", self.request(), repository, self.clock)
        response = list_assessments(basis="PROPOSAL_FORECAST", repository=repository)
        alc001 = [row for row in response["data"] if row["proposal_id"] == "ALC-001"]
        self.assertEqual([row["id"] for row in alc001], [new["data"]["assessment"]["id"]])


if __name__ == "__main__":
    unittest.main()
