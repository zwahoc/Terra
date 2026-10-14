"""Repository boundary for carbon inputs, revisions, and impact exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terra.local_adapter import AdapterError, AdapterUnavailableError, LocalDataConnect


class ImpactRepositoryError(RuntimeError):
    pass


class ImpactRepositoryUnavailable(ImpactRepositoryError):
    pass


class ImpactPersistenceError(ImpactRepositoryError):
    pass


@dataclass(frozen=True)
class ImpactPersistenceState:
    head: dict[str, Any]
    operation: dict[str, Any] | None
    assessment: dict[str, Any] | None


class ImpactRepository:
    """Use only named administrative operations on the guarded local adapter."""

    def __init__(self, adapter: LocalDataConnect | None = None) -> None:
        try:
            self._adapter = adapter or LocalDataConnect()
        except ValueError as exc:
            raise ImpactRepositoryError("The local adapter configuration is invalid.") from exc

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        try:
            return self._adapter.snapshot()
        except AdapterUnavailableError as exc:
            raise ImpactRepositoryUnavailable("The local emulator is unavailable.") from exc
        except AdapterError as exc:
            raise ImpactRepositoryError("Carbon input retrieval failed.") from exc

    @staticmethod
    def _head(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "basis": row["basis"],
            "proposal_id": row["proposalId"],
            "transfer_id": row["transferId"],
            "current_assessment_id": row["currentAssessmentId"],
            "revision": row["revision"],
            "input_fingerprint": row["inputFingerprint"],
            "updated_at": row["updatedAt"],
        }

    @staticmethod
    def _assessment(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "basis": row["basis"],
            "proposal_id": row["proposalId"],
            "transfer_id": row["transferId"],
            "quantity_assessed": row["quantityAssessed"],
            "unit": row["unit"],
            "baseline_description": row["baselineDescription"],
            "avoided_production_kgco2e": row["avoidedProductionKgco2E"],
            "additional_transport_kgco2e": row["additionalTransportKgco2E"],
            "additional_processing_kgco2e": row["additionalProcessingKgco2E"],
            "net_avoided_kgco2e": row["netAvoidedKgco2E"],
            "factor_ids": row["factorIds"],
            "assumptions": row["assumptions"],
            "calculation_status": row["calculationStatus"],
            "calculated_at": row["calculatedAt"],
        }

    def persistence_state(
        self, scope_id: str, operation_id: str
    ) -> ImpactPersistenceState:
        try:
            result = self._adapter.execute(
                "GetImpactPersistenceState",
                {"scopeId": scope_id, "operationId": operation_id},
            )
            head = self._head(result["impactAssessmentHead"])
            operation_row = result["impactCalculationOperation"]
            operation = None
            assessment = None
            if operation_row is not None:
                operation = {
                    "id": operation_row["id"],
                    "request_fingerprint": operation_row["requestFingerprint"],
                    "scope_id": operation_row["scopeId"],
                    "assessment_id": operation_row["assessmentId"],
                }
                if operation_row["assessment"] is not None:
                    assessment = self._assessment(operation_row["assessment"])
            return ImpactPersistenceState(head, operation, assessment)
        except AdapterUnavailableError as exc:
            raise ImpactRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc:
            raise ImpactRepositoryError("Impact persistence state is invalid.") from exc

    def persist(self, basis: str, command: dict[str, Any]) -> None:
        operation = (
            "PersistForecastImpactAssessment"
            if basis == "PROPOSAL_FORECAST"
            else "PersistActualImpactAssessment"
        )
        variables = {
            "scopeId": command["scope_id"],
            "operationId": command["operation_id"],
            "requestFingerprint": command["request_fingerprint"],
            "assessmentId": command["assessment"]["id"],
            "expectedRevision": command["expected_revision"],
            "newRevision": command["new_revision"],
            "inputFingerprint": command["input_fingerprint"],
            "calculatedAt": command["assessment"]["calculated_at"],
            "assessment": {
                "id": command["assessment"]["id"],
                "basis": command["assessment"]["basis"],
                "proposalId": command["assessment"]["proposal_id"],
                "transferId": command["assessment"]["transfer_id"],
                "quantityAssessed": command["assessment"]["quantity_assessed"],
                "unit": command["assessment"]["unit"],
                "baselineDescription": command["assessment"]["baseline_description"],
                "avoidedProductionKgco2E": command["assessment"]["avoided_production_kgco2e"],
                "additionalTransportKgco2E": command["assessment"]["additional_transport_kgco2e"],
                "additionalProcessingKgco2E": command["assessment"]["additional_processing_kgco2e"],
                "netAvoidedKgco2E": command["assessment"]["net_avoided_kgco2e"],
                "factorIds": command["assessment"]["factor_ids"],
                "assumptions": command["assessment"]["assumptions"],
                "calculationStatus": command["assessment"]["calculation_status"],
                "calculatedAt": command["assessment"]["calculated_at"],
            },
        }
        if basis == "PROPOSAL_FORECAST":
            variables.update(
                {
                    "proposalId": command["source_guard"]["proposal_id"],
                    "expectedQuantity": command["source_guard"]["proposed_quantity"],
                    "expectedUnit": command["source_guard"]["unit"],
                }
            )
        else:
            variables.update(
                {
                    "transferId": command["source_guard"]["transfer_id"],
                    "expectedUsedQuantity": command["source_guard"]["actually_used_quantity"],
                    "expectedDispatchedQuantity": command["source_guard"]["dispatched_quantity"],
                    "expectedReceivedQuantity": command["source_guard"]["received_quantity"],
                    "expectedReuseConfirmedAt": command["source_guard"]["reuse_confirmed_at"],
                }
            )
        try:
            self._adapter.execute(operation, variables, write=True)
        except AdapterUnavailableError as exc:
            raise ImpactRepositoryUnavailable("The local emulator is unavailable.") from exc
        except AdapterError as exc:
            raise ImpactPersistenceError("The impact revision transaction was rejected.") from exc

    def list_heads(self) -> list[dict[str, Any]]:
        try:
            rows = self._adapter.execute("ListImpactAssessmentHeads")[
                "impactAssessmentHeads"
            ]
            return [self._head(row) for row in rows]
        except AdapterUnavailableError as exc:
            raise ImpactRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc:
            raise ImpactRepositoryError("Impact head retrieval failed.") from exc
