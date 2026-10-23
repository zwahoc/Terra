"""Non-persisting Member 3/4 connection and HTTP preview contracts."""
import asyncio
import copy
import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from terra.validation import load
from backend.app.repositories.impact_repository import ImpactRepositoryUnavailable
from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
from backend.app.services.optimisation_preview_service import preview_optimisation
from backend.app.services.impact_service import ImpactInvalid
from tests.test_impact_api import request


class ReadOnlyRepository:
    def __init__(self, records, unavailable=False):
        self.records, self.unavailable, self.reads = records, unavailable, 0

    def snapshot(self):
        self.reads += 1
        if self.unavailable:
            raise ImpactRepositoryUnavailable('offline')
        return self.records

    def persist(self, *_args, **_kwargs):
        raise AssertionError('Preview must never persist')

    def persistence_state(self, *_args):
        raise AssertionError('Preview must not require revision heads')


class ForecastPreviewTests(unittest.TestCase):
    def setUp(self):
        self.records = load()

    def calculator(self, records=None):
        return ForecastPreviewCalculator(records or self.records,
            planning_date=date(2026, 10, 12), factor_dataset_version='demo-v1')

    def test_known_arithmetic_and_explicit_linearity(self):
        calc = self.calculator()
        result = calc.assess_forecast_preview('SUP-003', 'DEM-003', 200)
        self.assertEqual(result['avoided_production_kgco2e'], Decimal('190'))
        self.assertEqual(result['additional_transport_kgco2e'], Decimal('5.19168'))
        self.assertEqual(result['additional_processing_kgco2e'], Decimal('4'))
        self.assertEqual(result['net_avoided_kgco2e'], Decimal('180.80832'))
        coefficient = calc.score_linear_candidates().net_kgco2e_per_piece['SUP-003', 'DEM-003']
        for q in (1, 50, 100, 200):
            self.assertEqual(calc.assess_forecast_preview('SUP-003', 'DEM-003', q)['net_avoided_kgco2e'],
                             coefficient * q)
        self.assertFalse(result['persisted'])
        self.assertNotIn('proposal_id', result)
        self.assertNotIn('id', result)
        self.assertTrue(result['factor_snapshots'])

    def test_eligibility_and_quantity_caps(self):
        calc = self.calculator()
        for pair, quantity in ((('SUP-003', 'DEM-003'), 201),
                               (('SUP-003', 'DEM-003'), 0),
                               (('SUP-003', 'DEM-003'), True),
                               (('SUP-020', 'DEM-019'), 1),
                               (('SUP-unknown', 'DEM-003'), 1)):
            with self.assertRaises(ImpactInvalid):
                calc.assess_forecast_preview(*pair, quantity)

    def test_detached_context_deterministic_hash_and_factor_change(self):
        before = copy.deepcopy(self.records)
        calc = self.calculator()
        reordered = {k: list(reversed(v)) if isinstance(v, list) else v
                     for k, v in self.records.items()}
        self.assertEqual(calc.carbon_context_id, self.calculator(reordered).carbon_context_id)
        self.assertEqual(self.records, before)
        next(f for f in self.records['emission_factors'] if f['id'] == 'EF-002')['value'] = 2
        self.assertEqual(calc.assess_forecast_preview('SUP-003', 'DEM-003', 200)['net_avoided_kgco2e'],
                         Decimal('180.80832'))
        self.assertNotEqual(calc.carbon_context_id, self.calculator().carbon_context_id)

    def test_missing_data_is_unscored_not_zero_and_negative_is_preserved(self):
        records = copy.deepcopy(self.records)
        records['emission_factors'] = [f for f in records['emission_factors'] if f['id'] != 'EF-008']
        calc = self.calculator(records)
        preview = calc.assess_forecast_preview('SUP-003', 'DEM-003', 200)
        self.assertIsNone(preview['net_avoided_kgco2e'])
        self.assertEqual(preview['calculation_status'], 'INSUFFICIENT_DATA')
        self.assertIsNone(calc.score_linear_candidates().net_kgco2e_per_piece['SUP-003', 'DEM-003'])
        records = copy.deepcopy(self.records)
        next(f for f in records['emission_factors'] if f['id'] == 'EF-007')['value'] = 1000
        self.assertLess(self.calculator(records).assess_forecast_preview('SUP-003', 'DEM-003', 200)
                        ['net_avoided_kgco2e'], 0)

    def test_missing_mass_route_and_invalid_factor(self):
        for field in ('mass', 'route'):
            records = copy.deepcopy(self.records)
            if field == 'mass':
                next(m for m in records['materials'] if m['id'] == 'MAT-002')['mass_kg_per_unit'] = None
            else:
                records['route_distances'] = [r for r in records['route_distances'] if r['id'] != 'RTE-003']
            self.assertIsNone(self.calculator(records).assess_forecast_preview('SUP-003', 'DEM-003', 200)
                              ['net_avoided_kgco2e'])
        records = copy.deepcopy(self.records)
        records['emission_factors'][0]['value'] = float('nan')
        with self.assertRaises(ImpactInvalid):
            self.calculator(records)

    def test_all_objectives_connect_to_final_quantity_forecasts(self):
        before = copy.deepcopy(self.records)
        for objective in ('MAX_REUSE', 'EARLIEST_DEADLINE', 'MAX_NET_CO2E_AVOIDED'):
            response = preview_optimisation(self.records, objective=objective,
                planning_date=date(2026, 10, 12), factor_dataset_version='demo-v1')
            allocations = response['plan']['allocations']
            forecasts = response['forecast_previews']
            self.assertEqual(len(allocations), len(forecasts))
            for allocation, forecast in zip(allocations, forecasts):
                self.assertEqual(allocation['proposed_quantity'], forecast['quantity_assessed'])
                self.assertEqual((allocation['supply_offer_id'], allocation['demand_request_id']),
                                 (forecast['supply_offer_id'], forecast['demand_request_id']))
                self.assertEqual(forecast['carbon_context_id'], response['carbon_context_id'])
            self.assertFalse(response['persisted'])
            json.dumps(response)
            if objective == 'MAX_REUSE':
                self.assertEqual(response['plan']['total_proposed_quantity'], 4480)
            if objective == 'MAX_NET_CO2E_AVOIDED':
                self.assertEqual(Decimal(response['plan']['estimated_net_avoided_kgco2e']),
                                 Decimal(response['forecast_summary']['net_avoided_kgco2e']))
        self.assertEqual(self.records, before)

    def test_matching_coverage_uses_this_runs_proposed_quantity(self):
        response = preview_optimisation(
            self.records, objective='MAX_REUSE', planning_date=date(2026, 10, 12),
            factor_dataset_version='demo-v1',
        )
        coverage = response['matching_coverage_by_demand']['DEM-003']
        self.assertEqual(coverage['required_quantity'], 500)
        self.assertEqual(coverage['proposed_quantity'], 200)
        self.assertEqual(coverage['status'], 'PARTIALLY_COVERED')

    def test_destination_project_scope_limits_allocations_on_the_backend(self):
        response = preview_optimisation(
            self.records,
            objective='MAX_REUSE',
            planning_date=date(2026, 10, 12),
            factor_dataset_version='demo-v1',
            destination_project_id='PRJ-001',
        )
        demand_project = {row['id']: row['destination_project_id']
                          for row in self.records['demand_requests']}
        self.assertEqual(response['destination_project_id'], 'PRJ-001')
        self.assertTrue(response['plan']['allocations'])
        self.assertTrue(all(demand_project[line['demand_request_id']] == 'PRJ-001'
                            for line in response['plan']['allocations']))
        with self.assertRaises(ImpactInvalid):
            preview_optimisation(
                self.records,
                objective='MAX_REUSE',
                planning_date=date(2026, 10, 12),
                factor_dataset_version='demo-v1',
                destination_project_id='PRJ-unknown',
            )

    def test_missing_forecasts_not_labelled_complete_total(self):
        records = copy.deepcopy(self.records)
        records['emission_factors'] = []
        for objective in ('MAX_REUSE', 'MAX_NET_CO2E_AVOIDED'):
            response = preview_optimisation(records, objective=objective,
                planning_date=date(2026, 10, 12), factor_dataset_version='demo-v1')
            if objective == 'MAX_REUSE':
                self.assertIsNone(response['forecast_summary']['net_avoided_kgco2e'])
                self.assertFalse(response['forecast_summary']['complete_for_selected_allocations'])
            else:
                self.assertFalse(response['plan']['carbon_scoring_available'])
                self.assertTrue(response['plan']['incomplete_carbon'])
                self.assertEqual(response['plan']['allocations'], [])

    def test_new_endpoints_read_once_and_do_not_persist(self):
        repo = ReadOnlyRepository(self.records)
        forecast = {'supply_offer_id': 'SUP-003', 'demand_request_id': 'DEM-003',
                    'quantity': 200, 'planning_date': '2026-10-12', 'factor_dataset_version': 'demo-v1'}
        with patch('backend.app.routes.impact.ImpactRepository', return_value=repo):
            status, _, body = asyncio.run(request('POST', '/api/impact-assessments/forecast-preview', body=forecast))
        self.assertEqual(status, 200, body)
        self.assertEqual(Decimal(json.loads(body)['data']['net_avoided_kgco2e']), Decimal('180.80832'))
        self.assertEqual(repo.reads, 1)

        repo.reads = 0
        with patch('backend.app.routes.impact.ImpactRepository', return_value=repo):
            status, _, body = asyncio.run(request('POST', '/api/optimisation-runs/preview', body={
                'objective': 'MAX_REUSE', 'planning_date': '2026-10-12',
                'factor_dataset_version': 'demo-v1', 'destination_project_id': 'PRJ-001'}))
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['data']['destination_project_id'], 'PRJ-001')
        self.assertEqual(repo.reads, 1)
        repo.reads = 0
        with patch('backend.app.routes.impact.ImpactRepository', return_value=repo):
            status, _, body = asyncio.run(request('POST', '/api/optimisation-runs/preview', body={
                'objective': 'MAX_NET_CO2E_AVOIDED', 'planning_date': '2026-10-12',
                'factor_dataset_version': 'demo-v1'}))
        self.assertEqual(status, 200, body)
        self.assertFalse(json.loads(body)['data']['persisted'])
        self.assertEqual(repo.reads, 1)

    def test_preview_api_errors_and_validation(self):
        payload = {'supply_offer_id': 'SUP-003', 'demand_request_id': 'DEM-003',
                   'quantity': 200, 'planning_date': '2026-10-12', 'factor_dataset_version': 'demo-v1'}
        repo = ReadOnlyRepository(self.records)
        for change, expected in (({'quantity': 201}, 400), ({'quantity': 200.0}, 422),
                                  ({'quantity': 0}, 422), ({'proposal_id': 'fake'}, 422)):
            with patch('backend.app.routes.impact.ImpactRepository', return_value=repo):
                status, _, _ = asyncio.run(request('POST', '/api/impact-assessments/forecast-preview',
                                                   body={**payload, **change}))
            self.assertEqual(status, expected)
        with patch('backend.app.routes.impact.ImpactRepository', return_value=ReadOnlyRepository(self.records)):
            status, _, body = asyncio.run(request('POST', '/api/impact-assessments/forecast-preview',body={**payload,'quantity':'200'}))
        self.assertEqual(status,200,body)
        with patch('backend.app.routes.impact.ImpactRepository', return_value=ReadOnlyRepository(self.records, True)):
            status, _, body = asyncio.run(request('POST', '/api/impact-assessments/forecast-preview', body=payload))
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['error']['code'], 'IMPACT_DATA_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
