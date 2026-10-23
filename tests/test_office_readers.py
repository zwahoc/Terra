"""Generic OOXML diagnostics generated only in temporary test directories."""
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from backend.app.services.ingestion_content import InitialContentReader
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_storage import SourceStore
from tests import test_analysis as fixtures

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'


def package(parts):
    data=io.BytesIO()
    with ZipFile(data,'w') as archive:
        for name,body in parts.items(): archive.writestr(name,body)
    return data.getvalue()


def word_parts():
    picture=io.BytesIO()
    with Image.new('RGB',(3,3),'white') as image: image.save(picture,'PNG')
    return {'word/document.xml':f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Diagnostic title</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>1.25</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
            'word/header1.xml':f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Header diagnostic</w:t></w:r></w:p></w:hdr>',
            'word/media/image1.png':picture.getvalue()}


def excel_parts():
    return {'xl/workbook.xml':f'<workbook xmlns="{S}" xmlns:r="{R}"><workbookPr date1904="1"/><sheets><sheet name="Diagnostic A" sheetId="1" r:id="rId1"/><sheet name="Hidden B" state="hidden" sheetId="2" r:id="rId2"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels':f'<Relationships xmlns="{P}"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>',
        'xl/sharedStrings.xml':f'<sst xmlns="{S}"><si><t>Diagnostic label</t></si></sst>',
        'xl/worksheets/sheet1.xml':f'<worksheet xmlns="{S}"><sheetData><row r="5" hidden="1"><c r="A5" t="s"><v>0</v></c><c r="B5"><v>1.25</v></c><c r="C5"><f>B5*2</f><v>2.5</v></c><c r="D5"><f>B5*3</f></c></row></sheetData><mergeCells><mergeCell ref="A1:B1"/></mergeCells></worksheet>',
        'xl/worksheets/sheet2.xml':f'<worksheet xmlns="{S}"><sheetData><row r="9"><c r="A9" t="inlineStr"><is><t>Hidden evidence</t></is></c></row></sheetData></worksheet>'}


class OfficeReaderTests(unittest.TestCase):
    def prepare(self,filename,parts):
        temp=tempfile.TemporaryDirectory(prefix='terra office 材料 ');self.addCleanup(temp.cleanup)
        store=SourceStore(Path(temp.name));raw=package(parts)
        source=store.put(io.BytesIO(raw),filename);path=store.path(source)
        result=InitialContentReader().prepare(source,path)
        self.assertEqual(path.read_bytes(),raw)
        return result

    def test_word_tables_headers_images_and_original_paragraph_locators(self):
        result=self.prepare('diagnostic.docx',word_parts())
        self.assertEqual(result.kind,'TEXT');self.assertIn('Diagnostic title',result.text)
        self.assertIn('table-row=1 cell=1',result.text);self.assertIn('1.25',result.text)
        self.assertIn('Header diagnostic',result.text)
        self.assertIn('word/document.xml#paragraph-2',result.metadata['locators'])
        self.assertFalse(result.metadata['rendered_pages'])
        self.assertEqual(len(result.attachments),1);self.assertEqual(result.attachments[0]['media_type'],'image/png')

    def test_all_excel_sheets_hidden_rows_formula_cache_and_cell_addresses_survive(self):
        result=self.prepare('diagnostic.xlsx',excel_parts())
        self.assertEqual(result.kind,'CELLS');self.assertEqual(result.metadata['date_system'],'1904')
        self.assertEqual(result.cells[1],['Diagnostic A','A5','Diagnostic label','','builtin:0','1'])
        self.assertIn(['Diagnostic A','C5','2.5','=B5*2','builtin:0','1'],result.cells)
        self.assertIn(['Hidden B','A9','Hidden evidence','','builtin:0','0'],result.cells)
        self.assertEqual(result.metadata['formulas_without_cached_values'],["'Diagnostic A'!D5"])
        self.assertFalse(result.metadata['formula_execution'])
        self.assertIn("'Hidden B'!A9",result.metadata['locators'])

    def test_xlsm_reads_values_without_executing_vba(self):
        parts=excel_parts();parts['xl/vbaProject.bin']=b'NOT EXECUTABLE DIAGNOSTIC'
        result=self.prepare('diagnostic.xlsm',parts)
        self.assertEqual(result.metadata['format'],'XLSM');self.assertTrue(result.cells)

    def test_unsupported_embedded_objects_do_not_yield_partial_success(self):
        parts=word_parts();parts['word/embeddings/object.bin']=b'opaque'
        with self.assertRaises(IngestionError) as error:self.prepare('diagnostic.docx',parts)
        self.assertEqual(error.exception.code,'OFFICE_CONTENT_UNSUPPORTED')
        parts=excel_parts();parts['xl/charts/chart1.xml']='<chart/>'
        with self.assertRaises(IngestionError):self.prepare('diagnostic.xlsx',parts)

    def test_invalid_or_entity_xml_fails_without_fetching_external_data(self):
        with self.assertRaises(IngestionError) as error:self.prepare('diagnostic.docx',{'word/document.xml':'<!DOCTYPE a [<!ENTITY ext SYSTEM "https://example.invalid/secret">]><a/>'})
        self.assertEqual(error.exception.code,'OFFICE_INVALID')
        with self.assertRaises(IngestionError):self.prepare('diagnostic.xlsx',{'xl/workbook.xml':'<broken'})

    def test_office_evidence_reaches_classifier_and_extractor_without_fake_pages(self):
        f=fixtures.AnalysisTests();f.setUp();self.addCleanup(f.doCleanups)
        f.service.settings=replace(f.service.settings,models=(f.service.settings.models[-1],))
        f.intake.add_files(f.batch_id,f.intake.get(f.batch_id).revision,[('diagnostic.xlsx',io.BytesIO(package(excel_parts())))])
        value=f.start();source=f.intake.get(f.batch_id).submissions[-1]
        file=next(file for file in value['runs'][0]['files'] if file['submission_id']==source.id)
        self.assertEqual(file['status'],'SUCCEEDED');self.assertIsNone(file['preparation'])
        self.assertEqual(file['reader_metadata']['format'],'XLSX')
        tasks=[entry['task'] for entry in f.log if entry['task'].get('submission_id')==source.id]
        self.assertEqual({task['stage'] for task in tasks},{'CLASSIFY_FILE','INTERPRET_FILE','RECONCILE_FILE'})
        for task in tasks:
            if task['stage'] in ('CLASSIFY_FILE','INTERPRET_FILE'):
                self.assertIn("'Hidden B'!A9",task['reader_metadata']['locators'])
                self.assertTrue(task['cells']);self.assertIsNone(task['content_preparation'])

    def test_embedded_image_labels_are_sent_by_both_provider_protocols(self):
        from backend.app.services.analysis_providers import ProviderAdapter
        from backend.app.services.analysis_budget import BudgetLedger
        result=self.prepare('diagnostic.docx',word_parts())
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        config=fixtures.settings();ledger=BudgetLedger(config,Path(temp.name))
        for spec in (config.models[0],config.models[-1]):
            adapter=ProviderAdapter(spec,config,ledger)
            session=adapter.session('Diagnostic system','Diagnostic task',result.attachments,[],{})
            blocks=session.history[0]['parts'] if spec.provider=='gemini' else session.messages[1]['content']
            self.assertTrue(any('word/media/image1.png' in block.get('text','') for block in blocks))
