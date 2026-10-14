"""Map complete current record collections into immutable optimiser inputs.

No I/O. The caller owns retrieval of one consistent snapshot, including all
transfers contributing to the supplied stock/demand counters. Field/enum shapes
come from the shared Terra registry, not independent DTO definitions.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from types import MappingProxyType
from typing import Iterable, Mapping

from terra.contract import MODELS, fields
from .eligibility import Demand, DemandQuantity, Material, Supply, SupplyQuantity
from .lead_time import demo_township_lead_time_days


class SnapshotMappingError(ValueError):
    """Malformed, contradictory or unsupported snapshot; no inputs returned."""


@dataclass(frozen=True)
class RouteDistance:
    id: str
    distance_km: Decimal
    is_synthetic: bool


@dataclass(frozen=True)
class DomainSnapshot:
    as_of_date: date
    project_townships: Mapping[str, str]
    materials: Mapping[str, Material]
    supplies: Mapping[str, Supply]
    demands: Mapping[str, Demand]
    incoming_transfer_ids_by_demand: Mapping[str, tuple[str, ...]]
    route_distances: Mapping[tuple[str, str], RouteDistance]

    def demo_lead_time_days(self, supply_offer_id: str, demand_request_id: str) -> int | None:
        supply = self.supplies[supply_offer_id]
        demand = self.demands[demand_request_id]
        return demo_township_lead_time_days(
            self.project_townships[supply.source_project_id],
            self.project_townships[demand.destination_project_id],
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotMappingError(message)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _parse_date(value: str, context: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotMappingError(f"{context}: invalid ISO date") from exc
    _require(parsed.isoformat() == value, f"{context}: expected YYYY-MM-DD")
    return parsed


def _index(entity: str, records: Iterable[Mapping], as_of: date) -> dict[str, dict]:
    result = {}
    for original in records:
        try:
            row = MODELS[entity].model_validate(dict(original)).model_dump()
        except (ValueError, TypeError) as exc:
            raise SnapshotMappingError(f"{entity}: invalid shared record shape: {exc}") from exc
        rid = row['id']
        _require(bool(rid.strip()), f"{entity}: blank ID")
        _require(rid not in result, f"{entity}: duplicate ID {rid}")
        for name, scalar, _ in fields(entity):
            value = row[name]
            if value is None:
                continue
            context = f"{rid}.{name}"
            if scalar == 'date':
                _parse_date(value, context)
            elif scalar == 'timestamp':
                try:
                    stamp = datetime.fromisoformat(value)
                except ValueError as exc:
                    raise SnapshotMappingError(f"{context}: invalid timestamp") from exc
                _require(value.endswith('+08:00'), f"{context}: expected +08:00 timestamp")
                _require(stamp.date() <= as_of, f"{context}: occurs after snapshot date")
            elif scalar in ('int', 'float'):
                _require(isfinite(value) and value >= 0, f"{context}: invalid nonnegative number")
        result[rid] = row
    return result


def _check_origin(row: dict, entity: str, idx: dict) -> None:
    origin_id = row['origin_document_row_id']
    if origin_id is None:  # Explicit manual record, permitted by the shared schema.
        return
    origin = idx['extracted_rows'][origin_id]
    document = idx['documents'][origin['document_id']]
    project_key = 'source_project_id' if entity == 'supply_offers' else 'destination_project_id'
    _require(origin['review_status'] in {'ACCEPTED', 'CORRECTED'},
             f"{row['id']}: origin row is not reviewed")
    _require(origin['suggested_material_id'] == row['material_id'],
             f"{row['id']}: origin material does not match")
    _require(document['project_id'] == row[project_key],
             f"{row['id']}: origin project does not match")
    kind = origin['parsed_fields'].get('record_kind')
    allowed = ({'ON_HAND_INVENTORY', 'POTENTIAL_SURPLUS', 'CONFIRMED_SURPLUS'}
               if entity == 'supply_offers' else {'OUTSTANDING_DEMAND'})
    _require(kind in allowed and document['document_type'] not in {'BOQ', 'PURCHASE_ORDER'},
             f"{row['id']}: origin is not a published supply/demand source")
    # Confirmation remains a separate business action. An accepted inventory
    # row does not become CONFIRMED here: the existing offer status is preserved.


def _check_transfer(t: dict, p: dict, s: dict, d: dict) -> None:
    rid, status = t['id'], t['status']
    approved, held, issued, received, used = (
        t['approved_quantity'], t['reserved_quantity'], t['dispatched_quantity'],
        t['received_quantity'], t['actually_used_quantity'],
    )
    _require(p['status'] == 'SELECTED' and p['compatibility_result'] == 'ELIGIBLE',
             f"{rid}: transfer must reference a selected eligible proposal")
    _require(s['source_project_id'] != d['destination_project_id'], f"{rid}: self-project transfer")
    _require(s['material_id'] == d['material_id'] and s['unit'] == d['unit'] == p['unit'],
             f"{rid}: transfer material/unit mismatch")
    _require(0 <= used <= received <= issued <= approved <= p['proposed_quantity'],
             f"{rid}: transfer quantity hierarchy invalid")
    _require(held + issued <= approved, f"{rid}: held plus issued exceeds approved")
    if status == 'CANCELLED':
        _require(issued == 0, f"{rid}: post-dispatch cancellation requires an explicit return/residual contract")
        _require(held == 0, f"{rid}: cancelled transfer retains a source hold")
    elif status == 'REQUESTED':
        _require(approved == held == issued == received == used == 0,
                 f"{rid}: requested transfer already has approval or stock effects")
    else:
        _require(approved > 0 and t['source_confirmation_status'] == 'CONFIRMED'
                 and t['destination_confirmation_status'] == 'CONFIRMED',
                 f"{rid}: missing approval/confirmations")
        if status == 'APPROVED':
            _require(held == issued == received == used == 0,
                     f"{rid}: approval alone cannot hold or move stock")
        elif status == 'RESERVED':
            _require(held > 0 and issued == received == used == 0,
                     f"{rid}: reserved stage quantities invalid")
        elif status == 'IN_TRANSIT':
            _require(issued > 0 and received == used == 0, f"{rid}: in-transit stage quantities invalid")
        elif status == 'RECEIVED':
            _require(received > 0 and used == 0, f"{rid}: received stage quantities invalid")
        elif status == 'REUSED':
            _require(used > 0, f"{rid}: reused transfer has no actual use")
    _require((t['delivered_at'] is not None) == (received > 0), f"{rid}: receipt timestamp mismatch")
    _require((t['reuse_confirmed_at'] is not None) == (used > 0), f"{rid}: use timestamp mismatch")
    stamps = [t['requested_at'], t['delivered_at'], t['reuse_confirmed_at']]
    stamps = [datetime.fromisoformat(value) for value in stamps if value is not None]
    _require(stamps == sorted(stamps), f"{rid}: transfer timestamps out of order")
    _require(datetime.fromisoformat(t['requested_at']) >= datetime.fromisoformat(p['created_at']),
             f"{rid}: transfer predates proposal")


def map_record_collections(
    *,
    as_of_date: date,
    projects: Iterable[Mapping],
    materials: Iterable[Mapping],
    documents: Iterable[Mapping],
    extracted_rows: Iterable[Mapping],
    supply_offers: Iterable[Mapping],
    demand_requests: Iterable[Mapping],
    optimisation_runs: Iterable[Mapping],
    allocation_proposals: Iterable[Mapping],
    transfers: Iterable[Mapping],
    route_distances: Iterable[Mapping] = (),
) -> DomainSnapshot:
    """Validate and map complete collections; preserves external field contracts.

    Dates/IDs/counts are not tied to the synthetic fixture. Existing record
    schemas are required in full. No new states or residual-resolution fields
    are invented. Missing related collections must not be replaced by empty
    lists if their records contribute to the supplied balances.
    """
    _require(type(as_of_date) is date, "as_of_date must be a Python date")
    collections = {
        'projects': projects, 'materials': materials, 'documents': documents,
        'extracted_rows': extracted_rows, 'supply_offers': supply_offers,
        'demand_requests': demand_requests, 'optimisation_runs': optimisation_runs,
        'allocation_proposals': allocation_proposals, 'transfers': transfers,
        'route_distances': route_distances,
    }
    idx = {name: _index(name, records, as_of_date) for name, records in collections.items()}
    for entity, records in idx.items():
        for row in records.values():
            for name, scalar, _ in fields(entity):
                if scalar.startswith('FK=') and row[name] is not None:
                    target = scalar.split('=', 1)[1]
                    _require(row[name] in idx[target], f"{row['id']}: orphan {name} {row[name]}")
    for entity in ('supply_offers', 'demand_requests'):
        for row in idx[entity].values():
            _check_origin(row, entity, idx)

    held, issued, fulfilled, incoming = (defaultdict(int) for _ in range(4))
    incoming_ids = defaultdict(list)
    used_proposals = set()
    for p in idx['allocation_proposals'].values():
        _require(p['proposed_quantity'] > 0, f"{p['id']}: proposal quantity must be positive")
        _require(p['status'] != 'SELECTED' or p['compatibility_result'] == 'ELIGIBLE',
                 f"{p['id']}: selected proposal is not eligible")
    for t in idx['transfers'].values():
        pid = t['proposal_id']
        _require(pid not in used_proposals, f"{t['id']}: duplicate transfer for proposal {pid}")
        used_proposals.add(pid)
        p = idx['allocation_proposals'][pid]
        sid, did = p['supply_offer_id'], p['demand_request_id']
        _check_transfer(t, p, idx['supply_offers'][sid], idx['demand_requests'][did])
        held[sid] += t['reserved_quantity']
        issued[sid] += t['dispatched_quantity']
        fulfilled[did] += t['actually_used_quantity']
        if t['status'] in {'RESERVED', 'IN_TRANSIT', 'RECEIVED', 'REUSED'}:
            remaining_promise = t['approved_quantity'] - t['actually_used_quantity']
            incoming[did] += remaining_promise
            if remaining_promise:
                incoming_ids[did].append(t['id'])

    mapped_supplies, mapped_demands = {}, {}
    try:
        for sid, row in idx['supply_offers'].items():
            _require(row['reserved_active_quantity'] == held[sid]
                     and row['transferred_out_quantity'] == issued[sid],
                     f"{sid}: source counters do not reconcile with supplied transfers")
            confirmed = row['confirmed_quantity']
            _require(confirmed is None or confirmed <= row['declared_quantity'],
                     f"{sid}: confirmed quantity exceeds declared quantity")
            quantity = SupplyQuantity(confirmed, held[sid], issued[sid])
            mapped_supplies[sid] = Supply(
                sid, row['source_project_id'], row['material_id'], row['unit'],
                row['surplus_status'], row['condition'], date.fromisoformat(row['available_from']),
                date.fromisoformat(row['available_until']) if row['available_until'] else None,
                quantity, row['batch_or_lot_code'], tuple(row['evidence_refs']),
            )
        for did, row in idx['demand_requests'].items():
            _require(row['fulfilled_quantity'] == fulfilled[did],
                     f"{did}: fulfilled counter does not reconcile with actual use")
            mapped_demands[did] = Demand(
                did, row['destination_project_id'], row['material_id'], row['unit'],
                row['request_status'], row['is_outstanding_need_confirmed'],
                date.fromisoformat(row['needed_from']), date.fromisoformat(row['required_by']),
                DemandQuantity(row['required_quantity'], fulfilled[did], incoming[did]),
            )
    except ValueError as exc:
        if isinstance(exc, SnapshotMappingError):
            raise
        raise SnapshotMappingError(f"Invalid domain quantities/status/window: {exc}") from exc
    mapped_materials = {
        mid: Material(mid, row['category'], row['standard_unit'], _freeze(row['specifications']))
        for mid, row in idx['materials'].items()
    }
    mapped_routes = {}
    for row in idx['route_distances'].values():
        pair = tuple(sorted((row['from_project_id'], row['to_project_id'])))
        _require(pair[0] != pair[1], f"{row['id']}: self-project route")
        _require(pair not in mapped_routes, f"{row['id']}: duplicate undirected route pair")
        _require(row['distance_km'] > 0, f"{row['id']}: route distance must be positive")
        mapped_routes[pair] = RouteDistance(row['id'], Decimal(str(row['distance_km'])), row['is_synthetic'])
    return DomainSnapshot(
        as_of_date,
        MappingProxyType({pid: row['township'] for pid, row in sorted(idx['projects'].items())}),
        MappingProxyType(dict(sorted(mapped_materials.items()))),
        MappingProxyType(dict(sorted(mapped_supplies.items()))),
        MappingProxyType(dict(sorted(mapped_demands.items()))),
        MappingProxyType({did: tuple(sorted(incoming_ids[did])) for did in sorted(mapped_demands)}),
        MappingProxyType(dict(sorted(mapped_routes.items()))),
    )
