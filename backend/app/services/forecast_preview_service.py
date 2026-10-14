"""Member 4 non-persisting forecast calculations on detached shared inputs."""
from copy import deepcopy
from datetime import date
from decimal import Decimal

from backend.app.domain.allocator import LinearCarbonScores, allocation_snapshot_hash
from backend.app.domain.candidates import generate_candidate_pairs
from backend.app.domain.snapshot_mapping import map_record_collections, SnapshotMappingError
from backend.app.services.impact_service import (
    BASELINE_DESCRIPTION, LIFECYCLE_BOUNDARY, OMISSIONS, ImpactInvalid,
    _hash, _route, _factor_snapshot, calculate_context_components,
)
from terra.contract import MODELS


COLLECTIONS = ('projects', 'materials', 'documents', 'extracted_rows', 'supply_offers',
               'demand_requests', 'optimisation_runs', 'allocation_proposals',
               'transfers', 'route_distances')


class ForecastPreviewCalculator:
    """No database calls/writes. Share this instance across scoring/allocation.

    Forecast quantities are proposed=moved=processed, substitution ratio 1,
    with fixed factors/mass/distance and no fixed/shared trip costs. This
    explicitly guarantees per-piece linearity throughout eligible pair caps.
    Inputs are detached from the caller; methods never change them.
    """
    def __init__(self, records, *, planning_date: date, factor_dataset_version: str):
        if type(planning_date) is not date or not isinstance(factor_dataset_version, str) or not factor_dataset_version.strip():
            raise ImpactInvalid('FORECAST_INPUT_INVALID', 'Planning date and factor version are required.')
        self._records = deepcopy(records)
        try:
            self.snapshot = map_record_collections(as_of_date=planning_date,
                **{name: self._records[name] for name in COLLECTIONS})
            self._factors = [MODELS['emission_factors'].model_validate(row).model_dump()
                             for row in self._records['emission_factors']]
            if len({f['id'] for f in self._factors}) != len(self._factors):
                raise ValueError('Duplicate factor IDs')
            if any(not Decimal(str(f['value'])).is_finite() or f['value'] < 0 for f in self._factors):
                raise ValueError('Invalid factor value')
        except (SnapshotMappingError, KeyError, ValueError, TypeError) as exc:
            raise ImpactInvalid('FORECAST_INPUT_INVALID', 'Forecast records failed validation.') from exc
        self.factor_dataset_version = factor_dataset_version
        self._pairs = {(p.supply_offer_id, p.demand_request_id): p
                       for p in generate_candidate_pairs(self.snapshot).pairs}
        self._materials = {r['id']: r for r in self._records['materials']}
        self.allocation_snapshot_hash = allocation_snapshot_hash(self.snapshot)
        self.carbon_context_id = _hash({
            'allocation_snapshot_hash': self.allocation_snapshot_hash,
            'planning_date': planning_date.isoformat(),
            'factor_dataset_version': factor_dataset_version,
            'materials': sorted(self._records['materials'], key=lambda r: r['id']),
            'routes': sorted(self._records['route_distances'], key=lambda r: r['id']),
            'factors': sorted(self._factors, key=lambda r: r['id']),
            'boundary': LIFECYCLE_BOUNDARY,
            'model': 'linear-all-proposed-units-moved-and-processed-v1',
        })

    def assess_forecast_preview(self, supply_offer_id: str, demand_request_id: str,
                                quantity: int) -> dict:
        """Return components/provenance for one eligible hypothetical quantity."""
        pair = self._pairs.get((supply_offer_id, demand_request_id))
        if pair is None or pair.compatibility_result != 'ELIGIBLE':
            raise ImpactInvalid('FORECAST_PAIR_NOT_ELIGIBLE', 'Only an eligible candidate can be previewed.')
        if type(quantity) is not int or not 0 < quantity <= pair.max_allocatable_quantity:
            raise ImpactInvalid('FORECAST_QUANTITY_INVALID', 'Quantity must be positive and within the candidate cap.')
        supply = self.snapshot.supplies[supply_offer_id]
        demand = self.snapshot.demands[demand_request_id]
        material = self._materials[supply.material_id]
        route, route_issue = _route(self._records['route_distances'],
                                    supply.source_project_id, demand.destination_project_id)
        context = {
            'material': material, 'run': {'factor_dataset_version': self.factor_dataset_version},
            'route': route, 'route_issue': route_issue,
            'quantity': quantity, 'moved_quantity': quantity, 'processed_quantity': quantity,
            # Preview factor applicability is explicitly bound to planning_date.
            'activity_at': self.snapshot.as_of_date.isoformat(),
        }
        result, factors = calculate_context_components(context, self._factors)
        return {
            'preview': True, 'persisted': False,
            'supply_offer_id': supply_offer_id, 'demand_request_id': demand_request_id,
            'quantity_assessed': quantity, 'unit': 'pcs',
            'planning_date': self.snapshot.as_of_date.isoformat(),
            'allocation_snapshot_hash': self.allocation_snapshot_hash,
            'carbon_context_id': self.carbon_context_id,
            'factor_dataset_version': self.factor_dataset_version,
            'avoided_production_kgco2e': result.avoided_production_kgco2e,
            'additional_transport_kgco2e': result.additional_transport_kgco2e,
            'additional_processing_kgco2e': result.additional_processing_kgco2e,
            'net_avoided_kgco2e': result.net_avoided_kgco2e,
            'missing_data': result.missing_data,
            'calculation_status': ('INSUFFICIENT_DATA' if result.net_avoided_kgco2e is None
                                   else 'DEMO' if all(f['is_demo_factor'] for f in factors)
                                   else 'PRELIMINARY'),
            'factor_ids': tuple(f['id'] for f in factors),
            'factor_snapshots': tuple(_factor_snapshot(f) for f in factors),
            'baseline_description': BASELINE_DESCRIPTION,
            'assumptions': {
                'synthetic': True, 'linear_scaling_guaranteed': True,
                'moved_quantity': quantity, 'processed_quantity': quantity,
                'handling_allocation': 'ALL_MOVED_UNITS', 'substitution_ratio': 1,
                'mass_kg_per_unit': material['mass_kg_per_unit'],
                'distance_km': route['distance_km'] if route else None,
                'route_id': route['id'] if route else None,
                'lifecycle_boundary': LIFECYCLE_BOUNDARY, 'omissions': tuple(OMISSIONS),
            },
        }

    def score_linear_candidates(self) -> LinearCarbonScores:
        """Use the shared one-piece forecast under the explicit linear model.

        No arbitrary cap-total division or stored assessment Float round-trip.
        Unknown net remains None; negative coefficients are preserved for the
        allocator's separate exclusion policy.
        """
        coefficients = {}
        for pid, pair in self._pairs.items():
            if pair.compatibility_result == 'ELIGIBLE':
                coefficients[pid] = self.assess_forecast_preview(*pid, 1)['net_avoided_kgco2e']
        return LinearCarbonScores(self.allocation_snapshot_hash, self.factor_dataset_version,
                                  self.carbon_context_id, coefficients, True)
