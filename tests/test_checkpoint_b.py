"""Real isolated adapter checks for confirmation, movement and impact revisions."""
import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from tests import test_checkpoint_a as checkpoint_a
NOW=checkpoint_a.NOW
from backend.app.schemas.transfers import TransferConfirmationRequest
from backend.app.services.matching_service import MatchingService,current_records
from backend.app.services.transfer_confirmation_service import prepare_confirmation,confirm_transfer
from backend.app.services.transfer_workflow_service import run_transfer_workflow,WorkflowInput,TransferWorkflowInvalid,TransferWorkflowConflict
from backend.app.repositories.transfer_repository import TransferRepository
from backend.app.services.automatic_impact_service import AutomaticImpactService
from backend.app.repositories.impact_repository import ImpactRepository
from backend.app.services.runtime_inputs import correct_inputs
from backend.app.routes.matching import InputCorrection
from backend.app.services.ingestion_errors import IngestionError

@unittest.skipUnless(os.environ.get('TERRA_RUN_CHECKPOINT_B_TESTS')=='1','Requires dedicated checkpoint B emulator')
class CheckpointBEmulatorTests(unittest.TestCase):
    def setUp(self):
        checkpoint_a.CheckpointAEmulatorTests.setUp(self)
        self.match=MatchingService(self.a,lambda:NOW);self.match.refresh()
        self.repo=TransferRepository(self.a)
        self.imp=AutomaticImpactService(self.a,lambda:NOW)
    def proposal(self):
        view=self.match.view();gen=view['materials'][0]['generation'];run=gen['alternatives'][0]['run_id']
        records,_=current_records(self.a)
        return next(p for p in records['allocation_proposals'] if p['run_id']==run and p['demand_request_id']=='DEM-R2'),gen['generation_id']
    def confirm(self,key='confirm',quantity='3.25'):
        proposal,gid=self.proposal();preview=prepare_confirmation(self.a,proposal['id'],quantity,gid,lambda:NOW)
        command=TransferConfirmationRequest(actor_label='Operator',idempotency_key=key,quantity=quantity,generation_id=gid,expected_revision=preview['expected_revision'])
        return confirm_transfer(proposal['id'],command,self.a,lambda:NOW),proposal,command
    def workflow(self,tid,action,key,quantity=None):
        return run_transfer_workflow(tid,action,WorkflowInput('Operator',key,quantity,reason='Change quantity' if action=='cancel' else None),self.repo,lambda:NOW)
    def moved(self):
        result,_,_=self.confirm();tid=result['data']['transfer']['id']
        self.workflow(tid,'dispatch','dispatch');self.workflow(tid,'receive','receive');return tid
    def head(self,tid):return ImpactRepository(self.a).persistence_state('ACTUAL_CONFIRMED_USE:'+tid,'none').head
    def test_reduced_confirmation_replay_and_immutable_forecast(self):
        result,p,cmd=self.confirm();t=result['data']['transfer']
        self.assertEqual(t['status'],'RESERVED');self.assertEqual(t['reserved_quantity'],Decimal('3.25'))
        self.assertEqual(result['data']['event']['payload']['chosen_quantity'],'3.25')
        self.assertEqual(result['data']['event']['payload']['forecast']['quantity_assessed'],'3.25')
        replay=confirm_transfer(p['id'],cmd,self.a,lambda:NOW);self.assertTrue(replay['data']['replayed'])
        self.assertEqual(self.repo.get_supply_offer('SUP-R1')['reserved_active_quantity'],Decimal('3.25'))
        with self.assertRaises(IngestionError):confirm_transfer(p['id'],cmd.model_copy(update={'quantity':Decimal('3')}),self.a,lambda:NOW)

    def test_reviewed_open_categories_refresh_confirm_move_and_use_without_family_rules(self):
        from tests.test_reviewed_catalogue_matching import MATERIALS, reviewed_records
        from terra.local_adapter import variables
        for material in (MATERIALS[0], MATERIALS[-1]):
            with self.subTest(category=material[0]):
                self.a.execute('ClearBaseline',write=True)
                records=reviewed_records(*material)
                self.a.execute('ImportBaseline',variables(records),write=True)
                # A persisted generation from an older eligibility policy cannot
                # remain current, even when the database records are unchanged.
                with patch('backend.app.services.matching_service.ELIGIBILITY_POLICY_VERSION','older-family-policy'):
                    self.match.refresh()
                    old=self.match.view()['materials'][0]['generation']
                old_proposal=old['alternatives'][0]['proposal_ids'][0]
                self.assertEqual(self.match.view()['materials'][0]['status'],'PENDING')
                with self.assertRaises(IngestionError):
                    prepare_confirmation(self.a,old_proposal,'300',old['generation_id'],lambda:NOW)
                self.match.refresh()
                current=self.match.view()['materials'][0]['generation']
                self.assertNotEqual(old['generation_id'],current['generation_id'])
                self.assertEqual(len(current['alternatives'][0]['plan']['allocations']),1)
                self.assertEqual(current['alternatives'][0]['plan']['allocations'][0]['unit'],material[1])
                result,proposal,command=self.confirm('open-'+material[0],quantity='300')
                tid=result['data']['transfer']['id']
                replay=confirm_transfer(proposal['id'],command,self.a,lambda:NOW)
                self.assertTrue(replay['data']['replayed'])
                self.assertEqual(self.repo.get_supply_offer('SUP-R1')['reserved_active_quantity'],300)
                self.workflow(tid,'dispatch','dispatch-'+material[0])
                self.workflow(tid,'receive','receive-'+material[0])
                for key,qty in [('first','200'),('last','100')]:
                    self.workflow(tid,'confirm_use',key+'-'+material[0],qty)
                    self.imp.refresh()
                transfer=self.repo.get(tid)
                self.assertEqual(transfer['actually_used_quantity'],300)
                self.assertEqual(self.repo.get_demand_request('DEM-R2')['fulfilled_quantity'],300)
                self.assertEqual(self.head(tid)['revision'],2)
                self.assertEqual(self.a.snapshot()['materials'][0]['category'],material[0])
    def test_old_alternative_is_unusable_and_new_holds_survive(self):
        p,gid=self.proposal();preview=prepare_confirmation(self.a,p['id'],'4',gid,lambda:NOW)
        cmd=TransferConfirmationRequest(actor_label='Operator',idempotency_key='other',quantity='4',generation_id=gid,expected_revision=preview['expected_revision'])
        self.confirm()
        with self.assertRaises(IngestionError):confirm_transfer(p['id'],cmd,self.a,lambda:NOW)
        self.assertEqual(self.repo.get_supply_offer('SUP-R1')['reserved_active_quantity'],Decimal('3.25'))
    def test_full_movement_partial_then_repeated_use_and_impact(self):
        tid=self.moved()
        from backend.app.services.publication_service import provider_row
        transfer=self.repo.get(tid);transfer['notes']='Keep under cover.'
        self.a.execute('UpsertTransfers',{'rows':[provider_row('transfers',transfer)]},write=True)
        self.assertEqual(self.repo.get_supply_offer('SUP-R1')['transferred_out_quantity'],Decimal('3.25'))
        self.workflow(tid,'confirm_use','use1','1.25');self.imp._calculate(self.imp.view()[0])
        first=self.head(tid);self.assertEqual(first['revision'],1)
        state=ImpactRepository(self.a).persistence_state(first['id'],'none')
        rows,_=current_records(self.a);assessment=next(r for r in rows['impact_assessments'] if r['id']==first['current_assessment_id'])
        self.assertIsNone(assessment['additional_processing_kgco2e'])
        self.assertIsNone(assessment['net_avoided_kgco2e'])
        self.assertEqual(assessment['calculation_status'],'INSUFFICIENT_DATA')
        self.assertEqual(assessment['assumptions']['moved_quantity'],'3.25')
        self.assertEqual(self.repo.get_demand_request('DEM-R2')['committed_incoming_quantity'],2)
        self.workflow(tid,'confirm_use','use1','1.25');self.imp.refresh();self.assertEqual(self.head(tid)['revision'],1)
        self.workflow(tid,'confirm_use','use2','2');self.imp.refresh();self.assertEqual(self.head(tid)['revision'],2)
        self.assertEqual(self.repo.get_demand_request('DEM-R2')['fulfilled_quantity'],Decimal('3.25'))
        self.assertEqual(self.repo.get_demand_request('DEM-R2')['committed_incoming_quantity'],0)
        self.assertEqual(self.repo.get(tid)['notes'],'Keep under cover.')
        use_events=[e for e in self.repo.list_events(tid) if e['event_type']=='USED']
        self.assertEqual([Decimal(str(e['payload']['unresolved_quantity'])) for e in use_events],[Decimal('2'),Decimal('0')])
        with self.assertRaises(TransferWorkflowInvalid):self.workflow(tid,'confirm_use','too-much','1')
    def test_cancel_releases_once_and_reapprove_new_quantity(self):
        result,_,_=self.confirm();tid=result['data']['transfer']['id']
        self.workflow(tid,'cancel','cancel');self.workflow(tid,'cancel','cancel')
        self.assertEqual(self.repo.get_supply_offer('SUP-R1')['reserved_active_quantity'],0)
        self.assertEqual(self.repo.get_demand_request('DEM-R2')['committed_incoming_quantity'],0)
        self.match.refresh();new,_,_=self.confirm('new','2.5')
        self.assertNotEqual(tid,new['data']['transfer']['id'])
        self.workflow(new['data']['transfer']['id'],'dispatch','d2')
        with self.assertRaises(TransferWorkflowConflict):self.workflow(new['data']['transfer']['id'],'cancel','late-cancel')
    def test_calculation_failure_preserves_use_and_retries_without_use(self):
        tid=self.moved();self.workflow(tid,'confirm_use','use','1')
        with patch.object(ImpactRepository,'persist',side_effect=RuntimeError('Transient calculation failure')):self.imp.refresh()
        self.assertEqual(self.imp.view()[0]['status'],'FAILED')
        self.assertEqual(self.repo.get(tid)['actually_used_quantity'],1)
        self.imp.refresh(retry_failed=True);self.assertEqual(self.head(tid)['revision'],1)
        self.assertEqual(self.repo.get(tid)['actually_used_quantity'],1)
    def test_confirmed_weight_correction_creates_new_revision(self):
        tid=self.moved();self.workflow(tid,'confirm_use','use','1.25');self.imp.refresh()
        records,revision=current_records(self.a)
        correction=InputCorrection(expected_revision=revision,idempotency_key='weight',kind='MATERIAL_MASS',material_id='MAT-PIPE',values={'mass_kg_per_unit':'1.5'},basis='Supplier weight sheet',confirmed=True)
        correct_inputs(self.a,correction);self.imp.refresh()
        self.assertEqual(self.head(tid)['revision'],2)
        correct_inputs(self.a,correction);self.imp.refresh();self.assertEqual(self.head(tid)['revision'],2)
        self.assertEqual(self.repo.get(tid)['actually_used_quantity'],Decimal('1.25'))
    def test_confirmation_http_contract_and_legacy_bypass_guard(self):
        import asyncio
        from tests.test_transfers_api import request
        p,gid=self.proposal();preview=prepare_confirmation(self.a,p['id'],'2.25',gid,lambda:NOW)
        status,legacy=asyncio.run(request('POST',f"/api/allocation-proposals/{p['id']}/approve",{'actor_label':'Operator','idempotency_key':'legacy'}))
        self.assertEqual(status,409,legacy)
        cmd={'actor_label':'Operator','idempotency_key':'http-confirm','quantity':'2.25','generation_id':gid,'expected_revision':preview['expected_revision']}
        with patch('backend.app.services.transfer_confirmation_service.datetime') as frozen:
            frozen.now.return_value=NOW
            status,result=asyncio.run(request('POST',f"/api/allocation-proposals/{p['id']}/confirm",cmd))
        self.assertEqual(status,201,result);self.assertEqual(result['data']['transfer']['status'],'RESERVED')
        self.assertEqual(result['data']['transfer']['reserved_quantity'],'2.25')
        status,replay=asyncio.run(request('POST',f"/api/allocation-proposals/{p['id']}/confirm",cmd))
        self.assertEqual(status,201,replay);self.assertTrue(replay['data']['replayed'])
    def test_future_opportunity_cannot_reserve_early(self):
        from datetime import timedelta
        from backend.app.services.publication_service import provider_row
        offer=self.data['supply_offers'][0];offer['available_from']=str(NOW.date()+timedelta(days=7))
        self.a.execute('UpsertSupplyOffers',{'rows':[provider_row('supply_offers',offer)]},write=True)
        self.match.refresh();gen=self.match.view()['materials'][0]['generation'];p=gen['alternatives'][0]['proposals'][0]
        preview=prepare_confirmation(self.a,p['id'],'2',gen['generation_id'],lambda:NOW)
        self.assertFalse(preview['confirmable'])
        cmd=TransferConfirmationRequest(actor_label='Operator',idempotency_key='future',quantity='2',generation_id=gen['generation_id'],expected_revision=preview['expected_revision'])
        with self.assertRaises(IngestionError):confirm_transfer(p['id'],cmd,self.a,lambda:NOW)
        self.assertEqual(self.repo.get_supply_offer('SUP-R1')['reserved_active_quantity'],0)
    def test_competing_normal_confirmations_leave_one_hold(self):
        from concurrent.futures import ThreadPoolExecutor
        from terra.local_adapter import LocalDataConnect
        p,gid=self.proposal();preview=prepare_confirmation(self.a,p['id'],'3',gid,lambda:NOW)
        def send(i):
            cmd=TransferConfirmationRequest(actor_label='Operator',idempotency_key=f'parallel-{i}',quantity='3',generation_id=gid,expected_revision=preview['expected_revision'])
            try:return confirm_transfer(p['id'],cmd,LocalDataConnect(),lambda:NOW)
            except IngestionError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(send,(1,2)))
        self.assertEqual(sum(r is not None for r in outcomes),1)
        self.assertEqual(self.repo.get_supply_offer('SUP-R1')['reserved_active_quantity'],3)
        self.assertEqual(self.repo.get_demand_request('DEM-R2')['committed_incoming_quantity'],3)
    def test_stale_impact_result_cannot_overwrite_new_correction(self):
        tid=self.moved();self.workflow(tid,'confirm_use','use','1.25')
        original=ImpactRepository.persist
        def correction_then_persist(repo,basis,command):
            _,revision=current_records(self.a)
            correct_inputs(self.a,InputCorrection(expected_revision=revision,idempotency_key='during-calc',kind='MATERIAL_MASS',material_id='MAT-PIPE',values={'mass_kg_per_unit':'1.8'},basis='Confirmed weight',confirmed=True))
            return original(repo,basis,command)
        with patch.object(ImpactRepository,'persist',correction_then_persist):self.imp.refresh()
        self.assertEqual(self.head(tid)['revision'],0)
        self.assertEqual(self.imp.view()[0]['status'],'PENDING')
        self.imp.refresh();self.assertEqual(self.head(tid)['revision'],1)
    def test_pending_or_failed_estimates_are_not_current_or_exported(self):
        from backend.app.services.impact_service import list_assessments
        from backend.app.services.impact_export_service import export_json
        tid=self.moved();self.workflow(tid,'confirm_use','use1','1');self.imp.refresh()
        self.assertTrue(list_assessments(basis='ACTUAL_CONFIRMED_USE',repository=ImpactRepository(self.a))['data'])
        self.workflow(tid,'confirm_use','use2','1')
        self.assertFalse(list_assessments(basis='ACTUAL_CONFIRMED_USE',repository=ImpactRepository(self.a))['data'])
        self.assertFalse(export_json('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a))['data']['records'])
        self.imp.refresh();self.assertTrue(export_json('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a))['data']['records'])
    def test_reverting_weight_reuses_matching_generation_and_new_impact_revision(self):
        tid=self.moved();self.workflow(tid,'confirm_use','use','1.25');self.imp.refresh();self.match.refresh()
        generations=[]
        for index,mass in enumerate(('1.8','1.2','1.8')):
            _,revision=current_records(self.a)
            correct_inputs(self.a,InputCorrection(expected_revision=revision,idempotency_key=f'revert-{index}',kind='MATERIAL_MASS',material_id='MAT-PIPE',values={'mass_kg_per_unit':mass},basis='Catalogue weight',confirmed=True))
            self.match.refresh();self.imp.refresh();generations.append(self.match.view()['materials'][0]['generation']['generation_id'])
        self.assertEqual(self.head(tid)['revision'],4)
        self.assertEqual(generations[0],generations[2])
        self.assertEqual(self.match.view()['materials'][0]['status'],'CURRENT')
    def test_lost_confirmation_ack_replays_one_reserved_transfer(self):
        from terra.local_adapter import LocalDataConnect,AdapterUnavailableError
        class LostAck(LocalDataConnect):
            def execute(self,operation,*args,**kwargs):
                result=super().execute(operation,*args,**kwargs)
                if operation=='ConfirmTransferReservation':raise AdapterUnavailableError('Acknowledgement lost after commit')
                return result
        p,gid=self.proposal();preview=prepare_confirmation(self.a,p['id'],'2.25',gid,lambda:NOW)
        cmd=TransferConfirmationRequest(actor_label='Operator',idempotency_key='lost-ack',quantity='2.25',generation_id=gid,expected_revision=preview['expected_revision'])
        result=confirm_transfer(p['id'],cmd,LostAck(),lambda:NOW)
        self.assertTrue(result['data']['replayed'])
        self.assertEqual(result['data']['transfer']['reserved_quantity'],Decimal('2.25'))
        self.assertEqual(len(current_records(self.a)[0]['transfers']),1)

    def test_carbon_policy_refresh_replaces_bad_current_estimate_preserves_history(self):
        from backend.app.services.impact_service import list_assessments
        from backend.app.services.impact_export_service import export_json
        from backend.app.services.publication_service import provider_row
        from backend.app.domain.carbon import CALCULATION_POLICY_VERSION
        tid=self.moved();self.workflow(tid,'confirm_use','use','1.25');self.imp.refresh()
        prior_head=self.head(tid)
        old=next(r for r in current_records(self.a)[0]['impact_assessments'] if r['id']==prior_head['current_assessment_id'])
        old['assumptions'].pop('calculation_policy_version',None)
        old['assumptions']['source_input'].pop('calculation_policy_version',None)
        old['assumptions']['factor_snapshots'].append(next(f for f in self.data['emission_factors'] if f['id']=='EF-008'))
        old['factor_ids'].append('EF-008');old['additional_processing_kgco2e']=.078
        old['net_avoided_kgco2e']=2.8752;old['calculation_status']='DEMO'
        self.a.execute('UpsertImpactAssessments',{'rows':[provider_row('impact_assessments',old)]},write=True)
        self.a.execute('SetImpactIntent',{'id':tid,'token':'OLD-POLICY','status':'COMPLETED','payload':{'reason':'Old calculation'}},write=True)
        self.assertFalse(list_assessments(basis='ACTUAL_CONFIRMED_USE',repository=ImpactRepository(self.a))['data'])
        self.assertFalse(export_json('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a))['data']['records'])
        self.imp.refresh();head=self.head(tid)
        self.assertEqual(head['revision'],prior_head['revision']+1)
        rows=current_records(self.a)[0]['impact_assessments']
        self.assertEqual(next(r for r in rows if r['id']==old['id']),old)
        current=next(r for r in rows if r['id']==head['current_assessment_id'])
        self.assertIsNone(current['additional_processing_kgco2e']);self.assertIsNone(current['net_avoided_kgco2e'])
        self.assertEqual(current['assumptions']['calculation_policy_version'],CALCULATION_POLICY_VERSION)
        self.assertEqual(self.repo.get(tid)['actually_used_quantity'],Decimal('1.25'))
        self.imp.refresh();self.assertEqual(self.head(tid)['revision'],head['revision'])

    def test_compatible_mass_handling_factor_restores_complete_revision(self):
        from backend.app.services.publication_service import provider_row
        tid=self.moved();self.workflow(tid,'confirm_use','use','1.25');self.imp.refresh()
        first=self.head(tid)
        factor=__import__('copy').deepcopy(next(f for f in self.data['emission_factors'] if f['id']=='EF-008'))
        factor.update(id='EF-PIPE-HANDLING',material_id='MAT-PIPE',unit='kgCO2e/kg')
        self.a.execute('UpsertEmissionFactors',{'rows':[provider_row('emission_factors',factor)]},write=True)
        # Explicit recalculation intent, without changing or repeating physical use.
        self.a.execute('SetImpactIntent',{'id':tid,'token':'COMPATIBLE-FACTOR','status':'PENDING','payload':{'reason':'Confirmed applicable handling factor'}},write=True)
        self.imp.refresh();head=self.head(tid);self.assertEqual(head['revision'],first['revision']+1)
        assessment=next(r for r in current_records(self.a)[0]['impact_assessments'] if r['id']==head['current_assessment_id'])
        self.assertEqual(assessment['additional_processing_kgco2e'],.078)
        self.assertEqual(assessment['net_avoided_kgco2e'],2.8752)
        self.assertEqual(self.repo.get(tid)['actually_used_quantity'],Decimal('1.25'))
