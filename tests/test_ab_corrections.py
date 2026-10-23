"""Regression tests for dimensional factors and stale generated use notes."""
import copy
import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

from backend.app.domain.carbon import calculate_components
from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
from backend.app.services.transfer_workflow_service import WorkflowInput, run_transfer_workflow
from tests.test_checkpoint_a import runtime_records, DAY, NOW
from tests import test_transfer_workflow as workflow_tests


class FactorUnitRegressionTests(unittest.TestCase):
    def components(self, **changes):
        args=dict(quantity_assessed=Decimal('1.25'),moved_quantity=Decimal('3.25'),
            processed_quantity=Decimal('3.25'),mass_kg_per_unit=Decimal('1.2'),distance_km=Decimal(100),
            quantity_unit='m',production_factor={'unit':'kgCO2e/kg','value':2},
            transport_factor={'unit':'kgCO2e/t-km','value':'.12'},
            processing_factor={'unit':'kgCO2e/pcs','value':'.02'})
        return calculate_components(**{**args,**changes})

    def test_piece_handling_cannot_be_applied_to_metres(self):
        result=self.components()
        self.assertEqual(result.avoided_production_kgco2e,Decimal('3'))
        self.assertIsNone(result.additional_processing_kgco2e)
        self.assertIsNone(result.net_avoided_kgco2e)
        self.assertIn('PROCESSING_FACTOR_UNIT',result.missing_data)

    def test_piece_production_cannot_be_treated_as_mass_based_for_metres(self):
        result=self.components(production_factor={'unit':'kgCO2e/pcs','value':2},
            processing_factor={'unit':'kgCO2e/kg','value':'.02'})
        self.assertIsNone(result.avoided_production_kgco2e)
        self.assertIsNone(result.net_avoided_kgco2e)

    def test_forecast_and_carbon_scores_reject_wrong_unit(self):
        calculator=ForecastPreviewCalculator(runtime_records(),planning_date=DAY,factor_dataset_version='demo-v1')
        forecast=calculator.assess_forecast_preview('SUP-R1','DEM-R2','3.25')
        self.assertEqual(forecast['calculation_status'],'INSUFFICIENT_DATA')
        self.assertIsNone(forecast['additional_processing_kgco2e'])
        self.assertIsNone(forecast['net_avoided_kgco2e'])
        self.assertNotIn('EF-008',forecast['factor_ids'])
        self.assertTrue(all(v is None for v in calculator.score_linear_candidates().net_kgco2e_per_piece.values()))

    def test_dimension_check_also_rejects_wrong_transport_factor(self):
        result=self.components(transport_factor={'unit':'kgCO2e/kg','value':'.12'})
        self.assertIsNone(result.additional_transport_kgco2e)
        self.assertIn('TRANSPORT_FACTOR_UNIT',result.missing_data)

    def test_matching_units_and_known_mass_still_calculate(self):
        for factor_unit,expected in (('kgCO2e/m',Decimal('.065')),('kgCO2e/kg',Decimal('.078'))):
            with self.subTest(unit=factor_unit):
                result=self.components(processing_factor={'unit':factor_unit,'value':'.02'})
                self.assertEqual(result.additional_processing_kgco2e,expected)
                self.assertIsNotNone(result.net_avoided_kgco2e)
        result=self.components(processing_factor={'unit':'kgCO2e/kg','value':'.02'},mass_kg_per_unit=None)
        self.assertIsNone(result.additional_processing_kgco2e)
        self.assertIn('MASS_KG_PER_UNIT_FOR_PROCESSING',result.missing_data)


class UseNoteRegressionTests(unittest.TestCase):
    def test_use_does_not_overwrite_operator_note_with_remaining_balance(self):
        helper=workflow_tests.TransferWorkflowValidationTests();helper.setUpClass()
        state=helper.state('RECEIVED',approved_quantity=200,reserved_quantity=0,
            dispatched_quantity=200,received_quantity=200,actually_used_quantity=0,
            notes='Store under cover. Supplier reference ABC-14.')
        commands=[]
        repository=workflow_tests.FakeRepository(state)
        repository.run_workflow=lambda operation,command:commands.append(copy.deepcopy(command))
        def replay_result(*_args):return len(commands)>0
        with patch('backend.app.services.transfer_workflow_service._replay',side_effect=replay_result), \
             patch('backend.app.services.transfer_workflow_service._response',return_value={}):
            run_transfer_workflow(state.transfer['id'],'confirm_use',WorkflowInput('Operator','first',120),repository,lambda:NOW)
        self.assertEqual(commands[0]['notes'],state.transfer['notes'])
        self.assertEqual(commands[0]['event_payload']['unresolved_quantity'],80)
