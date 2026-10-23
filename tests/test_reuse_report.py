"""Report totals, uncertainty, snapshot guards and Excel/API regressions."""
import asyncio
import copy
from datetime import datetime
from decimal import Decimal
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from backend.app.services.reuse_report import build_reuse_report, ZONE
from backend.app.services.reuse_workbook import write_workbook, export_reuse_excel, MIME
from backend.app.services.impact_service import ImpactConflict, ImpactNotFound
from terra.demo_workspace import build_demo, TEMPLATE_DATE
from terra.quantities import json_default
from tests.test_impact_service import FakeImpactRepository
from tests.test_impact_api import request

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
NOW=datetime(2026,10,24,16,tzinfo=ZONE)


def repository():
    return FakeImpactRepository(json.loads(json.dumps(build_demo(TEMPLATE_DATE),default=json_default)))


def strings(z):
    root=ET.fromstring(z.read('xl/sharedStrings.xml'))
    return [''.join(n.itertext()) for n in root.findall('s:si',NS)]


def sheet_rows(z,name):
    book=ET.fromstring(z.read('xl/workbook.xml'))
    index=[s.attrib['name'] for s in book.findall('s:sheets/s:sheet',NS)].index(name)+1
    root=ET.fromstring(z.read(f'xl/worksheets/sheet{index}.xml'))
    shared=strings(z);out={}
    for cell in root.findall('.//s:sheetData/s:row/s:c',NS):
        value=cell.find('s:v',NS)
        if value is not None:out[cell.attrib['r']]=shared[int(value.text)] if cell.attrib.get('t')=='s' else value.text
    return root,out


class ReuseReportTests(unittest.TestCase):
    def test_published_demand_uses_its_exact_projection_and_page_reference(self):
        from backend.app.services.reuse_report import _evidence
        from backend.app.services.publication_service import stable
        repo=repository();snapshot=repo.snapshot()
        record={'id':'observation','publication_id':'publication','review_row_id':'review-row',
            'record_kind':'OUTSTANDING_DEMAND','source':{'kind':'FILE','document_id':snapshot['documents'][1]['id'],
            'source_page':2,'source_item_ref':'M12','source_locator':'Table requirements'}}
        demand={**snapshot['demand_requests'][0],'id':stable('DEM','publication','review-row'),'origin_document_row_id':None}
        result=_evidence(snapshot['supply_offers'][0],demand,snapshot,{'observation':record},[])
        entry=next(e for e in result if e['role']=='Recipient')
        self.assertEqual(entry['locator'],'Page 2 · M12 · Table requirements')
        wrong={**demand,'id':'other-demand'}
        self.assertFalse(any(e['role']=='Recipient' for e in _evidence(snapshot['supply_offers'][0],wrong,snapshot,{'observation':record},[])))

    def test_all_projects_once_project_role_and_cumulative_known_totals(self):
        repo=repository();before=copy.deepcopy(repo.seed)
        all_report=build_reuse_report(repo,clock=lambda:NOW)
        self.assertEqual(all_report['summary']['transfers'],5)
        self.assertEqual(all_report['summary']['used_transfers'],2)
        self.assertEqual(all_report['summary']['known_reuse_tonnes'],Decimal('.3'))
        self.assertEqual(all_report['summary']['known_net_kgco2e'],Decimal('160.95'))
        self.assertEqual(all_report['summary']['net_by_factor_basis']['Demonstration'],Decimal('160.95'))
        for pid,role in [('PRJ-DEMO-001','Supplied'),('PRJ-DEMO-002','Received')]:
            report=build_reuse_report(repo,project_id=pid)
            self.assertEqual(len(report['transfers']),5)
            self.assertEqual({r['role'] for r in report['transfers']},{role})
            self.assertEqual(report['summary']['known_net_kgco2e'],all_report['summary']['known_net_kgco2e'])
        self.assertFalse(build_reuse_report(repo,project_id='PRJ-DEMO-003')['transfers'])
        steel=next(r for r in all_report['transfers'] if r['material_id']=='MAT-DEMO-006')
        self.assertEqual((steel['dispatched'],steel['used'],steel['unused']),(100,50,50))
        self.assertEqual(repo.seed,before);self.assertEqual(repo.persisted,[])
        self.assertEqual({r['unit'] for r in all_report['materials']},{'pcs','m','bag','kg'})

    def test_old_revision_ignored_missing_negative_and_unknown_remain_visible(self):
        repo=repository();old=copy.deepcopy(repo.seed['impact_assessments'][0]);old['id']='old';old['net_avoided_kgco2e']=999999
        repo.seed['impact_assessments'].append(old)
        active=repo.seed['impact_assessments'][0]
        active['net_avoided_kgco2e']=-5
        repo.seed['impact_assessments'][1]['net_avoided_kgco2e']=None
        repo.seed['impact_assessments'][1]['calculation_status']='INSUFFICIENT_DATA'
        repo.seed['impact_assessments'][1]['assumptions']['missing_data']=['MISSING_PROCESSING_FACTOR']
        repo.seed['materials'][0]['mass_kg_per_unit']=None
        report=build_reuse_report(repo)
        self.assertEqual(report['summary']['known_net_kgco2e'],Decimal(-5))
        self.assertEqual(report['summary']['complete_estimates'],1)
        self.assertEqual(report['summary']['missing_estimates'],1)
        self.assertEqual(report['summary']['unknown_mass_transfers'],1)
        self.assertEqual(report['summary']['known_reuse_tonnes'],Decimal('.05'))
        self.assertTrue(any('processing' in i['details'] for i in report['issues']))
        self.assertTrue(any(i['status']=='Weight unavailable' for i in report['issues']))

    def test_missing_heads_units_and_changed_physical_use_do_not_export_old_benefits(self):
        for mode in ('head','unit','used','factor','link'):
            repo=repository()
            if mode=='head':repo.heads['ACTUAL_CONFIRMED_USE:TRF-DEMO-001']['current_assessment_id']=None
            elif mode=='unit':
                factor=next(f for f in repo.seed['emission_factors'] if f['id']=='EF-DEMO-001-NEW_MATERIAL_PRODUCTION');factor['unit']='kgCO2e/m'
            elif mode=='used':repo.seed['transfers'][0]['actually_used_quantity']=99
            elif mode=='factor':repo.seed['emission_factors']=[f for f in repo.seed['emission_factors'] if f['id']!='EF-DEMO-001-NEW_MATERIAL_PRODUCTION']
            else:repo.seed['impact_assessments'][0]['transfer_id']='TRF-DEMO-005'
            report=build_reuse_report(repo)
            row=report['transfers'][0]
            self.assertIsNone(row['assessment']);self.assertNotEqual(row['assessment_status'],'Complete')
            self.assertEqual(report['summary']['known_net_kgco2e'],Decimal('88.7'))

    def test_scope_errors_and_no_use_do_not_look_like_missing_transfers(self):
        repo=repository()
        with self.assertRaises(ImpactNotFound):build_reuse_report(repo,project_id='not-a-project')
        with self.assertRaises(ImpactNotFound):build_reuse_report(repo,transfer_id='not-a-transfer')
        report=build_reuse_report(repo,transfer_id='TRF-DEMO-002')
        self.assertEqual(len(report['transfers']),1)
        self.assertEqual(report['summary']['used_transfers'],0)
        self.assertEqual(report['issues'],[])

    def test_pending_failed_snapshot_guard_and_exact_recipient_evidence(self):
        from backend.app.services.publication_service import stable
        for state in ('PENDING','FAILED'):
            repo=repository()
            class Adapter:
                version=1
                def execute(self,operation,*args,**kwargs):
                    if kwargs.get('write'):raise AssertionError('Report must never write')
                    return {'GetQuantityEncoding':{'quantityEncoding':{'version':'millionths-v1'}},'GetOperationalVersion':{'operationalVersion':{'revision':self.version}}}[operation]
            repo._adapter=Adapter()
            with patch('backend.app.services.matching_service.pages',return_value=iter([{'id':'TRF-DEMO-001','status':state}])):
                report=build_reuse_report(repo,include_evidence=False)
            self.assertIsNone(report['transfers'][0]['assessment'])
            self.assertEqual(report['summary']['complete_estimates'],1)
            self.assertEqual(report['summary']['known_net_kgco2e'],Decimal('88.7'))
        repo=repository();repo._adapter=Adapter()
        original=repo.list_heads
        def changing():repo._adapter.version+=1;return original()
        repo.list_heads=changing
        with patch('backend.app.services.matching_service.pages',return_value=iter([])):
            with self.assertRaises(ImpactConflict):build_reuse_report(repo,include_evidence=False)
        repo=repository();r=build_reuse_report(repo)
        self.assertTrue(any(e['role']=='Recipient' for e in r['transfers'][0]['evidence']))

    def test_saved_factor_inputs_win_and_no_global_synthetic_label_is_invented(self):
        repo=repository();a=repo.seed['impact_assessments'][0]
        snapshots=[copy.deepcopy(f) for f in repo.seed['emission_factors'] if f['id'] in a['factor_ids']]
        for f in snapshots:f['is_demo_factor']=False;f['source_label']='Supplied reference dataset'
        a['assumptions']['factor_snapshots']=snapshots
        a['assumptions']['source_input']={'mass_kg_per_unit':2.5,'mass_source':'Saved supplier weight','distance_km':25}
        repo.seed['materials'][0]['is_synthetic']=False
        report=build_reuse_report(repo);r=report['transfers'][0]
        self.assertEqual(r['factor_kind'],'Other factors')
        self.assertEqual(r['carbon_weight'],2.5)
        self.assertNotIn('synthetic',r)
        self.assertEqual(report['summary']['net_by_factor_basis']['Other factors'],Decimal('72.25'))


class ReuseWorkbookTests(unittest.TestCase):
    def test_summary_scrolls_freely_while_detail_headers_stay_frozen(self):
        content,_=export_reuse_excel(repository(),clock=lambda:NOW)
        with ZipFile(BytesIO(content)) as z:
            summary,_=sheet_rows(z,'Summary')
            self.assertIsNone(summary.find('s:sheetViews/s:sheetView/s:pane',NS),
                'Summary must not pin rows 1–24 or leave a tiny scrolling area')
            for name in ('Transfers','Carbon breakdown','Factors & evidence','Needs attention'):
                detail,_=sheet_rows(z,name)
                pane=detail.find('s:sheetViews/s:sheetView/s:pane',NS)
                self.assertEqual(pane.attrib['ySplit'],'6',name)

    def test_workbook_sheets_types_filters_chart_dates_and_preserved_quantities(self):
        content,name=export_reuse_excel(repository(),project_id='PRJ-DEMO-001',clock=lambda:NOW)
        self.assertTrue(name.endswith('.xlsx'));self.assertIn('LG-EW-P1',name)
        with ZipFile(BytesIO(content)) as z:
            root=ET.fromstring(z.read('xl/workbook.xml'))
            self.assertEqual([s.attrib['name'] for s in root.findall('s:sheets/s:sheet',NS)],['Summary','Transfers','Carbon breakdown','Factors & evidence','Needs attention'])
            _,summary=sheet_rows(z,'Summary')
            self.assertEqual(Decimal(summary['D12']),Decimal('160.95'))
            tree,rows=sheet_rows(z,'Transfers')
            self.assertEqual(Decimal(rows['K7']),100)
            self.assertEqual(Decimal(rows['I7']),100)
            self.assertNotEqual(rows['N7'],'2026-10-11T09:00:00+08:00')
            self.assertIsNotNone(tree.find('s:autoFilter',NS))
            self.assertIsNotNone(tree.find('s:sheetViews/s:sheetView/s:pane',NS))
            self.assertTrue(any(n.startswith('xl/charts/chart') for n in z.namelist()))
            self.assertEqual(sum(len(ET.fromstring(z.read(n)).findall('.//s:f',NS)) for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')),0)

    def test_injection_strings_extreme_precision_empty_and_missing_cells(self):
        report=build_reuse_report(repository(),clock=lambda:NOW)
        report['transfers'][0]['material']='=HYPERLINK("https://bad.example","click")'
        report['transfers'][0]['used']=Decimal('1000000000000.000001')
        report['transfers'][0]['assessment']=None
        report['transfers'][0]['assessment_status']='Calculation pending'
        with ZipFile(BytesIO(write_workbook(report))) as z:
            tree,rows=sheet_rows(z,'Transfers')
            self.assertEqual(rows['C7'],'=HYPERLINK("https://bad.example","click")')
            self.assertEqual(rows['K7'],'1000000000000.000001')
            self.assertEqual(tree.find(".//s:c[@r='K7']",NS).attrib['t'],'s')
            _,carbon=sheet_rows(z,'Carbon breakdown')
            self.assertNotIn('R7',carbon)
            self.assertNotIn('HYPERLINK',str(tree.findall('.//s:f',NS)))
        empty=build_reuse_report(repository(),project_id='PRJ-DEMO-003')
        self.assertTrue(write_workbook(empty).startswith(b'PK'))

    def test_excel_endpoint_and_summary_scope_and_existing_csv_are_compatible(self):
        content,name=export_reuse_excel(repository(),clock=lambda:NOW)
        with patch('backend.app.services.reuse_workbook.export_reuse_excel',return_value=(content,name)) as export:
            status,headers,body=asyncio.run(request('GET','/api/exports/impact','basis=ACTUAL_CONFIRMED_USE&format=xlsx&project_id=PRJ-DEMO-001'))
        self.assertEqual(status,200);self.assertEqual(headers[b'content-type'].decode(),MIME)
        self.assertEqual(headers[b'cache-control'],b'no-store');self.assertEqual(body,content)
        self.assertEqual(export.call_args.kwargs['project_id'],'PRJ-DEMO-001')
        with patch('backend.app.services.reuse_report.build_reuse_report',return_value=build_reuse_report(repository())) as read:
            status,_,body=asyncio.run(request('GET','/api/reports/reuse','project_id=PRJ-DEMO-002'))
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['data']['summary']['used_transfers'],2)
        self.assertEqual(read.call_args.kwargs,{'project_id':'PRJ-DEMO-002','include_evidence':False})
        status,_,_=asyncio.run(request('GET','/api/exports/impact','basis=PROPOSAL_FORECAST&format=xlsx'))
        self.assertNotEqual(status,200)
