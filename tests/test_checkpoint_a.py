"""Checkpoint A: exact quantities, fair alternatives and real local transactions."""
import copy
import os
import unittest
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from terra.contract import FIELDS
from terra.validation import load
from terra.quantities import amount,wire,unit
from backend.app.services.optimisation_preview_service import preview_comparison

DAY=date(2026,10,22)
NOW=datetime(2026,10,22,10,tzinfo=timezone(timedelta(hours=8)))

def runtime_records():
    seed=load(); data={e:[] for e in FIELDS}
    for index,name in enumerate(('Lakeview Gardens','Cedar Grove Community Park','Meridian Courtyard'),1):
        p=copy.deepcopy(seed['projects'][index-1]);p.update(id=f'PRJ-R{index}',code=f'P-R{index}',name=name,managing_organisation='Crestfield Development',township=f'Area {index}')
        data['projects'].append(p)
    material=copy.deepcopy(seed['materials'][0]);material.update(id='MAT-PIPE',category='PIPE',canonical_name='uPVC drainage pipe 110 mm SN4',standard_unit='m',mass_kg_per_unit=1.2,
        specifications={'material_type':'uPVC','nominal_diameter_mm':110,'stiffness_class':'SN4'})
    data['materials']=[material]
    offer=copy.deepcopy(seed['supply_offers'][0]);offer.update(id='SUP-R1',source_project_id='PRJ-R1',material_id='MAT-PIPE',origin_document_row_id=None,
        declared_quantity=Decimal('12.75'),confirmed_quantity=Decimal('12.75'),reserved_active_quantity=0,transferred_out_quantity=0,unit='m',surplus_status='CONFIRMED',condition='UNUSED',
        available_from=str(DAY),available_until=str(DAY+timedelta(days=30)),evidence_refs=['Release register LG-22'],batch_or_lot_code='LOT-P110')
    data['supply_offers']=[offer]
    for i,q in ((2,'4.25'),(3,'10')):
        demand=copy.deepcopy(seed['demand_requests'][0]);demand.update(id=f'DEM-R{i}',destination_project_id=f'PRJ-R{i}',material_id='MAT-PIPE',origin_document_row_id=None,
            required_quantity=Decimal(q),fulfilled_quantity=0,unit='m',request_status='OPEN',is_outstanding_need_confirmed=True,
            needed_from=str(DAY),required_by=str(DAY+timedelta(days=5 if i==2 else 10)))
        data['demand_requests'].append(demand)
        route=copy.deepcopy(seed['route_distances'][0]);route.update(id=f'RTE-R{i}',from_project_id='PRJ-R1',to_project_id=f'PRJ-R{i}',distance_km=100 if i==2 else 5)
        data['route_distances'].append(route)
    data['emission_factors']=[copy.deepcopy(f) for f in seed['emission_factors'] if f['material_id'] is None and f['material_category'] is None]
    production=copy.deepcopy(seed['emission_factors'][0]);production.update(id='EF-PIPE',material_id='MAT-PIPE',material_category=None,unit='kgCO2e/kg',value=2)
    data['emission_factors'].append(production)
    return data

def legacy_requested_for_transaction_proof(adapter,proposal_id,key):
    """Administrative fixture only; normal current proposals use combined confirmation."""
    from backend.app.repositories.transfer_repository import TransferRepository
    from backend.app.services.transfer_request_service import _identity
    repo=TransferRepository(adapter);oid,tid,eid=_identity(key)
    proposal=next(p for p in adapter.snapshot()['allocation_proposals'] if p['id']==proposal_id)
    repo.create_request({'proposal_id':proposal_id,'operation_id':oid,'request_fingerprint':key,
        'transfer_id':tid,'event_id':eid,'actor_label':'Operator','evidence_ref':None,'notes':None,
        'approved_quantity':proposal['proposed_quantity'],'occurred_at':NOW.isoformat(),
        'event_payload':{'proposal_id':proposal_id,'quantity':str(proposal['proposed_quantity'])}})
    return {'data':{'transfer':repo.get(tid)}}

class QuantityDomainTests(unittest.TestCase):
    def test_exact_wire_and_preserved_json_evidence(self):
        value={'quantity':'250.500001','payload':{'quantity':'250.500001'},'revision':4}
        encoded=wire(value,encode=True)
        self.assertEqual(encoded['quantity'],'250500001')
        self.assertEqual(encoded['payload'],value['payload'])
        self.assertEqual(wire(encoded,encode=False)['quantity'],Decimal('250.500001'))
        self.assertEqual(unit('m³'),'m3')
        for bad in ('0.0000001','9223372036854.775808','-1','NaN',True,float('inf')):
            with self.assertRaises(ValueError):amount(bad)
        with self.assertRaises(ValueError):amount('1.5',unit_name='pcs')
        from backend.app.services.review_calculations import group_id,preview_groups
        self.assertEqual(group_id('P','M','m³'),group_id('P','M','m3'))
        inputs=[{'id':str(i),'project':'P','material':'M','unit':u,'quantity':'1.25','kind':'ON_HAND_INVENTORY'} for i,u in enumerate(('m³','m3'))]
        groups=preview_groups(inputs,{},[group_id('P','M','m3')])
        self.assertEqual(len(groups),1);self.assertEqual(Decimal(groups[0]['on_hand_observations']),Decimal('2.5'))
        from backend.app.services.analysis_tools import model_business_context
        from backend.app.schemas.analysis import ToolObservation
        observed=model_business_context({'quantity':Decimal('12.750001'),'is_synthetic':True})
        self.assertEqual(observed,{'quantity':'12.750001'})
        self.assertEqual(ToolObservation(tool='get_project_context',arguments={},result=observed,observed_at=NOW).result,observed)

    def test_fractional_three_way_plans_are_exact_and_nonmutating(self):
        data=runtime_records();before=copy.deepcopy(data)
        result=preview_comparison(data,planning_date=DAY,factor_dataset_version='demo-v1')
        self.assertEqual([a['plan']['objective'] for a in result['alternatives']],['MAX_REUSE','EARLIEST_DEADLINE','MAX_NET_CO2E_AVOIDED'])
        for alternative in result['alternatives']:
            quantities=[Decimal(str(a['proposed_quantity'])) for a in alternative['plan']['allocations']]
            self.assertLessEqual(sum(quantities),Decimal('12.75'))
            self.assertTrue(all(a['unit']=='m' for a in alternative['plan']['allocations']))
        self.assertEqual(data,before)

    def test_different_catalogue_pipe_or_unreleased_supply_is_not_allocated(self):
        data=runtime_records()
        other=copy.deepcopy(data['materials'][0]);other.update(id='MAT-PIPE-OTHER',specifications={**other['specifications'],'nominal_diameter_mm':160})
        data['materials'].append(other)
        for demand in data['demand_requests']:demand['material_id']=other['id']
        result=preview_comparison(data,planning_date=DAY,factor_dataset_version='demo-v1')
        self.assertTrue(all(not a['plan']['allocations'] for a in result['alternatives']))
        data=runtime_records();data['supply_offers'][0].update(surplus_status='POTENTIAL',confirmed_quantity=None)
        self.assertTrue(all(not a['plan']['allocations'] for a in preview_comparison(data,planning_date=DAY,factor_dataset_version='demo-v1')['alternatives']))

    def test_future_release_is_visible_with_later_start(self):
        data=runtime_records();data['supply_offers'][0]['available_from']=str(DAY+timedelta(days=7))
        result=preview_comparison(data,planning_date=DAY,factor_dataset_version='demo-v1')
        allocations=result['alternatives'][0]['plan']['allocations']
        self.assertTrue(allocations)
        self.assertTrue(all(a['earliest_dispatch_date']==str(DAY+timedelta(days=7)) for a in allocations))
        self.assertTrue(all(a['demand_request_id']=='DEM-R3' for a in allocations))

@unittest.skipUnless(os.environ.get('TERRA_RUN_CHECKPOINT_A_TESTS')=='1','Requires explicit isolated checkpoint A emulator')
class CheckpointAEmulatorTests(unittest.TestCase):
    def setUp(self):
        from terra.local_adapter import LocalDataConnect,variables
        self.a=LocalDataConnect()
        self.assertIn('127.0.0.1:9499',self.a.base,'Never reset the owner database in this suite')
        self.a.execute('ClearBaseline',write=True)
        if not self.a.execute('GetQuantityEncoding')['quantityEncoding']:self.a.execute('InitializeExactQuantities',write=True)
        self.data=runtime_records();self.a.execute('ImportBaseline',variables(self.data),write=True)

    def test_saved_generation_refresh_and_stale_refusal(self):
        from backend.app.services.matching_service import MatchingService
        from backend.app.repositories.optimisation_repository import OptimisationRepository
        from backend.app.services.ingestion_errors import IngestionError
        s=MatchingService(self.a,lambda:NOW);s.refresh();view=s.view()
        row=view['materials'][0];self.assertEqual(row['status'],'CURRENT')
        gid=row['generation']['generation_id'];self.assertEqual(len(row['generation']['alternatives']),3)
        pid=row['generation']['alternatives'][0]['proposal_ids'][0]
        run=row['generation']['alternatives'][0]['run_id']
        proposal=next(p for p in OptimisationRepository(self.a).get(run).proposals if p['id']==pid)
        s.require_current(proposal)
        s.refresh();self.assertEqual(s.view()['materials'][0]['generation']['generation_id'],gid)
        offer=self.a.snapshot()['supply_offers'][0];offer['confirmed_quantity']=Decimal('10.25');offer['declared_quantity']=Decimal('10.25')
        from backend.app.services.publication_service import provider_row
        self.a.execute('UpsertSupplyOffers',{'rows':[provider_row('supply_offers',offer)]},write=True)
        with self.assertRaises(IngestionError):s.require_current(proposal)
        self.assertEqual(s.view()['materials'][0]['status'],'PENDING')
        s.refresh();self.assertNotEqual(s.view()['materials'][0]['generation']['generation_id'],gid)

    def test_fractional_reservation_exact_rollback_and_replay(self):
        from backend.app.services.matching_service import MatchingService
        from backend.app.services.transfer_request_service import create_transfer_request,TransferRequestInput
        from backend.app.repositories.transfer_repository import TransferRepository
        from terra.local_adapter import AdapterError
        s=MatchingService(self.a,lambda:NOW);s.refresh();alt=s.view()['materials'][0]['generation']['alternatives'][0]
        # Use the existing request path only to prove the provider arithmetic.
        # Combined confirmation is now exercised separately in Checkpoint B.
        from unittest.mock import patch
        with patch.object(MatchingService,'require_current'):
            result=legacy_requested_for_transaction_proof(self.a,alt['proposal_ids'][0],'proof-request')
        transfer=result['data']['transfer'];proposal=next(p for p in self.a.snapshot()['allocation_proposals'] if p['id']==transfer['proposal_id'])
        values={'transferId':transfer['id'],'operationId':'PROOF-RES','requestFingerprint':'proof','eventId':'PROOF-EVT','quantity':Decimal('4.25'),
                'actorLabel':'Operator','evidenceRef':'LG release','eventPayload':{'quantity':'4.25'},'occurredAt':NOW.isoformat(),'operationDate':str(DAY),
                'supplyOfferId':proposal['supply_offer_id'],'demandRequestId':proposal['demand_request_id']}
        before=self.a.snapshot()
        wrong={**values,'quantity':Decimal('99.5')}
        with self.assertRaises(AdapterError):self.a.execute('ReserveTransfer',wrong,write=True)
        self.assertEqual(self.a.snapshot(),before)
        self.a.execute('ReserveTransfer',values,write=True)
        after=self.a.snapshot();self.assertEqual(after['supply_offers'][0]['reserved_active_quantity'],Decimal('4.25'))
        with self.assertRaises(AdapterError):self.a.execute('ReserveTransfer',values,write=True)
        self.assertEqual(self.a.snapshot(),after)

    def test_competing_fractional_reservations_never_overdraw(self):
        from concurrent.futures import ThreadPoolExecutor
        from backend.app.services.matching_service import MatchingService
        from backend.app.services.transfer_request_service import create_transfer_request,TransferRequestInput
        from backend.app.repositories.transfer_repository import TransferRepository
        from backend.app.services.publication_service import provider_row
        from terra.local_adapter import AdapterError
        from unittest.mock import patch
        s=MatchingService(self.a,lambda:NOW);s.refresh()
        alt=s.view()['materials'][0]['generation']['alternatives'][0]
        original=next(p for p in self.a.snapshot()['allocation_proposals'] if p['id'] in alt['proposal_ids'])
        proposals=[{**original,'id':f'ALC-COMPETE-{i}','proposed_quantity':Decimal('10.25'),'demand_request_id':'DEM-R3'} for i in (1,2)]
        self.a.execute('UpsertAllocationProposals',{'rows':[provider_row('allocation_proposals',p) for p in proposals]},write=True)
        transfers=[]
        with patch.object(MatchingService,'require_current'):
            for i,p in enumerate(proposals):
                transfers.append(legacy_requested_for_transaction_proof(self.a,p['id'],f'compete-{i}')['data']['transfer'])
        def reserve(i):
            from terra.local_adapter import LocalDataConnect
            try:
                LocalDataConnect().execute('ReserveTransfer',{'transferId':transfers[i]['id'],'operationId':f'WFO-COMPETE-{i}',
                    'requestFingerprint':f'compete-{i}','eventId':f'EVT-COMPETE-{i}','quantity':Decimal('10.25'),
                    'actorLabel':'Operator','evidenceRef':'Release register','eventPayload':{'quantity':'10.25'},'occurredAt':NOW.isoformat(),'operationDate':str(DAY),
                    'supplyOfferId':'SUP-R1','demandRequestId':'DEM-R3'},write=True)
                return True
            except AdapterError:return False
        # Recipient cap is 10, so neither oversized request may succeed.
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(reserve,(0,1))),[False,False])
        demand=next(d for d in self.a.snapshot()['demand_requests'] if d['id']=='DEM-R3');demand['required_quantity']=Decimal('30')
        self.a.execute('UpsertDemandRequests',{'rows':[provider_row('demand_requests',demand)]},write=True)
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(reserve,(0,1))),1)
        self.assertEqual(self.a.snapshot()['supply_offers'][0]['reserved_active_quantity'],Decimal('10.25'))

    def test_confirmed_inputs_update_master_and_invalidate_matching(self):
        from backend.app.services.matching_service import MatchingService,current_records
        from backend.app.services.runtime_inputs import correct_inputs
        from backend.app.routes.matching import InputCorrection
        s=MatchingService(self.a,lambda:NOW);s.refresh();old=s.view()['materials'][0]['generation']['generation_id']
        _,revision=current_records(self.a)
        command=InputCorrection(expected_revision=revision,idempotency_key='project-correction',kind='PROJECT_FACTS',project_id='PRJ-R1',
            values={'township':'Area 2'},basis='Checked project register',confirmed=True)
        correct_inputs(self.a,command)
        self.assertEqual(s.view()['materials'][0]['status'],'PENDING')
        self.assertTrue(correct_inputs(self.a,command)['replayed'])
        s.refresh();self.assertNotEqual(s.view()['materials'][0]['generation']['generation_id'],old)
        self.assertEqual(next(p for p in self.a.snapshot()['projects'] if p['id']=='PRJ-R1')['township'],'Area 2')

    def test_fractional_publication_triggers_real_matching(self):
        import tempfile
        from pathlib import Path
        from backend.app.services.ingestion_service import IntakeService
        from backend.app.services.ingestion_storage import SourceStore
        from backend.app.repositories.ingestion_repository import IngestionRepository,TerraReadRepository
        from backend.app.services.review_service import ReviewService
        from backend.app.services.publication_service import PublicationService
        from backend.app.schemas.analysis import DraftRecord
        from backend.app.schemas.review import ManualSubmission,BulkDecision,RowEdit,ScopeConfirmation,ApproveSubmission
        from backend.app.schemas.publication import PublishBatch
        from backend.app.services.matching_service import MatchingService
        with tempfile.TemporaryDirectory() as folder:
            intake=IntakeService(IngestionRepository(self.a),TerraReadRepository(self.a),SourceStore(Path(folder)))
            batch=intake.create();review=ReviewService(intake)
            def record(kind,q,**extra):return DraftRecord(raw_description='Drainage pipe register',project_ref={'kind':'EXISTING','id':'PRJ-R1'},
                material_ref={'kind':'EXISTING','id':'MAT-PIPE'},record_kind=kind,quantity_basis='MATERIAL',quantity=q,unit='m',application='ADD',**extra)
            view=review.manual(batch.id,ManualSubmission(expected_revision=1,records=[record('ON_HAND_INVENTORY','100.25'),record('REMAINING_LOCAL_REQUIREMENT','20'),
                record('CONFIRMED_SURPLUS','50.5',available_from=DAY)]))
            sub=view['review']['submissions'][0]
            view=review.bulk(batch.id,sub['id'],BulkDecision(expected_revision=view['revision'],row_ids=[r['id'] for r in sub['rows']],decision='ACCEPTED',application='ADD',assumptions_confirmed=True))
            surplus=view['review']['submissions'][0]['rows'][2]
            view=review.row(batch.id,sub['id'],surplus['id'],RowEdit(expected_revision=view['revision'],current=DraftRecord.model_validate(surplus['current']),decision='ACCEPTED',assumptions_confirmed=True,release_confirmed=True))
            view=review.scopes(batch.id,ScopeConfirmation(expected_revision=view['revision'],scopes=[g['id'] for g in view['groups']]))
            view=review.approve(batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
            publisher=PublicationService(intake);plan=publisher.plan(batch.id)
            self.assertFalse(plan['blockers'],plan['blockers'])
            receipt=publisher.publish(batch.id,PublishBatch(expected_revision=plan['revision'],plan_digest=plan['plan_digest'],idempotency_key='fractional-publication'))
            self.assertEqual(receipt['counts']['supplyOffers'],1)
            offers=self.a.snapshot()['supply_offers'];self.assertIn(Decimal('50.5'),[o['confirmed_quantity'] for o in offers])
            service=MatchingService(self.a,lambda:NOW);service.refresh()
            self.assertEqual(service.view()['materials'][0]['status'],'CURRENT')
            self.assertEqual(publisher.get_receipt(batch.id)['handoff']['matcher_execution'],'COMPLETED')

    def test_local_worker_recovers_saved_pending_scope_without_manual_refresh(self):
        import time
        from unittest.mock import patch
        from backend.app.services.matching_service import MatchingService,current_records
        from backend.app.services.matching_worker import MatchingWorker
        _,revision=current_records(self.a)
        self.a.execute('DirtyMatchingScope',{'id':'MAT-PIPE','token':'saved-before-restart','expectedRevision':revision},write=True)
        with patch.dict(os.environ,{'TERRA_AUTOMATCH_ENABLED':'1'}),patch('backend.app.services.matching_worker.MatchingService',side_effect=lambda:MatchingService(clock=lambda:NOW)):
            worker=MatchingWorker();worker.start()
            try:
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    scope=self.a.execute('GetMatchingScope',{'id':'MAT-PIPE'})['matchingScope']
                    if scope['status']=='CURRENT':break
                    time.sleep(.05)
                self.assertEqual(scope['status'],'CURRENT')
            finally:worker.stop()

    def test_combined_transaction_foundation_creates_reserved_or_nothing(self):
        from backend.app.services.matching_service import MatchingService,current_records
        from terra.local_adapter import AdapterError
        s=MatchingService(self.a,lambda:NOW);s.refresh()
        generation=s.view()['materials'][0]['generation'];alt=generation['alternatives'][0]
        allocation=alt['plan']['allocations'][0]
        _,revision=current_records(self.a)
        values={'expectedRevision':revision,'generationId':generation['generation_id'],'materialId':'MAT-PIPE',
            'proposalId':alt['proposal_ids'][0],'transferId':'TRF-COMBINED','operationId':'WFO-COMBINED','requestFingerprint':'combined',
            'approvalEventId':'EVT-COMBINED-APPROVED','eventId':'EVT-COMBINED-RESERVED','quantity':Decimal('2.25'),
            'actorLabel':'Operator','evidenceRef':'Confirmed release','occurredAt':NOW.isoformat(),'operationDate':str(DAY),
            'arrivalDate':str(DAY+timedelta(days=2)),'supplyOfferId':allocation['supply_offer_id'],'demandRequestId':allocation['demand_request_id'],'eventPayload':{'quantity':'2.25'}}
        before=self.a.snapshot()
        with self.assertRaises(AdapterError):self.a.execute('ProveCombinedTransferReservation',{**values,'arrivalDate':str(DAY+timedelta(days=100))},write=True)
        self.assertEqual(self.a.snapshot(),before)
        self.a.execute('ProveCombinedTransferReservation',values,write=True)
        state=self.a.snapshot();transfer=next(t for t in state['transfers'] if t['id']=='TRF-COMBINED')
        self.assertEqual(transfer['status'],'RESERVED');self.assertEqual(transfer['reserved_quantity'],Decimal('2.25'))
        self.assertEqual({e['event_type'] for e in state['transfer_events']},{'APPROVED','RESERVED'})
        self.assertEqual(self.a.execute('GetMatchingScope',{'id':'MAT-PIPE'})['matchingScope']['status'],'PENDING')
        with self.assertRaises(AdapterError):self.a.execute('ProveCombinedTransferReservation',values,write=True)
        self.assertEqual(self.a.snapshot(),state)
