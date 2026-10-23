"""Prepared recommendations remain drafts until one explicit file acceptance."""
import copy
import unittest

from backend.app.schemas.analysis import DraftRecord, FileDraft, ReconciliationAnalysis, ReconciliationResult
from backend.app.schemas.review import SelectReview, ApproveSubmission, RowEdit
from backend.app.services.review_service import ReviewService
from backend.app.services.review_preparation import prepare
from backend.app.services.ingestion_errors import IngestionError
from tests.test_review import Reads, record
from tests import test_analysis as fixtures


class PreparedReviewTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AnalysisTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        result = self.f.start()
        self.f.intake.reads = Reads()
        self.service = ReviewService(self.f.intake)
        def diagnostic(batch):
            run = batch.comparisons[0].runs[-1]
            for i, file in enumerate(run.files):
                value = record('ON_HAND_INVENTORY' if i == 0 else 'REMAINING_LOCAL_REQUIREMENT', '100' if i == 0 else '40')
                value.application = 'UNDECIDED'
                file.draft = FileDraft(extraction_version='MATERIAL_V2', document_type='INVENTORY', summary='Diagnostic',
                    records=[value], project_info=[{'project_ref':{'kind':'EXISTING','id':'PRJ-001'},'name':'Project A','association_explanation':'Source identifies the existing project.'}])
                file.reconciliation = ReconciliationAnalysis(status='SUCCEEDED', result=ReconciliationResult(summary='Diagnostic',
                    projects=[{'project_info_index':0,'explanation':'Same project'}],
                    materials=[{'record_index':0,'relationship':'NEW_INFORMATION','suggested_treatment':'ADD','explanation':'Separate diagnostic observation.'}]))
        self.f.intake.update_analysis(self.f.batch_id, diagnostic)
        b = self.f.intake.get(self.f.batch_id)
        self.original = b.comparisons[0].model_dump(mode='json')
        self.view = self.service.prepare(b.id, SelectReview(expected_revision=b.revision, comparison_id=result['id'], run_id=result['runs'][-1]['id']))

    def approve(self, view, index):
        return self.service.approve(self.f.batch_id, view['review']['submissions'][index]['id'], ApproveSubmission(
            expected_revision=view['revision'], preview_digest=view['preview_digest'], summary_confirmed=True, accept_recommendations=True))

    def test_prepared_values_are_not_human_approved_or_operational(self):
        v = self.view
        self.assertTrue(v['prepared']); self.assertFalse(any(v['approvals'].values()))
        self.assertFalse(any(v['blockers'].values()), v['blockers'])
        self.assertEqual(v['groups'][0]['calculated_potential_surplus'], '60')
        self.assertEqual(v['review']['confirmed_stock_scopes'], [])
        for sub in v['review']['submissions']:
            self.assertFalse(sub['projects'][0]['confirmed'])
            self.assertEqual(sub['rows'][0]['decision'], 'PENDING')
            self.assertFalse(sub['rows'][0]['edited_by_operator'])
        self.assertEqual(self.f.intake.get(self.f.batch_id).comparisons[0].model_dump(mode='json'), self.original)

    def test_one_click_file_approval_accepts_its_values_and_keeps_prior_approval(self):
        first = self.approve(self.view, 0)
        self.assertEqual(list(first['approvals'].values()), [True, False])
        final = self.approve(first, 1)
        self.assertTrue(all(final['approvals'].values()))
        self.assertTrue(final['publication_available'])
        self.assertTrue(all(r['decision']=='ACCEPTED' for s in final['review']['submissions'] for r in s['rows']))

    def test_legacy_approval_command_cannot_accept_prepared_confirmation(self):
        v = self.view
        with self.assertRaises(IngestionError) as caught:
            self.service.approve(self.f.batch_id,v['review']['submissions'][0]['id'],ApproveSubmission(
                expected_revision=v['revision'],preview_digest=v['preview_digest'],summary_confirmed=True))
        self.assertEqual(caught.exception.code,'PREPARED_CONFIRMATION_REQUIRED')

    def test_edit_and_changed_database_invalidate_approval(self):
        v = self.approve(self.view,0); row = v['review']['submissions'][0]['rows'][0]
        value = DraftRecord.model_validate(row['current']);value.quantity='120'
        v = self.service.row(self.f.batch_id,v['review']['submissions'][0]['id'],row['id'],RowEdit(
            expected_revision=v['revision'],current=value,decision='PENDING'))
        self.assertFalse(v['approvals'][v['review']['submissions'][0]['id']])
        self.assertEqual(v['groups'][0]['calculated_potential_surplus'],'80')
        self.assertTrue(v['review']['submissions'][0]['rows'][0]['edited_by_operator'])
        self.f.intake.reads.context['project']['name']='Changed externally'
        with self.assertRaises(IngestionError) as caught:self.approve(v,0)
        self.assertEqual(caught.exception.code,'PREVIEW_STALE')

    def test_true_specification_conflict_stays_blocked(self):
        v=self.view;row=v['review']['submissions'][0]['rows'][0]
        value=DraftRecord.model_validate(row['current']);value.specifications={'thickness_mm':'80'}
        v=self.service.row(self.f.batch_id,v['review']['submissions'][0]['id'],row['id'],RowEdit(
            expected_revision=v['revision'],current=value,decision='PENDING'))
        self.assertTrue(any('Specifications differ' in m for b in v['blockers'][v['review']['submissions'][0]['id']] for m in b['messages']))
        with self.assertRaises(IngestionError):self.approve(v,0)

    def test_preparation_preserves_explicit_operator_treatment(self):
        b=self.f.intake.get(self.f.batch_id);row=b.review.submissions[0].rows[0]
        row.edited_by_operator=True;row.current.application='HISTORY_ONLY';row.preparation={}
        prepare(self.service,b)
        self.assertEqual(row.current.application,'HISTORY_ONLY')

    def test_exact_replacement_ignores_stock_head_reference_and_preserves_old_output(self):
        b=self.f.intake.get(self.f.batch_id);row=b.review.submissions[0].rows[0];row.preparation={}
        row.current.application='UNDECIDED'
        self.f.intake.reads.context['collections']['published_records']=[{
            'id':'PMR-prior','project_id':'PRJ-001','material_id':'MAT-001','application':'ADD',
            'quantity':'80','unit':'pcs','record_kind':'ON_HAND_INVENTORY','source':{'submission_id':'old'}}]
        f=b.comparisons[0].runs[-1].files[0]
        item=f.reconciliation.result.materials[0]
        item.relationship='NEWER_OBSERVATION';item.suggested_treatment='REPLACE'
        from backend.app.schemas.analysis import StoredRecordRef
        item.existing_records=[StoredRecordRef(project_id='PRJ-001',collection='published_records',record_id='PMR-prior'),
                               StoredRecordRef(project_id='PRJ-001',collection='stock_heads',record_id='STOCK-prior')]
        # Revalidate typed references assigned for this diagnostic.
        f.reconciliation.result=ReconciliationResult.model_validate(f.reconciliation.result.model_dump(mode='json'))
        prepare(self.service,b)
        self.assertEqual(row.current.replaces_record_ids,['PMR-prior'])
        self.assertEqual(row.current.application,'REPLACE')
        self.assertFalse(row.edited_by_operator)

    def test_conversion_uses_only_same_product_explicit_factor(self):
        b=self.f.intake.get(self.f.batch_id);row=b.review.submissions[0].rows[0]
        row.current.unit='m2';row.current.quantity='3.125';row.preparation={};row.current.application='UNDECIDED'
        evidence=b.review.submissions[1].rows[0]
        evidence.original.specifications={'nominal_coverage':'32 pcs per 1 m² of nominal coverage'}
        prepare(self.service,b)
        self.assertIsNotNone(row.conversion)
        self.assertEqual(row.conversion.factor,'32');self.assertFalse(row.conversion.confirmed)
        self.assertEqual(row.current.quantity,'3.125');self.assertEqual(row.current.unit,'m2')
        self.assertIn('conversion_evidence_row',row.preparation)

    def test_conflicting_conversion_factors_are_not_guessed(self):
        b=self.f.intake.get(self.f.batch_id);row=b.review.submissions[0].rows[0]
        row.current.unit='m2';row.preparation={};row.current.application='UNDECIDED'
        row.original.specifications={'coverage':'20 pcs per m²'}
        b.review.submissions[1].rows[0].original.specifications={'coverage':'32 pcs per m²'}
        prepare(self.service,b)
        self.assertIsNone(row.conversion)

    def test_source_gap_mapping_does_not_calculate_or_change_quantity(self):
        b=self.f.intake.get(self.f.batch_id);row=b.review.submissions[0].rows[0]
        row.preparation={};row.current.application='UNDECIDED';row.current.record_kind='REMAINING_LOCAL_REQUIREMENT'
        row.current.raw_fields={'quantity_column':'Outstanding gap','gap_basis':'net of usable local stock','receipt_window':'23 October - 27 November 2026'}
        prepare(self.service,b)
        self.assertEqual(row.current.record_kind,'OUTSTANDING_DEMAND')
        self.assertEqual(row.current.quantity,'100')
        self.assertEqual(str(row.current.needed_from),'2026-10-23')


    def test_repreparation_preserves_declined_project_correction(self):
        from backend.app.schemas.review import ProjectEdit
        from datetime import date
        batch=self.f.intake.get(self.f.batch_id)
        project=batch.review.submissions[0].projects[0]
        project.current.end_date=date(2026,12,11)
        project.original=project.current.model_copy(deep=True)
        project.master_updates={'target_end_date':'2026-12-11'}
        self.f.intake.reads.context['project']['target_end_date']='2026-12-04'
        self.f.intake.update_analysis(batch.id,lambda saved:setattr(saved,'review',batch.review))
        view=self.service.get(batch.id)
        view=self.service.project(batch.id,view['review']['submissions'][0]['id'],project.id,
            ProjectEdit(expected_revision=view['revision'],current=project.current,confirmed=False,master_updates={}))
        saved=self.f.intake.get(batch.id)
        prepare(self.service,saved)
        self.assertEqual(saved.review.submissions[0].projects[0].master_updates,{})

    def test_same_product_code_never_overwrites_physical_conflict(self):
        batch=self.f.intake.get(self.f.batch_id)
        row=batch.review.submissions[0].rows[0]
        row.current.specifications={'thickness_mm':'60','type':'paver'}
        row.current.raw_fields={'product_reference':'PV80'}
        original_get=self.f.intake.reads.get_entity
        self.f.intake.reads.get_entity=lambda kind,identity: {'id':'MAT-001','standard_unit':'pcs','reference_code':'PV80','specifications':{'thickness_mm':'80','type':'concrete paver'}} if kind=='materials' else original_get(kind,identity)
        from backend.app.services.review_preparation import prepare_material
        before=row.current.specifications.copy()
        prepare_material(self.service,batch.review,row)
        self.assertEqual(row.current.specifications,before)

    def test_operator_project_association_does_not_need_invented_model_explanation(self):
        from backend.app.schemas.review import ProjectEdit
        view=self.view;sub=view['review']['submissions'][0];project=sub['projects'][0]
        current=project['current'].copy();current['association_explanation']=''
        view=self.service.project(self.f.batch_id,sub['id'],project['id'],ProjectEdit(
            expected_revision=view['revision'],current=current,confirmed=False))
        self.assertFalse(view['blockers'][sub['id']],view['blockers'])
        view=self.approve(view,0)
        self.assertTrue(view['approvals'][sub['id']])
