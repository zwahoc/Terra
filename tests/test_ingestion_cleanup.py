"""Regression contracts for the bounded pre-review cleanup."""
import unittest
from pydantic import ValidationError
from backend.app.schemas.analysis import DocumentClassification,FileDraft
from backend.app.services.analysis_prompts import PromptBundle
from backend.app.services.analysis_coverage import numbered_table_references,validate_pdf_coverage
from backend.app.services.ingestion_errors import IngestionError

class CleanupTests(unittest.TestCase):
 def test_coherent_primary_document_routes_multiple_trusted_modules(self):
  obj=DocumentClassification(primary_family='MATERIAL_MOVEMENT',applicable_families=['MATERIAL_MOVEMENT','INVENTORY','DEMAND'],basis='One integrated statement')
  self.assertEqual(PromptBundle().route(obj),['families/inventory.md','families/material_movement.md','families/demand.md'])
  with self.assertRaises(ValidationError):DocumentClassification(primary_family='MATERIAL_MOVEMENT',applicable_families=['INVENTORY'],basis='Missing primary')
  with self.assertRaises(ValidationError):DocumentClassification(primary_family='OTHER',applicable_families=['INVENTORY'],basis='Invalid generic')
 def test_mrs_table_headers_detect_numbered_rows_and_block_omission(self):
  refs=numbered_table_references('REF PO REF MATERIAL / SPECIFICATION UNIT OPEN RECD. USED CLOSE LOCAL NEED VAR. ASSESS.\nM01 P01 First\nM02 P02 Second\nM03 P03 Third')
  self.assertEqual(refs,['M01','M02','M03'])
  draft=FileDraft(document_type='INVENTORY',summary='Incomplete',page_coverage=[1],records=[{'raw_description':'First','source_page':1,'source_item_ref':'M01'}])
  with self.assertRaises(IngestionError):validate_pdf_coverage(draft,{1:refs},[1])
  self.assertEqual(numbered_table_references('Arbitrary references\nM01 First\nM02 Second\nM03 Third'),[])
 def test_all_extraction_routes_carry_structured_observation_and_unknown_spec_rules(self):
  prompts=PromptBundle()
  for module in ['generic','inventory','purchase_order','material_movement']:
   system=prompts.compose('INTERPRET_FILE',[f'families/{module}.md'])
   self.assertIn('retaining LOCAL NEED only in raw_fields is insufficient',system)
   self.assertIn('absent catalogue attribute is unknown',system)
