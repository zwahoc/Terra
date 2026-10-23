"""Connected extraction-to-reuse proof and backed-up local cutover checks."""
import copy
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from terra.local_adapter import LocalDataConnect,variables
from terra.validation import load
from terra.contract import FIELDS
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore
from backend.app.repositories.ingestion_repository import IngestionRepository,TerraReadRepository
from backend.app.services.analysis_service import ComparisonService
from backend.app.services.analysis_budget import BudgetLedger
from backend.app.repositories.model_preference_repository import ModelPreferenceRepository
from backend.app.services.analysis_providers import ProviderTurn,ToolCall
from backend.app.schemas.analysis import AnalyseRequest,DraftRecord
from backend.app.schemas.review import SelectReview,EntityEdit,ProjectEdit,BulkDecision,RowEdit,ScopeConfirmation,ApproveSubmission
from backend.app.schemas.publication import PublishBatch
from backend.app.services.review_service import ReviewService
from backend.app.services.publication_service import PublicationService
from backend.app.services.matching_service import MatchingService,current_records
from backend.app.services.transfer_confirmation_service import prepare_confirmation,confirm_transfer
from backend.app.schemas.transfers import TransferConfirmationRequest
from backend.app.services.transfer_workflow_service import run_transfer_workflow,WorkflowInput
from backend.app.repositories.transfer_repository import TransferRepository
from backend.app.services.automatic_impact_service import AutomaticImpactService
from backend.app.repositories.impact_repository import ImpactRepository
from backend.app.services.impact_export_service import export_json,export_csv
from backend.app.services.runtime_inputs import correct_inputs
from backend.app.routes.matching import InputCorrection
from backend.app.services.workspace_service import workspace_data
from terra.workspace_archive import archive_workspace,cutover_workspace,verify_archive
from tests.test_analysis import settings,usage

NOW=datetime(2026,10,23,10,tzinfo=timezone(timedelta(hours=8)))
DAY=NOW.date()

class ConnectedProvider:
    """Only a scripted provider. Uses real Terra draft tools and validation."""
    def check_availability(self):return {'available':True}
    def session(self,system,instruction,attachments,tools,output_schema):
        task=json.loads(instruction)['task']
        class Session:
            def step(self,results=None):
                stage=task['stage']
                if stage=='CLASSIFY_FILE':return ProviderTurn([],json.dumps({'primary_family':'OTHER','applicable_families':[],'basis':'Generic mechanical fixture'}),usage())
                if stage=='RECONCILE_FILE':
                    extraction=task['extraction'];value={'summary':'Saved-response fixture comparison',
                        'projects':[{'project_info_index':i,'explanation':'Provisional source or observed destination'} for i,_ in enumerate(extraction['project_info'])],
                        'materials':[{'record_index':i,'relationship':'NEW_INFORMATION','explanation':'New fixture evidence'} for i,_ in enumerate(extraction['records'])]}
                    return ProviderTurn([],json.dumps(value),usage())
                if stage=='CROSS_CHECK_BATCH':return ProviderTurn([],json.dumps({'summary':'Connected diagnostic checked','findings':[]}),usage())
                if results is None:return ProviderTurn([
                    ToolCall('source','propose_project',{'name':'Orchard Link External Works','code':'OL-EW','township':'Orchard','managing_organisation':'Crestfield Development'}),
                    ToolCall('pipe','propose_material',{'canonical_name':'uPVC drainage pipe 160 mm SN8','category_code':'PIPE','standard_unit':'m',
                        'specifications':{'material_type':'uPVC','diameter_mm':'160','stiffness_class':'SN8'}}),
                    ToolCall('destination','get_project_context',{'project_id':'PRJ-002'})], '',usage())
                source={'kind':'PROPOSED','id':results[0]['result']['proposal']['id']}
                pipe={'kind':'PROPOSED','id':results[1]['result']['proposal']['id']}
                dest={'kind':'EXISTING','id':'PRJ-002'};brick={'kind':'EXISTING','id':'MAT-009'}
                rows=[]
                for material,unit_name,stock,local,surplus,demand in ((pipe,'m','20.75','8','12.75','4.25'),(brick,'pcs','500','200','300','300')):
                    for kind,q,project in [('ON_HAND_INVENTORY',stock,source),('REMAINING_LOCAL_REQUIREMENT',local,source),('CONFIRMED_SURPLUS',surplus,source),('OUTSTANDING_DEMAND',demand,dest)]:
                        row={'raw_description':'Connected mechanical fixture','project_ref':project,'material_ref':material,'record_kind':kind,
                            'quantity_basis':'MATERIAL','raw_quantity':q,'raw_unit':unit_name,'quantity':q,'unit':unit_name,'application':'UNDECIDED','source_locator':f'Fixture item {len(rows)+1}'}
                        if kind=='CONFIRMED_SURPLUS':row['available_from']=str(DAY)
                        if kind=='OUTSTANDING_DEMAND':row.update(needed_from=str(DAY),required_by=str(DAY+timedelta(days=10)))
                        rows.append(row)
                value={'extraction_version':'MATERIAL_V2','document_type':'OTHER','summary':'Generic saved-response integration fixture',
                    'records':rows,'project_refs':[source,dest],'project_info':[{'project_ref':source,'name':'Orchard Link External Works','association_explanation':'New source project proposal'},
                        {'project_ref':dest,'name':'Observed destination project','association_explanation':'Matched stored project'}]}
                return ProviderTurn([],json.dumps(value),usage())
        return Session()

@unittest.skipUnless(os.environ.get('TERRA_RUN_CHECKPOINT_C_TESTS')=='1','Dedicated disposable checkpoint C emulator only')
class CheckpointCEmulatorTests(unittest.TestCase):
    def setUp(self):
        self.a=LocalDataConnect();self.assertIn('127.0.0.1:9499',self.a.base)
        version=self.a.execute('GetOperationalVersion')['operationalVersion']
        if version:self.a.execute('ResetLocalWorkspace',{'expectedOperationalRevision':version['revision'],'expectedBatches':{'batches':self.a.execute('GetCutoverBatchHeads')['ingestionBatches']}},write=True)
        else:self.a.execute('ClearBaseline',write=True)
        if not self.a.execute('GetQuantityEncoding')['quantityEncoding']:self.a.execute('InitializeExactQuantities',write=True)
        seed=load();self.seed=seed
        self.data={e:[] for e in FIELDS}
        self.data['projects']=copy.deepcopy(seed['projects'][:2])
        self.data['materials']=[copy.deepcopy(next(m for m in seed['materials'] if m['id']=='MAT-009'))]
        self.data['emission_factors']=[copy.deepcopy(f) for f in seed['emission_factors'] if f['material_category']=='BRICK' or f['material_id']=='MAT-009' or f['material_id'] is None and f['material_category'] is None]
        for kind,unit_name,value in [('NEW_MATERIAL_PRODUCTION','kgCO2e/kg',2),('PROCESSING','kgCO2e/kg',.02)]:
            factor=copy.deepcopy(next(f for f in seed['emission_factors'] if f['factor_type']==kind))
            factor.update(id='EF-C-'+kind,material_id=None,material_category='PIPE',unit=unit_name,value=value)
            self.data['emission_factors'].append(factor)
        self.a.execute('ImportBaseline',variables(self.data),write=True)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        self.intake=IntakeService(IngestionRepository(self.a),TerraReadRepository(self.a),SourceStore(self.folder/'sources'))

    def background_until(self,predicate):
        import time
        from backend.app.services.matching_worker import MatchingWorker
        with patch.dict(os.environ,{'TERRA_AUTOMATCH_ENABLED':'1'}), \
             patch('backend.app.services.matching_worker.MatchingService',side_effect=lambda:MatchingService(self.a,lambda:NOW)), \
             patch('backend.app.services.matching_worker.AutomaticImpactService',side_effect=lambda:AutomaticImpactService(self.a,lambda:NOW)):
            worker=MatchingWorker();worker.start()
            try:
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    if predicate():return
                    time.sleep(.1)
                self.fail('Durable background work did not complete')
            finally:worker.stop()

    def test_upload_extract_review_publish_match_transfer_use_report_and_export(self):
        batch=self.intake.create();batch=self.intake.add_files(batch.id,batch.revision,[('diagnostic.txt',io.BytesIO(b'Generic saved-response integration fixture.'))])['batch']
        config=settings();config=replace(config,models=(config.models[-1],))
        service=ComparisonService(self.intake,config,BudgetLedger(config,self.folder/'usage'),provider_factory=lambda spec:ConnectedProvider(),schedule=lambda fn,*args:fn(*args),preferences=ModelPreferenceRepository(self.folder/'preference'))
        comparison=service.start(batch['id'],AnalyseRequest(expected_revision=batch['revision'],idempotency_key='connected-extraction'))
        run=comparison['runs'][0];self.assertEqual(run['status'],'SUCCEEDED',[(f.get('status'),f.get('error')) for f in run.get('files',[])])
        review=ReviewService(self.intake)
        view=review.select(batch['id'],SelectReview(expected_revision=self.intake.get(batch['id']).revision,comparison_id=comparison['id'],run_id=run['id']))
        for entity in list(view['review']['entities']):view=review.entity(batch['id'],entity['proposal']['id'],EntityEdit(expected_revision=view['revision'],kind=entity['proposal']['kind'],attributes=entity['proposal']['attributes'],confirmed=True))
        for sub in list(view['review']['submissions']):
            for project in sub['projects']:view=review.project(batch['id'],sub['id'],project['id'],ProjectEdit(expected_revision=view['revision'],current=project['current'],confirmed=True))
            view=review.bulk(batch['id'],sub['id'],BulkDecision(expected_revision=view['revision'],row_ids=[r['id'] for r in sub['rows']],decision='ACCEPTED',application='ADD',assumptions_confirmed=True))
            for row in view['review']['submissions'][0]['rows']:
                if row['current']['record_kind']=='CONFIRMED_SURPLUS':view=review.row(batch['id'],sub['id'],row['id'],RowEdit(expected_revision=view['revision'],current=DraftRecord.model_validate(row['current']),decision='ACCEPTED',assumptions_confirmed=True,release_confirmed=True))
        view=review.scopes(batch['id'],ScopeConfirmation(expected_revision=view['revision'],scopes=[g['id'] for g in view['groups'] if g['on_hand_observations'] is not None]))
        for sub in view['review']['submissions']:view=review.approve(batch['id'],sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        publisher=PublicationService(self.intake);plan=publisher.plan(batch['id']);self.assertFalse(plan['blockers'],plan['blockers'])
        receipt=publisher.publish(batch['id'],PublishBatch(expected_revision=plan['revision'],plan_digest=plan['plan_digest'],idempotency_key='connected-publication'))
        self.assertEqual(receipt['counts']['projects'],1);self.assertEqual(receipt['counts']['materials'],1)
        records,revision=current_records(self.a);new_project=next(p for p in records['projects'] if p['code']=='OL-EW');pipe=next(m for m in records['materials'] if m['category']=='PIPE')
        correct_inputs(self.a,InputCorrection(expected_revision=revision,idempotency_key='mass',kind='MATERIAL_MASS',material_id=pipe['id'],values={'mass_kg_per_unit':'1.2'},basis='Confirmed fixture weight',confirmed=True))
        _,revision=current_records(self.a)
        correct_inputs(self.a,InputCorrection(expected_revision=revision,idempotency_key='route',kind='ROUTE_DISTANCE',source_project_id=new_project['id'],destination_project_id='PRJ-002',values={'distance_km':'25'},basis='Confirmed fixture road estimate',confirmed=True))
        self.background_until(lambda:self.a.execute('GetPublicationReceipt',{'id':receipt['publication_id']})['ingestionPublication']['handoffStatus']=='COMPLETED')
        matcher=MatchingService(self.a,lambda:NOW)
        self.assertEqual({m['status'] for m in matcher.view()['materials']},{'CURRENT'},[(m['material_name'],m['error']) for m in matcher.view()['materials']])
        for material,quantity,first_use,last_use in [(pipe['id'],'3.25','1.25','2'),('MAT-009','250','200','50')]:
            generation=next(m['generation'] for m in matcher.view()['materials'] if m['material_id']==material)
            self.assertEqual(len(generation['alternatives']),3)
            if not generation['alternatives'][0]['proposal_ids']:
                from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
                from backend.app.domain.candidates import generate_candidate_pairs
                from backend.app.services.matching_service import material_records
                current=current_records(self.a)[0]
                calculator=ForecastPreviewCalculator(material_records(current,material),planning_date=DAY,factor_dataset_version='demo-v1')
                self.fail(str((material,generate_candidate_pairs(calculator.snapshot).pairs)))
            proposal=generation['alternatives'][0]['proposal_ids'][0]
            preview=prepare_confirmation(self.a,proposal,quantity,generation['generation_id'],lambda:NOW)
            result=confirm_transfer(proposal,TransferConfirmationRequest(quantity=quantity,generation_id=generation['generation_id'],expected_revision=preview['expected_revision'],actor_label='Operator',idempotency_key='confirm-'+material),self.a,lambda:NOW)
            transfer=result['data']['transfer'];repository=TransferRepository(self.a)
            for action,increment in [('dispatch',None),('receive',None),('confirm_use',first_use),('confirm_use',last_use)]:
                run_transfer_workflow(transfer['id'],action,WorkflowInput('Operator',f'{material}-{action}-{increment}',increment),repository,lambda:NOW)
                if action=='confirm_use':self.background_until(lambda:self.a.execute('GetImpactIntent',{'id':transfer['id']})['impactRefreshIntent']['status']=='COMPLETED')
            self.assertEqual(Decimal(str(repository.get(transfer['id'])['actually_used_quantity'])),Decimal(quantity))
            head=ImpactRepository(self.a).persistence_state('ACTUAL_CONFIRMED_USE:'+transfer['id'],'none').head;self.assertEqual(head['revision'],2)
            matcher.refresh()
        workspace=workspace_data(self.a)
        self.assertTrue(any(p['id']==new_project['id'] for p in workspace['terra']['projects']))
        self.assertEqual({r['unit'] for r in workspace['transfer_views']},{'pcs','m'})
        self.assertTrue(all(r['received_but_unused_quantity']==0 for r in workspace['transfer_views']))
        self.assertEqual(workspace['dashboard']['by_project'][new_project['id']]['actual_reuse_tonnes'],workspace['dashboard']['actual_reuse_tonnes'])
        self.assertEqual(workspace['dashboard']['by_project']['PRJ-002']['actual_reuse_tonnes'],workspace['dashboard']['actual_reuse_tonnes'])
        self.assertTrue(all(r['components_kgco2e']['net_avoided'] is not None for r in export_json('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a))['data']['records']))
        self.assertIn('3.25',export_csv('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a)))
        self.assertEqual(len(export_json('ACTUAL_CONFIRMED_USE',ImpactRepository(self.a))['data']['records']),2)

    def test_verified_archive_cutover_and_historical_batch_stays_out_of_runtime(self):
        batch=self.intake.create();self.intake.add_files(batch.id,1,[('diagnostic.txt',io.BytesIO(b'Generic archival source'))])
        manifest,folder=archive_workspace(self.a,destination=self.folder/'archives',sources=self.folder/'sources',label='Isolated cutover proof')
        self.assertEqual(verify_archive(folder)['status'],'COMPLETE')
        self.assertEqual(len(manifest['batches']),1)
        result=cutover_workspace(self.seed,folder,self.a,confirmation='demo-terra-local',state_file=self.folder/'state.json')
        self.assertEqual(self.a.execute('GetWorkspaceIdentity')['workspaceIdentity']['epoch'],result['epoch'])
        self.assertIsNone(self.a.execute('GetIngestionBatch',{'id':batch.id})['ingestionBatch'])
        self.assertEqual(len(self.a.snapshot()['projects']),len(self.seed['projects']))
        from backend.app.routes.history import batch as read_history
        with patch.dict(os.environ,{'TERRA_WORKSPACE_ARCHIVES':str(self.folder/'archives')}):
            saved=read_history(manifest['id'],batch.id)
        self.assertEqual(saved['id'],batch.id)
        self.assertEqual((folder/'sources/objects'/saved['submissions'][0]['source']['sha256']).read_bytes(),b'Generic archival source')
        self.assertEqual(self.a.snapshot()['transfers'],self.seed['transfers'])

    def test_cutover_refuses_a_draft_edited_after_the_archive(self):
        from backend.app.schemas.ingestion import ContextPatch
        from terra.local_adapter import AdapterError
        batch=self.intake.create()
        manifest,folder=archive_workspace(self.a,destination=self.folder/'archives',sources=self.folder/'sources')
        self.intake.patch_context(batch.id,ContextPatch(expected_revision=1,operator_notes='Saved after archive'))
        before=self.a.snapshot()
        with self.assertRaises(AdapterError) as caught:
            cutover_workspace(self.seed,folder,self.a,confirmation='demo-terra-local',state_file=self.folder/'state.json')
        self.assertIn('CUTOVER_DRAFTS_CHANGED',str(caught.exception))
        self.assertEqual(self.a.snapshot(),before)
        self.assertEqual(self.intake.get(batch.id).context.operator_notes,'Saved after archive')

    def test_prepared_file_approval_publishes_exact_operational_payload_once(self):
        batch=self.intake.create()
        batch=self.intake.add_files(batch.id,batch.revision,[('prepared-diagnostic.txt',io.BytesIO(b'Generic connected prepared-review fixture.'))])['batch']
        config=replace(settings(),models=(settings().models[-1],))
        analysis=ComparisonService(self.intake,config,BudgetLedger(config,self.folder/'prepared-usage'),
            provider_factory=lambda spec:ConnectedProvider(),schedule=lambda fn,*args:fn(*args),
            preferences=ModelPreferenceRepository(self.folder/'prepared-preference'))
        comparison=analysis.start(batch['id'],AnalyseRequest(expected_revision=batch['revision'],idempotency_key='prepared-analysis'))
        run=comparison['runs'][0]
        self.assertEqual(run['status'],'SUCCEEDED')
        reviewer=ReviewService(self.intake)
        view=reviewer.prepare(batch['id'],SelectReview(expected_revision=self.intake.get(batch['id']).revision,
            comparison_id=comparison['id'],run_id=run['id']))
        self.assertFalse(any(view['blockers'].values()),view['blockers'])
        self.assertFalse(any(view['approvals'].values()))
        publisher=PublicationService(self.intake)
        self.assertIn('Every included file/manual submission needs a current approval.',publisher.plan(batch['id'])['blockers'])
        sub=view['review']['submissions'][0]
        view=reviewer.approve(batch['id'],sub['id'],ApproveSubmission(expected_revision=view['revision'],
            preview_digest=view['preview_digest'],summary_confirmed=True,accept_recommendations=True))
        self.assertTrue(view['approvals'][sub['id']])
        plan=publisher.plan(batch['id']);self.assertFalse(plan['blockers'],plan['blockers'])
        self.assertEqual(plan['counts']['supplyOffers'],2);self.assertEqual(plan['counts']['demandRequests'],2)
        command=PublishBatch(expected_revision=plan['revision'],plan_digest=plan['plan_digest'],idempotency_key='prepared-publication')
        receipt=publisher.publish(batch['id'],command)
        self.assertTrue(publisher.publish(batch['id'],command)['replayed'])
        context=self.intake.reads.project_context(next(v for k,v in receipt['id_mapping'].items() if k.startswith('DRAFT-PROJECT')))
        self.assertEqual(sorted(r['quantity'] for r in context['collections']['published_records'] if r['record_kind']=='ON_HAND_INVENTORY'),['20.75','500'])
        self.assertEqual(sorted(str(o['confirmed_quantity']) for o in context['collections']['supply_offers']),['12.75','300'])
        self.assertEqual(self.intake.get(batch['id']).comparisons[0].runs[0].files[0].draft.model_dump(mode='json'),run['files'][0]['draft'])

    def test_manual_conversion_reaches_publication_without_changing_document_units(self):
        from backend.app.schemas.review import ManualSubmission,Conversion
        batch=self.intake.create();project={'kind':'EXISTING','id':'PRJ-001'};material={'kind':'EXISTING','id':'MAT-009'}
        records=[]
        for kind,q,unit_name in [('ON_HAND_INVENTORY','2.5','m²'),('REMAINING_LOCAL_REQUIREMENT','20','pcs'),('CONFIRMED_SURPLUS','60','pcs')]:
            records.append(DraftRecord(raw_description='Operator-provided diagnostic',project_ref=project,material_ref=material,
                record_kind=kind,quantity_basis='MATERIAL',quantity=q,unit=unit_name,application='ADD',
                available_from=DAY if kind=='CONFIRMED_SURPLUS' else None))
        reviewer=ReviewService(self.intake)
        view=reviewer.manual(batch.id,ManualSubmission(expected_revision=batch.revision,prepared=True,records=records,
            conversions=[Conversion(to_unit='pcs',factor='32',basis='Operator-confirmed product coverage'),None,None]))
        self.assertFalse(any(view['blockers'].values()),view['blockers'])
        sub=view['review']['submissions'][0]
        self.assertFalse(sub['rows'][0]['conversion']['confirmed'])
        view=reviewer.approve(batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True,accept_recommendations=True))
        publisher=PublicationService(self.intake);plan=publisher.plan(batch.id)
        self.assertFalse(plan['blockers'],plan['blockers'])
        receipt=publisher.publish(batch.id,PublishBatch(expected_revision=plan['revision'],plan_digest=plan['plan_digest'],idempotency_key='manual-conversion-publication'))
        context=self.intake.reads.project_context('PRJ-001')['collections']
        stock=next(r for r in context['published_records'] if r['record_kind']=='ON_HAND_INVENTORY')
        self.assertEqual(Decimal(stock['quantity']),Decimal('80'));self.assertEqual(stock['unit'],'pcs')
        saved=self.intake.get(batch.id).review.submissions[0].rows[0]
        self.assertEqual(saved.current.quantity,'2.5');self.assertEqual(saved.current.unit,'m²')
        self.assertIsNone(saved.original);self.assertEqual(saved.provenance,'OPERATOR_MANUAL')
        self.assertEqual(receipt['counts']['supplyOffers'],1)
        self.assertEqual(Decimal(str(context['supply_offers'][0]['confirmed_quantity'])),Decimal('60'))
