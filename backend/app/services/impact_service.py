"""Carbon assessment orchestration, immutable revisions, and current reads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from backend.app.domain.carbon import (
    CarbonResult,
    PROCESSING_UNITS,
    PRODUCTION_UNITS,
    TRANSPORT_UNIT,
    calculate_components,
    decimal,
    select_factor,
)
from backend.app.repositories.impact_repository import (
    ImpactPersistenceError,
    ImpactRepository,
    ImpactRepositoryError,
    ImpactRepositoryUnavailable,
)
from backend.app.services.transfer_read_service import load_baseline_metadata


LIFECYCLE_BOUNDARY = (
    "Hypothetical production substitution; extra road freight and per-piece "
    "handling. Excludes baseline freight/disposal, credits and official inventory."
)
BASELINE_DESCRIPTION = (
    "Hypothetical displacement of functionally equivalent new procurement, "
    "synthetic baseline; no official inventory deduction."
)
OMISSIONS = ["baseline freight", "disposal", "credit issuance"]


class ImpactError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class ImpactNotFound(ImpactError):
    pass


class ImpactInvalid(ImpactError):
    pass


class ImpactConflict(ImpactError):
    pass


class ImpactUnavailable(ImpactError):
    pass


@dataclass(frozen=True)
class ImpactCalculationInput:
    idempotency_key: str
    revision_reason: str
    actor_label: str


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in rows}


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identity(key: str) -> tuple[str, str]:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"ICO-{digest}", f"IMP-CALC-{digest[:32]}"


def _numeric(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _route(
    routes: list[dict[str, Any]], source_project_id: str, destination_project_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    matches = [
        row
        for row in routes
        if {row["from_project_id"], row["to_project_id"]}
        == {source_project_id, destination_project_id}
        and row["transport_mode"] == "ROAD_FREIGHT"
        and row["assumption_type"] == "SIMULATED_ROAD_DISTANCE"
    ]
    if not matches:
        return None, "ROUTE_DISTANCE"
    if len(matches) != 1:
        return None, "AMBIGUOUS_ROUTE"
    return matches[0], None


def _factor_snapshot(factor: dict[str, Any]) -> dict[str, Any]:
    return {
        key: factor[key]
        for key in (
            "id",
            "factor_type",
            "material_id",
            "material_category",
            "transport_mode",
            "value",
            "unit",
            "source_label",
            "source_url",
            "geography",
            "lifecycle_boundary",
            "version",
            "valid_from",
            "is_demo_factor",
        )
    }


def _load(repository: ImpactRepository) -> dict[str, list[dict[str, Any]]]:
    try:
        return repository.snapshot()
    except ImpactRepositoryUnavailable as exc:
        raise ImpactUnavailable(
            "IMPACT_DATA_UNAVAILABLE", "The local SQL Connect emulator is unavailable."
        ) from exc
    except ImpactRepositoryError as exc:
        raise ImpactError("IMPACT_DATA_ERROR", "Impact inputs could not be read.") from exc


def _context(
    snapshot: dict[str, list[dict[str, Any]]], basis: str, entity_id: str
) -> dict[str, Any]:
    proposals = _index(snapshot["allocation_proposals"])
    transfers = _index(snapshot["transfers"])
    supplies = _index(snapshot["supply_offers"])
    demands = _index(snapshot["demand_requests"])
    materials = _index(snapshot["materials"])
    runs = _index(snapshot["optimisation_runs"])

    transfer = None
    if basis == "PROPOSAL_FORECAST":
        proposal = proposals.get(entity_id)
        if proposal is None:
            raise ImpactNotFound(
                "PROPOSAL_NOT_FOUND", "The requested proposal was not found.", {"proposal_id": entity_id}
            )
        if proposal["compatibility_result"] != "ELIGIBLE":
            raise ImpactInvalid(
                "PROPOSAL_NOT_ELIGIBLE", "Only an ELIGIBLE proposal can be assessed."
            )
        quantity = proposal["proposed_quantity"]
        moved_quantity = quantity
        processed_quantity = quantity
        handling_allocation = "ALL_MOVED_UNITS"
        activity_at = proposal["created_at"]
    else:
        transfer = transfers.get(entity_id)
        if transfer is None:
            raise ImpactNotFound(
                "TRANSFER_NOT_FOUND", "The requested transfer was not found.", {"transfer_id": entity_id}
            )
        proposal = proposals.get(transfer["proposal_id"])
        if proposal is None:
            raise ImpactError("IMPACT_DATA_ERROR", "The transfer proposal is missing.")
        quantity = transfer["actually_used_quantity"]
        if quantity <= 0 or transfer["reuse_confirmed_at"] is None:
            raise ImpactInvalid(
                "ACTUAL_USE_NOT_CONFIRMED",
                "Actual impact requires a positive confirmed-use quantity.",
            )
        moved_quantity = transfer["dispatched_quantity"] or None
        fully_used = moved_quantity is not None and quantity == moved_quantity
        processed_quantity = moved_quantity if fully_used else None
        handling_allocation = (
            "ALL_MOVED_UNITS" if fully_used else "UNDEFINED_PARTIAL_USE"
        )
        activity_at = transfer["reuse_confirmed_at"]

    supply = supplies.get(proposal["supply_offer_id"])
    demand = demands.get(proposal["demand_request_id"])
    if supply is None or demand is None:
        raise ImpactError("IMPACT_DATA_ERROR", "Linked supply or demand is missing.")
    if supply["material_id"] != demand["material_id"]:
        raise ImpactInvalid("MATERIAL_MISMATCH", "Supply and demand materials differ.")
    material = materials.get(supply["material_id"])
    run = runs.get(proposal["run_id"])
    if material is None or run is None:
        raise ImpactError("IMPACT_DATA_ERROR", "Material or optimisation run is missing.")
    route, route_issue = _route(
        snapshot["route_distances"],
        supply["source_project_id"],
        demand["destination_project_id"],
    )
    return {
        "basis": basis,
        "proposal": proposal,
        "transfer": transfer,
        "supply": supply,
        "demand": demand,
        "material": material,
        "run": run,
        "route": route,
        "route_issue": route_issue,
        "quantity": quantity,
        "moved_quantity": moved_quantity,
        "processed_quantity": processed_quantity,
        "handling_allocation": handling_allocation,
        "activity_at": activity_at,
    }


def calculate_context_components(
    context: dict[str, Any],
    factors: list[dict[str, Any]],
) -> tuple[CarbonResult, list[dict[str, Any]]]:
    """Shared non-persisting arithmetic for previews and stored assessments.

    Context supplies explicit activity date, quantities, material, route and
    factor version. This function does not read repositories or assign IDs.
    """
    material = context["material"]
    activity_date = datetime.fromisoformat(
        context["activity_at"].replace("Z", "+00:00")
    ).date()
    common = {
        "material_id": material["id"],
        "material_category": material["category"],
        "version": context["run"]["factor_dataset_version"],
        "activity_date": activity_date,
        "lifecycle_boundary": LIFECYCLE_BOUNDARY,
    }
    production = select_factor(
        factors,
        factor_type="NEW_MATERIAL_PRODUCTION",
        transport_mode=None,
        supported_units=PRODUCTION_UNITS,
        **common,
    )
    transport = select_factor(
        factors,
        factor_type="TRANSPORT",
        transport_mode="ROAD_FREIGHT",
        supported_units={TRANSPORT_UNIT},
        **common,
    )
    processing = select_factor(
        factors,
        factor_type="PROCESSING",
        transport_mode=None,
        supported_units=PROCESSING_UNITS,
        **common,
    )
    selected = [choice.factor for choice in (production, transport)]
    if context["processed_quantity"] is not None:
        selected.append(processing.factor)
    selected_factors = [factor for factor in selected if factor is not None]
    initial_missing = [
        issue
        for issue in (
            context["route_issue"],
            production.issue,
            transport.issue,
            processing.issue if context["processed_quantity"] is not None else None,
        )
        if issue is not None
    ]
    mass = (
        decimal(material["mass_kg_per_unit"])
        if material["mass_kg_per_unit"] is not None
        else None
    )
    distance = (
        decimal(context["route"]["distance_km"])
        if context["route"] is not None
        else None
    )
    result = calculate_components(
        quantity_assessed=decimal(context["quantity"]),
        moved_quantity=(
            decimal(context["moved_quantity"])
            if context["moved_quantity"] is not None
            else None
        ),
        processed_quantity=(
            decimal(context["processed_quantity"])
            if context["processed_quantity"] is not None
            else None
        ),
        mass_kg_per_unit=mass,
        distance_km=distance,
        production_factor=production.factor,
        transport_factor=transport.factor,
        processing_factor=(
            processing.factor if context["processed_quantity"] is not None else None
        ),
        missing_data=initial_missing,
    )
    return result, selected_factors


def _build_assessment(
    context: dict[str, Any],
    factors: list[dict[str, Any]],
    *,
    assessment_id: str,
    calculated_at: str,
    revision: int,
    previous_assessment_id: str | None,
    revision_reason: str,
    actor_label: str,
) -> tuple[dict[str, Any], str]:
    material = context["material"]
    result, selected_factors = calculate_context_components(context, factors)
    source_input = {
        "basis": context["basis"],
        "proposal_id": context["proposal"]["id"],
        "transfer_id": context["transfer"]["id"] if context["transfer"] else None,
        "quantity_assessed": context["quantity"],
        "moved_quantity": context["moved_quantity"],
        "processed_quantity": context["processed_quantity"],
        "unit": context["proposal"]["unit"],
        "material_id": material["id"],
        "mass_kg_per_unit": material["mass_kg_per_unit"],
        "mass_source": material["mass_source"],
        "route_id": context["route"]["id"] if context["route"] else None,
        "distance_km": context["route"]["distance_km"] if context["route"] else None,
        "transport_mode": "ROAD_FREIGHT",
        "factor_dataset_version": context["run"]["factor_dataset_version"],
        "activity_at": context["activity_at"],
    }
    factor_snapshots = [_factor_snapshot(factor) for factor in selected_factors]
    input_fingerprint = _hash(
        {"source_input": source_input, "factors": factor_snapshots, "boundary": LIFECYCLE_BOUNDARY}
    )
    unresolved = (
        context["moved_quantity"] - context["quantity"]
        if context["moved_quantity"] is not None
        else None
    )
    assumptions = {
        "symmetric_route_id": source_input["route_id"],
        "distance_km": source_input["distance_km"],
        "transport_mode": "ROAD_FREIGHT",
        "mass_kg_per_unit": material["mass_kg_per_unit"],
        "moved_quantity": context["moved_quantity"],
        "processed_quantity": context["processed_quantity"],
        "handling_allocation": context["handling_allocation"],
        "substitution_ratio": 1,
        "synthetic": True,
        "omissions": OMISSIONS,
        "unresolved_quantity": unresolved,
        "missing_data": list(result.missing_data),
        "source_input": source_input,
        "factor_snapshots": factor_snapshots,
        "lifecycle_boundary": LIFECYCLE_BOUNDARY,
        "route_assumption": "SIMULATED_SYMMETRIC_ROAD_DISTANCE",
        "revision": {
            "number": revision,
            "previous_assessment_id": previous_assessment_id,
            "reason": revision_reason,
            "actor_label": actor_label,
            "operator_reviewed_at": calculated_at,
            "operator_review_is_not_independent_environmental_verification": True,
            "input_fingerprint": input_fingerprint,
        },
    }
    all_demo = bool(selected_factors) and all(
        factor["is_demo_factor"] for factor in selected_factors
    )
    status = (
        "INSUFFICIENT_DATA"
        if result.net_avoided_kgco2e is None
        else "DEMO"
        if all_demo
        else "REVIEWED"
    )
    assessment = {
        "id": assessment_id,
        "basis": context["basis"],
        "proposal_id": (
            context["proposal"]["id"]
            if context["basis"] == "PROPOSAL_FORECAST"
            else None
        ),
        "transfer_id": (
            context["transfer"]["id"]
            if context["basis"] == "ACTUAL_CONFIRMED_USE"
            else None
        ),
        "quantity_assessed": context["quantity"],
        "unit": context["proposal"]["unit"],
        "baseline_description": BASELINE_DESCRIPTION,
        "avoided_production_kgco2e": _numeric(result.avoided_production_kgco2e),
        "additional_transport_kgco2e": _numeric(result.additional_transport_kgco2e),
        "additional_processing_kgco2e": _numeric(result.additional_processing_kgco2e),
        "net_avoided_kgco2e": _numeric(result.net_avoided_kgco2e),
        "factor_ids": [factor["id"] for factor in selected_factors],
        "assumptions": assumptions,
        "calculation_status": status,
        "calculated_at": calculated_at,
    }
    return assessment, input_fingerprint


def calculate_impact(
    basis: str,
    entity_id: str,
    request: ImpactCalculationInput,
    repository: ImpactRepository | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if basis not in {"PROPOSAL_FORECAST", "ACTUAL_CONFIRMED_USE"}:
        raise ValueError(basis)
    repository = repository or ImpactRepository()
    operation_id, assessment_id = _identity(request.idempotency_key)
    scope_id = f"{basis}:{entity_id}"
    try:
        state = repository.persistence_state(scope_id, operation_id)
    except ImpactRepositoryUnavailable as exc:
        raise ImpactUnavailable("IMPACT_DATA_UNAVAILABLE", "The local emulator is unavailable.") from exc
    except ImpactRepositoryError as exc:
        raise ImpactError("IMPACT_DATA_ERROR", "Impact revision state could not be read.") from exc
    request_fingerprint = _hash(
        {
            "basis": basis,
            "entity_id": entity_id,
            "revision_reason": request.revision_reason,
            "actor_label": request.actor_label,
        }
    )
    if state.operation is not None:
        if state.operation["request_fingerprint"] != request_fingerprint:
            raise ImpactConflict(
                "IDEMPOTENCY_KEY_REUSED",
                "The idempotency_key was used with different calculation input.",
            )
        if state.assessment is None:
            raise ImpactError("IMPACT_DATA_ERROR", "The stored calculation retry is incomplete.")
        return {
            "data": {"assessment": state.assessment, "current": True, "replayed": True},
            "meta": load_baseline_metadata(),
            "error": None,
        }

    now = (clock or (lambda: datetime.now(timezone(timedelta(hours=8)))))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ImpactError("IMPACT_TIME_INVALID", "The calculation clock must be timezone-aware.")
    snapshot = _load(repository)
    context = _context(snapshot, basis, entity_id)
    new_revision = state.head["revision"] + 1
    assessment, input_fingerprint = _build_assessment(
        context,
        snapshot["emission_factors"],
        assessment_id=assessment_id,
        calculated_at=now.isoformat(timespec="seconds"),
        revision=new_revision,
        previous_assessment_id=state.head["current_assessment_id"],
        revision_reason=request.revision_reason,
        actor_label=request.actor_label,
    )
    source_guard = (
        {
            "proposal_id": context["proposal"]["id"],
            "proposed_quantity": context["proposal"]["proposed_quantity"],
            "unit": context["proposal"]["unit"],
        }
        if basis == "PROPOSAL_FORECAST"
        else {
            "transfer_id": context["transfer"]["id"],
            "actually_used_quantity": context["transfer"]["actually_used_quantity"],
            "dispatched_quantity": context["transfer"]["dispatched_quantity"],
            "received_quantity": context["transfer"]["received_quantity"],
            "reuse_confirmed_at": context["transfer"]["reuse_confirmed_at"],
        }
    )
    command = {
        "scope_id": scope_id,
        "operation_id": operation_id,
        "request_fingerprint": request_fingerprint,
        "expected_revision": state.head["revision"],
        "new_revision": new_revision,
        "input_fingerprint": input_fingerprint,
        "assessment": assessment,
        "source_guard": source_guard,
    }
    try:
        repository.persist(basis, command)
    except ImpactRepositoryUnavailable as exc:
        raise ImpactUnavailable("IMPACT_DATA_UNAVAILABLE", "The local emulator is unavailable.") from exc
    except ImpactPersistenceError as exc:
        try:
            latest = repository.persistence_state(scope_id, operation_id)
        except ImpactRepositoryUnavailable as read_exc:
            raise ImpactUnavailable(
                "IMPACT_DATA_UNAVAILABLE", "The local emulator is unavailable."
            ) from read_exc
        except ImpactRepositoryError as read_exc:
            raise ImpactError(
                "IMPACT_DATA_ERROR",
                "The rejected impact transaction could not be reconciled.",
            ) from read_exc
        if latest.operation is not None:
            if latest.operation["request_fingerprint"] != request_fingerprint:
                raise ImpactConflict("IDEMPOTENCY_KEY_REUSED", "The key has different input.") from exc
            if latest.assessment is not None:
                return {
                    "data": {"assessment": latest.assessment, "current": True, "replayed": True},
                    "meta": load_baseline_metadata(),
                    "error": None,
                }
        raise ImpactConflict(
            "IMPACT_INPUT_STALE",
            "Calculation inputs or the current revision changed before persistence; recalculate from current data.",
        ) from exc
    return {
        "data": {"assessment": assessment, "current": True, "replayed": False},
        "meta": load_baseline_metadata(),
        "error": None,
    }


def list_assessments(
    *,
    basis: str | None = None,
    current_only: bool = True,
    repository: ImpactRepository | None = None,
) -> dict[str, Any]:
    repository = repository or ImpactRepository()
    snapshot = _load(repository)
    rows = snapshot["impact_assessments"]
    if basis is not None:
        rows = [row for row in rows if row["basis"] == basis]
    if current_only:
        try:
            current_ids = {
                head["current_assessment_id"]
                for head in repository.list_heads()
                if head["current_assessment_id"] is not None
                and (basis is None or head["basis"] == basis)
            }
        except ImpactRepositoryUnavailable as exc:
            raise ImpactUnavailable("IMPACT_DATA_UNAVAILABLE", "The local emulator is unavailable.") from exc
        except ImpactRepositoryError as exc:
            raise ImpactError("IMPACT_DATA_ERROR", "Current impact selection failed.") from exc
        rows = [row for row in rows if row["id"] in current_ids]
    rows = sorted(rows, key=lambda row: (row["calculated_at"], row["id"]))
    return {"data": rows, "meta": load_baseline_metadata(), "error": None}


def get_assessment(
    assessment_id: str, repository: ImpactRepository | None = None
) -> dict[str, Any]:
    response = list_assessments(current_only=False, repository=repository)
    row = next((item for item in response["data"] if item["id"] == assessment_id), None)
    if row is None:
        raise ImpactNotFound(
            "IMPACT_ASSESSMENT_NOT_FOUND",
            "The requested impact assessment was not found.",
            {"assessment_id": assessment_id},
        )
    response["data"] = row
    return response
