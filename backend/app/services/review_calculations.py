"""Exact, draft-only stock/need previews. No FastAPI or database dependency."""
from decimal import Decimal, localcontext
from backend.app.services.ingestion_storage import digest_json
from terra.quantities import unit as canonical_unit


def amount(value):
    return Decimal(value) if value is not None else None


def decimal_text(value):
    return format(value, 'f') if value is not None else None


def group_id(project, material, unit):
    return digest_json({'project': project, 'material': material, 'unit': canonical_unit(unit)})


def preview_groups(records, contexts, confirmed_scopes):
    """Input records have reviewed meaning/treatment and checked comparable units.

    Existing extracted rows are observations, not assumed a complete inventory.
    Caller includes effective accepted baseline observations once. Completeness
    is acknowledged explicitly by the operator for each input group.
    """
    groups = {}
    with localcontext() as decimal_context:
        decimal_context.prec = max(1000, max((len(str(item['quantity'])) for item in records), default=0) + len(str(len(records))) + 32)
        for item in records:
            item={**item,'unit':canonical_unit(item['unit'])}
            key = group_id(item['project'], item['material'], item['unit'])
            group = groups.setdefault(key, {'id': key, 'project': item['project'], 'material': item['material'],
                'unit': item['unit'], 'inputs': [], 'amounts': {}, 'warnings': []})
            group['inputs'].append({k: v for k, v in item.items() if k != 'quantity'})
            values = group['amounts'].setdefault(item['kind'], [])
            values.append(amount(item['quantity']))
        for group in groups.values():
            values = group.pop('amounts')
            def total(kind):
                items = values.get(kind, [])
                return sum(items, Decimal(0)) if items and all(q is not None for q in items) else None
            stock = total('ON_HAND_INVENTORY')
            need = total('REMAINING_LOCAL_REQUIREMENT')
            direct_demand = total('OUTSTANDING_DEMAND')
            potential = total('POTENTIAL_SURPLUS')
            confirmed = total('CONFIRMED_SURPLUS')
            reserved, incoming = Decimal(0), Decimal(0)
            context = contexts.get(group['project'], {}).get('collections', {})
            for offer in context.get('supply_offers', []):
                if offer['material_id'] == group['material'] and canonical_unit(offer['unit']) == group['unit']:
                    reserved += Decimal(str(offer['reserved_active_quantity']))
            demands = {row['id']: row for row in context.get('demand_requests', [])}
            for commitment in context.get('demand_commitments', []):
                demand = demands.get(commitment['demand_request_id'])
                if demand and demand['material_id'] == group['material'] and canonical_unit(demand['unit']) == group['unit']:
                    incoming += Decimal(str(commitment['committed_incoming_quantity']))
            complete = group['id'] in confirmed_scopes
            available = max(stock - reserved, Decimal(0)) if stock is not None and complete else None
            computed_surplus = max(available - need, Decimal(0)) if available is not None and need is not None else None
            # Explicit demand is already net of stock. Never subtract stock twice.
            computed_demand = (max(direct_demand - incoming, Decimal(0)) if direct_demand is not None else
                               max(need - stock - incoming, Decimal(0)) if complete and need is not None and stock is not None else None)
            if values.get('PURCHASE_ORDER') and (direct_demand is not None or need is not None):
                group['warnings'].append('Purchase-order observations are not received stock or automatically mapped incoming commitments; confirm procurement coverage before allocating new demand.')
            if not complete:
                group['warnings'].append('Stock scope is not confirmed complete. Stock-based surplus/demand calculations are not determined.')
            if reserved and stock is not None and reserved > stock:
                group['warnings'].append('Active reservations exceed reviewed on-hand stock; resolve before publication.')
            for label, declared in [('Potential surplus', potential), ('Confirmed surplus', confirmed)]:
                if declared is not None and (available is None or declared > available):
                    group['warnings'].append(f'{label} cannot be validated against available stock.')
            if confirmed is not None and computed_surplus is not None and confirmed > computed_surplus:
                group['warnings'].append('Confirmed surplus exceeds stock remaining after local need.')
            group.update({k: decimal_text(v) for k, v in {
                'on_hand_observations': stock, 'remaining_local_requirement': need,
                'declared_potential_surplus': potential, 'declared_confirmed_surplus': confirmed,
                'declared_net_demand': direct_demand, 'active_reservations': reserved,
                'incoming_commitments': incoming, 'available_stock': available,
                'calculated_potential_surplus': computed_surplus, 'newly_allocatable_demand': computed_demand,
            }.items()})
            group['stock_scope_confirmed'] = complete
            group['demand_basis'] = 'DECLARED_NET_OF_STOCK' if direct_demand is not None else 'REMAINING_REQUIREMENT_MINUS_STOCK'
            # Only explicit CONFIRMED declarations with verified stock/timing can
            # become future offers; a calculation never grants release approval.
            group['reservable_offer_created'] = False
    return list(groups.values())
