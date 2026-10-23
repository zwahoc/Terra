"""Read-only editor previews and manual conversion retention, no provider calls."""
import unittest
from datetime import date
from decimal import Decimal
from backend.app.schemas.review import EditorPreview, ManualSubmission, Conversion, RowEdit
from backend.app.services.material_editor import editor_preview
from backend.app.services.ingestion_errors import IngestionError
from tests import test_review as review_fixtures
record = review_fixtures.record


class MaterialEditorTests(unittest.TestCase):
    setUp = review_fixtures.ReviewTests.setUp
    # Reuse the established in-memory service setup without provider/model calls.
    def preview(self, value=None, conversion=None, revision=None):
        return editor_preview(self.service,self.batch.id,EditorPreview(
            expected_revision=revision or self.intake.get(self.batch.id).revision,
            current=value or record(),conversion=conversion))

    def test_exact_conversion_preview_never_saves_or_approves(self):
        before=self.intake.get(self.batch.id).model_dump(mode='json')
        result=self.preview(record(quantity='2.5').model_copy(update={'unit':'m²'}),Conversion(to_unit='pcs',factor='32',basis='Product coverage',confirmed=False))
        self.assertEqual(result['quantity'],'80');self.assertEqual(result['unit'],'pcs')
        self.assertFalse(result['questions']);self.assertFalse(result['operational_writes'])
        self.assertEqual(before,self.intake.get(self.batch.id).model_dump(mode='json'))

    def test_fractional_pieces_are_not_rounded(self):
        result=self.preview(record(quantity='0.1'),Conversion(to_unit='pcs',factor='3',basis='Documented example'))
        self.assertEqual(result['quantity'],'0.3')
        self.assertTrue(any('whole counts' in q for q in result['questions']))

    def test_mismatch_stale_revision_and_decimal_bounds(self):
        result=self.preview(record().model_copy(update={'unit':'m²'}))
        self.assertTrue(any('units differ' in q for q in result['questions']))
        result=self.preview(record(quantity='0.0000001').model_copy(update={'unit':'m'}))
        self.assertTrue(any('six decimal places' in q for q in result['questions']))
        with self.assertRaises(IngestionError):self.preview(revision=999)

    def test_predecessors_are_exact_effective_not_superseded(self):
        item={'id':'prior','material_id':'MAT-001','record_kind':'ON_HAND_INVENTORY','unit':'pcs','quantity':'80','application':'ADD','effective_date':'2026-10-20','source':{'label':'Earlier count'}}
        self.reads.context['collections']['published_records']=[item,{**item,'id':'wrong-material','material_id':'MAT-002'},
            {**item,'id':'wrong-kind','record_kind':'OUTSTANDING_DEMAND'}, {**item,'id':'wrong-unit','unit':'m'},
            {**item,'id':'history','application':'HISTORY_ONLY'}, {**item,'id':'superseded'}]
        self.reads.context['collections']['superseded_records']=[{'id':'superseded','successor_id':'prior'}]
        candidates=self.preview()['predecessors']
        self.assertEqual([r['id'] for r in candidates],['prior']);self.assertEqual(candidates[0]['source'],'Earlier count')

    def test_manual_conversion_retained_but_confirmation_not_inferred(self):
        result=self.service.manual(self.batch.id,ManualSubmission(expected_revision=1,prepared=True,
            records=[record(quantity='2.5').model_copy(update={'unit':'m²','effective_date':date(2026,10,23)})],
            conversions=[Conversion(to_unit='pcs',factor='32',basis='Product coverage',confirmed=True)]))
        row=result['review']['submissions'][0]['rows'][0]
        self.assertEqual(row['conversion']['factor'],'32');self.assertFalse(row['conversion']['confirmed'])
        self.assertEqual(row['provenance'],'OPERATOR_MANUAL');self.assertIsNone(row['original'])
        self.assertFalse(any(result['approvals'].values()));self.assertEqual(Decimal(result['effective_rows'][row['id']]['quantity']),Decimal('80'))

    def test_manual_conversion_length_failure_is_atomic(self):
        before=self.intake.get(self.batch.id).model_dump(mode='json')
        with self.assertRaises(IngestionError):
            self.service.manual(self.batch.id,ManualSubmission(expected_revision=1,records=[record(),record()],conversions=[None]))
        self.assertEqual(before,self.intake.get(self.batch.id).model_dump(mode='json'))

    def test_editor_endpoint_is_local_read_only_and_revision_guarded(self):
        from backend.app.main import app
        from backend.app.routes.review import service
        from tests.test_ingestion import json_request
        app.dependency_overrides[service]=lambda:self.service
        self.addCleanup(app.dependency_overrides.clear)
        path=f'/api/ingestion/batches/{self.batch.id}/review/editor-preview'
        payload={'expected_revision':1,'current':record().model_dump(mode='json')}
        status,value=json_request('POST',path,payload)
        self.assertEqual(status,200);self.assertFalse(value['meta']['operational_writes'])
        status,_=json_request('POST',path,payload,client='192.168.1.10');self.assertEqual(status,403)
        status,_=json_request('POST',path,{**payload,'expected_revision':99});self.assertEqual(status,409)
