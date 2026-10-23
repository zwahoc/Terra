"""Phase 4 state/revision/calculation proofs without provider or operational writes."""
import copy
import io
import unittest
from pathlib import Path
import tempfile
from backend.app.schemas.analysis import DraftRecord
from backend.app.schemas.review import ManualSubmission, RowEdit, ScopeConfirmation, ApproveSubmission, SelectReview
from backend.app.services.review_service import ReviewService
from backend.app.services.review_calculations import preview_groups,group_id
from backend.app.services.ingestion_service import IntakeService
from backend.app.services.ingestion_storage import SourceStore
from backend.app.services.ingestion_errors import IngestionError
from tests.test_ingestion import MemoryDraftRepository
from tests import test_analysis as fixtures


class Reads:
    def __init__(self):
        self.context = {'project': {'id':'PRJ-001','name':'Project A'}, 'collections': {
            'documents': [], 'extracted_rows': [], 'materials':[], 'supply_offers': [], 'demand_requests': [],
            'demand_commitments': [], 'allocation_proposals': [], 'transfers': []}}
    def get_entity(self, kind, identity):
        if identity == 'PRJ-001': return self.context['project']
        if identity == 'MAT-001': return {'id':'MAT-001','standard_unit':'pcs','specifications':{'thickness_mm':60}}
        return None
    def project_context(self, identity):
        if identity != 'PRJ-001': raise IngestionError('PROJECT_NOT_FOUND','Missing',404)
        return copy.deepcopy(self.context)


def record(kind='ON_HAND_INVENTORY',quantity='100', **values):
    return DraftRecord(raw_description='Operator supplied material', material_name='Paver',
        project_ref={'kind':'EXISTING','id':'PRJ-001'}, material_ref={'kind':'EXISTING','id':'MAT-001'},
        record_kind=kind,quantity_basis='MATERIAL',quantity=quantity,unit='pcs',application='ADD',**values)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.repo=MemoryDraftRepository();self.reads=Reads()
        self.intake=IntakeService(self.repo,self.reads,SourceStore(Path(self.temp.name)))
        self.batch=self.intake.create();self.service=ReviewService(self.intake)

    def manual(self,rows):
        return self.service.manual(self.batch.id,ManualSubmission(expected_revision=self.intake.get(self.batch.id).revision,records=rows))

    def accept(self,view,index=0,**updates):
        sub=view['review']['submissions'][0]; row=sub['rows'][index]
        current=DraftRecord.model_validate(row['current']).model_copy(update=updates)
        return self.service.row(self.batch.id,sub['id'],row['id'],RowEdit(expected_revision=view['revision'],current=current,
            decision='ACCEPTED',assumptions_confirmed=True))

    def test_manual_edit_calculation_revision_approval_and_checkpoint(self):
        view=self.manual([record(),record('REMAINING_LOCAL_REQUIREMENT','40')])
        self.assertEqual(view['review']['submissions'][0]['kind'],'MANUAL')
        view=self.accept(view);view=self.accept(view,1)
        scope=view['groups'][0]['id']
        self.assertIsNone(view['groups'][0]['calculated_potential_surplus'])
        view=self.service.scopes(self.batch.id,ScopeConfirmation(expected_revision=view['revision'],scopes=[scope]))
        self.assertEqual(view['groups'][0]['calculated_potential_surplus'],'60')
        sub=view['review']['submissions'][0]
        view=self.service.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        self.assertTrue(view['approvals'][sub['id']]);self.assertTrue(view['publication_available'])
        view=self.accept(view,quantity='120')
        self.assertIsNone(view['groups'][0]['calculated_potential_surplus'])
        view=self.service.scopes(self.batch.id,ScopeConfirmation(expected_revision=view['revision'],scopes=[scope]))
        self.assertEqual(view['groups'][0]['calculated_potential_surplus'],'80')
        self.assertFalse(view['approvals'][sub['id']])
        self.assertEqual(self.intake.store.recoverable(self.batch.id).review.submissions[0].rows[0].current.quantity,'120')
        self.assertTrue(all(r['provenance']=='OPERATOR_MANUAL' for r in sub['rows']))
        self.assertEqual(self.reads.context['collections']['extracted_rows'],[])

    def test_stale_revision_and_context_digest_reject_approval(self):
        view=self.manual([record()]);view=self.accept(view);sub=view['review']['submissions'][0]
        command=ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True)
        self.reads.context['project']['name']='Changed project'
        with self.assertRaises(IngestionError) as error:self.service.approve(self.batch.id,sub['id'],command)
        self.assertEqual(error.exception.code,'PREVIEW_STALE')
        with self.assertRaises(IngestionError):self.service.manual(self.batch.id,ManualSubmission(expected_revision=1))

    def test_release_confirmation_must_be_renewed_after_identity_change(self):
        view=self.manual([record('CONFIRMED_SURPLUS','10')]);sub=view['review']['submissions'][0];row=sub['rows'][0]
        command=lambda v,current:RowEdit(expected_revision=v['revision'],current=current,decision='ACCEPTED',assumptions_confirmed=True,release_confirmed=True)
        view=self.service.row(self.batch.id,sub['id'],row['id'],command(view,DraftRecord.model_validate(row['current'])))
        self.assertTrue(view['review']['submissions'][0]['rows'][0]['release_confirmed'])
        changed=DraftRecord.model_validate({**row['current'],'specifications':{'thickness_mm':'80'}})
        view=self.service.row(self.batch.id,sub['id'],row['id'],command(view,changed))
        self.assertFalse(view['review']['submissions'][0]['rows'][0]['release_confirmed'])

    def test_manual_cannot_claim_document_provenance_and_exclusion_resolves_unknown(self):
        with self.assertRaises(IngestionError):self.manual([record(source_page=1)])
        view=self.manual([DraftRecord(raw_description='Unclear material')]);sub=view['review']['submissions'][0];row=sub['rows'][0]
        view=self.service.row(self.batch.id,sub['id'],row['id'],RowEdit(expected_revision=view['revision'],current=DraftRecord.model_validate(row['current']),decision='EXCLUDED'))
        self.assertEqual(view['blockers'][sub['id']],[])
        view=self.service.approve(self.batch.id,sub['id'],ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        self.assertTrue(view['approvals'][sub['id']]);self.assertEqual(view['groups'],[])

    def test_replace_legacy_stock_retains_history_and_blocks_active_transfer(self):
        self.reads.context['collections']['extracted_rows']=[{'id':'ROW-old','document_id':'DOC-old','suggested_material_id':'MAT-001',
            'review_status':'ACCEPTED','parsed_fields':{'record_kind':'ON_HAND_INVENTORY','quantity':100,'unit':'pcs'}}]
        view=self.manual([record(quantity='120')]);view=self.accept(view,application='REPLACE',replaces_record_ids=['ROW-old'])
        self.assertEqual(view['groups'][0]['on_hand_observations'],'120')
        self.reads.context['collections'].update(supply_offers=[{'id':'SUP-old','material_id':'MAT-001','unit':'pcs','reserved_active_quantity':10}],
            allocation_proposals=[{'id':'ALC-old','supply_offer_id':'SUP-old'}],transfers=[{'proposal_id':'ALC-old','status':'IN_TRANSIT'}])
        view=self.service.get(self.batch.id)
        self.assertTrue(any('active transfer' in msg for e in view['blockers'][view['review']['submissions'][0]['id']] for msg in e['messages']))
        self.assertEqual(self.reads.context['collections']['extracted_rows'][0]['parsed_fields']['quantity'],100)

    def test_conversion_required_for_effective_row_and_exact_arithmetic(self):
        from backend.app.schemas.review import Conversion
        view=self.manual([record(quantity='0.1')]);view=self.accept(view,unit='bag');sub=view['review']['submissions'][0];row=sub['rows'][0]
        self.assertTrue(view['blockers'][sub['id']])
        view=self.service.row(self.batch.id,sub['id'],row['id'],RowEdit(expected_revision=view['revision'],
            current=DraftRecord.model_validate(row['current']),decision='ACCEPTED',assumptions_confirmed=True,
            conversion=Conversion(to_unit='pcs',factor='3',basis='Operator confirmed packaging',confirmed=True)))
        self.assertEqual(view['groups'][0]['on_hand_observations'],'0.3')

    def test_select_working_analysis_preserves_original_and_never_overwrites_edits(self):
        f=fixtures.AnalysisTests();f.setUp();self.addCleanup(f.doCleanups)
        value=f.start();service=ReviewService(f.intake)
        original=f.intake.get(f.batch_id).comparisons[0].model_dump(mode='json')
        view=service.select(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,comparison_id=value['id'],run_id=value['runs'][2]['id']))
        self.assertEqual(view['review']['run_id'],value['runs'][2]['id'])
        self.assertEqual(f.intake.get(f.batch_id).comparisons[0].model_dump(mode='json'),original)
        with self.assertRaises(IngestionError):service.select(f.batch_id,SelectReview(expected_revision=view['revision'],comparison_id=value['id'],run_id=value['runs'][1]['id']))

    def test_net_demand_not_double_subtracted_and_incoming_commitments_count_once(self):
        ctx={'PRJ-001':{'collections':{'supply_offers':[], 'demand_requests':[{'id':'DEM-old','material_id':'MAT-001','unit':'pcs'}],
            'demand_commitments':[{'demand_request_id':'DEM-old','committed_incoming_quantity':15}]}}}
        rows=[{'id':str(i),'project':'PRJ-001','material':'MAT-001','unit':'pcs','quantity':q,'kind':kind} for i,(kind,q) in enumerate([
            ('ON_HAND_INVENTORY','20'),('REMAINING_LOCAL_REQUIREMENT','70'),('OUTSTANDING_DEMAND','50'),('POTENTIAL_SURPLUS','5')])]
        gid=group_id('PRJ-001','MAT-001','pcs');group=preview_groups(rows,ctx,[gid])[0]
        self.assertEqual(group['newly_allocatable_demand'],'35')
        self.assertEqual(group['on_hand_observations'],'20')
        self.assertFalse(group['reservable_offer_created'])


    def test_same_batch_replacement_and_history_only_preserve_originals(self):
        view=self.manual([record(quantity='100'),record(quantity='120')])
        view=self.accept(view,0)
        target=view['review']['submissions'][0]['rows'][0]['id']
        view=self.accept(view,1,application='REPLACE',replaces_record_ids=[target])
        self.assertEqual(view['groups'][0]['on_hand_observations'],'120')
        self.assertEqual(view['review']['submissions'][0]['rows'][0]['current']['quantity'],'100')
        view=self.accept(view,1,application='HISTORY_ONLY',replaces_record_ids=[])
        self.assertEqual(view['groups'][0]['on_hand_observations'],'100')

    def test_confirmed_surplus_cannot_be_approved_without_verified_stock(self):
        view=self.manual([record('CONFIRMED_SURPLUS','30',available_from='2026-10-18')])
        view=self.accept(view)
        sid=view['review']['submissions'][0]['id']
        self.assertTrue(any('verified complete stock' in m for e in view['blockers'][sid] for m in e['messages']))
        with self.assertRaises(IngestionError):self.service.approve(self.batch.id,sid,ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))

    def test_http_manual_review_local_only_and_no_publication_route(self):
        from backend.app.main import app
        from backend.app.routes.review import service
        from tests.test_ingestion import json_request
        app.dependency_overrides[service]=lambda:self.service
        self.addCleanup(app.dependency_overrides.clear)
        path=f'/api/ingestion/batches/{self.batch.id}'
        status,response=json_request('POST',path+'/manual-submissions',{'expected_revision':1,'records':[record().model_dump(mode='json')]})
        self.assertEqual(status,200);self.assertFalse(response['data']['operational_writes'])
        self.assertEqual(response['meta']['stage'],'DRAFT_REVIEW')
        status,response=json_request('GET',path+'/review')
        self.assertEqual(status,200);self.assertEqual(response['data']['review']['submissions'][0]['kind'],'MANUAL')
        status,_=json_request('GET',path+'/review',client='192.168.1.10')
        self.assertEqual(status,403)
        self.assertTrue(any(path.endswith('/publish') for path in app.openapi()['paths']), 'Phase 5 adds a separately guarded publication action')
