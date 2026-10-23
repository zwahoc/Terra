"""Durable, same-input three-objective matching. No LLM or transfer writes."""
from copy import deepcopy
from backend.app.domain.carbon import CALCULATION_POLICY_VERSION
from backend.app.domain.eligibility import ELIGIBILITY_POLICY_VERSION
from datetime import datetime, timezone, timedelta
from terra.local_adapter import LocalDataConnect, map_entity_rows, AdapterError
from terra.contract import FIELDS,TYPES
from backend.app.services.ingestion_storage import digest_json
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.optimisation_run_service import OptimisationRunInput,build_run_command
from backend.app.services.optimisation_preview_service import preview_comparison

ZONE=timezone(timedelta(hours=8))

def pages(adapter, operation):
    after=''
    while True:
        rows=adapter.execute(operation,{'after':after,'limit':200})['records']
        if not isinstance(rows,list) or any(not isinstance(r.get('id'),str) for r in rows):
            raise ValueError('Invalid paginated matching data')
        if rows and (rows[0]['id']<=after or any(a['id']>=b['id'] for a,b in zip(rows,rows[1:]))):
            raise ValueError('Matching pagination is not strictly increasing')
        yield from rows
        if len(rows)<200:break
        after=rows[-1]['id']

def current_records(adapter):
    before=adapter.execute('GetOperationalVersion')['operationalVersion']
    if before is None:raise ValueError('Operational version is not initialised')
    records={e:map_entity_rows(e,list(pages(adapter,'PageRuntime'+TYPES[e]+'s'))) for e in FIELDS}
    identity=adapter.execute('GetWorkspaceIdentity')['workspaceIdentity']
    records['_workspace_epoch']=identity['epoch'] if identity else None
    after=adapter.execute('GetOperationalVersion')['operationalVersion']
    if before!=after:raise IngestionError('MATCHING_INPUT_STALE','Inputs changed while loading matching.',409)
    return records,after['revision']

def dependency(records,mid,day):
    supplies=[r for r in records['supply_offers'] if r['material_id']==mid]
    demands=[r for r in records['demand_requests'] if r['material_id']==mid]
    sids={r['id'] for r in supplies};dids={r['id'] for r in demands}
    projects={r['source_project_id'] for r in supplies}|{r['destination_project_id'] for r in demands}
    proposals={r['id']:r for r in records['allocation_proposals'] if r['supply_offer_id'] in sids or r['demand_request_id'] in dids}
    transfers=[r for r in records['transfers'] if r['proposal_id'] in proposals]
    used={r['proposal_id'] for r in transfers}
    material=next(r for r in records['materials'] if r['id']==mid)
    return digest_json({'workspace_epoch':records.get('_workspace_epoch'),'eligibility_policy_version':ELIGIBILITY_POLICY_VERSION,'calculation_policy_version':CALCULATION_POLICY_VERSION,'date':str(day),'material':material,'supplies':supplies,'demands':demands,
        'projects':[r for r in records['projects'] if r['id'] in projects],
        'transfers':transfers,'committed_proposals':[r for k,r in proposals.items() if k in used],
        'routes':[r for r in records['route_distances'] if r['from_project_id'] in projects and r['to_project_id'] in projects],
        'factors':[r for r in records['emission_factors'] if r['material_id'] in (None,mid) and r['material_category'] in (None,material['category'])]})

def material_records(records,mid):
    """Keep related transfer provenance; no old unexecuted plans enter inputs."""
    data=deepcopy(records)
    data['supply_offers']=[r for r in data['supply_offers'] if r['material_id']==mid]
    data['demand_requests']=[r for r in data['demand_requests'] if r['material_id']==mid]
    sids={r['id'] for r in data['supply_offers']};dids={r['id'] for r in data['demand_requests']}
    props={r['id']:r for r in data['allocation_proposals'] if r['supply_offer_id'] in sids and r['demand_request_id'] in dids}
    data['transfers']=[r for r in data['transfers'] if r['proposal_id'] in props]
    used={r['proposal_id'] for r in data['transfers']}
    data['allocation_proposals']=[r for k,r in props.items() if k in used]
    runs={r['run_id'] for r in data['allocation_proposals']}
    data['optimisation_runs']=[r for r in data['optimisation_runs'] if r['id'] in runs]
    origins={r['origin_document_row_id'] for r in [*data['supply_offers'],*data['demand_requests']] if r['origin_document_row_id']}
    data['extracted_rows']=[r for r in data['extracted_rows'] if r['id'] in origins]
    documents={r['document_id'] for r in data['extracted_rows']}
    data['documents']=[r for r in data['documents'] if r['id'] in documents]
    projects={r['source_project_id'] for r in data['supply_offers']}|{r['destination_project_id'] for r in data['demand_requests']}
    projects|={r['project_id'] for r in data['documents']}
    data['projects']=[r for r in data['projects'] if r['id'] in projects]
    data['materials']=[r for r in data['materials'] if r['id']==mid]
    data['route_distances']=[r for r in data['route_distances'] if r['from_project_id'] in projects and r['to_project_id'] in projects]
    category=data['materials'][0]['category']
    data['emission_factors']=[r for r in data['emission_factors'] if r['material_id'] in (None,mid) and r['material_category'] in (None,category)]
    data['impact_assessments']=[]
    return data

class MatchingService:
    def __init__(self,adapter=None,clock=None):
        self.adapter=adapter or LocalDataConnect()
        self.clock=clock or (lambda:datetime.now(ZONE))

    def refresh(self,*,retry_failed=False):
        a=self.adapter
        if not a.execute('GetQuantityEncoding').get('quantityEncoding'):
            return {'state':'AWAITING_LOCAL_CUTOVER','scopes':[]}
        records,revision=current_records(a);today=self.clock().date()
        existing={r['id']:r for r in pages(a,'PageMatchingScopes')}
        mids=sorted({r['material_id'] for r in records['supply_offers']}|{r['material_id'] for r in records['demand_requests']})
        outcomes=[]
        for mid in mids:
            fingerprint=dependency(records,mid,today)
            scope=existing.get(mid)
            token=f'{today}:{fingerprint}'
            if scope and scope['status']=='CURRENT' and scope['token']==token:
                outcomes.append({'material_id':mid,'status':'CURRENT'});continue
            if scope and scope['status']=='FAILED' and scope['token']==token and not retry_failed:
                outcomes.append({'material_id':mid,'status':'FAILED'});continue
            # Only changed scopes need another consistent read. Unchanged
            # materials do not reload the entire database on every poll.
            records,revision=current_records(a)
            fingerprint=dependency(records,mid,today);token=f'{today}:{fingerprint}'
            scope=a.execute('GetMatchingScope',{'id':mid})['matchingScope']
            if scope and scope['status']=='CURRENT' and scope['token']==token:continue
            if not scope or scope['token']!=token or scope['status']!='PENDING':
                a.execute('DirtyMatchingScope',{'id':mid,'token':token,'expectedRevision':revision},write=True)
            try:
                records,revision=current_records(a)
                if dependency(records,mid,today)!=fingerprint:continue
                gid='GEN-'+digest_json({'material':mid,'token':token})[:32]
                if a.execute('GetMatchingGeneration',{'id':gid})['matchingGeneration']:
                    a.execute('ReactivateMatchingGeneration',{'id':gid,'materialId':mid,'token':token,
                        'fingerprint':fingerprint,'expectedRevision':revision},write=True)
                    outcomes.append({'material_id':mid,'status':'CURRENT'});continue
                inputs=material_records(records,mid)
                versions=sorted({r['version'] for r in records['emission_factors']})
                version='demo-v1' if 'demo-v1' in versions else versions[-1] if versions else 'demo-v1'
                result=preview_comparison(inputs,planning_date=today,factor_dataset_version=version)
                gid='GEN-'+digest_json({'material':mid,'token':token})[:32]
                commands=[];alternatives=[]
                for option in result['alternatives']:
                    objective=option['plan']['objective']
                    request=OptimisationRunInput(objective,today,version,None,f'{gid}:{objective}','Terra matching')
                    command=build_run_command(request,option,inputs,occurred=self.clock().isoformat(),proposal_status='PROPOSED')
                    command['run']['assumptions'].update(matching_generation=gid,matching_material_id=mid)
                    commands.append(command)
                    alternatives.append({**option,'run_id':command['runId'],'proposal_ids':[p['id'] for p in command['proposals']],
                        'proposals':[{**p,'earliest_start':allocation['earliest_dispatch_date']} for p,allocation in zip(command['proposals'],option['plan']['allocations'])]})
                payload={'generation_id':gid,'material_id':mid,'eligibility_policy_version':ELIGIBILITY_POLICY_VERSION,'fingerprint':fingerprint,'planning_date':str(today),
                    'generated_at':self.clock().isoformat(),'alternatives':alternatives}
                values={'id':gid,'materialId':mid,'token':token,'fingerprint':fingerprint,'payload':payload,'expectedRevision':revision,
                    'operations':[{'id':c['operationId'],'requestFingerprint':c['requestFingerprint'],'runId':c['runId']} for c in commands]}
                for key in ('proposals','assessments','heads'):values[key]=[r for c in commands for r in c[key]]
                values['runs']=[c['run'] for c in commands]
                a.execute('CommitMatchingGeneration',values,write=True)
                outcomes.append({'material_id':mid,'status':'CURRENT'})
            except Exception as exc:
                if isinstance(exc,IngestionError) and exc.code=='MATCHING_INPUT_STALE':continue
                if isinstance(exc,AdapterError) and ('STALE' in str(exc) or 'ALREADY_EXISTS' in str(exc)):continue
                # Store a bounded public diagnostic, never a source document or credential.
                a.execute('FailMatchingScope',{'id':mid,'token':token,'payload':{'code':'MATCHING_FAILED','message':str(exc)[:500]}},write=True)
                outcomes.append({'material_id':mid,'status':'FAILED'})
        pending=[p for p in pages(a,'PageMatchingPublications') if p['handoffStatus'] in ('PENDING','RECORDED_STUB')]
        if pending and all(m['status']=='CURRENT' for m in self.view().get('materials',[])):
            for pub in pending:
                a.execute('FinishMatchingPublication',{'id':pub['id'],'payload':{**pub['handoffPayload'],'matcher_execution':'COMPLETED','mode':'AUTOMATIC_MATCHING','scope_results':outcomes}},write=True)
        return {'state':'READY','scopes':outcomes}

    def view(self):
        a=self.adapter
        if not a.execute('GetQuantityEncoding').get('quantityEncoding'):
            return {'state':'AWAITING_LOCAL_CUTOVER','materials':[]}
        records,_=current_records(a);today=self.clock().date();result=[]
        scopes={r['id']:r for r in pages(a,'PageMatchingScopes')}
        mids=sorted({r['material_id'] for r in records['supply_offers']}|{r['material_id'] for r in records['demand_requests']})
        for mid in mids:
            scope=scopes.get(mid);fingerprint=dependency(records,mid,today)
            current=scope and scope['status']=='CURRENT' and scope['token']==f'{today}:{fingerprint}'
            payload=a.execute('GetMatchingGeneration',{'id':scope['generationId']})['matchingGeneration']['payload'] if current else None
            material=next(r for r in records['materials'] if r['id']==mid)
            result.append({'material_id':mid,'material_name':material['canonical_name'],'unit':material['standard_unit'],
                'status':'CURRENT' if current else 'FAILED' if scope and scope['status']=='FAILED' else 'PENDING',
                'generation':payload,'error':scope['payload'] if scope and scope['status']=='FAILED' else None})
        return {'state':'READY','materials':result,'observed_on':str(today)}

    def require_current(self,proposal):
        a=self.adapter
        from backend.app.repositories.optimisation_repository import OptimisationRepository
        run=OptimisationRepository(a).get(proposal['run_id']).run
        gid=run['assumptions'].get('matching_generation')
        if not gid:
            if not a.execute('GetQuantityEncoding').get('quantityEncoding'):return
            snapshot=run.get('input_snapshot',{})
            if all(k in snapshot for k in ('materials','supply_offers','demand_requests','projects','transfers','allocation_proposals','route_distances','emission_factors')):
                records,_=current_records(a)
                offer=next((r for r in records['supply_offers'] if r['id']==proposal['supply_offer_id']),None)
                day=self.clock().date()
                if offer and snapshot.get('as_of')==str(day) and dependency(snapshot,offer['material_id'],day)==dependency(records,offer['material_id'],day):return
            raise IngestionError('RECOMMENDATION_SUPERSEDED','Open current matching results before confirming.',409)
        mid=run['assumptions']['matching_material_id']
        scope=a.execute('GetMatchingScope',{'id':mid})['matchingScope']
        records,_=current_records(a)
        if not scope or scope['status']!='CURRENT' or scope['generationId']!=gid or scope['token']!=f'{self.clock().date()}:{dependency(records,mid,self.clock().date())}':
            raise IngestionError('RECOMMENDATION_SUPERSEDED','This recommendation is no longer current. Open refreshed matching results.',409)
