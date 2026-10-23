"""Live screen reads must include runtime entities and retain domain distinctions."""
import asyncio,copy,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from backend.app.services.workspace_service import build_workspace,workspace_data
from backend.app.services.ingestion_errors import IngestionError
from terra.validation import load
from tests.test_transfers_api import request

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.records=copy.deepcopy(load())
        self.records.update(published_records=[],stock_heads=[],superseded_records=[])
        self.now=datetime(2026,10,12,tzinfo=timezone(timedelta(hours=8)))
    def test_current_balances_do_not_ignore_incoming_commitments(self):
        data=build_workspace(self.records,self.now)
        demand=next(d for d in data['demand_views'] if d['id']=='DEM-001')
        self.assertLess(demand['newly_allocatable_quantity'],demand['remaining_unfulfilled_quantity'])
        self.assertFalse(any(c['id']==t['proposal_id'] for c in data['candidate_matches'] for t in self.records['transfers']))
    def test_new_entities_and_proposal_are_joined_without_seed_lookup(self):
        records=self.records
        records['projects'].append({**records['projects'][0],'id':'PRJ-runtime','name':'Runtime project'})
        records['materials'].append({**records['materials'][0],'id':'MAT-runtime','canonical_name':'Runtime material'})
        records['supply_offers'].append({**records['supply_offers'][0],'id':'SUP-runtime','material_id':'MAT-runtime','source_project_id':'PRJ-runtime'})
        records['allocation_proposals'].append({**records['allocation_proposals'][0],'id':'ALC-runtime','supply_offer_id':'SUP-runtime'})
        records['transfers'].append({**records['transfers'][0],'id':'TRF-runtime','proposal_id':'ALC-runtime','actually_used_quantity':0})
        transfer=next(t for t in build_workspace(records,self.now)['transfer_views'] if t['id']=='TRF-runtime')
        self.assertEqual(transfer['source_project_name'],'Runtime project')
        self.assertEqual(transfer['material_name'],'Runtime material')
    def test_unknown_mass_is_incomplete_and_expired_supply_is_not_ready(self):
        for material in self.records['materials']:material['mass_kg_per_unit']=None
        for supply in self.records['supply_offers']:supply['available_until']='2026-10-11'
        data=build_workspace(self.records,self.now)
        self.assertIsNone(data['dashboard']['actual_reuse_tonnes'])
        self.assertTrue(data['dashboard']['unknown_mass_transfer_ids'])
        self.assertTrue(all(s['reservable_quantity']==0 for s in data['supply_views']))
    def test_units_remain_separate(self):
        self.records['supply_offers'].append({**self.records['supply_offers'][1],'id':'SUP-kg','unit':'kg'})
        self.assertEqual(set(build_workspace(self.records,self.now)['dashboard']['confirmed_by_unit']),{'pcs','kg'})
    def test_route_read_only_envelope(self):
        with patch('backend.app.routes.workspace.workspace_data',return_value={'terra':{'projects':[]}}):
            status,response=asyncio.run(request('GET','/api/workspace'))
        self.assertEqual(status,200);self.assertFalse(response['meta']['operational_writes'])
    def test_source_history_marks_supersession_without_deleting_evidence(self):
        from terra.local_adapter import variables
        raw=variables(self.records)
        raw.update(operationalVersion={'revision':1},registeredMaterials=[],projectStockHeads=[],
            projectMaterialRecords=[{'payload':{'id':identity,'application':application}}
                for identity,application in [('old','ADD'),('new','REPLACE'),('history','HISTORY_ONLY')]],
            supersededRecords=[{'id':'old','projectId':'PRJ-001','successorId':'new'}])
        class Adapter:
            def execute(self,op):
                if op=='GetOperationalVersion':return {'operationalVersion':{'revision':1}}
                if op=='GetPublicationState':return raw
                return {'impactAssessmentHeads':[]}
        data=workspace_data(Adapter())['terra']
        rows={r['id']:r for r in data['published_records']}
        self.assertEqual(len(rows),3)
        self.assertFalse(rows['old']['is_effective']);self.assertEqual(rows['old']['superseded_by'],'new')
        self.assertTrue(rows['new']['is_effective']);self.assertFalse(rows['history']['is_effective'])
        self.assertEqual(data['superseded_records'][0]['project_id'],'PRJ-001')
    def test_revision_drift_blocks_mixed_context(self):
        class Adapter:
            calls=0
            def execute(self,op):
                if op=='GetOperationalVersion':
                    self.calls+=1;return {'operationalVersion':{'revision':self.calls}}
                if op=='GetPublicationState':return {'operationalVersion':{'revision':1}}
                return {'impactAssessmentHeads':[]}
        with self.assertRaises(IngestionError) as caught:workspace_data(Adapter())
        self.assertEqual(caught.exception.code,'WORKSPACE_CHANGED')
    def test_read_limit_blocks_partial_view(self):
        class Adapter:
            def execute(self,op):
                if op=='GetOperationalVersion':return {'operationalVersion':None}
                if op=='GetPublicationState':return {'operationalVersion':None,'projects':[{}]*1000}
                return {'impactAssessmentHeads':[]}
        with self.assertRaises(IngestionError) as caught:workspace_data(Adapter())
        self.assertEqual(caught.exception.code,'WORKSPACE_READ_CAPACITY')

class CheckpointCWorkspaceTests(unittest.TestCase):
    def test_summary_uses_one_alternative_and_keeps_decimal_units_and_project_scope(self):
        from tests.test_checkpoint_a import runtime_records,NOW
        records=runtime_records();records.update(published_records=[],stock_heads=[],superseded_records=[])
        records['allocation_proposals']=[{'id':'P-'+run,'run_id':run,'supply_offer_id':'SUP-R1','demand_request_id':'DEM-R2','proposed_quantity':__import__('decimal').Decimal('4.25'),'unit':'m','status':'PROPOSED','compatibility_result':'ELIGIBLE'} for run in ('REUSE','DEADLINE','CARBON')]
        records['current_matching_run_ids']={'REUSE'}
        view=build_workspace(records,NOW)
        self.assertEqual(len(view['candidate_matches']),1)
        self.assertEqual(view['dashboard']['confirmed_by_unit'],{'m':__import__('decimal').Decimal('12.75')})
        self.assertEqual(view['dashboard']['by_project']['PRJ-R2']['demand_by_unit'],{'m':__import__('decimal').Decimal('4.25')})
        self.assertEqual(view['dashboard']['by_project']['PRJ-R2']['confirmed_by_unit'],{})

    def test_forecast_accepts_runtime_factor_category_without_changing_seed_enums(self):
        from tests.test_checkpoint_a import runtime_records,DAY
        from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
        records=runtime_records()
        production=next(f for f in records['emission_factors'] if f['id']=='EF-PIPE')
        production.update(material_id=None,material_category='PIPE')
        preview=ForecastPreviewCalculator(records,planning_date=DAY,factor_dataset_version='demo-v1').assess_forecast_preview('SUP-R1','DEM-R2','3.25')
        self.assertEqual(preview['avoided_production_kgco2e'],__import__('decimal').Decimal('7.8'))
        self.assertIsNone(preview['additional_processing_kgco2e'])

