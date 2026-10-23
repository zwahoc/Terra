"""Shareable current-runtime demo. Never copies an operator's database or sources."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import itertools
import json
from pathlib import Path
from uuid import uuid4

from terra.contract import FIELDS, RUNTIME_MODELS, fields
from terra.local_adapter import LocalDataConnect, equivalent, variables
from terra.quantities import amount, ordinary, json_default
from terra.seeding import seed_lock
from terra.validation import sha

ZONE = timezone(timedelta(hours=8))
TEMPLATE_DATE = date(2026, 10, 24)
TEMPLATE = Path(__file__).resolve().parents[1] / 'data/demo_workspace.json'
RECEIPT_ID = 'DEMO-WORKSPACE-BOOTSTRAP'


def build_demo(as_of):
    """Deterministic fictional facts; dates move together, historical events stay past."""
    from backend.app.services.impact_service import (
        BASELINE_DESCRIPTION, LIFECYCLE_BOUNDARY, calculate_context_components)

    def day(offset): return str(as_of + timedelta(days=offset))
    def stamp(offset, hour=9): return f'{day(offset)}T{hour:02}:00:00+08:00'
    s = {'metadata': {'dataset_name': 'Terra integrated demo', 'version': '1.0.0',
                     'as_of_date': str(as_of), 'synthetic': True,
                     'disclaimer': 'Fictional workflow data and illustrative carbon assumptions, not verified environmental performance.'},
         **{name: [] for name in FIELDS}}
    project_specs = [('Lakeview Gardens External Works', 'LG-EW-P1', 'Shah Alam', 'Meridian Civil Works Sdn. Bhd.'),
                     ('Cedar Grove Community Park', 'CGP-LW-01', 'Klang', 'Crestfield Landscape Sdn. Bhd.'),
                     ('Orchard Link Streetscape', 'OL-ST-01', 'Shah Alam', 'Orchard Civil Sdn. Bhd.'),
                     ('Willow Lane Pocket Park', 'WL-PP-01', 'Subang Jaya', 'Willow Construction Sdn. Bhd.')]
    for i, (name, code, town, organisation) in enumerate(project_specs, 1):
        s['projects'].append(dict(id=f'PRJ-DEMO-{i:03}', name=name, code=code, township=town,
            location=None, start_date=day(-90), target_end_date=day(180), status='ACTIVE', managing_organisation=organisation))
    material_specs = [
        ('PAVING_BLOCK', 'Grey concrete interlocking paver, 200 x 100 x 60 mm', 'pcs', 2.5, .75, .02, {'length_mm':200, 'width_mm':100, 'thickness_mm':60, 'colour':'grey', 'finish':'smooth'}),
        ('PAVING_BLOCK', 'Grey concrete interlocking paver, 200 x 100 x 80 mm', 'pcs', 3.4, .95, .02, {'length_mm':200, 'width_mm':100, 'thickness_mm':80, 'colour':'grey', 'finish':'smooth'}),
        ('BRICK', 'Red fired-clay masonry brick, 215 x 102.5 x 65 mm, 20 MPa', 'pcs', 2.8, .55, .02, {'length_mm':215, 'width_mm':102.5, 'height_mm':65, 'material_type':'clay', 'strength_mpa':20}),
        ('DRAINAGE_PIPE', 'uPVC gravity drainage pipe, 110 mm, SN8', 'm', 1.2, 2.4, .03, {'material_type':'uPVC', 'diameter_mm':110, 'stiffness_class':'SN8'}),
        ('DRAINAGE_PIPE', 'uPVC gravity drainage pipe, 110 mm, SN4', 'm', 1.0, 2.0, .03, {'material_type':'uPVC', 'diameter_mm':110, 'stiffness_class':'SN4'}),
        ('REINFORCEMENT', 'Deformed reinforcement bar, 12 mm, B500B', 'kg', 1.0, 1.8, .01, {'diameter_mm':12, 'grade':'B500B'}),
        ('CEMENT', 'Portland cement CEM I 42.5 N, sealed 50 kg bag', 'bag', 50.0, 40.0, .2, {'cement_type':'CEM I', 'strength_class':'42.5 N', 'bag_mass_kg':50, 'packaging':'sealed'}),
        ('GEOTEXTILE', 'Non-woven separation geotextile, 200 gsm', 'm2', .2, .6, .01, {'material_type':'non-woven', 'mass_gsm':200, 'application':'separation'}),
    ]
    for i, (category, name, unit, mass, production, handling, spec) in enumerate(material_specs, 1):
        mid=f'MAT-DEMO-{i:03}'
        s['materials'].append(dict(id=mid, category=category, canonical_name=name,
            specifications=spec, standard_unit=unit, mass_kg_per_unit=mass,
            mass_source='Declared fictional demo weight; not a manufacturer measurement',
            reference_code=f'DEMO-SKU-{i:03}', is_synthetic=True))
        for kind, value in [('NEW_MATERIAL_PRODUCTION', production), ('PROCESSING', handling)]:
            s['emission_factors'].append(dict(id=f'EF-DEMO-{i:03}-{kind}', factor_type=kind,
                material_id=mid, material_category=None, transport_mode=None, value=value,
                unit=f'kgCO2e/{unit}', source_label='Illustrative demo assumption', source_url=None,
                geography='Fictional Malaysian demonstration', lifecycle_boundary=LIFECYCLE_BOUNDARY,
                version='demo-v1', valid_from=day(-365), is_demo_factor=True))
    s['emission_factors'].append(dict(id='EF-DEMO-FREIGHT', factor_type='TRANSPORT', material_id=None,
        material_category=None, transport_mode='ROAD_FREIGHT', value=.12, unit='kgCO2e/t-km',
        source_label='Illustrative demo assumption', source_url=None, geography='Fictional Malaysian demonstration',
        lifecycle_boundary=LIFECYCLE_BOUNDARY, version='demo-v1', valid_from=day(-365), is_demo_factor=True))
    for i, ((a,b), km) in enumerate(zip(itertools.combinations(range(1,5),2), [25,8,35,30,18,28]), 1):
        s['route_distances'].append(dict(id=f'RTE-DEMO-{i:03}', from_project_id=f'PRJ-DEMO-{a:03}',
            to_project_id=f'PRJ-DEMO-{b:03}', distance_km=float(km), assumption_type='SIMULATED_ROAD_DISTANCE',
            transport_mode='ROAD_FREIGHT', is_synthetic=True))
    for i, project in enumerate(s['projects'], 1):
        s['documents'].append(dict(id=f'DOC-DEMO-{i:03}', project_id=project['id'], document_type='OTHER',
            display_filename=f'{project["code"]} material register', file_uri=None, file_hash=None,
            source_availability='METADATA_ONLY', processing_status='SIMULATED', recorded_at=stamp(-20), is_simulated=True))

    def evidence(project, mid, kind, q, unit):
        rid=f'ROW-DEMO-{len(s["extracted_rows"])+1:03}'
        material=s['materials'][mid-1]
        s['extracted_rows'].append(dict(id=rid, document_id=f'DOC-DEMO-{project:03}',
            source_locator=f'Demo register item {len(s["extracted_rows"])+1}', raw_description=material['canonical_name'],
            raw_quantity=str(q), raw_unit=unit, parsed_fields={'record_kind':kind, 'quantity':q, 'unit':unit, 'effective_date':day(-20)},
            suggested_material_id=material['id'], confidence_score=None, review_status='ACCEPTED',
            review_mode='DEMO_PREAPPROVED', is_simulated=True))
        return rid

    def offer(project, mid, q, status='CONFIRMED', start=-20):
        unit=s['materials'][mid-1]['standard_unit']; sid=f'SUP-DEMO-{len(s["supply_offers"])+1:03}'
        origin=evidence(project,mid,'CONFIRMED_SURPLUS' if status=='CONFIRMED' else 'POTENTIAL_SURPLUS',q,unit)
        s['supply_offers'].append(dict(id=sid, source_project_id=f'PRJ-DEMO-{project:03}', material_id=f'MAT-DEMO-{mid:03}',
            origin_document_row_id=origin, declared_quantity=q, confirmed_quantity=q if status=='CONFIRMED' else None,
            reserved_active_quantity=0, transferred_out_quantity=0, unit=unit, surplus_status=status, condition='UNUSED',
            available_from=day(start), available_until=day(60), batch_or_lot_code=sid.replace('SUP','LOT'),
            material_owner_label=s['projects'][project-1]['managing_organisation'], evidence_refs=[f'Demo register release {origin}; no real inspection']))
        return sid

    def demand(project, mid, q, needed=-15):
        unit=s['materials'][mid-1]['standard_unit']; did=f'DEM-DEMO-{len(s["demand_requests"])+1:03}'
        origin=evidence(project,mid,'OUTSTANDING_DEMAND',q,unit)
        s['demand_requests'].append(dict(id=did, destination_project_id=f'PRJ-DEMO-{project:03}', material_id=f'MAT-DEMO-{mid:03}',
            origin_document_row_id=origin, required_quantity=q, fulfilled_quantity=0, unit=unit,
            needed_from=day(needed), required_by=day(30), request_status='OPEN', is_outstanding_need_confirmed=True))
        return did

    for mid, q, need in [(1,500,300),(2,250,100),(3,1000,400),(4,Decimal('144.5'),Decimal('96.5')),
                         (5,60,48),(6,Decimal('1500.5'),Decimal('750.5')),(7,60,40),(8,300,200)]:
        offer(1,mid,q,status='POTENTIAL' if mid==5 else 'CONFIRMED',start=5 if mid==2 else -20)
        demand(2,mid,need)
    for mid, q, need in [(1,200,200),(3,300,300),(4,60,60)]:
        offer(3,mid,q); demand(4,mid,need)
    # Historical examples are declared fixture history, never a claim of model approval.
    snapshot={name:deepcopy(s[name]) for name in FIELDS}
    snapshot['as_of']=day(-15); snapshot['factor_dataset_version']='demo-v1'
    s['optimisation_runs'].append(dict(id='RUN-DEMO-HISTORY', created_at=stamp(-14,8), objective='MAX_REUSE',
        input_snapshot=snapshot, inputs_snapshot_hash=sha(snapshot), factor_dataset_version='demo-v1', solver_status='SUCCEEDED',
        assumptions={'method':'Manually authored fictional transfer history, not an executed solver', 'synthetic':True}))
    for i,(mid,q,stage,used) in enumerate([(1,100,'REUSED',100),(3,200,'RESERVED',0),(4,24,'IN_TRANSIT',0),
                                          (7,10,'RECEIVED',0),(6,100,'REUSED',50)],1):
        source=s['supply_offers'][mid-1]; dest=s['demand_requests'][mid-1]; material=s['materials'][mid-1]
        pid=f'ALC-DEMO-{i:03}'; tid=f'TRF-DEMO-{i:03}'
        s['allocation_proposals'].append(dict(id=pid,run_id='RUN-DEMO-HISTORY',supply_offer_id=source['id'],
            demand_request_id=dest['id'],proposed_quantity=q,unit=material['standard_unit'],compatibility_result='ELIGIBLE',
            status='SELECTED',reason_codes=['DEMO_HISTORY'],created_at=stamp(-14)))
        moved=q if stage!='RESERVED' else 0
        received=q if stage in ('RECEIVED','REUSED') else 0
        held=q if stage=='RESERVED' else 0
        s['transfers'].append(dict(id=tid,proposal_id=pid,approved_quantity=q,reserved_quantity=held,dispatched_quantity=moved,
            received_quantity=received,actually_used_quantity=used,status=stage,source_confirmation_status='CONFIRMED',
            destination_confirmation_status='CONFIRMED',requested_at=stamp(-13),delivered_at=stamp(-10) if received else None,
            reuse_confirmed_at=stamp(-9) if used else None,notes='Fictional demo history. Received unused remainder stays committed for later use.'))
        source['reserved_active_quantity']+=held;source['transferred_out_quantity']+=moved;dest['fulfilled_quantity']+=used
        events=[('REQUESTED',0,-13,9),('APPROVED',q,-13,10),('RESERVED',q,-13,11)]
        if moved:events.append(('DISPATCHED',q,-12,9))
        if received:events.append(('RECEIVED',q,-10,9))
        if used:events.append(('USED',used,-9,9))
        for event,value,offset,hour in events:
            s['transfer_events'].append(dict(id=f'EVT-DEMO-{len(s["transfer_events"])+1:03}',transfer_id=tid,event_type=event,
                occurred_at=stamp(offset,hour),actor_label='Demo operator',payload={'quantity':value,'synthetic':True},
                evidence_ref='Fictional seed event; no physical evidence'))
        if used:
            route=s['route_distances'][0]
            context={'material':material,'run':{'factor_dataset_version':'demo-v1'},'route':route,'route_issue':None,
                'quantity':used,'moved_quantity':moved,'processed_quantity':moved,'activity_at':stamp(-9)}
            result,factors=calculate_context_components(context,s['emission_factors'])
            s['impact_assessments'].append(dict(id=f'IMP-DEMO-{i:03}',basis='ACTUAL_CONFIRMED_USE',proposal_id=None,transfer_id=tid,
                quantity_assessed=used,unit=material['standard_unit'],baseline_description=BASELINE_DESCRIPTION,
                avoided_production_kgco2e=float(result.avoided_production_kgco2e),
                additional_transport_kgco2e=float(result.additional_transport_kgco2e),
                additional_processing_kgco2e=float(result.additional_processing_kgco2e),net_avoided_kgco2e=float(result.net_avoided_kgco2e),
                factor_ids=[f['id'] for f in factors],assumptions={'synthetic':True,'moved_quantity':moved,'processed_quantity':moved,
                    'mass_kg_per_unit':material['mass_kg_per_unit'],'distance_km':route['distance_km'],
                    'lifecycle_boundary':LIFECYCLE_BOUNDARY,'handling_allocation':'ALL_MOVED_UNITS'},
                calculation_status='DEMO',calculated_at=stamp(-8)))
    # Any-typed evidence is ordinary-unit JSON. Decimal evidence is encoded
    # as an exact string, just as the REST adapter sends it to SQL Connect.
    for entity in FIELDS:
        for row in s[entity]:
            for name,spec,_ in fields(entity):
                if spec in ('json','array'):
                    row[name]=json.loads(json.dumps(row[name],default=json_default))
    return s


def validate_demo(seed):
    """Runtime validation plus fixture history/provenance checks, no baseline relaxation."""
    from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
    from backend.app.domain.candidates import generate_candidate_pairs
    if set(seed)!=set(FIELDS)|{'metadata'}: raise ValueError('Demo collection contract mismatch')
    as_of=date.fromisoformat(seed['metadata']['as_of_date'])
    if seed['metadata']['synthetic'] is not True: raise ValueError('Demo provenance is required')
    index={e:{r['id']:r for r in seed[e]} for e in FIELDS}
    for entity in FIELDS:
        if len(index[entity])!=len(seed[entity]): raise ValueError('Duplicate demo ID')
        for row in seed[entity]:
            RUNTIME_MODELS[entity].model_validate(row)
            for name,spec,_ in fields(entity):
                value=row[name]
                if value is None: continue
                if spec.startswith('FK=') and value not in index[spec.split('=')[1]]: raise ValueError('Demo orphan reference')
                if spec=='int': amount(value,unit_name=row.get('unit'))
                if spec=='timestamp' and datetime.fromisoformat(value).date()>as_of: raise ValueError('Future completed history')
    for d in seed['documents']:
        if not(d['is_simulated'] and d['file_uri'] is None and d['file_hash'] is None and d['source_availability']=='METADATA_ONLY'):
            raise ValueError('Demo must not forge source files')
    for run in seed['optimisation_runs']:
        if sha(run['input_snapshot'])!=run['inputs_snapshot_hash']: raise ValueError('Demo snapshot hash mismatch')
    for t in seed['transfers']:
        if t['status'] in ('RECEIVED','REUSED') and t['received_quantity']!=t['dispatched_quantity']: raise ValueError('Demo requires full receipt')
        events=sorted([e for e in seed['transfer_events'] if e['transfer_id']==t['id']],key=lambda e:e['occurred_at'])
        stages=['REQUESTED','APPROVED','RESERVED']
        if t['dispatched_quantity']:stages.append('DISPATCHED')
        if t['received_quantity']:stages.append('RECEIVED')
        if t['actually_used_quantity']:stages.append('USED')
        if [e['event_type'] for e in events]!=stages: raise ValueError('Demo event history mismatch')
        if events[0]['payload']['quantity']!=0 or events[2]['payload']['quantity']!=t['approved_quantity']:
            raise ValueError('Demo request/reservation event mismatch')
        for event,column in [('APPROVED','approved_quantity'),('DISPATCHED','dispatched_quantity'),('RECEIVED','received_quantity'),('USED','actually_used_quantity')]:
            actual=next((e['payload']['quantity'] for e in events if e['event_type']==event),0)
            if actual!=t[column]: raise ValueError('Demo event quantity mismatch')
    calculator=ForecastPreviewCalculator(seed,planning_date=as_of,factor_dataset_version='demo-v1')
    eligible=0
    for pair in generate_candidate_pairs(calculator.snapshot).pairs:
        if pair.compatibility_result=='ELIGIBLE':
            result=calculator.assess_forecast_preview(pair.supply_offer_id,pair.demand_request_id,pair.max_allocatable_quantity)
            if result['net_avoided_kgco2e'] is None: raise ValueError('Demo carbon inputs are incomplete')
            eligible+=1
    return {'as_of_date':str(as_of),'counts':{e:len(seed[e]) for e in FIELDS},'eligible_pairs':eligible,'fingerprint':sha(seed)}


def bootstrap_demo(adapter=None, *, as_of=None):
    """One-time empty-only transaction. Re-running never restores changed stock."""
    adapter=adapter or LocalDataConnect()
    with seed_lock():
        receipt=adapter.execute('GetRuntimeAudit',{'id':RECEIPT_ID})['runtimeAudit']
        if receipt:
            payload=receipt['payload']
            if as_of and str(as_of)!=payload['as_of_date']:raise ValueError('Demo already installed with a different date. Existing workspace preserved.')
            return {'action':'already installed; existing work preserved',**payload}
        # Preflight all tables, including unpublished drafts. Transaction repeats these checks.
        from scripts.generate_provider import render
        from terra.workspace_provider import table_specs
        for spec in table_specs(render()[0]):
            if spec['type'] in ('OperationalVersion','QuantityEncoding'):continue
            if adapter.execute('PageArchive'+spec['type'],{'after':'','limit':1})['records']:
                raise ValueError('Demo setup requires an empty workspace, including drafts. Existing data preserved; no reset was performed.')
        seed=build_demo(as_of or datetime.now(ZONE).date());report=validate_demo(seed)
        marker=adapter.execute('GetQuantityEncoding')['quantityEncoding']
        if marker and marker['version']!='millionths-v1': raise ValueError('Unknown quantity encoding')
        if not marker:adapter.execute('InitializeExactQuantities',write=True)
        if not adapter.execute('GetOperationalVersion')['operationalVersion']:
            adapter.execute('InitializeOperationalVersion',write=True)
        revision=adapter.execute('GetOperationalVersion')['operationalVersion']['revision']
        payload={**report,'dataset':'Terra integrated demo v1','epoch':str(uuid4())}
        adapter.execute('ImportDemoWorkspace',{**variables(seed),'expectedRevision':revision,'epoch':payload['epoch'],
            'createdAt':datetime.now(ZONE).isoformat(),'receipt':payload},write=True)
        if not equivalent(adapter.snapshot(),seed):raise RuntimeError('Demo read-back differs from import; preserve workspace and inspect before continuing')
        return {'action':'installed',**payload}
