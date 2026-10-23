"""Public clone setup: current dates, exact units, guarded import and usable workflows."""
import copy
from datetime import date, datetime, timedelta
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from terra.demo_workspace import build_demo, validate_demo, bootstrap_demo, RECEIPT_ID, ZONE, TEMPLATE, TEMPLATE_DATE
from terra.local_adapter import LocalDataConnect, AdapterError, variables
from terra.quantities import json_default
from terra.validation import sha

DAY=date(2026,10,24)
NOW=datetime(2026,10,24,12,tzinfo=ZONE)


class DemoWorkspaceTests(unittest.TestCase):
    def test_checked_template_and_deterministic_relative_dates(self):
        import json
        expected=json.dumps(build_demo(TEMPLATE_DATE),indent=2,ensure_ascii=False,default=json_default)+'\n'
        self.assertEqual(TEMPLATE.read_text(encoding='utf-8'),expected)
        for anchor in (DAY,date(2027,1,31),date(2028,2,29)):
            seed=build_demo(anchor);report=validate_demo(seed)
            self.assertEqual(report['counts']['materials'],8)
            self.assertEqual(report['eligible_pairs'],16)
            self.assertEqual(seed,build_demo(anchor))
            self.assertTrue(all(date.fromisoformat(d['required_by'])>anchor for d in seed['demand_requests']))
            self.assertTrue(all(datetime.fromisoformat(e['occurred_at']).date()<anchor for e in seed['transfer_events']))

    def test_three_objectives_have_broad_unit_complete_carbon_results(self):
        from backend.app.services.optimisation_preview_service import preview_comparison
        from backend.app.services.matching_service import material_records
        seed=build_demo(DAY)
        units=set()
        for material in seed['materials']:
            result=preview_comparison(material_records(seed,material['id']),planning_date=DAY,factor_dataset_version='demo-v1')
            self.assertEqual(len(result['alternatives']),3)
            for option in result['alternatives']:
                for assessment in option['forecast_previews']:
                    self.assertIsNotNone(assessment['net_avoided_kgco2e'])
                    units.add(assessment['unit'])
        self.assertEqual(units,{'pcs','m','kg','bag','m2'})

    def test_provenance_exact_values_and_invalid_history(self):
        seed=build_demo(DAY)
        self.assertEqual(seed['supply_offers'][3]['declared_quantity'],Decimal('144.5'))
        self.assertEqual(sum(Decimal(str(r['net_avoided_kgco2e'])) for r in seed['impact_assessments']),Decimal('160.95'))
        self.assertTrue(all(m['is_synthetic'] and m['mass_source'] for m in seed['materials']))
        self.assertTrue(all(f['is_demo_factor'] and f['source_url'] is None for f in seed['emission_factors']))
        for mutate in (
            lambda s:s['documents'][0].update(file_hash='not-an-upload'),
            lambda s:s['transfers'][0].update(received_quantity=99),
            lambda s:s['transfer_events'][0]['payload'].update(quantity=1),
            lambda s:s['supply_offers'][3].update(declared_quantity=144.5),
            lambda s:s['emission_factors'].clear(),
        ):
            candidate=copy.deepcopy(seed);mutate(candidate)
            with self.assertRaises((ValueError,TypeError)):validate_demo(candidate)

    def test_repeat_is_non_mutating_even_after_ordinary_work(self):
        class Saved:
            def execute(self,operation,variables=None,write=False):
                if write:raise AssertionError('Repeat import must not write')
                if operation!='GetRuntimeAudit':raise AssertionError('Repeat must not restore baseline')
                return {'runtimeAudit':{'payload':{'as_of_date':str(DAY),'fingerprint':'saved'}}}
        self.assertIn('existing work preserved',bootstrap_demo(Saved())['action'])
        with self.assertRaises(ValueError):bootstrap_demo(Saved(),as_of=DAY+timedelta(days=1))


@unittest.skipUnless(os.environ.get('TERRA_RUN_EMULATOR_TESTS')=='1','Disposable 9499 integration runner only')
class DemoWorkspaceEmulatorTests(unittest.TestCase):
    def setUp(self):
        self.a=LocalDataConnect()
        self.assertIn('127.0.0.1:9499',self.a.base)
        version=self.a.execute('GetOperationalVersion')['operationalVersion']
        if version:
            self.a.execute('ResetLocalWorkspace',{'expectedOperationalRevision':version['revision'],
                'expectedBatches':{'batches':self.a.execute('GetCutoverBatchHeads')['ingestionBatches']}},write=True)
        else:self.a.execute('ClearBaseline',write=True)

    def test_new_clone_matching_delivery_use_report_and_repeat_preserves_work(self):
        from backend.app.services.matching_service import MatchingService
        from backend.app.services.transfer_confirmation_service import prepare_confirmation,confirm_transfer
        from backend.app.schemas.transfers import TransferConfirmationRequest
        from backend.app.services.transfer_workflow_service import run_transfer_workflow,WorkflowInput
        from backend.app.repositories.transfer_repository import TransferRepository
        from backend.app.services.automatic_impact_service import AutomaticImpactService
        from backend.app.repositories.impact_repository import ImpactRepository
        from backend.app.services.impact_export_service import export_json
        from backend.app.services.workspace_service import workspace_data
        report=bootstrap_demo(self.a,as_of=DAY)
        self.assertEqual(report['action'],'installed')
        self.assertEqual(self.a.execute('GetWorkspaceIdentity')['workspaceIdentity']['epoch'],report['epoch'])
        self.assertEqual(self.a.snapshot()['supply_offers'][3]['declared_quantity'],Decimal('144.5'))
        matcher=MatchingService(self.a,lambda:NOW);matcher.refresh()
        view=matcher.view();self.assertTrue(all(m['status']=='CURRENT' for m in view['materials']),view)
        generation=next(m['generation'] for m in view['materials'] if m['material_id']=='MAT-DEMO-001')
        self.assertEqual(len(generation['alternatives']),3)
        pid=generation['alternatives'][0]['proposal_ids'][0]
        preview=prepare_confirmation(self.a,pid,'100',generation['generation_id'],lambda:NOW)
        command=TransferConfirmationRequest(quantity='100',generation_id=generation['generation_id'],
            expected_revision=preview['expected_revision'],actor_label='Demo tester',idempotency_key='clone-test-confirm')
        result=confirm_transfer(pid,command,self.a,lambda:NOW)
        tid=result['data']['transfer']['id'];repo=TransferRepository(self.a)
        for action,quantity in [('dispatch',None),('receive',None),('confirm_use','60'),('confirm_use','40')]:
            run_transfer_workflow(tid,action,WorkflowInput('Demo tester',f'clone-{action}-{quantity}',quantity),repo,lambda:NOW)
            if action=='confirm_use':AutomaticImpactService(self.a,lambda:NOW).refresh()
        self.assertEqual(repo.get(tid)['actually_used_quantity'],100)
        matcher.refresh()
        with patch('backend.app.services.matching_service.datetime') as clock:
            clock.now.return_value=NOW
            workspace=workspace_data(self.a)
        self.assertEqual(len(workspace['terra']['projects']),4)
        records=export_json('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a))['data']['records']
        self.assertEqual(len(records),3)
        self.assertTrue(all(r['components_kgco2e']['net_avoided'] is not None for r in records))
        before=self.a.snapshot();revision=self.a.execute('GetOperationalVersion')
        self.assertIn('existing work preserved',bootstrap_demo(self.a)['action'])
        self.assertEqual(before,self.a.snapshot());self.assertEqual(revision,self.a.execute('GetOperationalVersion'))

    def test_draft_only_database_is_not_empty_and_is_not_modified(self):
        import tempfile
        from backend.app.services.ingestion_service import IntakeService
        from backend.app.services.ingestion_storage import SourceStore
        from backend.app.repositories.ingestion_repository import IngestionRepository,TerraReadRepository
        with tempfile.TemporaryDirectory() as folder:
            intake=IntakeService(IngestionRepository(self.a),TerraReadRepository(self.a),SourceStore(folder))
            batch=intake.create();before=self.a.execute('GetIngestionBatch',{'id':batch.id})
            with self.assertRaisesRegex(ValueError,'empty workspace'):bootstrap_demo(self.a,as_of=DAY)
            self.assertEqual(before,self.a.execute('GetIngestionBatch',{'id':batch.id}))
            self.assertIsNone(self.a.execute('GetRuntimeAudit',{'id':RECEIPT_ID})['runtimeAudit'])

    def test_atomic_guard_refuses_direct_import_over_existing_data(self):
        seed=build_demo(DAY);bootstrap_demo(self.a,as_of=DAY)
        before=self.a.snapshot();version=self.a.execute('GetOperationalVersion')['operationalVersion']['revision']
        with self.assertRaisesRegex(AdapterError,'DEMO_REQUIRES_EMPTY_WORKSPACE'):
            self.a.execute('ImportDemoWorkspace',{**variables(seed),'expectedRevision':version,
                'epoch':'must-not-replace','createdAt':NOW.isoformat(),'receipt':{}},write=True)
        self.assertEqual(self.a.snapshot(),before)
        self.assertEqual(self.a.execute('GetOperationalVersion')['operationalVersion']['revision'],version)
