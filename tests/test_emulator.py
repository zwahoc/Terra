"""Destructive tests on demo-terra-local only. Use a fresh ephemeral emulator."""
import asyncio,copy,os,unittest
from backend.app.repositories.transfer_repository import TransferRepository
from backend.app.repositories.impact_repository import ImpactRepository
from backend.app.services.impact_service import ImpactCalculationInput,calculate_impact,list_assessments
from backend.app.services.impact_export_service import export_json,export_csv
from terra.local_adapter import LocalDataConnect,variables,equivalent,AdapterError
from terra.seeding import seed_local,verify
from terra.validation import load,validate
from terra.contract import FIELDS,TYPES,camel
from tests.test_transfers_api import request

@unittest.skipUnless(os.environ.get('TERRA_RUN_EMULATOR_TESTS')=='1','Use npm run test:integration for isolated local emulator tests')
class EmulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter=LocalDataConnect();cls.seed=load()
        seed_local(cls.seed,cls.adapter,reset_confirmation='demo-terra-local')
    def tearDown(self):seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
    def test_all_named_queries(self):
        for entity in FIELDS:
            result=self.adapter.execute('List'+TYPES[entity]+'s')
            self.assertEqual(len(result[camel(entity)]),len(self.seed[entity]),entity)
        verify(self.adapter,self.seed)
        actual=self.adapter.snapshot();actual['metadata']=self.seed['metadata']
        self.assertEqual(validate(actual)['confirmed_reuse_mass_t'],2.375)
    def test_repeat_import(self):
        self.adapter.execute('ImportBaseline',variables(self.seed),write=True)
        self.adapter.execute('ImportBaseline',variables(self.seed),write=True)
        self.assertEqual(seed_local(self.seed,self.adapter)['action'],'unchanged')
        verify(self.adapter,self.seed)
    def test_reset_same_state(self):
        before=self.adapter.snapshot();seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
        self.assertTrue(equivalent(before,self.adapter.snapshot()))
    def test_python_named_write_read_back(self):
        row=variables(self.seed)['projects'][0].copy();row['name']='Elmina Demo Python read/write proof'
        self.adapter.execute('UpsertProjects',{'rows':[row]},write=True)
        data=self.adapter.execute('ListProjects')['projects']
        self.assertEqual(next(x for x in data if x['id']=='PRJ-001')['name'],row['name'])
    def test_transfer_repository_and_api_reads(self):
        repository=TransferRepository(self.adapter)
        self.assertEqual(repository.list(),self.seed['transfers'])
        self.assertEqual(repository.get('TRF-001'),self.seed['transfers'][0])
        list_status,list_body=asyncio.run(request('GET','/api/transfers'))
        one_status,one_body=asyncio.run(request('GET','/api/transfers/TRF-001'))
        missing_status,missing_body=asyncio.run(request('GET','/api/transfers/TRF-999'))
        self.assertEqual((list_status,list_body['data']),(200,self.seed['transfers']))
        self.assertEqual((one_status,one_body['data']),(200,self.seed['transfers'][0]))
        self.assertEqual(missing_status,404)
        self.assertEqual(missing_body['error']['code'],'TRANSFER_NOT_FOUND')
    def test_transfer_approval_api_is_atomic_idempotent_and_persistent(self):
        repository=TransferRepository(self.adapter)
        transfer_before=repository.get('TRF-001')
        supply_before=self.adapter.execute('ListSupplyOffers')['supplyOffers']
        demand_before=self.adapter.execute('ListDemandRequests')['demandRequests']
        events_before=self.adapter.execute('ListTransferEvents')['transferEvents']
        rollback_variables={
            'transferId':'TRF-001','operationId':'APR-rollback-proof',
            'requestFingerprint':'rollback-proof','eventId':'EVT-001',
            'approvedQuantity':200,'sourceConfirmationStatus':'CONFIRMED',
            'destinationConfirmationStatus':'CONFIRMED','actorLabel':'Demo operator',
            'evidenceRef':'SYNTHETIC rollback proof','eventPayload':{'quantity':200,'synthetic':True},
            'occurredAt':'2026-10-13T10:00:00+08:00'}
        with self.assertRaises(AdapterError):
            self.adapter.execute('ApproveTransfer',rollback_variables,write=True)
        rollback_state=repository.get_approval_state('TRF-001','APR-rollback-proof','EVT-001')
        self.assertEqual(rollback_state.transfer,transfer_before)
        self.assertIsNone(rollback_state.operation)

        base_body={'approved_quantity':200,'source_confirmation_status':'CONFIRMED','destination_confirmation_status':'CONFIRMED','actor_label':'Demo operator','idempotency_key':'integration-approve-trf-001','evidence_ref':'SYNTHETIC integration approval'}
        excessive_status,_=asyncio.run(request('POST','/api/transfers/TRF-001/approve',{**base_body,'approved_quantity':251,'idempotency_key':'integration-excessive'}))
        confirmation_status,_=asyncio.run(request('POST','/api/transfers/TRF-001/approve',{**base_body,'source_confirmation_status':'PENDING','idempotency_key':'integration-confirmation'}))
        unknown_status,_=asyncio.run(request('POST','/api/transfers/TRF-999/approve',{**base_body,'idempotency_key':'integration-unknown'}))
        self.assertEqual((excessive_status,confirmation_status,unknown_status),(400,400,404))

        async def concurrent_approval():
            return await asyncio.gather(
                request('POST','/api/transfers/TRF-001/approve',base_body),
                request('POST','/api/transfers/TRF-001/approve',base_body))
        concurrent_results=asyncio.run(concurrent_approval())
        self.assertEqual([result[0] for result in concurrent_results],[200,200])
        self.assertEqual(sorted(result[1]['data']['replayed'] for result in concurrent_results),[False,True])
        body=next(result[1] for result in concurrent_results if not result[1]['data']['replayed'])
        self.assertEqual(body['data']['transfer']['status'],'APPROVED')
        self.assertEqual(body['data']['transfer']['approved_quantity'],200)
        self.assertEqual(body['data']['event']['event_type'],'APPROVED')
        self.assertFalse(body['data']['replayed'])
        read_status,read_body=asyncio.run(request('GET','/api/transfers/TRF-001'))
        self.assertEqual(read_status,200)
        self.assertEqual(read_body['data'],body['data']['transfer'])

        replay_status,replay_body=asyncio.run(request('POST','/api/transfers/TRF-001/approve',base_body))
        conflict_status,conflict_body=asyncio.run(request('POST','/api/transfers/TRF-001/approve',{**base_body,'approved_quantity':199}))
        invalid_stage_status,_=asyncio.run(request('POST','/api/transfers/TRF-001/approve',{**base_body,'idempotency_key':'integration-new-key'}))
        self.assertEqual(replay_status,200)
        self.assertTrue(replay_body['data']['replayed'])
        self.assertEqual(conflict_status,409)
        self.assertEqual(conflict_body['error']['code'],'IDEMPOTENCY_KEY_REUSED')
        self.assertEqual(invalid_stage_status,409)

        events_after=self.adapter.execute('ListTransferEvents')['transferEvents']
        self.assertEqual(len(events_after),len(events_before)+1)
        self.assertEqual(self.adapter.execute('ListSupplyOffers')['supplyOffers'],supply_before)
        self.assertEqual(self.adapter.execute('ListDemandRequests')['demandRequests'],demand_before)
        persisted=repository.get('TRF-001')
        self.assertEqual(persisted['reserved_quantity'],0)
    def test_transfer_full_workflow_replays_counters_events_and_cancellation(self):
        approval={'approved_quantity':200,'source_confirmation_status':'CONFIRMED','destination_confirmation_status':'CONFIRMED','actor_label':'Demo operator','idempotency_key':'workflow-approve','evidence_ref':'SYNTHETIC workflow approval'}
        status,_=asyncio.run(request('POST','/api/transfers/TRF-001/approve',approval))
        self.assertEqual(status,200)
        steps=[
            ('reserve',{'actor_label':'Demo operator','idempotency_key':'workflow-reserve','evidence_ref':'SYNTHETIC reserve'},'RESERVED'),
            ('dispatch',{'actor_label':'Demo operator','idempotency_key':'workflow-dispatch','evidence_ref':'SYNTHETIC dispatch'},'IN_TRANSIT'),
            ('receive',{'actor_label':'Demo operator','idempotency_key':'workflow-receive','evidence_ref':'SYNTHETIC receipt'},'RECEIVED'),
            ('confirm-use',{'quantity':200,'actor_label':'Demo operator','idempotency_key':'workflow-use','evidence_ref':'SYNTHETIC use'},'REUSED')]
        for action,body,expected in steps:
            status,response=asyncio.run(request('POST',f'/api/transfers/TRF-001/{action}',body))
            self.assertEqual(status,200,response)
            self.assertEqual(response['data']['transfer']['status'],expected)
            self.assertFalse(response['data']['replayed'])
            replay_status,replay=asyncio.run(request('POST',f'/api/transfers/TRF-001/{action}',body))
            self.assertEqual(replay_status,200,replay)
            self.assertTrue(replay['data']['replayed'])
            changed=dict(body);changed['actor_label']='Changed operator'
            conflict_status,conflict=asyncio.run(request('POST',f'/api/transfers/TRF-001/{action}',changed))
            self.assertEqual(conflict_status,409,conflict)
            self.assertEqual(conflict['error']['code'],'IDEMPOTENCY_KEY_REUSED')
        transfer=TransferRepository(self.adapter).get('TRF-001')
        supply=TransferRepository(self.adapter).get_supply_offer('SUP-011')
        demand=TransferRepository(self.adapter).get_demand_request('DEM-010')
        event_status,event_body=asyncio.run(request('GET','/api/transfers/TRF-001/events'))
        self.assertEqual((transfer['reserved_quantity'],transfer['dispatched_quantity'],transfer['received_quantity'],transfer['actually_used_quantity']),(0,200,200,200))
        self.assertEqual((supply['reserved_active_quantity'],supply['transferred_out_quantity']),(0,200))
        self.assertEqual((demand['fulfilled_quantity'],demand['committed_incoming_quantity'],demand['uncommitted_quantity']),(200,0,50))
        self.assertEqual(event_status,200)
        self.assertEqual([e['event_type'] for e in event_body['data']],['REQUESTED','APPROVED','RESERVED','DISPATCHED','RECEIVED','USED'])
        transfer_status,transfer_body=asyncio.run(request('GET','/api/transfers/TRF-001'))
        supply_status,supply_body=asyncio.run(request('GET','/api/supply-offers/SUP-011'))
        demand_status,demand_body=asyncio.run(request('GET','/api/demand-requests/DEM-010'))
        self.assertEqual((transfer_status,supply_status,demand_status),(200,200,200))
        self.assertEqual(transfer_body['data']['status'],'REUSED')
        self.assertEqual(supply_body['data']['transferred_out_quantity'],200)
        self.assertEqual(demand_body['data']['fulfilled_quantity'],200)

        seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
        approval['idempotency_key']='cancel-approve'
        asyncio.run(request('POST','/api/transfers/TRF-001/approve',approval))
        reserve={'actor_label':'Demo operator','idempotency_key':'cancel-reserve','evidence_ref':'SYNTHETIC reserve'}
        asyncio.run(request('POST','/api/transfers/TRF-001/reserve',reserve))
        cancel={'reason':'Synthetic local cancellation test','actor_label':'Demo operator','idempotency_key':'cancel-operation','evidence_ref':'SYNTHETIC cancellation'}
        cancel_status,cancel_body=asyncio.run(request('POST','/api/transfers/TRF-001/cancel',cancel))
        self.assertEqual(cancel_status,200,cancel_body)
        self.assertEqual(cancel_body['data']['transfer']['status'],'CANCELLED')
        self.assertEqual(cancel_body['data']['supply_offer']['reserved_active_quantity'],0)
        self.assertEqual(cancel_body['data']['demand_request']['committed_incoming_quantity'],0)
        replay_status,replay=asyncio.run(request('POST','/api/transfers/TRF-001/cancel',cancel))
        self.assertEqual(replay_status,200);self.assertTrue(replay['data']['replayed'])
        changed_status,changed=asyncio.run(request('POST','/api/transfers/TRF-001/cancel',{**cancel,'reason':'Changed reason'}))
        self.assertEqual(changed_status,409)
        self.assertEqual(changed['error']['code'],'IDEMPOTENCY_KEY_REUSED')

    def test_partial_workflow_preserves_residual_commitments_and_rejects_cancel(self):
        approval={'approved_quantity':200,'source_confirmation_status':'CONFIRMED','destination_confirmation_status':'CONFIRMED','actor_label':'Demo operator','idempotency_key':'partial-approve'}
        asyncio.run(request('POST','/api/transfers/TRF-001/approve',approval))
        asyncio.run(request('POST','/api/transfers/TRF-001/reserve',{'actor_label':'Demo operator','idempotency_key':'partial-reserve'}))
        dispatch_status,dispatch=asyncio.run(request('POST','/api/transfers/TRF-001/dispatch',{'actor_label':'Demo operator','idempotency_key':'partial-dispatch'}))
        self.assertEqual(dispatch_status,200,dispatch)
        self.assertEqual(dispatch['data']['event']['payload']['quantity'],200)
        cancel_status,_=asyncio.run(request('POST','/api/transfers/TRF-001/cancel',{'reason':'too late','actor_label':'Demo operator','idempotency_key':'partial-cancel'}))
        self.assertEqual(cancel_status,409)
        receive_status,receive=asyncio.run(request('POST','/api/transfers/TRF-001/receive',{'actor_label':'Demo operator','idempotency_key':'partial-receive'}))
        self.assertEqual(receive_status,200,receive)
        self.assertEqual(receive['data']['transfer']['received_quantity'],200)
        use_status,use=asyncio.run(request('POST','/api/transfers/TRF-001/confirm-use',{'quantity':120,'actor_label':'Demo operator','idempotency_key':'partial-use'}))
        self.assertEqual(use_status,200,use)
        self.assertEqual(use['data']['transfer']['reserved_quantity'],0)
        self.assertEqual(use['data']['transfer']['dispatched_quantity'],200)
        self.assertEqual(use['data']['supply_offer']['reserved_active_quantity'],0)
        self.assertEqual(use['data']['supply_offer']['transferred_out_quantity'],200)
        self.assertEqual(use['data']['demand_request']['fulfilled_quantity'],120)
        self.assertEqual(use['data']['demand_request']['committed_incoming_quantity'],80)
        self.assertIn('disposition pending',use['data']['transfer']['notes'])
        repeated_status,repeated=asyncio.run(request('POST','/api/transfers/TRF-001/confirm-use',{'quantity':50,'actor_label':'Demo operator','idempotency_key':'partial-use-again'}))
        self.assertEqual(repeated_status,200,repeated)
        self.assertEqual(repeated['data']['transfer']['actually_used_quantity'],170)
        self.assertEqual(repeated['data']['event']['payload']['quantity'],50)
        self.assertEqual(repeated['data']['event']['payload']['cumulative_used_quantity'],170)
        self.assertEqual(repeated['data']['demand_request']['fulfilled_quantity'],170)
        self.assertEqual(repeated['data']['demand_request']['committed_incoming_quantity'],30)
        self.assertEqual([e['event_type'] for e in TransferRepository(self.adapter).list_events('TRF-001')].count('USED'),2)

    def test_impact_calculation_revision_retry_stale_guard_and_export(self):
        repository=ImpactRepository(self.adapter)
        body=ImpactCalculationInput('impact-integration-forecast','Seed arithmetic regression','Demo operator')
        forecast=calculate_impact('PROPOSAL_FORECAST','ALC-001',body,repository)
        assessment=forecast['data']['assessment']
        self.assertEqual((assessment['avoided_production_kgco2e'],assessment['additional_transport_kgco2e'],assessment['additional_processing_kgco2e'],assessment['net_avoided_kgco2e']),(450.0,4.5,12.0,433.5))
        replay=calculate_impact('PROPOSAL_FORECAST','ALC-001',body,repository)
        self.assertTrue(replay['data']['replayed'])
        self.assertEqual(replay['data']['assessment']['id'],assessment['id'])

        second=calculate_impact('PROPOSAL_FORECAST','ALC-001',ImpactCalculationInput('impact-integration-forecast-2','Second reviewed revision','Demo operator'),repository)
        self.assertEqual(second['data']['assessment']['assumptions']['revision']['number'],3)
        self.assertEqual(second['data']['assessment']['assumptions']['revision']['previous_assessment_id'],assessment['id'])
        current=list_assessments(basis='PROPOSAL_FORECAST',repository=repository)['data']
        current_alc=[row for row in current if row['proposal_id']=='ALC-001']
        self.assertEqual([row['id'] for row in current_alc],[second['data']['assessment']['id']])

        actual=calculate_impact('ACTUAL_CONFIRMED_USE','TRF-007',ImpactCalculationInput('impact-integration-actual','Actual use recalculation','Demo operator'),repository)
        self.assertEqual(actual['data']['assessment']['quantity_assessed'],400)
        self.assertEqual(actual['data']['assessment']['net_avoided_kgco2e'],291.04)
        json_export=export_json('ACTUAL_CONFIRMED_USE',repository)
        exported=next(row for row in json_export['data']['records'] if row['transfer_id']=='TRF-007')
        self.assertEqual(exported['assessment_id'],actual['data']['assessment']['id'])
        self.assertEqual(exported['components_kgco2e']['net_avoided'],291.04)
        self.assertIn('factor_snapshots',exported['assumptions'])
        self.assertIn('TRF-007',export_csv('ACTUAL_CONFIRMED_USE',repository))

        head=next(row for row in repository.list_heads() if row['id']=='ACTUAL_CONFIRMED_USE:TRF-007')
        stale_assessment={**actual['data']['assessment'],'id':'IMP-STALE-PROOF','calculated_at':'2026-10-14T15:00:00+08:00'}
        stale_variables={
            'scopeId':head['id'],'operationId':'ICO-STALE-PROOF','requestFingerprint':'stale',
            'assessmentId':stale_assessment['id'],'expectedRevision':head['revision'],
            'newRevision':head['revision']+1,'inputFingerprint':'stale-input',
            'calculatedAt':stale_assessment['calculated_at'],'assessment':{
                'id':stale_assessment['id'],'basis':stale_assessment['basis'],
                'proposalId':None,'transferId':'TRF-007','quantityAssessed':400,'unit':'pcs',
                'baselineDescription':stale_assessment['baseline_description'],
                'avoidedProductionKgco2E':300.0,'additionalTransportKgco2E':0.96,
                'additionalProcessingKgco2E':8.0,'netAvoidedKgco2E':291.04,
                'factorIds':['EF-001','EF-007','EF-008'],'assumptions':{'stale':True},
                'calculationStatus':'DEMO','calculatedAt':stale_assessment['calculated_at']},
            'transferId':'TRF-007','expectedUsedQuantity':399,
            'expectedDispatchedQuantity':400,'expectedReceivedQuantity':400,
            'expectedReuseConfirmedAt':'2026-10-08T09:00:00+08:00'}
        with self.assertRaises(AdapterError):
            self.adapter.execute('PersistActualImpactAssessment',stale_variables,write=True)
        unchanged=next(row for row in repository.list_heads() if row['id']==head['id'])
        self.assertEqual(unchanged['current_assessment_id'],head['current_assessment_id'])
    def test_full_dispatch_and_receipt_are_atomic_under_concurrency(self):
        approval={'approved_quantity':100,'source_confirmation_status':'CONFIRMED','destination_confirmation_status':'CONFIRMED','actor_label':'Demo operator','idempotency_key':'dispatch-approve'}
        asyncio.run(request('POST','/api/transfers/TRF-001/approve',approval))
        asyncio.run(request('POST','/api/transfers/TRF-001/reserve',{'actor_label':'Demo operator','idempotency_key':'dispatch-reserve'}))
        repository=TransferRepository(self.adapter)
        before_transfer=repository.get('TRF-001')
        before_supply=repository.get_supply_offer('SUP-011')
        before_events=repository.list_events('TRF-001')
        rollback={
            'transferId':'TRF-001','operationId':'WFO-dispatch-rollback',
            'requestFingerprint':'dispatch-rollback','eventId':'EVT-001',
            'quantity':100,'actorLabel':'Demo operator','evidenceRef':None,
            'eventPayload':{'quantity':100,'synthetic':True},
            'occurredAt':'2026-10-13T10:00:00+08:00','operationDate':'2026-10-13',
            'supplyOfferId':'SUP-011','demandRequestId':'DEM-010'}
        with self.assertRaises(AdapterError):
            self.adapter.execute('DispatchTransfer',rollback,write=True)
        self.assertEqual(repository.get('TRF-001'),before_transfer)
        self.assertEqual(repository.get_supply_offer('SUP-011'),before_supply)
        self.assertEqual(repository.list_events('TRF-001'),before_events)
        self.assertIsNone(repository.get_workflow_state(
            'TRF-001','WFO-dispatch-rollback','EVT-001').operation)

        bodies=[
            {'actor_label':'Demo operator','idempotency_key':'dispatch-race-a'},
            {'actor_label':'Demo operator','idempotency_key':'dispatch-race-b'}]
        async def race():
            return await asyncio.gather(*[
                request('POST','/api/transfers/TRF-001/dispatch',body)
                for body in bodies])
        results=asyncio.run(race())
        self.assertEqual(sorted(result[0] for result in results),[200,409])
        success=next(result[1] for result in results if result[0]==200)
        self.assertEqual(success['data']['transfer']['reserved_quantity'],0)
        self.assertEqual(success['data']['transfer']['dispatched_quantity'],100)
        self.assertEqual(success['data']['supply_offer']['reserved_active_quantity'],0)
        self.assertEqual(success['data']['supply_offer']['transferred_out_quantity'],100)
        self.assertEqual(success['data']['event']['payload']['quantity'],100)
        self.assertEqual(success['data']['demand_request']['committed_incoming_quantity'],100)
        winning=next(body for body in bodies
                     if body['idempotency_key']==success['data']['idempotency_key'])
        replay_status,replay=asyncio.run(request(
            'POST','/api/transfers/TRF-001/dispatch',winning))
        self.assertEqual(replay_status,200,replay)
        self.assertTrue(replay['data']['replayed'])
        second_status,_=asyncio.run(request(
            'POST','/api/transfers/TRF-001/dispatch',
            {'actor_label':'Demo operator','idempotency_key':'dispatch-after-complete'}))
        self.assertEqual(second_status,409)
        self.assertEqual(
            [e['event_type'] for e in repository.list_events('TRF-001')].count('DISPATCHED'),1)

        receipt_transfer=repository.get('TRF-001')
        receipt_supply=repository.get_supply_offer('SUP-011')
        receipt_demand=repository.get_demand_request('DEM-010')
        receipt_events=repository.list_events('TRF-001')
        receipt_rollback={
            'transferId':'TRF-001','operationId':'WFO-receipt-rollback',
            'requestFingerprint':'receipt-rollback','eventId':'EVT-001',
            'quantity':100,'actorLabel':'Demo operator','evidenceRef':None,
            'eventPayload':{'quantity':100,'synthetic':True},
            'occurredAt':'2026-10-13T11:00:00+08:00','operationDate':'2026-10-13',
            'supplyOfferId':'SUP-011','demandRequestId':'DEM-010'}
        with self.assertRaises(AdapterError):
            self.adapter.execute('ReceiveTransfer',receipt_rollback,write=True)
        self.assertEqual(repository.get('TRF-001'),receipt_transfer)
        self.assertEqual(repository.get_supply_offer('SUP-011'),receipt_supply)
        self.assertEqual(repository.get_demand_request('DEM-010'),receipt_demand)
        self.assertEqual(repository.list_events('TRF-001'),receipt_events)
        self.assertIsNone(repository.get_workflow_state(
            'TRF-001','WFO-receipt-rollback','EVT-001').operation)

        receipt_bodies=[
            {'actor_label':'Demo operator','idempotency_key':'receipt-race-a'},
            {'actor_label':'Demo operator','idempotency_key':'receipt-race-b'}]
        async def receipt_race():
            return await asyncio.gather(*[
                request('POST','/api/transfers/TRF-001/receive',body)
                for body in receipt_bodies])
        receipt_results=asyncio.run(receipt_race())
        self.assertEqual(sorted(result[0] for result in receipt_results),[200,409])
        receipt_success=next(result[1] for result in receipt_results if result[0]==200)
        self.assertEqual(receipt_success['data']['transfer']['status'],'RECEIVED')
        self.assertEqual(receipt_success['data']['transfer']['received_quantity'],100)
        self.assertEqual(receipt_success['data']['transfer']['actually_used_quantity'],0)
        self.assertIsNotNone(receipt_success['data']['transfer']['delivered_at'])
        self.assertEqual(receipt_success['data']['event']['payload']['quantity'],100)
        self.assertEqual(receipt_success['data']['supply_offer'],receipt_supply)
        self.assertEqual(receipt_success['data']['demand_request'],receipt_demand)
        receipt_winner=next(body for body in receipt_bodies
            if body['idempotency_key']==receipt_success['data']['idempotency_key'])
        receipt_replay_status,receipt_replay=asyncio.run(request(
            'POST','/api/transfers/TRF-001/receive',receipt_winner))
        self.assertEqual(receipt_replay_status,200,receipt_replay)
        self.assertTrue(receipt_replay['data']['replayed'])
        receipt_second_status,_=asyncio.run(request(
            'POST','/api/transfers/TRF-001/receive',
            {'actor_label':'Demo operator','idempotency_key':'receipt-after-complete'}))
        self.assertEqual(receipt_second_status,409)
        self.assertEqual(
            [e['event_type'] for e in repository.list_events('TRF-001')].count('RECEIVED'),1)
    def test_reservation_rejects_stock_demand_and_competing_requests_atomically(self):
        approval={'approved_quantity':200,'source_confirmation_status':'CONFIRMED','destination_confirmation_status':'CONFIRMED','actor_label':'Demo operator','idempotency_key':'capacity-approve'}
        asyncio.run(request('POST','/api/transfers/TRF-001/approve',approval))
        supply=variables(self.seed)['supplyOffers'][10].copy();supply['confirmedQuantity']=100
        self.adapter.execute('UpsertSupplyOffers',{'rows':[supply]},write=True)
        stock_status,stock=asyncio.run(request('POST','/api/transfers/TRF-001/reserve',{'actor_label':'Demo operator','idempotency_key':'stock-failure'}))
        self.assertEqual(stock_status,409,stock)
        self.assertEqual(stock['error']['code'],'SOURCE_STOCK_UNAVAILABLE')
        self.assertEqual(TransferRepository(self.adapter).get('TRF-001')['status'],'APPROVED')

        seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
        approval['idempotency_key']='demand-approve'
        asyncio.run(request('POST','/api/transfers/TRF-001/approve',approval))
        demand=variables(self.seed)['demandRequests'][9].copy();demand['requiredQuantity']=100
        self.adapter.execute('UpsertDemandRequests',{'rows':[demand]},write=True)
        demand_status,demand_body=asyncio.run(request('POST','/api/transfers/TRF-001/reserve',{'actor_label':'Demo operator','idempotency_key':'demand-failure'}))
        self.assertEqual(demand_status,409,demand_body)
        self.assertEqual(demand_body['error']['code'],'DEMAND_UNAVAILABLE')

        seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
        proposal=variables(self.seed)['allocationProposals'][6].copy()
        proposal['id']='ALC-LOCAL-COMPETE';proposal['proposedQuantity']=150
        transfer=variables(self.seed)['transfers'][0].copy()
        transfer['id']='TRF-LOCAL-COMPETE';transfer['proposalId']=proposal['id']
        event=variables(self.seed)['transferEvents'][0].copy()
        event['id']='EVT-LOCAL-COMPETE';event['transferId']=transfer['id']
        self.adapter.execute('UpsertAllocationProposals',{'rows':[proposal]},write=True)
        self.adapter.execute('UpsertTransfers',{'rows':[transfer]},write=True)
        self.adapter.execute('UpsertTransferEvents',{'rows':[event]},write=True)
        first={**approval,'approved_quantity':150,'idempotency_key':'compete-approve-one'}
        second={**approval,'approved_quantity':150,'idempotency_key':'compete-approve-two'}
        asyncio.run(request('POST','/api/transfers/TRF-001/approve',first))
        asyncio.run(request('POST','/api/transfers/TRF-LOCAL-COMPETE/approve',second))
        async def compete():
            return await asyncio.gather(
                request('POST','/api/transfers/TRF-001/reserve',{'actor_label':'Demo operator','idempotency_key':'compete-reserve-one'}),
                request('POST','/api/transfers/TRF-LOCAL-COMPETE/reserve',{'actor_label':'Demo operator','idempotency_key':'compete-reserve-two'}))
        results=asyncio.run(compete())
        self.assertEqual(sorted(result[0] for result in results),[200,409])
        repository=TransferRepository(self.adapter)
        self.assertEqual(repository.get_supply_offer('SUP-011')['reserved_active_quantity'],150)
        self.assertEqual(repository.get_demand_request('DEM-010')['committed_incoming_quantity'],150)
        statuses=[repository.get('TRF-001')['status'],repository.get('TRF-LOCAL-COMPETE')['status']]
        self.assertEqual(sorted(statuses),['APPROVED','RESERVED'])
        total_events=sum(len(repository.list_events(tid)) for tid in ['TRF-001','TRF-LOCAL-COMPETE'])
        self.assertEqual(total_events,5) # two REQUESTED, two APPROVED, one RESERVED
    def test_runtime_changes_refused(self):
        row=variables(self.seed)['projects'][0].copy();row['name']='Demo runtime edit'
        self.adapter.execute('UpsertProjects',{'rows':[row]},write=True)
        with self.assertRaisesRegex(ValueError,'Refusing overwrite'):seed_local(self.seed,self.adapter)
        self.assertEqual(self.adapter.snapshot()['projects'][0]['name'],row['name'])
    def test_ordinary_query_and_write_denied(self):
        with self.assertRaisesRegex(AdapterError,'403'):self.adapter.execute('SeedSnapshot',admin=False)
        with self.assertRaisesRegex(AdapterError,'403'):self.adapter.execute('UpsertProjects',{'rows':variables(self.seed)['projects']},write=True,admin=False)
    def test_atomic_import_rollback(self):
        before=self.adapter.snapshot();bad=variables(self.seed)
        bad['projects'][0]['name']='Demo mutation that must rollback'
        bad['impactAssessments'][-1]['proposalId']='ALC-999'
        with self.assertRaises(AdapterError):self.adapter.execute('ImportBaseline',bad,write=True)
        self.assertTrue(equivalent(before,self.adapter.snapshot()))
    def test_primary_key_upsert(self):
        rows=variables(self.seed)['materials']
        self.adapter.execute('UpsertMaterials',{'rows':rows},write=True)
        self.adapter.execute('UpsertMaterials',{'rows':rows},write=True)
        self.assertEqual(len(self.adapter.execute('ListMaterials')['materials']),20)
    def test_invalid_fk(self):
        bad=variables(self.seed)['supplyOffers'][0].copy();bad['materialId']='MAT-999'
        with self.assertRaises(AdapterError):self.adapter.execute('UpsertSupplyOffers',{'rows':[bad]},write=True)
        verify(self.adapter,self.seed)
    def test_invalid_enum(self):
        bad=variables(self.seed)['transfers'][0].copy();bad['status']='DONE'
        with self.assertRaises(AdapterError):self.adapter.execute('UpsertTransfers',{'rows':[bad]},write=True)
        verify(self.adapter,self.seed)

if __name__=='__main__':unittest.main()
