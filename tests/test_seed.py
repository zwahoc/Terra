import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal as D
from terra.validation import load,validate,balances,reservable,summary
from terra.local_adapter import LocalDataConnect,equivalent,AdapterError
from terra.seeding import seed_local
from scripts.generate_seed import build
from scripts.generate_provider import render

class SeedTests(unittest.TestCase):
    def setUp(self):self.seed=load()
    def invalid(self,change):
        change(self.seed)
        with self.assertRaises((ValueError,KeyError,TypeError)):validate(self.seed)
    def test_full_baseline(self):
        metrics=validate(self.seed)
        self.assertEqual(metrics['confirmed_reuse_mass_t'],2.375)
        self.assertEqual(metrics['counts']['transfer_events'],31)
        self.assertEqual(metrics['incomplete_assessments'],['IMP-004','IMP-005'])
    def test_deterministic(self):self.assertEqual(build(),self.seed)
    def test_generated_schema_current(self):
        root=Path(__file__).resolve().parents[1];schema,operations=render()
        self.assertEqual(schema,(root/'dataconnect/schema/schema.gql').read_text(encoding='utf-8'))
        self.assertEqual(operations,(root/'dataconnect/terra/operations.gql').read_text(encoding='utf-8'))
        self.assertNotRegex(operations,r'@auth\(level:\s*PUBLIC\)')
    def test_scenario_index_ids_resolve(self):
        import re
        root=Path(__file__).resolve().parents[1]
        text=(root/'data/SCENARIOS.md').read_text(encoding='utf-8')
        ids={row['id'] for entity in self.seed if entity!='metadata' for row in self.seed[entity]}
        for value in re.findall(r'\b(?:PRJ|MAT|DOC|ROW|SUP|DEM|RTE|RUN|ALC|TRF|EVT|EF|IMP)-\d{3}\b',text):
            self.assertIn(value,ids)
    def test_duplicate_id(self):self.invalid(lambda s:s['projects'][1].update(id='PRJ-001'))
    def test_orphan_fk(self):self.invalid(lambda s:s['supply_offers'][0].update(material_id='MAT-999'))
    def test_unknown_field(self):self.invalid(lambda s:s['projects'][0].update(user_id='USER-001'))
    def test_enum(self):self.invalid(lambda s:s['transfers'][0].update(status='DONE'))
    def test_negative_stock(self):self.invalid(lambda s:s['supply_offers'][0].update(confirmed_quantity=-1))
    def test_overbook_stock(self):self.invalid(lambda s:s['supply_offers'][0].update(confirmed_quantity=999))
    def test_counter_drift(self):self.invalid(lambda s:s['supply_offers'][2].update(reserved_active_quantity=301))
    def test_demand_double_commitment(self):self.invalid(lambda s:s['demand_requests'][2].update(required_quantity=299))
    def test_false_fulfilment_on_receipt(self):self.invalid(lambda s:s['demand_requests'][4].update(fulfilled_quantity=200))
    def test_pending_publication(self):self.invalid(lambda s:s['extracted_rows'][0].update(review_status='PENDING'))
    def test_potential_reservation(self):self.invalid(lambda s:s['supply_offers'][6].update(confirmed_quantity=300,reserved_active_quantity=1))
    def test_material_mismatch(self):self.invalid(lambda s:s['allocation_proposals'][11].update(compatibility_result='ELIGIBLE'))
    def test_date_mismatch(self):self.invalid(lambda s:s['allocation_proposals'][12].update(compatibility_result='ELIGIBLE'))
    def test_self_project(self):self.invalid(lambda s:s['supply_offers'][0].update(source_project_id='PRJ-002'))
    def test_wrong_unit(self):self.invalid(lambda s:s['demand_requests'][0].update(unit='m2'))
    def test_use_exceeds_receipt(self):self.invalid(lambda s:s['transfers'][5].update(actually_used_quantity=581))
    def test_event_missing(self):self.invalid(lambda s:s['transfer_events'].pop(0))
    def test_event_quantity(self):self.invalid(lambda s:s['transfer_events'][1]['payload'].update(quantity=601))
    def test_event_future(self):self.invalid(lambda s:s['transfer_events'][0].update(occurred_at='2026-10-13T09:00:00+08:00'))
    def test_bad_snapshot_hash(self):self.invalid(lambda s:s['optimisation_runs'][0].update(inputs_snapshot_hash='fake'))
    def test_duplicate_outcomes(self):self.invalid(lambda s:s['impact_assessments'][1].update(proposal_id='ALC-001'))
    def test_missing_factor_not_zero(self):self.invalid(lambda s:s['impact_assessments'][3].update(net_avoided_kgco2e=0))
    def test_fake_source(self):self.invalid(lambda s:s['documents'][0].update(file_uri='https://invalid.example/stock.xlsx'))
    def test_bad_arithmetic(self):self.invalid(lambda s:s['impact_assessments'][0].update(net_avoided_kgco2e=500))
    def test_wrong_factor(self):self.invalid(lambda s:s['impact_assessments'][0].update(factor_ids=['EF-002','EF-007','EF-008']))
    def test_partial_use_retains_commitment(self):
        held,issued,fulfilled,incoming=balances(self.seed)
        self.assertEqual((held['SUP-001'],issued['SUP-001'],fulfilled['DEM-001'],incoming['DEM-001']),(0,1000,550,50))
        self.assertEqual(summary(self.seed)['newly_allocatable_demand_pcs_by_id']['DEM-001'],0)
        self.assertIsNone(self.seed['impact_assessments'][4]['net_avoided_kgco2e'])
    def test_receipt_without_use_no_reuse(self):
        before=summary(self.seed)['confirmed_reuse_mass_t']
        t=next(x for x in self.seed['transfers'] if x['id']=='TRF-005');t['received_quantity']=0
        self.assertEqual(summary(self.seed)['confirmed_reuse_mass_t'],before)
    def test_a07_a09_arithmetic(self):
        offer=copy.deepcopy(self.seed['supply_offers'][0]);offer.update(confirmed_quantity=1000,reserved_active_quantity=400,transferred_out_quantity=200)
        self.assertEqual(reservable(offer,'2026-10-12'),400)
        self.seed['demand_requests'][2].update(required_quantity=600,fulfilled_quantity=200)
        self.assertEqual(summary(self.seed)['newly_allocatable_demand_pcs_by_id']['DEM-003'],100)
    def test_a11_partial_stage_quantities(self):
        t=next(t for t in self.seed['transfers'] if t['id']=='TRF-006')
        t.update(approved_quantity=580,reserved_quantity=10,dispatched_quantity=570,received_quantity=550,actually_used_quantity=500)
        self.seed['supply_offers'][0]['reserved_active_quantity']=10
        self.seed['supply_offers'][0]['transferred_out_quantity']=970
        self.seed['demand_requests'][0]['fulfilled_quantity']=500
        for e in self.seed['transfer_events']:
            if e['transfer_id']=='TRF-006':
                quantities={'REQUESTED':0,'APPROVED':580,'RESERVED':580,'DISPATCHED':570,'RECEIVED':550,'USED':500}
                e['payload']['quantity']=quantities[e['event_type']]
                if e['event_type']=='USED':e['payload']['unresolved_quantity']=80
        i=self.seed['impact_assessments'][4]
        i.update(quantity_assessed=500,avoided_production_kgco2e=375,additional_transport_kgco2e=4.275)
        i['assumptions'].update(moved_quantity=570,unresolved_quantity=70)
        self.assertEqual(validate(self.seed,check_scenarios=False)['newly_allocatable_demand_pcs_by_id']['DEM-001'],20)
    def test_a16_a17_arithmetic(self):
        self.assertEqual(D(600)*D('2.5')/1000*25*D('.12'),D('4.5'))
        self.assertEqual(self.seed['impact_assessments'][0]['avoided_production_kgco2e'],450)
        self.assertEqual(self.seed['impact_assessments'][0]['additional_transport_kgco2e'],4.5)
    def test_cloud_host_guard(self):
        for host in ['firebasedataconnect.googleapis.com:443','localhost:9399','127.0.0.1:9399@evil.example','127.0.0.1:9399/path']:
            with self.assertRaises(ValueError):LocalDataConnect(host)
        with self.assertRaises(ValueError):LocalDataConnect(project='production-terra')
    def test_reset_confirmation_before_network(self):
        adapter=LocalDataConnect()
        with patch.object(adapter,'snapshot',side_effect=AssertionError('network')):
            with self.assertRaises(ValueError):seed_local(self.seed,adapter,reset_confirmation='yes')
    def test_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('{"id":1,"id":2}', encoding="utf-8", newline="\n")
            with self.assertRaises(ValueError):load(p)
    def test_reject_nan(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('{"value":NaN}', encoding="utf-8", newline="\n")
            with self.assertRaises(ValueError):load(p)

if __name__=='__main__':unittest.main()
