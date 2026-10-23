"""Explicitly confirmed master/input corrections, never model tool writes."""
from copy import deepcopy
from datetime import date
from terra.contract import camel,fields
from terra.quantities import amount
from backend.app.services.matching_service import current_records
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.ingestion_errors import IngestionError

def correct_inputs(adapter,command):
    if not command.confirmed:raise IngestionError('CONFIRMATION_REQUIRED','Confirm the input correction before saving.',409)
    if command.kind!='PROJECT_FACTS' and not command.basis.strip():
        raise IngestionError('INPUT_BASIS_REQUIRED','Record the source or estimate basis for this carbon input.',422)
    aid='INPUT-'+digest_json(command.idempotency_key)[:32]
    prior=adapter.execute('GetRuntimeAudit',{'id':aid})['runtimeAudit']
    fingerprint=digest_json(command.model_dump(mode='json',exclude={'expected_revision'}))
    if prior:
        if prior['payload']['request_fingerprint']!=fingerprint:raise IngestionError('INPUT_KEY_REUSED','This key belongs to a different input correction.',409)
        return {'id':aid,'replayed':True}
    records,revision=current_records(adapter)
    if revision!=command.expected_revision:raise IngestionError('RUNTIME_INPUT_STALE','Inputs changed; review the current values.',409)
    projects=[];materials=[];routes=[];before=None;after=None
    def find(entity,rid):
        row=next((r for r in records[entity] if r['id']==rid),None)
        if row is None:raise IngestionError('INPUT_NOT_FOUND','The selected input record was not found.',404)
        return row
    if command.kind=='MATERIAL_MASS':
        before=deepcopy(find('materials',command.material_id));after=deepcopy(before)
        mass=amount(command.values.get('mass_kg_per_unit'))
        if mass<=0:raise IngestionError('INPUT_INVALID','Material weight must be positive.',422)
        after.update(mass_kg_per_unit=float(mass),mass_source=command.basis)
        materials=[after];affected={command.material_id}
    elif command.kind=='ROUTE_DISTANCE':
        source=find('projects',command.source_project_id);dest=find('projects',command.destination_project_id)
        if source['id']==dest['id']:raise IngestionError('INPUT_INVALID','Choose two different projects.',422)
        distance=amount(command.values.get('distance_km'))
        if distance<=0:raise IngestionError('INPUT_INVALID','Route distance must be positive.',422)
        before=next((r for r in records['route_distances'] if {r['from_project_id'],r['to_project_id']}=={source['id'],dest['id']}),None)
        after={**(before or {}),'id':before['id'] if before else 'RTE-'+digest_json(sorted([source['id'],dest['id']]))[:24],
            'from_project_id':source['id'],'to_project_id':dest['id'],'distance_km':float(distance),
            'assumption_type':'SIMULATED_ROAD_DISTANCE','transport_mode':'ROAD_FREIGHT','is_synthetic':True}
        routes=[after]
        affected={r['material_id'] for r in records['supply_offers'] if r['source_project_id'] in (source['id'],dest['id'])}
        affected|={r['material_id'] for r in records['demand_requests'] if r['destination_project_id'] in (source['id'],dest['id'])}
    else:
        before=deepcopy(find('projects',command.project_id));after=deepcopy(before)
        allowed={'name','code','township','managing_organisation','start_date','target_end_date','address'}
        if not command.values or set(command.values)-allowed or any(not v.strip() for v in command.values.values()):
            raise IngestionError('INPUT_INVALID','Choose explicit nonempty supported project corrections.',422)
        for k,v in command.values.items():
            if k.endswith('_date'):date.fromisoformat(v)
            if k=='address':after['location']={**(after.get('location') or {}),'address':v}
            else:after[k]=v
        if after['start_date'] and after['target_end_date'] and after['start_date']>after['target_end_date']:
            raise IngestionError('INPUT_INVALID','Project end date precedes its start.',422)
        projects=[after]
        affected={r['material_id'] for r in records['supply_offers'] if r['source_project_id']==after['id']}
        affected|={r['material_id'] for r in records['demand_requests'] if r['destination_project_id']==after['id']}
    def provider(entity,row):return {camel(n):row[n] for n,_,_ in fields(entity)}
    payload={'request_fingerprint':fingerprint,'basis':command.basis or 'Operator correction','before':before,'after':after}
    # A correction and its impact follow-up intent commit together. Physical
    # quantities are untouched, and unchanged fingerprints produce no revision.
    supplies={r['id']:r for r in records['supply_offers']}
    proposals={r['id']:r for r in records['allocation_proposals']}
    intents=[]
    for transfer in records['transfers']:
        proposal=proposals[transfer['proposal_id']]
        if transfer['actually_used_quantity']>0 and supplies[proposal['supply_offer_id']]['material_id'] in affected:
            if command.kind=='ROUTE_DISTANCE':
                demands={r['id']:r for r in records['demand_requests']}
                pair={supplies[proposal['supply_offer_id']]['source_project_id'],demands[proposal['demand_request_id']]['destination_project_id']}
                if pair!={command.source_project_id,command.destination_project_id}:continue
            intents.append({'id':transfer['id'],'token':aid,'status':'PENDING','payload':{'reason':'Confirmed '+command.kind,'audit_id':aid}})
    adapter.execute('ConfirmRuntimeInputs',{'expectedRevision':revision,'auditId':aid,'kind':command.kind,'payload':payload,
        'projects':[provider('projects',p) for p in projects],'materials':[provider('materials',m) for m in materials],
        'routes':[provider('route_distances',r) for r in routes],
        'impactIntents':intents,'scopes':[{'id':mid,'token':aid,'status':'PENDING','generationId':None,'payload':{}} for mid in sorted(affected)]},write=True)
    return {'id':aid,'replayed':False,'before':before,'after':after}
