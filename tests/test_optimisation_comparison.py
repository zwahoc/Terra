"""Shared snapshots, atomic commands, linked forecasts and explicit selection."""
import asyncio
import copy
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from terra.validation import load, sha
from backend.app.repositories.optimisation_repository import (
    OptimisationPersistenceState, OptimisationPersistenceError, _run, _proposal,
)
from backend.app.repositories.impact_repository import ImpactRepository
from backend.app.services.optimisation_comparison_service import (
    OptimisationComparisonInput, persist_optimisation_comparison,
)
from backend.app.services.optimisation_run_service import OptimisationRunConflict
from backend.app.services.optimisation_preview_service import preview_comparison
from tests.test_impact_api import request
from tests.test_transfer_request import FakeRequestRepository, BODY
from backend.app.services.transfer_request_service import create_transfer_request, TransferRequestInput


NOW = lambda: datetime(2026, 10, 17, 12, tzinfo=timezone(timedelta(hours=8)))


class ComparisonRepository:
    def __init__(self, records, fail=False, lost_response=False):
        self.records = copy.deepcopy(records)
        self.states, self.commands, self.reads = {}, [], 0
        self.fail, self.lost_response = fail, lost_response

    def snapshot(self):
        self.reads += 1
        return copy.deepcopy(self.records)

    def persistence_state(self, run_id, operation_id):
        return self.states.get(run_id, OptimisationPersistenceState(None, None, []))

    def persist_comparison(self, command):
        self.commands.append(copy.deepcopy(command))
        if self.fail:
            raise OptimisationPersistenceError('rollback')
        for run, operation in zip(command['runs'], command['operations']):
            proposals = [_proposal(p) for p in command['proposals'] if p['runId'] == run['id']]
            ids = {p['id'] for p in proposals}
            assessments = [ImpactRepository._assessment(a) for a in command['assessments']
                           if a['proposalId'] in ids]
            self.states[run['id']] = OptimisationPersistenceState(_run(run),
                {'id': operation['id'], 'request_fingerprint': operation['requestFingerprint'],
                 'run_id': run['id']}, proposals, assessments)
        if self.lost_response:
            raise OptimisationPersistenceError('lost response')


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.records = load()
        self.input = OptimisationComparisonInput(date(2026, 10, 12), 'demo-v1', None,
                                                 'compare-001', 'Demo operator')

    def test_preview_uses_one_prepared_calculator_and_same_budgets(self):
        from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
        with patch('backend.app.services.optimisation_preview_service.ForecastPreviewCalculator',
                   wraps=ForecastPreviewCalculator) as calculator:
            result = preview_comparison(self.records, planning_date=self.input.planning_date,
                                         factor_dataset_version='demo-v1')
        self.assertEqual(calculator.call_count, 1)
        left, right = result['alternatives']
        self.assertEqual(left['allocation_snapshot_hash'], right['allocation_snapshot_hash'])
        self.assertEqual(left['carbon_context_id'], right['carbon_context_id'])
        self.assertEqual(left['plan']['total_proposed_quantity'], 4480)
        self.assertGreater(right['plan']['total_proposed_quantity'], 0)

    def test_persistence_links_snapshots_forecasts_and_heads_without_stock_writes(self):
        repo = ComparisonRepository(self.records)
        result = persist_optimisation_comparison(self.input, repo, NOW)
        self.assertEqual(repo.reads, 1)
        self.assertEqual(len(repo.commands), 1)
        command = repo.commands[0]
        self.assertEqual(len(command['runs']), 2)
        self.assertEqual(command['runs'][0]['inputSnapshot'], command['runs'][1]['inputSnapshot'])
        for run in command['runs']:
            self.assertEqual(run['inputsSnapshotHash'], sha(run['inputSnapshot']))
            self.assertIn('supply_offers', run['inputSnapshot'])
            self.assertIn('emission_factors', run['inputSnapshot'])
        self.assertEqual(len(command['proposals']), len(command['assessments']))
        self.assertEqual(len(command['heads']), len(command['assessments']))
        proposals = {p['id']: p for p in command['proposals']}
        for assessment, head in zip(command['assessments'], command['heads']):
            proposal = proposals[assessment['proposalId']]
            self.assertEqual(proposal['status'], 'PROPOSED')
            self.assertEqual(assessment['quantityAssessed'], proposal['proposedQuantity'])
            self.assertEqual(assessment['basis'], 'PROPOSAL_FORECAST')
            self.assertEqual(head['currentAssessmentId'], assessment['id'])
            self.assertEqual(head['revision'], 1)
        self.assertEqual(repo.records, self.records)
        self.assertEqual(set(command), {'runs', 'operations', 'proposals', 'assessments', 'heads'})
        self.assertEqual(len(result['data']['alternatives']), 2)

    def test_retry_and_different_input_conflict(self):
        from dataclasses import replace
        repo = ComparisonRepository(self.records)
        persist_optimisation_comparison(self.input, repo, NOW)
        self.assertTrue(persist_optimisation_comparison(self.input, repo, NOW)['data']['replayed'])
        self.assertEqual(repo.reads, 1)
        with self.assertRaises(OptimisationRunConflict):
            persist_optimisation_comparison(replace(self.input, factor_dataset_version='other'), repo, NOW)

    def test_failed_transaction_and_lost_response(self):
        from backend.app.services.optimisation_run_service import OptimisationRunError
        repo = ComparisonRepository(self.records, fail=True)
        with self.assertRaises(OptimisationRunError):
            persist_optimisation_comparison(self.input, repo, NOW)
        self.assertFalse(repo.states)
        repo = ComparisonRepository(self.records, lost_response=True)
        self.assertTrue(persist_optimisation_comparison(self.input, repo, NOW)['data']['replayed'])
        self.assertEqual(len(repo.commands), 1)

    def test_proposed_alternative_can_be_selected_for_requested_transfer(self):
        repo = ComparisonRepository(self.records)
        saved = persist_optimisation_comparison(self.input, repo, NOW)
        proposal = saved['data']['alternatives'][0]['proposals'][0]
        transfer_repo = FakeRequestRepository(proposal)
        response = create_transfer_request(proposal['id'], TransferRequestInput(**BODY), transfer_repo, NOW)
        self.assertEqual(response['data']['transfer']['status'], 'REQUESTED')
        self.assertEqual(response['data']['transfer']['reserved_quantity'], 0)

    def test_comparison_routes(self):
        body = {'planning_date': '2026-10-12', 'factor_dataset_version': 'demo-v1'}
        with patch('backend.app.routes.impact._preview_records', return_value=self.records):
            status, _, payload = asyncio.run(request('POST', '/api/optimisation-comparisons/preview', body=body))
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(json.loads(payload)['data']['alternatives']), 2)
        with patch('backend.app.services.optimisation_comparison_service.OptimisationRepository',
                   return_value=ComparisonRepository(self.records)):
            status, _, payload = asyncio.run(request('POST', '/api/optimisation-comparisons', body={
                **body, 'idempotency_key': 'http-compare', 'actor_label': 'Demo operator'}))
        self.assertEqual(status, 201, payload)
        self.assertEqual(len(json.loads(payload)['data']['alternatives']), 2)


if __name__ == '__main__':
    unittest.main()
