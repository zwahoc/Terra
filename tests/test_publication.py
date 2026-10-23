"""Explicit Phase 5 proofs on an isolated SQL Connect emulator only."""
import copy,io,os,tempfile,unittest
from pathlib import Path
from backend.app.schemas.analysis import DraftRecord
from backend.app.schemas.review import ManualSubmission,BulkDecision,ApproveSubmission,ScopeConfirmation,EntityEdit,RowEdit
from backend.app.schemas.publication import PublishBatch
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore
from backend.app.services.review_service import ReviewService
from backend.app.services.publication_service import PublicationService,stable
from backend.app.repositories.ingestion_repository import IngestionRepository,TerraReadRepository
from backend.app.repositories.publication_repository import PublicationRepository
from backend.app.services.ingestion_errors import IngestionError
from terra.local_adapter import LocalDataConnect,variables,normalized,AdapterError
from terra.validation import load


def row(kind='ON_HAND_INVENTORY', quantity='10', **updates):
    values=dict(raw_description='Generic publication diagnostic',project_ref={'kind':'EXISTING','id':'PRJ-001'},
        material_ref={'kind':'EXISTING','id':'MAT-001'},record_kind=kind,quantity_basis='MATERIAL',quantity=quantity,unit='pcs',application='ADD')
    return DraftRecord(**{**values,**updates})


@unittest.skipUnless(os.environ.get('TERRA_RUN_EMULATOR_TESTS')=='1','Use isolated SQL Connect publication tests')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.adapter=LocalDataConnect();self.seed=load()
        self.adapter.execute('ClearBaseline',write=True);self.adapter.execute('ImportBaseline',variables(self.seed),write=True)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.intake=IntakeService(IngestionRepository(self.adapter),TerraReadRepository(self.adapter),SourceStore(Path(self.temp.name)))
        self.batch=self.intake.create();self.review=ReviewService(self.intake);self.publisher=PublicationService(self.intake)

    def test_failed_skip_manual_replacement_and_success_publish_once_together(self):
        from dataclasses import replace
        from tests.test_analysis import settings, ScriptedAdapter
        from backend.app.services.analysis_service import ComparisonService
        from backend.app.services.analysis_budget import BudgetLedger
        from backend.app.repositories.model_preference_repository import ModelPreferenceRepository
        from backend.app.schemas.analysis import AnalyseRequest
        from backend.app.schemas.review import ResolveFile, SelectReview, ProjectEdit
        upload=self.intake.add_files(self.batch.id,1,[('readable.txt',io.BytesIO(b'Generic text diagnostic')),
            ('unreadable-a.bin',io.BytesIO(b'opaque A')),('unreadable-b.bin',io.BytesIO(b'opaque B'))])['batch']
        config=settings();config=replace(config,models=(config.models[-1],));calls=[]
        analysis=ComparisonService(self.intake,config,BudgetLedger(config,Path(self.temp.name)/'budget'),
            provider_factory=lambda spec:ScriptedAdapter(spec,calls),schedule=lambda fn,*args:fn(*args),
            preferences=ModelPreferenceRepository(Path(self.temp.name)/'preference'))
        result=analysis.start(self.batch.id,AnalyseRequest(expected_revision=upload['revision'],idempotency_key='diagnostic-analysis'))
        run=result['runs'][0];self.assertEqual(run['status'],'PARTIAL')
        skip=upload['submissions'][1]['id'];manual=upload['submissions'][2]['id']
        self.review.resolve_file(self.batch.id,skip,ResolveFile(expected_revision=self.intake.get(self.batch.id).revision,
            resolution='SKIPPED',analysis_run_id=run['id']))
        view=self.review.manual(self.batch.id,ManualSubmission(expected_revision=self.intake.get(self.batch.id).revision,
            replaces_submission_id=manual,analysis_run_id=run['id'],records=[row('PURCHASE_ORDER','5')]))
        view=self.review.rebase(self.batch.id,SelectReview(expected_revision=view['revision'],comparison_id=result['id'],run_id=run['id']))
        # Added-file analysis owns fresh proposal IDs; the review reconnects its
        # prior edits through the explicit lineage, before one atomic publish.
        from tests.test_office_readers import package,word_parts
        original_file=next(s for s in view['review']['submissions'] if s['label']=='readable.txt')
        original_row=original_file['rows'][0]
        view=self.review.row(self.batch.id,original_file['id'],original_row['id'],RowEdit(expected_revision=view['revision'],
            current=DraftRecord.model_validate(original_row['current']).model_copy(update={'quantity':'9.75'}),decision='PENDING'))
        self.intake.add_files(self.batch.id,view['revision'],[('added.docx',io.BytesIO(package(word_parts())))])
        updated=analysis.start(self.batch.id,AnalyseRequest(expected_revision=self.intake.get(self.batch.id).revision,idempotency_key='added-office'))
        self.assertNotEqual(updated['runs'][0]['proposals'][0]['id'],run['proposals'][0]['id'])
        view=self.review.rebase(self.batch.id,SelectReview(expected_revision=self.intake.get(self.batch.id).revision,comparison_id=updated['id'],run_id=updated['runs'][0]['id']))
        retained=next(s for s in view['review']['submissions'] if s['id']==original_file['id'])['rows'][0]
        self.assertEqual(retained['current']['quantity'],'9.75');self.assertEqual(retained['original']['quantity'],'1.25')
        for entity in list(view['review']['entities']):
            view=self.review.entity(self.batch.id,entity['proposal']['id'],EntityEdit(expected_revision=view['revision'],
                kind=entity['proposal']['kind'],attributes=entity['proposal']['attributes'],confirmed=True))
        for sub in list(view['review']['submissions']):
            for project in sub['projects']:
                from backend.app.schemas.analysis import ExtractedProject
                view=self.review.project(self.batch.id,sub['id'],project['id'],ProjectEdit(expected_revision=view['revision'],
                    current=ExtractedProject.model_validate(project['current']),confirmed=True))
            if sub['rows']:
                view=self.review.bulk(self.batch.id,sub['id'],BulkDecision(expected_revision=view['revision'],row_ids=[r['id'] for r in sub['rows']],
                    decision='ACCEPTED',application='HISTORY_ONLY' if sub['kind']=='FILE' else 'ADD',assumptions_confirmed=True))
        for sub in view['review']['submissions']:
            view=self.review.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        self.assertTrue(view['publication_available'])
        plan=self.publisher.plan(self.batch.id);self.assertEqual(plan['blockers'],[])
        receipt=self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(receipt['counts']['documents'],2);self.assertEqual(receipt['counts']['projectMaterialRecords'],3)
        self.assertEqual({r['resolution'] for r in receipt['file_resolutions']},{'ANALYSE','SKIPPED','MANUAL'})
        stored=self.intake.reads.project_context('PRJ-001')['collections']['published_records']
        manual_row=next(r for r in stored if r['source']['kind']=='MANUAL')
        self.assertNotIn('document_id',manual_row['source']);self.assertIsNone(manual_row['original'])
        self.assertEqual(self.intake.get(self.batch.id).comparisons[0].runs[0].files[2].error.code,'UNSUPPORTED_FORMAT')
        self.assertTrue(self.publisher.publish(self.batch.id,self.command(plan))['replayed'])

    def ready(self,records=None,confirm_stock=False):
        view=self.review.manual(self.batch.id,ManualSubmission(expected_revision=1,records=records or [row()]))
        sub=view['review']['submissions'][0]
        view=self.review.bulk(self.batch.id,sub['id'],BulkDecision(expected_revision=view['revision'],row_ids=[r['id'] for r in sub['rows']],
            decision='ACCEPTED',application='ADD',assumptions_confirmed=True))
        if confirm_stock:
            view=self.review.scopes(self.batch.id,ScopeConfirmation(expected_revision=view['revision'],scopes=[g['id'] for g in view['groups']]))
        view=self.review.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        return view

    def command(self,plan,key='same-key'):
        return PublishBatch(expected_revision=plan['revision'],plan_digest=plan['plan_digest'],idempotency_key=key)

    def test_atomic_publish_replay_read_context_and_published_immutability(self):
        self.ready();plan=self.publisher.plan(self.batch.id)
        receipt=self.publisher.publish(self.batch.id,self.command(plan))
        state=self.publisher.repository.state()
        self.assertEqual(len(state['projectMaterialRecords']),1)
        self.assertEqual(receipt['handoff_status'],'PENDING')
        self.assertEqual(receipt['handoff']['matcher_execution'],'PENDING')
        replay=self.publisher.publish(self.batch.id,self.command(plan))
        self.assertTrue(replay['replayed'])
        self.assertEqual(len(self.publisher.repository.state()['projectMaterialRecords']),1)
        self.assertEqual(self.intake.get(self.batch.id).state,'PUBLISHED')
        self.assertEqual(self.intake.reads.project_context('PRJ-001')['collections']['published_records'][0]['quantity'],'10')
        with self.assertRaises(IngestionError):self.intake.patch_context(self.batch.id,type('Patch',(),{'expected_revision':999})())
        with self.assertRaises(IngestionError):self.publisher.publish(self.batch.id,self.command(plan,'different-key'))

    def test_unresolved_unapproved_and_late_state_changes_block(self):
        self.review.manual(self.batch.id,ManualSubmission(expected_revision=1,records=[row()]))
        plan=self.publisher.plan(self.batch.id);self.assertTrue(plan['blockers'])
        with self.assertRaises(IngestionError):self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(self.publisher.repository.state()['projectMaterialRecords'],[])

    def test_file_source_is_preserved_and_repeat_effective_upload_is_blocked(self):
        from backend.app.schemas.review import ReviewState,ReviewSubmission,ReviewRow
        def reviewed_file(batch):
            uploaded=self.intake.add_files(batch.id,batch.revision,[('diagnostic.txt',io.BytesIO(b'Generic source provenance diagnostic'))])['batch']
            submission=uploaded['submissions'][0]
            def install(value):
                original=row('PURCHASE_ORDER','5',source_locator='Diagnostic source')
                value.review=ReviewState(submissions=[ReviewSubmission(id=submission['id'],kind='FILE',label='diagnostic.txt',
                    rows=[ReviewRow(id='REV-diagnostic',original=original,current=original.model_copy(deep=True),
                                    decision='ACCEPTED',assumptions_confirmed=True)])])
            self.intake._edit(batch.id,uploaded['revision'],install)
            view=self.review.get(batch.id)
            self.review.approve(batch.id,submission['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
            return submission
        source=reviewed_file(self.batch)
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(receipt['counts']['documents'],1)
        stored=self.intake.reads.project_context('PRJ-001')['collections']['published_records'][0]
        self.assertEqual(stored['source']['sha256'],source['source']['sha256'])
        self.assertEqual(stored['source']['kind'],'FILE')
        self.assertEqual(stored['original']['source_locator'],'Diagnostic source')
        second=self.intake.create();reviewed_file(second)
        self.assertTrue(any('already published' in message for message in self.publisher.plan(second.id)['blockers']))

    def test_confirmed_release_projects_offer_without_adding_surplus_to_stock(self):
        self.ready([row(quantity='100'),row('REMAINING_LOCAL_REQUIREMENT','40'),row('CONFIRMED_SURPLUS','30',available_from='2026-10-18')],confirm_stock=True)
        view=self.review.get(self.batch.id);sub=view['review']['submissions'][0];surplus=sub['rows'][2]
        view=self.review.row(self.batch.id,sub['id'],surplus['id'],RowEdit(expected_revision=view['revision'],current=DraftRecord.model_validate(surplus['current']),
            decision='ACCEPTED',assumptions_confirmed=True,release_confirmed=True))
        self.review.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        state=self.publisher.repository.state()
        offer=next(o for o in state['supplyOffers'] if o['id'] in receipt['handoff']['supply_offer_ids'])
        self.assertEqual(offer['condition'],'UNUSED');self.assertEqual(offer['confirmedQuantity'],30)
        head=next(h for h in state['projectStockHeads'] if h['materialId']=='MAT-001')
        self.assertEqual(head['payload']['quantity'],'1100')

    def test_operational_version_is_monotonic_and_guards_other_mutations(self):
        before=self.adapter.execute('GetOperationalVersion')['operationalVersion']['revision']
        self.adapter.execute('UpsertProjects',{'rows':[]},write=True)
        after=self.adapter.execute('GetOperationalVersion')['operationalVersion']['revision']
        self.assertEqual(after,before+1)

    def test_midflight_context_change_rolls_back_every_write(self):
        self.ready();plan=self.publisher.plan(self.batch.id)
        repository=self.publisher.repository
        original=repository.publish
        def raced(values):
            self.adapter.execute('UpsertProjects',{'rows':[]},write=True)
            return original(values)
        repository.publish=raced
        with self.assertRaises(IngestionError) as caught:self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(caught.exception.code,'PUBLICATION_CONTEXT_STALE')
        self.assertEqual(repository.state()['projectMaterialRecords'],[])
        self.assertEqual(self.intake.get(self.batch.id).state,'INTAKE')

    def test_late_constraint_rolls_back_batch_records_receipt_and_guard(self):
        self.ready();plan=self.publisher.plan(self.batch.id)
        repository=self.publisher.repository;original=repository.publish;version=repository.state()['operationalVersion']
        def fail(values):
            changed=copy.deepcopy(values)
            changed['projects']=[copy.deepcopy(self.seed['projects'][0])]
            changed['projects']=[{k if '_' not in k else k.split('_')[0]+''.join(s.title() for s in k.split('_')[1:]):v for k,v in changed['projects'][0].items()}]
            return original(changed)
        repository.publish=fail
        with self.assertRaises(IngestionError):self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(repository.state()['projectMaterialRecords'],[])
        self.assertEqual(repository.state()['operationalVersion'],version)
        self.assertIsNone(repository.receipt(stable('PUB',self.batch.id)))
        self.assertEqual(self.intake.get(self.batch.id).state,'INTAKE')

    def test_stock_head_tracks_dispatch_effect_once_and_does_not_add_surplus(self):
        self.ready([row(quantity='100'),row('REMAINING_LOCAL_REQUIREMENT','40')],confirm_stock=True)
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        state=self.publisher.repository.state();head=next(h['payload'] for h in state['projectStockHeads'] if h['materialId']=='MAT-001')
        self.assertEqual(head['quantity'],'1100')  # 1000 explicit baseline observation + 100 independent ADD
        # A subsequent draft reads the authoritative scope once, not all source
        # snapshots plus the scope. No transfer is fabricated in this proof.
        next_batch=self.intake.create();v=self.review.manual(next_batch.id,ManualSubmission(expected_revision=1,records=[row('PURCHASE_ORDER','20')]))
        sub=v['review']['submissions'][0]
        v=self.review.bulk(next_batch.id,sub['id'],BulkDecision(expected_revision=v['revision'],row_ids=[sub['rows'][0]['id']],decision='ACCEPTED',application='ADD',assumptions_confirmed=True))
        group=next(g for g in v['groups'] if g['material']=='MAT-001')
        self.assertEqual(group['on_hand_observations'],'1100')

    def test_recording_failure_preserves_commit_for_explicit_retry(self):
        self.ready();plan=self.publisher.plan(self.batch.id)
        def fail(_):raise RuntimeError('Diagnostic handoff failure')
        self.publisher.repository.dispatch=fail
        receipt=self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(receipt['handoff_status'],'PENDING')
        self.assertEqual(len(self.publisher.repository.state()['projectMaterialRecords']),1)
        self.assertEqual(self.publisher.get_receipt(self.batch.id)['publication_id'],receipt['publication_id'])

    def test_administrative_connector_is_not_public(self):
        with self.assertRaises(AdapterError):self.adapter.execute('GetPublicationState',admin=False)

    def test_general_material_registration_is_one_logical_catalogue_and_project_context(self):
        view=self.review.manual(self.batch.id,ManualSubmission(expected_revision=1,records=[row(unit='kg',quantity='1.25')]))
        view=self.review.entity(self.batch.id,'new',EntityEdit(expected_revision=view['revision'],kind='MATERIAL',
            attributes={'canonical_name':'Generic steel diagnostic','category_code':'STEEL','standard_unit':'kg','specifications':{'grade':'B500B'}},confirmed=True))
        entity=view['review']['entities'][0]['proposal'];sub=view['review']['submissions'][0];record=sub['rows'][0]
        edited=DraftRecord.model_validate({**record['current'],'material_ref':{'kind':'PROPOSED','id':entity['id']}})
        view=self.review.row(self.batch.id,sub['id'],record['id'],RowEdit(expected_revision=view['revision'],current=edited,decision='ACCEPTED',assumptions_confirmed=True))
        view=self.review.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        material_id=receipt['id_mapping'][entity['id']]
        material=self.intake.reads.get_entity('materials',material_id)
        self.assertEqual(material['standard_unit'],'kg');self.assertEqual(material['category'],'STEEL')
        context=self.intake.reads.project_context('PRJ-001')
        self.assertIn(material_id,{m['id'] for m in context['collections']['materials']})
        from backend.app.services.workspace_service import workspace_data
        workspace=workspace_data(self.adapter)
        self.assertIn(material_id,{m['id'] for m in workspace['terra']['materials']})
        self.assertEqual(workspace['terra']['published_records'][0]['material_id'],material_id)
        self.assertEqual(receipt['counts']['supplyOffers'],0)
        self.assertEqual(self.review.get(self.batch.id)['groups'],receipt['groups'],'Published review is a frozen approved snapshot, not a second stock contribution')

    def test_concurrent_duplicate_request_creates_one_receipt(self):
        from concurrent.futures import ThreadPoolExecutor
        self.ready();plan=self.publisher.plan(self.batch.id);command=self.command(plan)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.publisher.publish(self.batch.id,command),range(2)))
        self.assertEqual(len({r['publication_id'] for r in results}),1)
        self.assertEqual(len(self.publisher.repository.state()['projectMaterialRecords']),1)

    def test_supported_demand_projects_once_without_double_subtracting_incoming(self):
        # A separate ADD requirement remains separate from already committed old
        # requests. Legacy transfer code subtracts its own mapped commitments.
        self.ready([row('OUTSTANDING_DEMAND','50',needed_from='2026-10-18',required_by='2026-11-01')])
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(receipt['counts']['demandRequests'],1)
        projected=next(d for d in self.publisher.repository.state()['demandRequests'] if d['id'] in receipt['handoff']['demand_request_ids'])
        self.assertEqual(projected['requiredQuantity'],50)
        self.assertEqual(projected['fulfilledQuantity'],0)

    def test_history_only_commit_does_not_request_matching(self):
        view=self.review.manual(self.batch.id,ManualSubmission(expected_revision=1,records=[row()]))
        sub=view['review']['submissions'][0]
        view=self.review.bulk(self.batch.id,sub['id'],BulkDecision(expected_revision=view['revision'],row_ids=[sub['rows'][0]['id']],decision='ACCEPTED',application='HISTORY_ONLY',assumptions_confirmed=True))
        self.review.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        self.assertEqual(receipt['handoff_status'],'NOT_REQUIRED')
        self.assertEqual(receipt['counts']['projectStockHeads'],0)

    def test_new_project_and_material_resolve_references_atomically(self):
        view=self.review.manual(self.batch.id,ManualSubmission(expected_revision=1,records=[row()]))
        for kind,attributes in [('PROJECT',{'name':'Diagnostic project','code':'DIAG-NEW','township':'Diagnostic township','managing_organisation':'Diagnostic organisation'}),
                                ('MATERIAL',{'canonical_name':'Diagnostic brick','category_code':'BRICK','standard_unit':'pcs','specifications':{'length_mm':'200'}})]:
            view=self.review.entity(self.batch.id,'new',EntityEdit(expected_revision=view['revision'],kind=kind,attributes=attributes,confirmed=True))
        sub=view['review']['submissions'][0];current=sub['rows'][0]
        proposals={e['proposal']['kind']:e['proposal']['id'] for e in view['review']['entities']}
        edited=DraftRecord.model_validate({**current['current'],'project_ref':{'kind':'PROPOSED','id':proposals['PROJECT']},'material_ref':{'kind':'PROPOSED','id':proposals['MATERIAL']}})
        view=self.review.row(self.batch.id,sub['id'],current['id'],RowEdit(expected_revision=view['revision'],current=edited,decision='ACCEPTED',assumptions_confirmed=True))
        self.review.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        plan=self.publisher.plan(self.batch.id);receipt=self.publisher.publish(self.batch.id,self.command(plan))
        pid=receipt['id_mapping'][proposals['PROJECT']];mid=receipt['id_mapping'][proposals['MATERIAL']]
        self.assertEqual(self.intake.reads.get_entity('projects',pid)['code'],'DIAG-NEW')
        self.assertEqual(self.intake.reads.get_entity('materials',mid)['standard_unit'],'pcs')
        records=self.intake.reads.project_context(pid)['collections']['published_records']
        self.assertEqual(records[0]['material_id'],mid)
