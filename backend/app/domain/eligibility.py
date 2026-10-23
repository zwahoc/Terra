"""Operational eligibility for reviewed catalogue identities; no I/O or writes.

Inputs must be published, reviewed domain snapshots from one consistent read.
An ELIGIBLE result is a planning decision, never a reservation or certification.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
import re
from typing import Mapping
from decimal import Decimal
from terra.quantities import amount, unit

ELIGIBILITY_POLICY_VERSION = 'reviewed-catalogue-identity-v2'


def _pieces(value: int, name: str) -> None:
    try: amount(value)
    except ValueError as exc: raise ValueError(f'{name}: {exc}') from exc


@dataclass(frozen=True)
class SupplyQuantity:
    confirmed_quantity: int | None
    reserved_active_quantity: int
    transferred_out_quantity: int

    def __post_init__(self) -> None:
        _pieces(self.reserved_active_quantity, "reserved_active_quantity")
        _pieces(self.transferred_out_quantity, "transferred_out_quantity")
        committed = self.reserved_active_quantity + self.transferred_out_quantity
        if self.confirmed_quantity is None:
            if committed:
                raise ValueError("Unconfirmed stock cannot have reservations or dispatches")
        else:
            _pieces(self.confirmed_quantity, "confirmed_quantity")
            if committed > self.confirmed_quantity:
                raise ValueError("Source commitments exceed confirmed stock")

    @property
    def uncommitted_quantity(self) -> int:
        if self.confirmed_quantity is None:
            return 0
        return (self.confirmed_quantity - self.reserved_active_quantity
                - self.transferred_out_quantity)


@dataclass(frozen=True)
class DemandQuantity:
    required_quantity: int
    fulfilled_quantity: int
    incoming_committed_quantity: int

    def __post_init__(self) -> None:
        for name in ("required_quantity", "fulfilled_quantity", "incoming_committed_quantity"):
            _pieces(getattr(self, name), name)
        if self.required_quantity == 0:
            raise ValueError("required_quantity must be positive")
        if self.fulfilled_quantity + self.incoming_committed_quantity > self.required_quantity:
            raise ValueError("Fulfilment and incoming commitments exceed required quantity")

    @property
    def remaining_unfulfilled_quantity(self) -> int:
        return self.required_quantity - self.fulfilled_quantity

    @property
    def newly_allocatable_quantity(self) -> int:
        return self.remaining_unfulfilled_quantity - self.incoming_committed_quantity


@dataclass(frozen=True)
class Material:
    id: str
    category: str
    standard_unit: str
    specifications: Mapping[str, object]


@dataclass(frozen=True)
class Supply:
    id: str
    source_project_id: str
    material_id: str
    unit: str
    surplus_status: str
    condition: str
    available_from: date
    available_until: date | None
    quantity: SupplyQuantity
    batch_or_lot_code: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for q in (self.quantity.confirmed_quantity,self.quantity.reserved_active_quantity,self.quantity.transferred_out_quantity):
            if q is not None: amount(q,unit_name=self.unit)
        if self.surplus_status not in {"POTENTIAL", "CONFIRMED", "SUSPENDED", "CLOSED"}:
            raise ValueError("Unknown surplus_status")
        if self.condition not in {"UNUSED", "RECOVERED", "UNKNOWN"}:
            raise ValueError("Unknown condition")
        if self.available_until is not None and self.available_until < self.available_from:
            raise ValueError("Supply availability window is reversed")
        if self.surplus_status == "POTENTIAL" and self.quantity.confirmed_quantity is not None:
            raise ValueError("Potential supply must have null confirmed_quantity")

    def reservable_quantity_on(self, on_date: date) -> int:
        """Snapshot estimate only: a write still needs atomic revalidation."""
        if self.surplus_status != "CONFIRMED" or self.condition != "UNUSED":
            return 0
        if on_date < self.available_from:
            return 0
        if self.available_until is not None and on_date > self.available_until:
            return 0
        return self.quantity.uncommitted_quantity


@dataclass(frozen=True)
class Demand:
    id: str
    destination_project_id: str
    material_id: str
    unit: str
    request_status: str
    is_outstanding_need_confirmed: bool
    needed_from: date
    required_by: date
    quantity: DemandQuantity

    def __post_init__(self) -> None:
        for q in (self.quantity.required_quantity,self.quantity.fulfilled_quantity,self.quantity.incoming_committed_quantity):
            amount(q,unit_name=self.unit)
        if self.request_status not in {"OPEN", "FULFILLED", "CANCELLED"}:
            raise ValueError("Unknown request_status")
        if type(self.is_outstanding_need_confirmed) is not bool:
            raise ValueError("is_outstanding_need_confirmed must be boolean")
        if self.required_by < self.needed_from:
            raise ValueError("Demand date window is reversed")
        if self.request_status == "FULFILLED" and self.quantity.remaining_unfulfilled_quantity:
            raise ValueError("FULFILLED demand must be fully satisfied")
        if self.request_status == "CANCELLED" and self.quantity.incoming_committed_quantity:
            raise ValueError("Cancelled demand has unresolved incoming commitments")


@dataclass(frozen=True)
class EligibilityResult:
    supply_offer_id: str
    demand_request_id: str
    compatibility_result: str
    reason_codes: tuple[str, ...]
    max_allocatable_quantity: int
    source_uncommitted_quantity: int
    demand_newly_allocatable_quantity: int
    source_reservable_quantity_on_planning_date: int
    earliest_dispatch_date: date | None
    earliest_delivery_date: date | None
    planning_date: date
    lead_time_days: int | None
    extra_required_spec_fields: tuple[str, ...]


def _valid_spec(key: str, value: object) -> bool:
    """Validate an explicitly requested context field, never infer family rules."""
    if key.endswith("_mm"):
        # MaterialProposal deliberately carries specification values as text.
        # A plain number in an explicitly millimetre field has a known basis;
        # qualifiers, unit-bearing prose and nonfinite values remain unresolved.
        if isinstance(value,str):
            value=value.strip()
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value):return False
            return Decimal(value)>0
        return (type(value) in (int, float, Decimal) and isfinite(value) and value > 0)
    return isinstance(value, str) and bool(value.strip())


def evaluate_eligibility(
    supply: Supply,
    demand: Demand,
    supply_material: Material,
    demand_material: Material,
    *,
    planning_date: date,
    lead_time_days: int | None,
    extra_required_spec_fields: tuple[str, ...] = (),
) -> EligibilityResult:
    """Evaluate one pair, using explicit dates and a caller-supplied lead time.

    Catalogue identity/specifications are reviewed before publication. Matching
    does not infer technical completeness from a predefined family vocabulary.
    Missing explicitly requested context fields/timing/traceability need review. Known
    blockers take precedence over review flags. Noneligible results have a zero
    allocation cap. Pair caps are NOT additive across a multi-pair plan.
    """
    if lead_time_days is not None:
        if type(lead_time_days) is not int: raise ValueError('Lead time must be a whole number of days.')
        _pieces(lead_time_days, "lead_time_days")
    if supply_material.id != supply.material_id or demand_material.id != demand.material_id:
        raise ValueError("Material records do not resolve the supplied material IDs")

    blockers: list[str] = []
    review: list[str] = []
    if supply.source_project_id == demand.destination_project_id:
        blockers.append("SAME_PROJECT")
    if supply.surplus_status != "CONFIRMED" or supply.quantity.confirmed_quantity is None:
        blockers.append("SUPPLY_NOT_CONFIRMED")
    if supply.condition != "UNUSED":
        review.append("CONDITION_REVIEW_REQUIRED")
    if not supply.batch_or_lot_code and not any(ref.strip() for ref in supply.evidence_refs):
        review.append("TRACEABILITY_REVIEW_REQUIRED")
    if demand.request_status != "OPEN":
        blockers.append("DEMAND_NOT_OPEN")
    if not demand.is_outstanding_need_confirmed:
        review.append("DEMAND_NOT_CONFIRMED")
    if supply.quantity.uncommitted_quantity == 0:
        blockers.append("INSUFFICIENT_STOCK")
    if demand.quantity.newly_allocatable_quantity == 0:
        blockers.append("DEMAND_ALREADY_COMMITTED")
    if not (unit(supply.unit) == unit(demand.unit) == unit(supply_material.standard_unit)
            == unit(demand_material.standard_unit)):
        blockers.append("UNIT_CONVERSION_UNSUPPORTED")
    if (supply_material.id != demand_material.id
            or supply_material.category != demand_material.category
            or dict(supply_material.specifications) != dict(demand_material.specifications)):
        blockers.append("MATERIAL_SPEC_MISMATCH")
    for material in (supply_material, demand_material):
        # Keep explicit caller requirements, e.g. a reviewed application's slip
        # rating. No current automatic caller adds category-derived requirements.
        if any(not _valid_spec(key,material.specifications.get(key)) for key in extra_required_spec_fields):
            review.append("MATERIAL_SPEC_REVIEW_REQUIRED")

    dispatch = delivery = None
    if planning_date > demand.required_by or supply.available_from > demand.required_by:
        blockers.append("INVALID_DATE_WINDOW")
    if supply.available_until is not None and supply.available_until < max(planning_date, supply.available_from):
        blockers.append("INVALID_DATE_WINDOW")
    if lead_time_days is None:
        review.append("LEAD_TIME_REVIEW_REQUIRED")
    else:
        lead = timedelta(days=lead_time_days)
        # Reservation cannot precede the recipient window (Member 4 policy).
        # Reserve at the earliest feasible source/demand date, then dispatch.
        # available_until remains the last permitted dispatch date.
        dispatch = max(planning_date, supply.available_from, demand.needed_from)
        delivery = dispatch + lead
        if (delivery > demand.required_by
                or supply.available_until is not None and dispatch > supply.available_until):
            blockers.append("INVALID_DATE_WINDOW")
    if "INVALID_DATE_WINDOW" in blockers:
        dispatch = delivery = None

    status = "INELIGIBLE" if blockers else "REVIEW_REQUIRED" if review else "ELIGIBLE"
    reasons = tuple(dict.fromkeys(blockers + review))
    cap = 0
    if status == "ELIGIBLE":
        cap = min(supply.quantity.uncommitted_quantity, demand.quantity.newly_allocatable_quantity)
        reasons = ("SAME_CANONICAL_MATERIAL", "SPECIFICATIONS_MATCH", "DATE_WINDOW_OK")
        if supply.available_from > planning_date:
            reasons += ("FUTURE_CONFIRMED_RELEASE",)
    return EligibilityResult(
        supply.id, demand.id, status, reasons, cap,
        supply.quantity.uncommitted_quantity, demand.quantity.newly_allocatable_quantity,
        supply.reservable_quantity_on(planning_date), dispatch, delivery,
        planning_date, lead_time_days, extra_required_spec_fields,
    )
