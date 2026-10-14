"""Member 3 preview orchestration using Member 4's shared forecast engine."""
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

from backend.app.domain.allocator import allocate
from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
from backend.app.services.impact_service import ImpactInvalid


def preview_json(value):
    """JSON DTO conversion: decimal strings preserve precision for the UI."""
    if is_dataclass(value):
        return {f.name: preview_json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: preview_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [preview_json(v) for v in value]
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def preview_optimisation(records, *, objective: str, planning_date: date,
                         factor_dataset_version: str) -> dict:
    """One detached snapshot, no run/proposal IDs, reservations or writes.

    Final-quantity forecasts here are temporary previews, not linked persisted
    assessments. Existing revision APIs remain responsible for saved results.
    """
    if objective not in ('MAX_REUSE', 'EARLIEST_DEADLINE', 'MAX_NET_CO2E_AVOIDED'):
        raise ImpactInvalid('OPTIMISATION_OBJECTIVE_INVALID', 'Unsupported objective.')
    calculator = ForecastPreviewCalculator(records, planning_date=planning_date,
                                            factor_dataset_version=factor_dataset_version)
    if objective == 'MAX_NET_CO2E_AVOIDED':
        plan = allocate(calculator.snapshot, objective=objective,
                        carbon_scores=calculator.score_linear_candidates(),
                        factor_dataset_version=calculator.factor_dataset_version,
                        carbon_context_id=calculator.carbon_context_id)
    else:
        plan = allocate(calculator.snapshot, objective=objective)
    forecasts = [calculator.assess_forecast_preview(a.supply_offer_id, a.demand_request_id,
                                                   a.proposed_quantity) for a in plan.allocations]
    incomplete = [ (f['supply_offer_id'], f['demand_request_id']) for f in forecasts
                   if f['net_avoided_kgco2e'] is None ]
    subtotal = sum((f['net_avoided_kgco2e'] for f in forecasts
                    if f['net_avoided_kgco2e'] is not None), Decimal(0))
    return preview_json({
        'preview': True, 'persisted': False,
        'allocation_snapshot_hash': calculator.allocation_snapshot_hash,
        'carbon_context_id': calculator.carbon_context_id,
        'factor_dataset_version': calculator.factor_dataset_version,
        'plan': plan,
        'forecast_previews': forecasts,
        'forecast_summary': {
            'net_avoided_kgco2e': None if incomplete else subtotal,
            'known_net_subtotal_kgco2e': subtotal,
            'complete_for_selected_allocations': not incomplete,
            'incomplete_allocations': incomplete,
            # Distinct from completeness of the chosen allocation forecasts.
            'candidate_scoring_incomplete': plan.incomplete_carbon,
            'carbon_scoring_available': plan.carbon_scoring_available,
        },
    })
