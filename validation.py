"""Offline validation of the baseline, histories and comparative impact arithmetic."""
import json,re,hashlib
from datetime import date,datetime,timedelta
from decimal import Decimal as D
from collections import defaultdict
from pathlib import Path
from terra.contract import FIELDS,MODELS,PREFIXES,COUNTS,fields

SEED=Path(__file__).resolve().parents[1]/'data/terra_seed.json'
ACTIVE={'RESERVED','IN_TRANSIT','RECEIVED','REUSED'}

def load(path=SEED):
    def invalid(value): raise ValueError(f'Invalid JSON numeric value: {value}')
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out: raise ValueError(f'Duplicate JSON key: {key}')
            out[key]=value
        return out
    return json.loads(Path(path).read_text(),parse_constant=invalid,object_pairs_hook=unique)

def require(condition,message):
    if not condition: raise ValueError(message)

def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def maps(seed):return {e:{r['id']:r for r in seed[e]} for e in FIELDS}

def balances(seed):
    idx=maps(seed);incoming=defaultdict(int);held=defaultdict(int);issued=defaultdict(int);fulfilled=defaultdict(int)
    for t in seed['transfers']:
        p=idx['allocation_proposals'][t['proposal_id']];sid=p['supply_offer_id'];did=p['demand_request_id']
        held[sid]+=t['reserved_quantity'];issued[sid]+=t['dispatched_quantity'];fulfilled[did]+=t['actually_used_quantity']
        if t['status'] in ACTIVE: incoming[did]+=t['approved_quantity']-t['actually_used_quantity']
    return held,issued,fulfilled,incoming

def reservable(supply,as_of):
    if supply['surplus_status']!='CONFIRMED' or supply['condition']!='UNUSED' or supply['confirmed_quantity'] is None: return 0
    if supply['available_from']>as_of or supply['available_until'] is not None and supply['available_until']<as_of:return 0
    return supply['confirmed_quantity']-supply['reserved_active_quantity']-supply['transferred_out_quantity']

def summary(seed):
    idx=maps(seed);_,_,_,incoming=balances(seed);mass=D(0);unknown=[];projects=set();outstanding={}
    for t in seed['transfers']:
        if not t['actually_used_quantity']:continue
        p=idx['allocation_proposals'][t['proposal_id']];s=idx['supply_offers'][p['supply_offer_id']];d=idx['demand_requests'][p['demand_request_id']];m=idx['materials'][s['material_id']]
        projects.update([s['source_project_id'],d['destination_project_id']])
        if m['mass_kg_per_unit'] is None: unknown.append(t['id'])
        else:mass+=D(t['actually_used_quantity'])*D(str(m['mass_kg_per_unit']))
    for d in seed['demand_requests']:
        outstanding[d['id']]=d['required_quantity']-d['fulfilled_quantity']-incoming[d['id']] if d['request_status']=='OPEN' and d['is_outstanding_need_confirmed'] else 0
    return {'counts':{e:len(seed[e]) for e in FIELDS},'confirmed_reuse_mass_t':float(mass/1000),'unknown_reuse_mass_transfers':unknown,'reuse_projects_source_and_destination':len(projects),'newly_allocatable_demand_pcs_by_id':outstanding,'reservable_pcs_by_offer':{s['id']:reservable(s,seed['metadata']['as_of_date']) for s in seed['supply_offers']},'actual_estimated_net_kgco2e':float(sum((D(str(i['net_avoided_kgco2e'])) for i in seed['impact_assessments'] if i['basis']=='ACTUAL_CONFIRMED_USE' and i['net_avoided_kgco2e'] is not None),D(0))),'incomplete_assessments':[i['id'] for i in seed['impact_assessments'] if i['calculation_status']=='INSUFFICIENT_DATA']}

def validate(seed,check_scenarios=True):
    require(set(seed)==set(FIELDS)|{'metadata'},'Exactly 13 entity arrays and metadata required')
    meta=seed['metadata']
    require(set(meta)=={'dataset_name','version','as_of_date','timezone','synthetic','currency','carbon_unit','disclaimer'},'Metadata fields missing or unexpected')
    require(meta['version']=='1.0.0' and meta['dataset_name']=='Terra Option B Synthetic Baseline' and 'Synthetic' in meta['disclaimer'],'Metadata identity/provenance mismatch')
    require(meta['synthetic'] is True,'Synthetic flag required')
    require(meta['as_of_date']=='2026-10-12' and meta['timezone']=='Asia/Kuala_Lumpur','Baseline/timezone mismatch')
    require(meta['currency']=='MYR' and meta['carbon_unit']=='kgCO2e','Currency/carbon units mismatch')
    date.fromisoformat(meta['as_of_date']);idx=maps(seed)
    for entity in FIELDS:
        lo,hi=COUNTS[entity];require(lo<=len(seed[entity])<=hi,f'{entity}: count outside fixture contract')
        require(len(idx[entity])==len(seed[entity]),f'{entity}: duplicate ID')
        for row in seed[entity]:
            MODELS[entity].model_validate(row)
            require(bool(re.fullmatch(PREFIXES[entity]+r'-\d{3}',row['id'])),f'{entity}: unstable ID')
            for name,spec,optional in fields(entity):
                v=row[name]
                if v is None:continue
                if spec.startswith('FK='):require(v in idx[spec.split('=')[1]],f'{row["id"]}: orphan {name}')
                if spec=='date': date.fromisoformat(v)
                if spec=='timestamp':
                    instant=datetime.fromisoformat(v);require(v.endswith('+08:00') and instant.utcoffset()==timedelta(hours=8),f'{row["id"]}: timestamp timezone')
                    require(instant.date()<=date.fromisoformat(meta['as_of_date']),f'{row["id"]}: future historical event')
                if spec in ('int','float'):
                    number=D(str(v));require(number.is_finite(),f'{row["id"]}: nonfinite numeric')
                    if name!='net_avoided_kgco2e':require(number>=0,f'{row["id"]}: negative {name}')
            if row.get('unit') is not None and entity not in ('emission_factors',):require(row['unit']=='pcs',f'{row["id"]}: unsupported unit')
    require(len({p['code'] for p in seed['projects']})==len(seed['projects']),'Duplicate project code')
    for p in seed['projects']:
        require('Demo' in p['name'],'Project not labelled demo')
        require(p['start_date']<=p['target_end_date'],'Project schedule invalid')
    specs=set()
    for m in seed['materials']:
        key=(m['category'],json.dumps(m['specifications'],sort_keys=True));require(key not in specs,'Duplicate material specification');specs.add(key)
        spec=m['specifications'];require(all(spec.get(k,0)>0 for k in ['length_mm','width_mm']),'Material dimensions absent')
        require(spec.get('thickness_mm',spec.get('height_mm',0))>0,'Material depth absent')
        require(m['is_synthetic'] and m['mass_source']==('SYNTHETIC_ASSUMPTION' if m['mass_kg_per_unit'] is not None else None),'Material mass provenance')
    for doc in seed['documents']:
        require(doc['file_uri'] is None and doc['file_hash'] is None and doc['is_simulated'] and doc['processing_status']=='SIMULATED' and doc['source_availability']=='METADATA_ONLY','Fake source file')
    kinds={'PLANNED_REQUIREMENT','PURCHASE_ORDER','ON_HAND_INVENTORY','POTENTIAL_SURPLUS','CONFIRMED_SURPLUS','OUTSTANDING_DEMAND'}
    for r in seed['extracted_rows']:
        f=r['parsed_fields'];require(r['is_simulated'] and 'SYNTHETIC' in r['source_locator'],'Row provenance not synthetic')
        require(f.get('record_kind') in kinds and type(f.get('quantity')) is int and f['quantity']>=0 and f.get('unit')=='pcs','Invalid parsed row')
        require(r['confidence_score'] is None or 0<=r['confidence_score']<=1,'Confidence out of range')
        doc=idx['documents'][r['document_id']]
        if doc['document_type']=='BOQ':require(f['record_kind']=='PLANNED_REQUIREMENT','BOQ reclassified as physical stock')
        if doc['document_type']=='PURCHASE_ORDER':require(f['record_kind']=='PURCHASE_ORDER','PO reclassified as physical stock')
        if r['review_status']=='CORRECTED':require('correction' in f and f['correction']['actor_label']=='Demo operator','Missing correction history')
    held,issued,fulfilled,incoming=balances(seed)
    for entity,project in [('supply_offers','source_project_id'),('demand_requests','destination_project_id')]:
        for r in seed[entity]:
            if r['origin_document_row_id']:
                origin=idx['extracted_rows'][r['origin_document_row_id']];doc=idx['documents'][origin['document_id']]
                require(origin['review_status'] in ['ACCEPTED','CORRECTED'],'Unreviewed published row')
                require(origin['suggested_material_id']==r['material_id'] and doc['project_id']==r[project],'Origin mapping mismatch')
                require(origin['parsed_fields']['record_kind'] not in ['PLANNED_REQUIREMENT','PURCHASE_ORDER'],'BOQ/PO published without independent reconciliation')
    for s in seed['supply_offers']:
        require(s['available_until'] is None or s['available_from']<=s['available_until'],'Offer window reversed')
        require(s['reserved_active_quantity']==held[s['id']] and s['transferred_out_quantity']==issued[s['id']],'Source counters do not reconcile')
        if s['surplus_status']=='POTENTIAL':require(s['confirmed_quantity'] is None and not held[s['id']] and not issued[s['id']],'Potential supply reserved')
        if s['confirmed_quantity'] is not None:require(s['confirmed_quantity']<=s['declared_quantity'] and held[s['id']]+issued[s['id']]<=s['confirmed_quantity'],'Stock overallocated')
    for d in seed['demand_requests']:
        require(d['needed_from']<=d['required_by'],'Demand window reversed')
        require(d['required_quantity']>0 and d['fulfilled_quantity']==fulfilled[d['id']],'Demand fulfilment drift')
        require(d['fulfilled_quantity']+incoming[d['id']]<=d['required_quantity'],'Demand overcommitted')
        if d['request_status']=='FULFILLED':require(d['fulfilled_quantity']==d['required_quantity'],'False fulfilled demand')
        if d['request_status']=='CANCELLED':require(not incoming[d['id']],'Cancelled demand has commitment')
    pairs=set()
    for route in seed['route_distances']:
        pair=(route['from_project_id'],route['to_project_id']);require(pair[0]<pair[1] and pair not in pairs and route['distance_km']>0,'Route pair invalid');pairs.add(pair)
        require(route['is_synthetic'],'Route not synthetic')
    for run in seed['optimisation_runs']:
        snap=run['input_snapshot'];require(sha(snap)==run['inputs_snapshot_hash'],'Run snapshot hash mismatch')
        require(snap['as_of']<=run['created_at'][:10],'Run references future snapshot')
        require(run['factor_dataset_version']=='demo-v1','Factor version mismatch')
    allocated=defaultdict(int);required=defaultdict(int)
    for p in seed['allocation_proposals']:
        run=idx['optimisation_runs'][p['run_id']];snapshot=run['input_snapshot'];ss={x['id']:x for x in snapshot['supply_offers']};dd={x['id']:x for x in snapshot['demand_requests']}
        s=ss[p['supply_offer_id']];d=dd[p['demand_request_id']]
        require(p['proposed_quantity']>0 and p['created_at']>=run['created_at'],'Proposal quantity/time')
        require(s['source_project_id']!=d['destination_project_id'],'Self-project match')
        eligible=s['material_id']==d['material_id'] and s['unit']==d['unit'] and s['surplus_status']=='CONFIRMED' and s['condition']=='UNUSED' and d['request_status']=='OPEN' and d['is_outstanding_need_confirmed'] and s['available_from']<=d['required_by'] and (s['available_until'] is None or s['available_until']>=d['needed_from'])
        if p['compatibility_result']=='ELIGIBLE':require(eligible,'Incompatible proposal marked eligible')
        if p['status']=='SELECTED':require(p['compatibility_result']=='ELIGIBLE','Invalid selected proposal')
        if p['compatibility_result']=='ELIGIBLE' and p['status'] in ['PROPOSED','SELECTED']:
            allocated[(run['id'],s['id'])]+=p['proposed_quantity'];required[(run['id'],d['id'])]+=p['proposed_quantity']
            require(allocated[(run['id'],s['id'])]<=s['confirmed_quantity']-s['reserved_active_quantity']-s['transferred_out_quantity'],'One run overallocates source')
            require(required[(run['id'],d['id'])]<=d['required_quantity']-d['fulfilled_quantity'],'One run overallocates recipient')
    used_proposals=set()
    path={'REQUESTED':['REQUESTED'],'APPROVED':['REQUESTED','APPROVED'],'RESERVED':['REQUESTED','APPROVED','RESERVED'],'IN_TRANSIT':['REQUESTED','APPROVED','RESERVED','DISPATCHED'],'RECEIVED':['REQUESTED','APPROVED','RESERVED','DISPATCHED','RECEIVED'],'REUSED':['REQUESTED','APPROVED','RESERVED','DISPATCHED','RECEIVED','USED'],'CANCELLED':['REQUESTED','APPROVED','RESERVED','CANCELLED']}
    for t in seed['transfers']:
        require(t['proposal_id'] not in used_proposals,'Duplicate transfer for proposal');used_proposals.add(t['proposal_id']);p=idx['allocation_proposals'][t['proposal_id']]
        require(p['status']=='SELECTED' and p['compatibility_result']=='ELIGIBLE','Transfer from unselected/incompatible candidate')
        require(0<=t['actually_used_quantity']<=t['received_quantity']<=t['dispatched_quantity']<=t['approved_quantity']<=p['proposed_quantity'],'Transfer quantity hierarchy')
        require(t['reserved_quantity']+t['dispatched_quantity']<=t['approved_quantity'],'Dispatched still reserved')
        events=sorted([e for e in seed['transfer_events'] if e['transfer_id']==t['id']],key=lambda e:e['occurred_at'])
        require([e['event_type'] for e in events]==path[t['status']],'Invalid transfer event history')
        require(t['requested_at']==events[0]['occurred_at'] and t['requested_at']>=p['created_at'],'Transfer requested chronology')
        values={e['event_type']:e for e in events}
        for event,column in [('APPROVED','approved_quantity'),('DISPATCHED','dispatched_quantity'),('RECEIVED','received_quantity'),('USED','actually_used_quantity')]:
            require((values[event]['payload']['quantity'] if event in values else 0)==t[column],f'Event/{column} mismatch')
        require(t['delivered_at']==(values['RECEIVED']['occurred_at'] if 'RECEIVED' in values else None),'Receipt timestamp mismatch')
        require(t['reuse_confirmed_at']==(values['USED']['occurred_at'] if 'USED' in values else None),'Use timestamp mismatch')
        require(t['reserved_quantity']==(t['approved_quantity'] if t['status']=='RESERVED' else 0),'Active hold stage mismatch')
        if t['status'] not in ['REQUESTED']:
            require(t['source_confirmation_status']=='CONFIRMED' and t['destination_confirmation_status']=='CONFIRMED','Missing transfer confirmations')
        if t['dispatched_quantity']:
            s=idx['supply_offers'][p['supply_offer_id']];d=idx['demand_requests'][p['demand_request_id']]
            require(values['DISPATCHED']['occurred_at'][:10]>=s['available_from'],'Dispatch before availability')
            if t['delivered_at']:require(d['needed_from']<=t['delivered_at'][:10]<=d['required_by'],'Receipt outside window')
        if t['status']=='REUSED':
            require(t['actually_used_quantity']>0,'False reused status')
            residual=t['approved_quantity']-t['actually_used_quantity']
            if residual:require(values['USED']['payload'].get('unresolved_quantity')==residual and 'pending' in t['notes'].lower(),'Unexplained partial reuse')
    for e in seed['transfer_events']:require(e['actor_label']=='Demo operator' and e['payload'].get('synthetic') and 'SYNTHETIC' in e['evidence_ref'],'Fake event attestation')
    for f in seed['emission_factors']:
        require(f['is_demo_factor'] and f['source_label']=='SYNTHETIC_DEMO_FACTOR' and f['source_url'] is None and f['version']=='demo-v1','Factor provenance invalid')
        require(f['valid_from']<=meta['as_of_date'],'Factor not valid at baseline')
        require(f['unit'] in {'kgCO2e/pcs','kgCO2e/kg','kgCO2e/t-km'},'Unsupported factor unit')
    assess_keys=set()
    for i in seed['impact_assessments']:
        actual=i['basis']=='ACTUAL_CONFIRMED_USE'; require(bool(i['transfer_id'])==actual and bool(i['proposal_id'])!=actual,'Impact basis link mismatch')
        key=(i['basis'],i['transfer_id'] or i['proposal_id']);require(key not in assess_keys,'Repeated environmental outcome');assess_keys.add(key)
        t=idx['transfers'][i['transfer_id']] if actual else None;p=idx['allocation_proposals'][t['proposal_id'] if t else i['proposal_id']]
        s=idx['supply_offers'][p['supply_offer_id']];d=idx['demand_requests'][p['demand_request_id']];m=idx['materials'][s['material_id']];a=i['assumptions'];q=i['quantity_assessed']
        require(q==(t['actually_used_quantity'] if t else p['proposed_quantity']),'Impact quantity basis wrong')
        require(i['calculated_at']>=(t['reuse_confirmed_at'] if t else p['created_at']),'Assessment before basis')
        require(all(f in idx['emission_factors'] for f in i['factor_ids']),'Orphan factor ID')
        ff=[idx['emission_factors'][f] for f in i['factor_ids']]
        production=next((f for f in ff if f['factor_type']=='NEW_MATERIAL_PRODUCTION'),None);freight=next((f for f in ff if f['factor_type']=='TRANSPORT'),None);processing=next((f for f in ff if f['factor_type']=='PROCESSING'),None)
        route=idx['route_distances'][a['symmetric_route_id']]
        require({route['from_project_id'],route['to_project_id']}=={s['source_project_id'],d['destination_project_id']} and a['distance_km']==route['distance_km'],'Impact route mismatch')
        require(a['mass_kg_per_unit']==m['mass_kg_per_unit'] and a['synthetic'] and a['substitution_ratio']==1,'Impact assumptions drift')
        moved=t['dispatched_quantity'] if t else q;require(a['moved_quantity']==moved,'Impact movement wrong')
        expected_production=None
        if production:
            require(production['material_id']==m['id'],'Wrong production factor applicability')
            expected_production=D(q)*D(str(production['value']))
            if production['unit']=='kgCO2e/kg':expected_production=expected_production*D(str(m['mass_kg_per_unit'])) if m['mass_kg_per_unit'] is not None else None
        expected_freight=D(moved)*D(str(m['mass_kg_per_unit']))/1000*D(str(route['distance_km']))*D(str(freight['value'])) if freight and m['mass_kg_per_unit'] is not None else None
        expected_processing=D(moved)*D(str(processing['value'])) if processing and a['handling_allocation']=='ALL_MOVED_UNITS' else None
        expected_net=expected_production-expected_freight-expected_processing if all(v is not None for v in [expected_production,expected_freight,expected_processing]) else None
        for name,value in zip(['avoided_production_kgco2e','additional_transport_kgco2e','additional_processing_kgco2e','net_avoided_kgco2e'],[expected_production,expected_freight,expected_processing,expected_net]):
            require((i[name] is None and value is None) or (i[name] is not None and value is not None and abs(D(str(i[name]))-value)<D('0.00000001')),f'{i["id"]}: carbon arithmetic {name}')
        require((i['calculation_status']=='INSUFFICIENT_DATA')==(expected_net is None),'Incomplete carbon status mismatch')
    if check_scenarios:scenario_checks(seed)
    return summary(seed)

def scenario_checks(seed):
    idx=maps(seed)
    require([sum(m['category']==c for m in seed['materials']) for c in ['PAVING_BLOCK','BRICK','TILE']]==[8,6,6],'Material category coverage')
    require(idx['extracted_rows']['ROW-001']['suggested_material_id']==idx['extracted_rows']['ROW-023']['suggested_material_id']=='MAT-001','Alias fixture missing')
    require(idx['allocation_proposals']['ALC-012']['compatibility_result']=='INELIGIBLE' and idx['allocation_proposals']['ALC-013']['reason_codes']==['TOO_LATE'],'Negative matching cases missing')
    require(idx['supply_offers']['SUP-007']['surplus_status']=='POTENTIAL','Potential fixture missing')
    require(idx['transfers']['TRF-006']['actually_used_quantity']==550 and idx['transfers']['TRF-005']['actually_used_quantity']==0,'Use stage fixtures missing')
    require(idx['optimisation_runs']['RUN-001']['inputs_snapshot_hash']==idx['optimisation_runs']['RUN-002']['inputs_snapshot_hash'],'Strategy inputs differ')
    require(idx['impact_assessments']['IMP-004']['net_avoided_kgco2e'] is None,'Missing carbon fixture absent')
    require(idx['impact_assessments']['IMP-002']['additional_transport_kgco2e']/500<idx['impact_assessments']['IMP-001']['additional_transport_kgco2e']/600,'Near route not demonstrable')
