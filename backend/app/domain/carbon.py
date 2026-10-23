"""Exact, framework-independent carbon component calculations.

All arithmetic remains ``Decimal`` until a repository serialises values for the
SQL Connect ``Float`` fields.  The engine deliberately returns missing
components instead of treating absent activity or factors as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable


CALCULATION_POLICY_VERSION = "catalogue-unit-factors-v2"

def activity_factor_units(quantity_unit: str) -> set[str]:
    """Only a direct catalogue-unit factor or explicit mass basis is usable.

    No catalogue-unit-to-piece conversion is inferred. Confirmed conversions
    belong upstream of these calculations.
    """
    return {f"kgCO2e/{quantity_unit}", "kgCO2e/kg"}


PRODUCTION_UNITS = {"kgCO2e/pcs", "kgCO2e/kg"}
TRANSPORT_UNIT = "kgCO2e/t-km"
PROCESSING_UNITS = {"kgCO2e/pcs", "kgCO2e/kg"}


def decimal(value: Any) -> Decimal:
    """Convert persisted numeric input without introducing binary-float error."""

    return Decimal(str(value))


@dataclass(frozen=True)
class FactorChoice:
    factor: dict[str, Any] | None
    issue: str | None = None


@dataclass(frozen=True)
class CarbonResult:
    avoided_production_kgco2e: Decimal | None
    additional_transport_kgco2e: Decimal | None
    additional_processing_kgco2e: Decimal | None
    net_avoided_kgco2e: Decimal | None
    missing_data: tuple[str, ...]


def select_factor(
    factors: Iterable[dict[str, Any]],
    *,
    factor_type: str,
    material_id: str,
    material_category: str,
    transport_mode: str | None,
    version: str,
    activity_date: date,
    lifecycle_boundary: str,
    supported_units: set[str],
) -> FactorChoice:
    """Select one applicable factor using Terra's documented fallback order.

    Exact material factors outrank category factors, which outrank general
    factors.  A factor must also match type, version, validity date, supported
    unit, lifecycle boundary, and transport mode where relevant.  The newest
    applicable ``valid_from`` wins; two factors tied at the same specificity
    and date are ambiguous and therefore unusable.
    """

    candidates: list[tuple[int, date, dict[str, Any]]] = []
    for factor in factors:
        if factor["factor_type"] != factor_type:
            continue
        if factor["version"] != version or factor["unit"] not in supported_units:
            continue
        if factor["lifecycle_boundary"] != lifecycle_boundary:
            continue
        valid_from = date.fromisoformat(factor["valid_from"])
        if valid_from > activity_date:
            continue
        if factor_type == "TRANSPORT":
            if factor["transport_mode"] != transport_mode:
                continue
        elif factor["transport_mode"] is not None:
            continue

        if factor["material_id"] == material_id:
            specificity = 0
        elif (
            factor["material_id"] is None
            and factor["material_category"] == material_category
        ):
            specificity = 1
        elif factor["material_id"] is None and factor["material_category"] is None:
            specificity = 2
        else:
            continue
        candidates.append((specificity, valid_from, factor))

    if not candidates:
        return FactorChoice(None, f"MISSING_{factor_type}_FACTOR")
    best_specificity = min(item[0] for item in candidates)
    specific = [item for item in candidates if item[0] == best_specificity]
    newest_date = max(item[1] for item in specific)
    newest = [item[2] for item in specific if item[1] == newest_date]
    if len(newest) != 1:
        return FactorChoice(None, f"AMBIGUOUS_{factor_type}_FACTOR")
    return FactorChoice(newest[0])


def assessment_factor_units_valid(assessment: dict[str, Any], factors: Iterable[dict[str, Any]]) -> bool:
    """Reject a saved estimate with factor dimensions incompatible with its unit.

    Prefer its immutable factor snapshots. Seed-era estimates fall back to
    their referenced factors; none of these reads rewrite historical evidence.
    """
    snapshots=assessment.get('assumptions',{}).get('factor_snapshots')
    if snapshots is None:
        by_id={factor['id']:factor for factor in factors}
        snapshots=[by_id[fid] for fid in assessment.get('factor_ids',[]) if fid in by_id]
    units=activity_factor_units(assessment['unit'])
    for factor in snapshots:
        kind=factor['factor_type']
        if kind in ('NEW_MATERIAL_PRODUCTION','PROCESSING') and factor['unit'] not in units:return False
        if kind=='TRANSPORT' and factor['unit']!=TRANSPORT_UNIT:return False
    return True


def calculate_components(
    *,
    quantity_assessed: Decimal,
    moved_quantity: Decimal | None,
    processed_quantity: Decimal | None,
    mass_kg_per_unit: Decimal | None,
    distance_km: Decimal | None,
    production_factor: dict[str, Any] | None,
    transport_factor: dict[str, Any] | None,
    processing_factor: dict[str, Any] | None,
    missing_data: Iterable[str] = (),
    quantity_unit: str = 'pcs',
) -> CarbonResult:
    """Calculate production, freight, processing, and simplified net impact."""

    missing = list(missing_data)
    production = transport = processing = None

    if production_factor is None:
        missing.append("PRODUCTION_FACTOR")
    elif production_factor["unit"] == f"kgCO2e/{quantity_unit}":
        production = quantity_assessed * decimal(production_factor["value"])
    elif production_factor["unit"] != "kgCO2e/kg":
        missing.append("PRODUCTION_FACTOR_UNIT")
    elif mass_kg_per_unit is None:
        missing.append("MASS_KG_PER_UNIT_FOR_PRODUCTION")
    else:
        production = (
            quantity_assessed
            * mass_kg_per_unit
            * decimal(production_factor["value"])
        )

    if moved_quantity is None:
        missing.append("MOVED_QUANTITY")
    if mass_kg_per_unit is None:
        missing.append("MASS_KG_PER_UNIT_FOR_TRANSPORT")
    if distance_km is None:
        missing.append("ROUTE_DISTANCE")
    if transport_factor is None:
        missing.append("TRANSPORT_FACTOR")
    if transport_factor is not None and transport_factor["unit"] != TRANSPORT_UNIT:
        missing.append("TRANSPORT_FACTOR_UNIT")
        transport_factor = None
    if all(
        value is not None
        for value in (moved_quantity, mass_kg_per_unit, distance_km, transport_factor)
    ):
        transport = (
            moved_quantity
            * mass_kg_per_unit
            / Decimal("1000")
            * distance_km
            * decimal(transport_factor["value"])
        )

    if processed_quantity is None:
        missing.append("PROCESSING_BOUNDARY")
    elif processing_factor is None:
        missing.append("PROCESSING_FACTOR")
    elif processing_factor["unit"] == f"kgCO2e/{quantity_unit}":
        processing = processed_quantity * decimal(processing_factor["value"])
    elif processing_factor["unit"] != "kgCO2e/kg":
        missing.append("PROCESSING_FACTOR_UNIT")
    elif mass_kg_per_unit is None:
        missing.append("MASS_KG_PER_UNIT_FOR_PROCESSING")
    else:
        processing = (
            processed_quantity
            * mass_kg_per_unit
            * decimal(processing_factor["value"])
        )

    net = None
    if production is not None and transport is not None and processing is not None:
        net = production - transport - processing
    return CarbonResult(
        production,
        transport,
        processing,
        net,
        tuple(dict.fromkeys(missing)),
    )
