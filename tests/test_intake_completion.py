"""Added-file rebase, explicit failure resolution and recovery, without live AI."""
import copy
import io
import unittest
from dataclasses import replace

from backend.app.schemas.analysis import RetryAnalysisRequest, DraftRecord
from backend.app.schemas.review import SelectReview, ResolveFile, ManualSubmission, RowEdit, ApproveSubmission, RevisionCommand
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.review_service import ReviewService
from tests import test_analysis as analysis_fixtures
from tests import test_review as review_fixtures
record = review_fixtures.record


class IntakeCompletionTests(unittest.TestCase):
    def fixture(self):
        f = analysis_fixtures.AnalysisTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.service.settings = replace(f.service.settings, models=(f.service.settings.models[-1],))
        return f

    def test_targeted_retry_skip_and_review_keep_other_failed_attempt_unchanged(self):
        f = self.fixture(); sources = f.intake.get(f.batch_id).submissions
        f.failures.update(('deepseek_flash', s.id) for s in sources)
        initial = f.start(); run = initial['runs'][0]
        self.assertEqual(run['status'], 'FAILED')
        revision = f.intake.get(f.batch_id).revision
        retried = f.service.retry(f.batch_id, initial['id'], run['id'], RetryAnalysisRequest(
            expected_revision=revision, idempotency_key='one-file-only', submission_ids=[sources[0].id]))
        current = retried['runs'][0]
        self.assertEqual(current['status'], 'PARTIAL')
        self.assertEqual(current['files'][0]['attempt'], 2)
        self.assertEqual(current['files'][1]['attempt'], 1)
        self.assertEqual(current['files'][1]['error'], run['files'][1]['error'])
        service = ReviewService(f.intake)
        service.resolve_file(f.batch_id, sources[1].id, ResolveFile(expected_revision=f.intake.get(f.batch_id).revision,
            resolution='SKIPPED', analysis_run_id=current['id']))
        self.assertTrue(f.service.get(f.batch_id,initial['id'])['runs'][0]['review_ready'])
        view = service.select(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,
            comparison_id=initial['id'], run_id=current['id']))
        skipped = next(s for s in view['review']['submissions'] if s['id'] == sources[1].id)
        self.assertEqual(skipped['resolution'],'SKIPPED'); self.assertEqual(skipped['rows'],[])
        self.assertFalse(view['publication_available'])
        self.assertEqual(f.intake.get(f.batch_id).comparisons[0].runs[0].files[1].error.code,'PROVIDER_RATE_LIMIT')

    def test_manual_replacement_retains_original_failure_and_has_no_document_source(self):
        f = self.fixture(); source = f.intake.get(f.batch_id).submissions[0]
        f.failures.add(('deepseek_flash',source.id)); result = f.start(); run = result['runs'][0]
        service = ReviewService(f.intake)
        view = service.manual(f.batch_id, ManualSubmission(expected_revision=f.intake.get(f.batch_id).revision,
            replaces_submission_id=source.id,analysis_run_id=run['id'],records=[record('PURCHASE_ORDER','25')]))
        replacement = next(s for s in view['review']['submissions'] if s['kind']=='MANUAL')
        stored = f.intake.get(f.batch_id)
        self.assertEqual(stored.submissions[0].manual_submission_id,replacement['id'])
        self.assertEqual(replacement['rows'][0]['provenance'],'OPERATOR_MANUAL')
        self.assertIsNone(replacement['rows'][0]['original'])
        self.assertIsNone(replacement['rows'][0]['current']['source_page'])
        view = service.rebase(f.batch_id, SelectReview(expected_revision=view['revision'],comparison_id=result['id'],run_id=run['id']))
        self.assertEqual(len(view['review']['submissions']),3)
        self.assertEqual(stored.comparisons[0].runs[0].files[0].status,'FAILED')
        service.resolve_file(f.batch_id,source.id,ResolveFile(expected_revision=view['revision'],resolution='ANALYSE'))
        restored=f.intake.get(f.batch_id)
        retained=next(s for s in restored.review.submissions if s.id==replacement['id'])
        self.assertEqual(retained.rows[0].current.quantity,'25')
        self.assertEqual(retained.rows[0].decision,'PENDING')
        self.assertIsNone(restored.submissions[0].manual_submission_id)

    def test_added_file_reuses_extraction_but_refreshes_comparison_and_preserves_edits(self):
        f=self.fixture(); result=f.start(); service=ReviewService(f.intake)
        view=service.select(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,
            comparison_id=result['id'],run_id=result['runs'][0]['id']))
        sub=view['review']['submissions'][0]; row=sub['rows'][0]
        changed=DraftRecord.model_validate(row['current']).model_copy(update={'quantity':'9.75','application':'HISTORY_ONLY'})
        view=service.row(f.batch_id,sub['id'],row['id'],RowEdit(expected_revision=view['revision'],current=changed,
            decision='ACCEPTED',assumptions_confirmed=True))
        original=copy.deepcopy(f.intake.get(f.batch_id).comparisons[0].model_dump(mode='json'))
        f.intake.add_files(f.batch_id,view['revision'],[('additional.txt',io.BytesIO(b'new diagnostic evidence'))])
        calls=len(f.log); updated=f.start('added-file')
        newcalls=f.log[calls:]
        self.assertEqual(len([c for c in newcalls if c['task']['stage']=='INTERPRET_FILE']),1)
        # Fresh reads allow exact-context reconciliation portions to be reused.
        self.assertEqual(len([c for c in newcalls if c['task']['stage']=='RECONCILE_FILE']),1)
        self.assertTrue(all(file['reused_from_run_id'] for file in updated['runs'][0]['files'][:2]))
        self.assertTrue(set(p['id'] for p in result['runs'][0]['proposals']).isdisjoint(p['id'] for p in updated['runs'][0]['proposals']))
        view=service.rebase(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,
            comparison_id=updated['id'],run_id=updated['runs'][0]['id']))
        saved=next(s for s in view['review']['submissions'] if s['id']==sub['id'])['rows'][0]
        self.assertEqual(saved['id'],row['id']);self.assertEqual(saved['current']['quantity'],'9.75')
        self.assertEqual(saved['original']['quantity'],'1.25'); self.assertEqual(saved['decision'],'ACCEPTED')
        self.assertEqual(len(view['review']['submissions']),3);self.assertEqual(view['warnings'],[])
        self.assertEqual(f.intake.get(f.batch_id).comparisons[0].model_dump(mode='json'),original)

    def test_unrelated_project_approval_survives_but_related_quantity_changes_invalidate(self):
        f=review_fixtures.ReviewTests();f.setUp();self.addCleanup(f.doCleanups)
        original_get=f.reads.get_entity; original_context=f.reads.project_context
        f.reads.get_entity=lambda kind,identity: {'id':'PRJ-002','name':'Another project'} if identity=='PRJ-002' else original_get(kind,identity)
        f.reads.project_context=lambda identity: {**original_context('PRJ-001'),'project':{'id':'PRJ-002','name':'Another project'}} if identity=='PRJ-002' else original_context(identity)
        view=f.manual([record('PURCHASE_ORDER','20')]);view=f.accept(view,application='HISTORY_ONLY')
        sid=view['review']['submissions'][0]['id']
        view=f.service.approve(f.batch.id,sid,ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        view=f.service.manual(f.batch.id,ManualSubmission(expected_revision=view['revision'],records=[record('PURCHASE_ORDER','5').model_copy(update={'project_ref':record().project_ref.model_copy(update={'id':'PRJ-002'})})]))
        self.assertTrue(view['approvals'][sid])
        view=f.service.manual(f.batch.id,ManualSubmission(expected_revision=view['revision'],records=[record('PURCHASE_ORDER','3')]))
        self.assertFalse(view['approvals'][sid])

    def test_fresh_analysis_with_exact_proposals_reconnects_edits_without_duplicate_rows(self):
        from backend.app.schemas.ingestion import ContextPatch
        f=self.fixture();result=f.start();service=ReviewService(f.intake)
        view=service.select(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,
            comparison_id=result['id'],run_id=result['runs'][0]['id']))
        sub=view['review']['submissions'][0];row=sub['rows'][0]
        view=service.row(f.batch_id,sub['id'],row['id'],RowEdit(expected_revision=view['revision'],
            current=DraftRecord.model_validate(row['current']).model_copy(update={'quantity':'9.75'}),decision='PENDING'))
        f.intake.patch_context(f.batch_id,ContextPatch(expected_revision=view['revision'],operator_notes='Additional context diagnostic'))
        refreshed=f.start('fresh-context')
        view=service.rebase(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,
            comparison_id=refreshed['id'],run_id=refreshed['runs'][0]['id']))
        saved=next(s for s in view['review']['submissions'] if s['id']==sub['id'])
        self.assertEqual(len(saved['rows']),1)
        self.assertEqual(saved['rows'][0]['id'],row['id'])
        self.assertEqual(saved['rows'][0]['current']['quantity'],'9.75')

    def test_restore_keeps_edits_clears_approvals_and_requires_current_manual_context(self):
        f=review_fixtures.ReviewTests();f.setUp();self.addCleanup(f.doCleanups)
        view=f.manual([record('PURCHASE_ORDER','12')]);view=f.accept(view,application='HISTORY_ONLY')
        sid=view['review']['submissions'][0]['id']
        view=f.service.approve(f.batch.id,sid,ApproveSubmission(expected_revision=view['revision'],preview_digest=view['preview_digest'],summary_confirmed=True))
        f.repo.rows.clear()
        restored=f.intake.restore(f.batch.id)
        self.assertEqual(restored.review.submissions[0].rows[0].current.quantity,'12')
        view=f.service.get(f.batch.id);self.assertFalse(view['approvals'][sid]);self.assertTrue(view['warnings'])
        view=f.service.refresh_manual_context(f.batch.id,RevisionCommand(expected_revision=view['revision']))
        self.assertEqual(view['warnings'],[]);self.assertFalse(view['approvals'][sid])

    def test_foreign_model_failure_cannot_skip_working_model_success(self):
        f=analysis_fixtures.AnalysisTests();f.setUp();self.addCleanup(f.doCleanups)
        source=f.intake.get(f.batch_id).submissions[0]
        f.failures.add(('gemini_flash',source.id));result=f.start();service=ReviewService(f.intake)
        view=service.select(f.batch_id,SelectReview(expected_revision=f.intake.get(f.batch_id).revision,
            comparison_id=result['id'],run_id=result['runs'][2]['id']))
        with self.assertRaises(IngestionError) as error:
            service.resolve_file(f.batch_id,source.id,ResolveFile(expected_revision=view['revision'],resolution='SKIPPED',analysis_run_id=result['runs'][0]['id']))
        self.assertEqual(error.exception.code,'MODEL_REVIEW_MISMATCH')
