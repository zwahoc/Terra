"""Reproduce the immutable synthetic baseline. No randomness or current-clock inputs."""
import sys,json,hashlib,itertools,copy
from pathlib import Path
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terra.contract import FIELDS
ROOT=Path(__file__).resolve().parents[1]

def ident(prefix,n): return f'{prefix}-{n:03}'
def ts(day,hour=9): return f'2026-10-{day:02}T{hour:02}:00:00+08:00'
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def build():
    s={'metadata':{'dataset_name':'Terra Option B Synthetic Baseline','version':'1.0.0','as_of_date':'2026-10-12','timezone':'Asia/Kuala_Lumpur','synthetic':True,'currency':'MYR','carbon_unit':'kgCO2e','disclaimer':'Synthetic demonstration data; not actual SDP inventory or verified GHG performance.'},**{e:[] for e in FIELDS}}
    townships=['Elmina','Bukit Raja','Serenia','Nilai Impian','Putra Heights']
    for i,town in enumerate(townships,1):
        s['projects'].append(dict(id=ident('PRJ',i),code=f'DEMO-{i:02}',name=f'{town} Demo Phase {chr(64+i)}',township=town,location=None,start_date='2026-01-01',target_end_date='2027-06-30',status='ACTIVE',managing_organisation=f'Synthetic Contractor {chr(64+i)}'))
    specs=[]
    for length,width,thick,colour,finish in [(200,100,60,'grey','smooth'),(200,100,80,'grey','smooth'),(200,100,60,'red','smooth'),(200,100,80,'red','smooth'),(225,112,60,'grey','textured'),(225,112,80,'red','textured'),(300,300,60,'grey','exposed aggregate'),(200,100,60,'charcoal','textured')]:
        specs.append(('PAVING_BLOCK',dict(length_mm=length,width_mm=width,thickness_mm=thick,colour=colour,finish=finish,material_type='concrete',intended_use='landscape paving'),2.5 if len(specs)==0 else round(length*width*thick*0.00000208,3)))
    for length,width,height,kind,grade in [(215,102,65,'clay','DEMO-G10'),(215,102,65,'concrete','DEMO-G7'),(220,105,65,'clay','DEMO-G10'),(215,102,65,'clay','DEMO-G15'),(390,90,190,'concrete hollow','DEMO-G5'),(230,110,75,'clay','DEMO-G10')]:
        specs.append(('BRICK',dict(length_mm=length,width_mm=width,height_mm=height,material_type=kind,grade=grade,intended_use='non-structural demo partition',colour='red' if kind=='clay' else 'grey'),None if len(specs)==10 else 2.8))
    for length,width,thick,finish,use,colour,slip in [(600,600,9,'matte','floor','beige','DEMO-R10'),(600,600,8,'gloss','wall','beige',None),(300,300,8,'matte','floor','grey','DEMO-R10'),(300,600,8,'gloss','wall','white',None),(600,600,10,'textured','floor','grey','DEMO-R11'),(300,600,9,'matte','floor','cream',None)]:
        specs.append(('TILE',dict(length_mm=length,width_mm=width,thickness_mm=thick,finish=finish,intended_use=use,colour=colour,slip_rating=slip,material_type='ceramic'),None if len(specs)==19 else round(length*width*thick*0.0000022,3)))
    for i,(category,spec,mass) in enumerate(specs,1):
        name=f'{spec["material_type"].title()} {category.lower().replace("_"," ")} {spec["length_mm"]}x{spec["width_mm"]}x{spec.get("thickness_mm",spec.get("height_mm"))} mm {spec["colour"]} {spec.get("finish",spec.get("grade"))}'
        s['materials'].append(dict(id=ident('MAT',i),category=category,canonical_name=name,specifications=spec,standard_unit='pcs',mass_kg_per_unit=mass,mass_source='SYNTHETIC_ASSUMPTION' if mass is not None else None,reference_code=f'DEMO-SKU-{i:03}',is_synthetic=True))
    # Three metadata-only registers per site; no files or fake hashes.
    for i in range(1,16):
        project=(i-1)//3+1; kind=['INVENTORY','DEMAND','BOQ' if project%2 else 'PURCHASE_ORDER'][(i-1)%3]
        s['documents'].append(dict(id=ident('DOC',i),project_id=ident('PRJ',project),document_type=kind,display_filename=f'PRJ-{project:03}_{kind}_DEMO.xlsx',file_uri=None,file_hash=None,source_availability='METADATA_ONLY',processing_status='SIMULATED',recorded_at='2026-09-25T09:00:00+08:00',is_simulated=True))
    def row(doc,mat,quantity,kind,review='ACCEPTED',raw=None):
        material=s['materials'][mat-1]; n=len(s['extracted_rows'])+1
        data=dict(id=ident('ROW',n),document_id=ident('DOC',doc),source_locator=f'SYNTHETIC Sheet: DemoRegister, Row: {n+1}',raw_description=raw or material['canonical_name'].upper(),raw_quantity=f'{quantity:,}',raw_unit='PCS',parsed_fields=dict(record_kind=kind,quantity=quantity,unit='pcs',specifications=copy.deepcopy(material['specifications']),effective_date='2026-09-25'),suggested_material_id=material['id'],confidence_score=0.91 if review=='ACCEPTED' else 0.45,review_status=review,review_mode={'ACCEPTED':'DEMO_PREAPPROVED','PENDING':'PENDING_DEMO','CORRECTED':'MANUAL_CORRECTION','REJECTED':'PENDING_DEMO'}[review],is_simulated=True)
        if review=='CORRECTED':
            data['raw_quantity']='12O'; data['parsed_fields']['correction']={'field':'quantity','from':'12O','to':quantity,'actor_label':'Demo operator','reviewed_at':'2026-09-26T10:00:00+08:00'}
        s['extracted_rows'].append(data);return data['id']
    # Operational offers intentionally vary, including potential, suspension and condition.
    offers=[(1,1,1000,'CONFIRMED','2026-09-26'),(4,1,500,'CONFIRMED','2026-09-26'),(1,2,800,'CONFIRMED','2026-09-26'),(2,3,450,'CONFIRMED','2026-09-26'),(3,15,300,'CONFIRMED','2026-09-26'),(4,9,700,'CONFIRMED','2026-09-26'),(1,4,300,'POTENTIAL','2026-10-20'),(3,16,400,'CONFIRMED','2026-09-26'),(5,17,200,'CONFIRMED','2026-10-25'),(5,11,150,'CONFIRMED','2026-09-26'),(2,18,250,'CONFIRMED','2026-09-26'),(3,5,500,'SUSPENDED','2026-09-26'),(4,6,350,'CLOSED','2026-09-26'),(5,7,250,'CONFIRMED','2026-10-15'),(2,8,400,'CONFIRMED','2026-09-26'),(3,10,600,'CONFIRMED','2026-09-26'),(4,12,450,'CONFIRMED','2026-09-26'),(5,13,300,'POTENTIAL','2026-10-18'),(1,14,900,'CONFIRMED','2026-09-26'),(2,19,100,'CONFIRMED','2026-09-26'),(3,20,180,'CONFIRMED','2026-09-26'),(3,1,350,'CONFIRMED','2026-09-26')]
    for i,(prj,mat,q,status,avail) in enumerate(offers,1):
        origin=row((prj-1)*3+1,mat,q,'POTENTIAL_SURPLUS' if status=='POTENTIAL' else 'ON_HAND_INVENTORY',raw='RECT CONC PAVER GREY 200X100X60' if i==1 else None)
        s['supply_offers'].append(dict(id=ident('SUP',i),source_project_id=ident('PRJ',prj),material_id=ident('MAT',mat),origin_document_row_id=origin,declared_quantity=q,confirmed_quantity=None if status=='POTENTIAL' else q,reserved_active_quantity=0,transferred_out_quantity=0,unit='pcs',surplus_status=status,condition='UNKNOWN' if i==20 else 'UNUSED',available_from=avail,available_until=None,batch_or_lot_code=f'DEMO-LOT-{i:03}',material_owner_label=f'Synthetic Contractor {chr(64+prj)}',evidence_refs=['SYNTHETIC release review; no real inspection or ownership certification']))
    demands=[(2,1,600),(3,1,400),(4,2,500),(5,3,400),(4,15,300),(1,9,300),(4,15,400),(1,17,200),(1,11,250),(5,18,250),(1,5,350),(2,6,300),(3,7,250),(4,8,350),(5,10,500),(1,12,400),(2,13,250),(3,14,700),(4,19,150),(5,20,220),(5,1,800),(3,9,400)]
    for i,(prj,mat,q) in enumerate(demands,1):
        origin=row((prj-1)*3+2,mat,q,'OUTSTANDING_DEMAND',raw='Grey Concrete Paving Block 200 x 100 x 60 mm' if i==1 else None)
        s['demand_requests'].append(dict(id=ident('DEM',i),destination_project_id=ident('PRJ',prj),material_id=ident('MAT',mat),origin_document_row_id=origin,required_quantity=q,fulfilled_quantity=0,unit='pcs',needed_from='2026-09-27',required_by='2026-10-18' if i==8 else '2026-10-30',request_status='CANCELLED' if i==13 else 'OPEN',is_outstanding_need_confirmed=True))
    row(3,1,2000,'PLANNED_REQUIREMENT','PENDING')
    row(6,1,1800,'PURCHASE_ORDER','ACCEPTED')
    row(1,1,500,'ON_HAND_INVENTORY','PENDING')
    row(2,15,120,'OUTSTANDING_DEMAND','CORRECTED')
    row(9,16,100,'PLANNED_REQUIREMENT','REJECTED')
    row(15,20,250,'PLANNED_REQUIREMENT','PENDING')
    distances=[25,8,65,35,70,6,28,55,60,45]
    for i,((a,b),distance) in enumerate(zip(itertools.combinations(range(1,6),2),distances),1):
        s['route_distances'].append(dict(id=ident('RTE',i),from_project_id=ident('PRJ',a),to_project_id=ident('PRJ',b),distance_km=distance,assumption_type='SIMULATED_ROAD_DISTANCE',transport_mode='ROAD_FREIGHT',is_synthetic=True))
    for i,(kind,mat,value,unit) in enumerate([('NEW_MATERIAL_PRODUCTION',1,.75,'kgCO2e/pcs'),('NEW_MATERIAL_PRODUCTION',2,.95,'kgCO2e/pcs'),('NEW_MATERIAL_PRODUCTION',3,.8,'kgCO2e/pcs'),('NEW_MATERIAL_PRODUCTION',9,.55,'kgCO2e/pcs'),('NEW_MATERIAL_PRODUCTION',15,2.1,'kgCO2e/pcs'),('NEW_MATERIAL_PRODUCTION',18,.85,'kgCO2e/pcs'),('TRANSPORT',None,.12,'kgCO2e/t-km'),('PROCESSING',None,.02,'kgCO2e/pcs')],1):
        s['emission_factors'].append(dict(id=ident('EF',i),factor_type=kind,material_id=ident('MAT',mat) if mat else None,material_category=None,transport_mode='ROAD_FREIGHT' if kind=='TRANSPORT' else None,value=value,unit=unit,source_label='SYNTHETIC_DEMO_FACTOR',source_url=None,geography='Synthetic Malaysian demo context, not a verified local factor',lifecycle_boundary='Hypothetical production substitution; extra road freight and per-piece handling. Excludes baseline freight/disposal, credits and official inventory.',version='demo-v1',valid_from='2026-09-01',is_demo_factor=True))
    snapshot={'as_of':'2026-09-26','supply_offers':copy.deepcopy(s['supply_offers']),'demand_requests':copy.deepcopy(s['demand_requests']),'materials':copy.deepcopy(s['materials']),'route_distances':copy.deepcopy(s['route_distances']),'factor_dataset_version':'demo-v1'}
    for i,objective in enumerate(['MAX_REUSE','MAX_NET_CO2E_AVOIDED','EARLIEST_DEADLINE','MAX_REUSE'],1):
        s['optimisation_runs'].append(dict(id=ident('RUN',i),created_at=ts(1,8),objective=objective,inputs_snapshot_hash=digest(snapshot),input_snapshot=copy.deepcopy(snapshot),factor_dataset_version='demo-v1',solver_status='SUCCEEDED',assumptions={'method':'Manually designed synthetic historical feasible/candidate plan, not an executed solver','symmetric_routes':True,'lead_time_days':1,'demo':True}))
    # One executed history, separate alternatives, ineligible candidates and current open case.
    plans=[(1,1,1,600,'ELIGIBLE','SELECTED',['SAME_SPEC']),(1,1,2,400,'ELIGIBLE','SELECTED',['SAME_SPEC','ONE_SUPPLY_MULTIPLE_DEMANDS']),(1,3,3,300,'ELIGIBLE','SELECTED',['PARTIAL_ALLOCATION']),(1,4,4,250,'ELIGIBLE','SELECTED',['PARTIAL_ALLOCATION']),(1,5,5,200,'ELIGIBLE','SELECTED',['SAME_SPEC']),(1,6,6,250,'ELIGIBLE','SELECTED',['SAME_SPEC']),(1,11,10,250,'ELIGIBLE','SELECTED',['SAME_SPEC']),(1,22,21,300,'ELIGIBLE','SELECTED',['PARTIAL_ALLOCATION']),(2,2,1,500,'ELIGIBLE','PROPOSED',['DISTANCE_BETTER']),(2,1,1,100,'ELIGIBLE','PROPOSED',['PARTIAL_ALLOCATION']),(2,1,2,400,'ELIGIBLE','PROPOSED',['SAME_SPEC']),(3,8,7,300,'INELIGIBLE','REJECTED',['MATERIAL_SPEC_MISMATCH']),(3,9,8,150,'INELIGIBLE','REJECTED',['TOO_LATE']),(3,10,9,150,'ELIGIBLE','EXPIRED',['CARBON_INSUFFICIENT_DATA']),(4,22,21,350,'ELIGIBLE','PROPOSED',['PARTIAL_ALLOCATION'])]
    for i,(run,sup,dem,q,compat,status,reasons) in enumerate(plans,1):
        s['allocation_proposals'].append(dict(id=ident('ALC',i),run_id=ident('RUN',run),supply_offer_id=ident('SUP',sup),demand_request_id=ident('DEM',dem),proposed_quantity=q,unit='pcs',compatibility_result=compat,status=status,reason_codes=reasons,created_at=ts(1,9)))
    # Current quantities and their complete chronological audit history.
    stages=[(6,'REUSED',600,0,600,580,550),(7,'REUSED',400,0,400,400,400),(3,'RESERVED',300,300,0,0,0),(4,'IN_TRANSIT',250,0,250,0,0),(5,'RECEIVED',200,0,200,200,0),(2,'APPROVED',250,0,0,0,0),(1,'REQUESTED',0,0,0,0,0),(8,'CANCELLED',300,0,0,0,0)]
    # tuple's first element is stable transfer number; proposals 1..8.
    for proposal,(num,status,approved,reserved,dispatched,received,used) in enumerate(stages,1):
        events=['REQUESTED']
        if status!='REQUESTED': events+=['APPROVED']
        if status in ['RESERVED','IN_TRANSIT','RECEIVED','REUSED','CANCELLED']: events+=['RESERVED']
        if status in ['IN_TRANSIT','RECEIVED','REUSED']: events+=['DISPATCHED']
        if status in ['RECEIVED','REUSED']: events+=['RECEIVED']
        if status=='REUSED': events+=['USED']
        if status=='CANCELLED': events+=['CANCELLED']
        quantities={'REQUESTED':0,'APPROVED':approved,'RESERVED':approved,'DISPATCHED':dispatched,'RECEIVED':received,'USED':used,'CANCELLED':approved}
        t=dict(id=ident('TRF',num),proposal_id=ident('ALC',proposal),approved_quantity=approved,reserved_quantity=reserved,dispatched_quantity=dispatched,received_quantity=received,actually_used_quantity=used,status=status,source_confirmation_status='PENDING' if status=='REQUESTED' else 'CONFIRMED',destination_confirmation_status='PENDING' if status=='REQUESTED' else 'CONFIRMED',requested_at=ts(2),delivered_at=ts(6) if received else None,reuse_confirmed_at=ts(7) if used else None,notes='Synthetic workflow history; no real approvals.' if num!=6 else 'Partial use: 20 missing and 30 received unused. All 50 remain incoming commitments pending disposition. No return or terminal closure is asserted.')
        s['transfers'].append(t)
        for j,event in enumerate(events,2):
            payload={'quantity':quantities[event],'synthetic':True}
            if num==6 and event=='USED':payload['unresolved_quantity']=50
            if event=='CANCELLED':payload['reason']='Demo destination schedule changed before dispatch; release the active 300 pcs hold.'
            s['transfer_events'].append(dict(id=ident('EVT',len(s['transfer_events'])+1),transfer_id=t['id'],event_type=event,occurred_at=ts(j),actor_label='Demo operator',payload=payload,evidence_ref='SYNTHETIC event; no physical evidence'))
        p=s['allocation_proposals'][proposal-1]; supply=s['supply_offers'][int(p['supply_offer_id'][-3:])-1];demand=s['demand_requests'][int(p['demand_request_id'][-3:])-1]
        supply['reserved_active_quantity']+=reserved;supply['transferred_out_quantity']+=dispatched;demand['fulfilled_quantity']+=used
        if demand['fulfilled_quantity']==demand['required_quantity']:demand['request_status']='FULFILLED'
    s['transfers'].sort(key=lambda x:x['id'])
    # Eight assessments, one per entity/basis. Partial actual use stays incomplete.
    for n,(basis,ref) in enumerate([('PROPOSAL_FORECAST',1),('PROPOSAL_FORECAST',9),('PROPOSAL_FORECAST',10),('PROPOSAL_FORECAST',14),('ACTUAL_CONFIRMED_USE',6),('ACTUAL_CONFIRMED_USE',7),('PROPOSAL_FORECAST',3),('PROPOSAL_FORECAST',5)],1):
        transfer=next((t for t in s['transfers'] if t['id']==ident('TRF',ref)),None) if basis=='ACTUAL_CONFIRMED_USE' else None
        p=s['allocation_proposals'][int(transfer['proposal_id'][-3:])-1] if transfer else s['allocation_proposals'][ref-1]
        offer=s['supply_offers'][int(p['supply_offer_id'][-3:])-1]; demand=s['demand_requests'][int(p['demand_request_id'][-3:])-1];material=s['materials'][int(offer['material_id'][-3:])-1]
        route=next(r for r in s['route_distances'] if {r['from_project_id'],r['to_project_id']}=={offer['source_project_id'],demand['destination_project_id']})
        factor=next((f for f in s['emission_factors'] if f['material_id']==material['id']),None)
        q=transfer['actually_used_quantity'] if transfer else p['proposed_quantity'];moved=transfer['dispatched_quantity'] if transfer else q
        production=float(D(q)*D(str(factor['value']))) if factor else None
        freight=float(D(moved)*D(str(material['mass_kg_per_unit']))/1000*D(route['distance_km'])*D('.12')) if material['mass_kg_per_unit'] is not None else None
        partial=bool(transfer and q!=moved);handling=None if partial else float(D(moved)*D('.02'))
        net=float(D(str(production))-D(str(freight))-D(str(handling))) if all(x is not None for x in [production,freight,handling]) else None
        s['impact_assessments'].append(dict(id=ident('IMP',n),basis=basis,proposal_id=p['id'] if not transfer else None,transfer_id=transfer['id'] if transfer else None,quantity_assessed=q,unit='pcs',baseline_description='Hypothetical displacement of functionally equivalent new procurement, synthetic baseline; no official inventory deduction.',avoided_production_kgco2e=production,additional_transport_kgco2e=freight,additional_processing_kgco2e=handling,net_avoided_kgco2e=net,factor_ids=([factor['id']] if factor else [])+['EF-007']+([] if partial else ['EF-008']),assumptions={'symmetric_route_id':route['id'],'distance_km':route['distance_km'],'transport_mode':'ROAD_FREIGHT','mass_kg_per_unit':material['mass_kg_per_unit'],'moved_quantity':moved,'handling_allocation':'UNDEFINED_PARTIAL_USE' if partial else 'ALL_MOVED_UNITS','substitution_ratio':1,'synthetic':True,'omissions':['baseline freight','disposal','credit issuance'],'unresolved_quantity':moved-q if partial else 0},calculation_status='DEMO' if net is not None else 'INSUFFICIENT_DATA',calculated_at=ts(8) if transfer else ts(1,10)))
    return s

if __name__=='__main__':
    value=json.dumps(build(),indent=2,ensure_ascii=False)+'\n'
    target=ROOT/'data/terra_seed.json'
    if '--check' in sys.argv:
        assert target.read_text(encoding='utf-8')==value,'Seed differs from deterministic generation';print('Deterministic baseline matches')
    else:target.write_text(value, encoding="utf-8", newline="\n");print('Wrote',target)
