"""Read and mutate transfers through Terra's local SQL Connect adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from terra.contract import camel
from terra.local_adapter import (
    AdapterError,
    AdapterUnavailableError,
    LocalDataConnect,
    map_entity_rows,
)


class TransferRepositoryError(RuntimeError):
    """The transfer query or provider response was invalid."""


class TransferRepositoryUnavailable(TransferRepositoryError):
    """The local SQL Connect emulator could not be reached."""


class TransferApprovalMutationError(TransferRepositoryError):
    """The provider rejected or could not complete an approval transaction."""


class TransferWorkflowMutationError(TransferRepositoryError):
    """The provider rejected or could not complete a workflow transaction."""


@dataclass(frozen=True)
class TransferApprovalState:
    """Current records needed to validate or replay an approval."""

    transfer: dict[str, Any] | None
    proposal: dict[str, Any] | None
    operation: dict[str, Any] | None
    event: dict[str, Any] | None


@dataclass(frozen=True)
class TransferWorkflowState:
    """Current records required to validate or replay a workflow operation."""

    transfer: dict[str, Any] | None
    proposal: dict[str, Any] | None
    supply_offer: dict[str, Any] | None
    demand_request: dict[str, Any] | None
    operation: dict[str, Any] | None
    event: dict[str, Any] | None


class TransferRepository:
    """Read transfers with the existing bounded ``ListTransfers`` operation.

    SQL Connect currently has no named single-transfer operation. ``get`` therefore
    performs an exact-ID lookup in the operation's ordered, 1,000-row result.
    Terra's synthetic baseline contains eight transfers.
    """

    OPERATION = "ListTransfers"
    APPROVAL_STATE_OPERATION = "GetTransferApprovalState"
    APPROVE_OPERATION = "ApproveTransfer"
    WORKFLOW_STATE_OPERATION = "GetTransferWorkflowState"
    ENTITY = "transfers"

    def __init__(self, adapter: LocalDataConnect | None = None) -> None:
        try:
            self._adapter = adapter if adapter is not None else LocalDataConnect()
        except ValueError as exc:
            raise TransferRepositoryError(
                "The local SQL Connect adapter configuration is invalid."
            ) from exc

    def list(self) -> list[dict[str, Any]]:
        try:
            result = self._adapter.execute(self.OPERATION)
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable(
                "The local SQL Connect emulator is unavailable."
            ) from exc
        except AdapterError as exc:
            raise TransferRepositoryError(
                "The SQL Connect transfer query failed."
            ) from exc

        result_field = camel(self.ENTITY)
        try:
            provider_rows = result[result_field]
            return map_entity_rows(self.ENTITY, provider_rows)
        except (KeyError, TypeError, AdapterError) as exc:
            raise TransferRepositoryError(
                "The SQL Connect transfer response is invalid."
            ) from exc

    def get(self, transfer_id: str) -> dict[str, Any] | None:
        return next(
            (transfer for transfer in self.list() if transfer["id"] == transfer_id),
            None,
        )

    @staticmethod
    def _timestamp(value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone(timedelta(hours=8))
        ).isoformat()

    def get_approval_state(
        self, transfer_id: str, operation_id: str, event_id: str
    ) -> TransferApprovalState:
        """Load the transfer/proposal and any prior replay-safe operation."""

        try:
            result = self._adapter.execute(
                self.APPROVAL_STATE_OPERATION,
                {
                    "transferId": transfer_id,
                    "operationId": operation_id,
                    "eventId": event_id,
                },
            )
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable(
                "The local SQL Connect emulator is unavailable."
            ) from exc
        except AdapterError as exc:
            raise TransferRepositoryError(
                "The SQL Connect approval-state query failed."
            ) from exc

        try:
            provider_transfer = result["transfer"]
            provider_operation = result["transferApprovalOperation"]
            provider_event = result["transferEvent"]

            transfer = None
            proposal = None
            if provider_transfer is not None:
                proposal_row = provider_transfer["proposal"]
                transfer_row = dict(provider_transfer)
                del transfer_row["proposal"]
                transfer = map_entity_rows("transfers", [transfer_row])[0]
                proposal = {
                    "id": proposal_row["id"],
                    "proposed_quantity": proposal_row["proposedQuantity"],
                    "unit": proposal_row["unit"],
                    "compatibility_result": proposal_row["compatibilityResult"],
                    "status": proposal_row["status"],
                    "supply_offer_id": proposal_row["supplyOfferId"],
                    "demand_request_id": proposal_row["demandRequestId"],
                }

            operation = None
            if provider_operation is not None:
                operation = {
                    "id": provider_operation["id"],
                    "request_fingerprint": provider_operation["requestFingerprint"],
                    "transfer_id": provider_operation["transferId"],
                    "event_id": provider_operation["eventId"],
                    "approved_quantity": provider_operation["approvedQuantity"],
                    "source_confirmation_status": provider_operation[
                        "sourceConfirmationStatus"
                    ],
                    "destination_confirmation_status": provider_operation[
                        "destinationConfirmationStatus"
                    ],
                    "actor_label": provider_operation["actorLabel"],
                    "evidence_ref": provider_operation["evidenceRef"],
                    "occurred_at": self._timestamp(provider_operation["occurredAt"]),
                }

            event = (
                map_entity_rows("transfer_events", [provider_event])[0]
                if provider_event is not None
                else None
            )
            return TransferApprovalState(transfer, proposal, operation, event)
        except (KeyError, TypeError, ValueError, AdapterError) as exc:
            raise TransferRepositoryError(
                "The SQL Connect approval-state response is invalid."
            ) from exc

    def approve(self, command: dict[str, Any]) -> None:
        """Execute the guarded transfer update, operation insert, and event insert."""

        variables = {
            "transferId": command["transfer_id"],
            "operationId": command["operation_id"],
            "requestFingerprint": command["request_fingerprint"],
            "eventId": command["event_id"],
            "approvedQuantity": command["approved_quantity"],
            "sourceConfirmationStatus": command["source_confirmation_status"],
            "destinationConfirmationStatus": command[
                "destination_confirmation_status"
            ],
            "actorLabel": command["actor_label"],
            "evidenceRef": command["evidence_ref"],
            "eventPayload": command["event_payload"],
            "occurredAt": command["occurred_at"],
        }
        try:
            self._adapter.execute(self.APPROVE_OPERATION, variables, write=True)
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable(
                "The local SQL Connect emulator is unavailable."
            ) from exc
        except AdapterError as exc:
            raise TransferApprovalMutationError(
                "The SQL Connect approval transaction was rejected."
            ) from exc

    @staticmethod
    def _map_supply(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source_project_id": row["sourceProjectId"],
            "material_id": row["materialId"],
            "declared_quantity": row["declaredQuantity"],
            "confirmed_quantity": row["confirmedQuantity"],
            "reserved_active_quantity": row["reservedActiveQuantity"],
            "transferred_out_quantity": row["transferredOutQuantity"],
            "unit": row["unit"],
            "surplus_status": row["surplusStatus"],
            "condition": row["condition"],
            "available_from": row["availableFrom"],
            "available_until": row["availableUntil"],
        }

    @staticmethod
    def _map_demand(
        row: dict[str, Any], committed_quantity: int | None = None
    ) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "destination_project_id": row["destinationProjectId"],
            "material_id": row["materialId"],
            "required_quantity": row["requiredQuantity"],
            "fulfilled_quantity": row["fulfilledQuantity"],
            "unit": row["unit"],
            "needed_from": row["neededFrom"],
            "required_by": row["requiredBy"],
            "request_status": row["requestStatus"],
            "is_outstanding_need_confirmed": row["isOutstandingNeedConfirmed"],
        }
        if committed_quantity is not None:
            result["committed_incoming_quantity"] = committed_quantity
            result["uncommitted_quantity"] = (
                result["required_quantity"]
                - result["fulfilled_quantity"]
                - committed_quantity
            )
        return result

    def get_workflow_state(
        self, transfer_id: str, operation_id: str, event_id: str
    ) -> TransferWorkflowState:
        """Load linked supply/demand context and any durable prior operation."""

        try:
            result = self._adapter.execute(
                self.WORKFLOW_STATE_OPERATION,
                {
                    "transferId": transfer_id,
                    "operationId": operation_id,
                    "eventId": event_id,
                },
            )
            provider_transfer = result["transfer"]
            transfer = proposal = supply = demand = None
            if provider_transfer is not None:
                proposal_row = provider_transfer["proposal"]
                transfer_row = dict(provider_transfer)
                del transfer_row["proposal"]
                transfer = map_entity_rows("transfers", [transfer_row])[0]
                supply = self._map_supply(proposal_row["supplyOffer"])
                demand = self._map_demand(proposal_row["demandRequest"])
                proposal = {
                    "id": proposal_row["id"],
                    "proposed_quantity": proposal_row["proposedQuantity"],
                    "unit": proposal_row["unit"],
                    "compatibility_result": proposal_row["compatibilityResult"],
                    "status": proposal_row["status"],
                    "supply_offer_id": proposal_row["supplyOfferId"],
                    "demand_request_id": proposal_row["demandRequestId"],
                }
            provider_operation = result["transferWorkflowOperation"]
            operation = None
            if provider_operation is not None:
                operation = {
                    "id": provider_operation["id"],
                    "operation_type": provider_operation["operationType"],
                    "request_fingerprint": provider_operation["requestFingerprint"],
                    "transfer_id": provider_operation["transferId"],
                    "event_id": provider_operation["eventId"],
                    "quantity": provider_operation["quantity"],
                    "reason": provider_operation["reason"],
                    "actor_label": provider_operation["actorLabel"],
                    "evidence_ref": provider_operation["evidenceRef"],
                    "occurred_at": self._timestamp(provider_operation["occurredAt"]),
                }
            event = (
                map_entity_rows("transfer_events", [result["transferEvent"]])[0]
                if result["transferEvent"] is not None
                else None
            )
            return TransferWorkflowState(
                transfer, proposal, supply, demand, operation, event
            )
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable(
                "The local SQL Connect emulator is unavailable."
            ) from exc
        except AdapterError as exc:
            raise TransferRepositoryError(
                "The SQL Connect workflow-state query failed."
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise TransferRepositoryError(
                "The SQL Connect workflow-state response is invalid."
            ) from exc

    def run_workflow(self, operation: str, command: dict[str, Any]) -> None:
        """Execute one named, atomic workflow mutation."""

        variables = {
            "transferId": command["transfer_id"],
            "operationId": command["operation_id"],
            "requestFingerprint": command["request_fingerprint"],
            "eventId": command["event_id"],
            "quantity": command["quantity"],
            "actorLabel": command["actor_label"],
            "evidenceRef": command["evidence_ref"],
            "eventPayload": command["event_payload"],
            "occurredAt": command["occurred_at"],
            "operationDate": command["operation_date"],
            "supplyOfferId": command["supply_offer_id"],
            "demandRequestId": command["demand_request_id"],
        }
        for optional in ("reason", "notes"):
            if optional in command:
                variables[optional] = command[optional]
        if "demand_status" in command:
            variables["demandStatus"] = command["demand_status"]
        if "previous_used_quantity" in command:
            variables["previousUsedQuantity"] = command["previous_used_quantity"]
            variables["newUsedQuantity"] = command["new_used_quantity"]
        try:
            self._adapter.execute(operation, variables, write=True)
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable(
                "The local SQL Connect emulator is unavailable."
            ) from exc
        except AdapterError as exc:
            raise TransferWorkflowMutationError(
                f"The SQL Connect {operation} transaction was rejected."
            ) from exc

    def list_events(self, transfer_id: str) -> list[dict[str, Any]]:
        try:
            result = self._adapter.execute(
                "GetTransferEvents", {"transferId": transfer_id}
            )
            return map_entity_rows("transfer_events", result["transferEvents"])
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc:
            raise TransferRepositoryError("Transfer events could not be read.") from exc

    def get_supply_offer(self, offer_id: str) -> dict[str, Any] | None:
        try:
            row = self._adapter.execute("GetSupplyOffer", {"id": offer_id})["supplyOffer"]
            return self._map_supply(row) if row is not None else None
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc:
            raise TransferRepositoryError("Supply offer could not be read.") from exc

    def get_demand_request(self, demand_id: str) -> dict[str, Any] | None:
        try:
            result = self._adapter.execute("GetDemandRequest", {"id": demand_id})
            row = result["demandRequest"]
            balance = result["demandCommitmentBalance"]
            if row is None:
                return None
            if balance is None:
                raise TypeError
            return self._map_demand(row, balance["committedQuantity"])
        except AdapterUnavailableError as exc:
            raise TransferRepositoryUnavailable("The local emulator is unavailable.") from exc
        except (AdapterError, KeyError, TypeError) as exc:
            raise TransferRepositoryError("Demand request could not be read.") from exc
