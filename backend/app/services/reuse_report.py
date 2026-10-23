"""Read-only cumulative reuse reporting from one guarded operational snapshot."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.app.domain.carbon import assessment_factor_units_valid
from backend.app.repositories.impact_repository import ImpactRepository, ImpactRepositoryError, ImpactRepositoryUnavailable
from backend.app.services.impact_service import _load, ImpactConflict, ImpactError, ImpactNotFound, ImpactUnavailable
from terra.local_adapter import AdapterError, AdapterUnavailableError
from terra.quantities import amount, unit
from backend.app.services.ingestion_errors import IngestionError

ZONE=timezone(timedelta(hours=8))
NOTICE='Comparative estimates only. Not an official emissions deduction, verified waste diversion or carbon credit.'


def _number(value):
    return None if value is None else Decimal(str(value))


def _input(assessment, name, default=None):
    assumptions=assessment.get('assumptions',{}) if assessment else {}
    saved=assumptions.get('source_input',{})
    return saved[name] if name in saved else assumptions.get(name,default)


def _factor_rows(assessment, factors):
    if not assessment:return []
    saved=assessment.get('assumptions',{}).get('factor_snapshots')
    return saved if saved is not None else [factors[i] for i in assessment['factor_ids'] if i in factors]


def _provenance(assessment, selected_factors, material, weight_source, route):
    demo=sum(f.get('is_demo_factor') is True for f in selected_factors)
    factor_kind=('Demonstration' if demo==len(selected_factors) else 'Mixed') if demo else 'Other factors' if selected_factors else 'Not available'
    notes=[]
    if demo:notes.append('Demonstration factors')
    if material.get('is_synthetic'):notes.append('Demonstration catalogue material')
    if route and route.get('is_synthetic'):notes.append('Demonstration route')
    if weight_source:notes.append('Weight basis: '+str(weight_source))
    elif unit(material['standard_unit'])!='kg':notes.append('Weight source not recorded')
    if assessment and not assessment.get('assumptions',{}).get('factor_snapshots'):
        notes.append('Legacy assessment: factor references use the current register')
    return factor_kind,notes


def _evidence(supply, demand, snapshot, published, events):
    documents={r['id']:r for r in snapshot['documents']}
    extracted={r['id']:r for r in snapshot['extracted_rows']}
    result=[]
    def location(source):
        return ' · '.join(str(x) for x in [f"Page {source['source_page']}" if source.get('source_page') else '',source.get('source_item_ref'),source.get('source_locator')] if x)
    def add(role, label, locator='', kind='', reference='', recorded_at=None):
        entry={'role':role,'label':str(label),'locator':str(locator or ''),'kind':kind,'reference':reference,'recorded_at':recorded_at}
        if entry not in result:result.append(entry)
    for role,record in [('Source',supply),('Recipient',demand)]:
        origin=extracted.get(record.get('origin_document_row_id'))
        if origin:
            doc=documents.get(origin['document_id'],{})
            add(role,doc.get('display_filename','Source register'),origin.get('source_locator'),
                'Demonstration register' if doc.get('is_simulated') else 'Document',origin['id'])
        for ref in record.get('evidence_refs',[]):
            observed=published.get(ref)
            if observed:
                source=observed.get('source',{});doc=documents.get(source.get('document_id'),{})
                locator=location(source)
                add(role,doc.get('display_filename') or source.get('label') or 'Published observation',locator,
                    'Operator entry' if source.get('kind')=='MANUAL' else 'Document',ref)
            else:add(role,ref,kind='Stored reference',reference=ref)
    # Published demand IDs are not source row IDs. Only claim an exact link
    # when its deterministic projection identity matches a stored observation.
    if demand.get('origin_document_row_id') is None and published:
        from backend.app.services.publication_service import stable
        for record in published.values():
            if (record.get('record_kind')=='OUTSTANDING_DEMAND'
                    and stable('DEM',record.get('publication_id'),record.get('review_row_id'))==demand['id']):
                source=record.get('source',{});doc=documents.get(source.get('document_id'),{})
                add('Recipient',doc.get('display_filename') or source.get('label') or 'Published demand',
                    location(source),'Document' if source.get('kind')=='FILE' else 'Operator entry',record['id'])
    for event in events:
        if event.get('evidence_ref'):add('Transfer',event['evidence_ref'],event['event_type'].replace('_',' ').title(),'Event',event['id'],event['occurred_at'])
    return result


def build_reuse_report(repository=None, *, project_id=None, transfer_id=None, clock=None, include_evidence=True):
    """No calculations or mutations of stored assessments, transfers or model state."""
    repository=repository or ImpactRepository()
    adapter=getattr(repository,'_adapter',None)
    try:
        guarded=adapter is not None and bool(adapter.execute('GetQuantityEncoding')['quantityEncoding'])
        before=adapter.execute('GetOperationalVersion')['operationalVersion'] if guarded else None
        snapshot=_load(repository)
        heads=repository.list_heads()
        if len(heads)>=1000:raise ImpactConflict('REPORT_READ_CAPACITY','Current assessment selection reached its read capacity. No partial report was exported.')
        intents={};published={}
        if guarded:
            from backend.app.services.matching_service import pages
            intents={r['id']:r for r in pages(adapter,'PageImpactIntents')}
            if include_evidence:
                published={r['id']:r['payload'] for r in pages(adapter,'PageArchiveProjectMaterialRecord')}
        after=adapter.execute('GetOperationalVersion')['operationalVersion'] if guarded else None
        if before!=after:raise ImpactConflict('IMPACT_INPUT_STALE','Terra changed while preparing the report. Please export again.')
    except (AdapterUnavailableError,ImpactRepositoryUnavailable) as exc:
        raise ImpactUnavailable('REPORT_UNAVAILABLE','Current report data is unavailable. Retry after reconnecting.') from exc
    except (AdapterError,ImpactRepositoryError) as exc:
        raise ImpactError('REPORT_DATA_ERROR','Report inputs could not be read consistently.') from exc
    except IngestionError as exc:
        if exc.code=='MATCHING_INPUT_STALE':
            raise ImpactConflict('IMPACT_INPUT_STALE','Terra changed while preparing the report. Please export again.') from exc
        raise
    indexes={name:{r['id']:r for r in snapshot[name]} for name in ('projects','materials','supply_offers','demand_requests','allocation_proposals','impact_assessments','route_distances')}
    if project_id and project_id not in indexes['projects']:raise ImpactNotFound('PROJECT_NOT_FOUND','The selected report project was not found.')
    if transfer_id and not any(t['id']==transfer_id for t in snapshot['transfers']):raise ImpactNotFound('TRANSFER_NOT_FOUND','The selected transfer was not found.')
    current={h['transfer_id']:indexes['impact_assessments'].get(h['current_assessment_id']) for h in heads if h['basis']=='ACTUAL_CONFIRMED_USE' and h.get('transfer_id')}
    events=defaultdict(list)
    for e in snapshot['transfer_events']:events[e['transfer_id']].append(e)
    factors={f['id']:f for f in snapshot['emission_factors']}
    rows=[];issues=[];groups={}
    for transfer in sorted(snapshot['transfers'],key=lambda r:(r['requested_at'],r['id'])):
        if transfer_id and transfer['id']!=transfer_id:continue
        proposal=indexes['allocation_proposals'][transfer['proposal_id']]
        supply=indexes['supply_offers'][proposal['supply_offer_id']];demand=indexes['demand_requests'][proposal['demand_request_id']]
        sid=supply['source_project_id'];did=demand['destination_project_id']
        if project_id and project_id not in (sid,did):continue
        material=indexes['materials'][supply['material_id']]
        used=amount(transfer['actually_used_quantity']);moved=amount(transfer['dispatched_quantity']);received=amount(transfer['received_quantity'])
        ref=f'T{len(rows)+1:03}'
        assessment=current.get(transfer['id']);intent=intents.get(transfer['id'])
        status='Not yet used';reason=None
        if used:
            if intent and intent['status']!='COMPLETED':
                status='Calculation failed' if intent['status']=='FAILED' else 'Calculation pending'
                reason='Retry the estimate in Reports.' if intent['status']=='FAILED' else 'Wait for the current estimate to finish, then export again.'
                assessment=None
            elif assessment is None:status='Not calculated';reason='Calculate or retry the current actual-use estimate.'
            elif assessment['basis']!='ACTUAL_CONFIRMED_USE' or assessment['transfer_id']!=transfer['id']:
                status='Assessment link needs review';reason='Retry the estimate for this transfer.';assessment=None
            elif not assessment_factor_units_valid(assessment,snapshot['emission_factors']):
                status='Inputs need review';reason='Check factor units and retry the estimate.';assessment=None
            elif (_number(assessment['quantity_assessed'])!=used
                    or unit(assessment['unit'])!=unit(proposal['unit'])
                    or _number(_input(assessment,'moved_quantity')) not in (None,moved)
                    or _input(assessment,'activity_at',transfer['reuse_confirmed_at'])!=transfer['reuse_confirmed_at']):
                status='Estimate out of date';reason='Retry the estimate against the latest confirmed use.';assessment=None
            else:
                status='Complete' if assessment['net_avoided_kgco2e'] is not None else 'Incomplete'
                if status=='Incomplete':reason='Supply the missing inputs and retry the estimate.'
                elif not {'NEW_MATERIAL_PRODUCTION','TRANSPORT','PROCESSING'}.issubset({f['factor_type'] for f in _factor_rows(assessment,factors)}):
                    status='Factor evidence missing';reason='Restore the factor references or recalculate the estimate.';assessment=None
        else:assessment=None
        selected_factors=_factor_rows(assessment,factors)
        mass=_number(1 if unit(material['standard_unit'])=='kg' else material.get('mass_kg_per_unit'))
        route=next((r for r in snapshot['route_distances'] if {r['from_project_id'],r['to_project_id']}=={sid,did}),None)
        factor_kind,notes=_provenance(assessment,selected_factors,material,_input(assessment,'mass_source',material.get('mass_source')),route)
        missing=list(assessment.get('assumptions',{}).get('missing_data',[])) if assessment else []
        if status=='Incomplete' and not missing:missing=['Required calculation inputs or boundary not recorded']
        if used and status!='Complete':issues.append({'ref':ref,'material':material['canonical_name'],'status':status,'details':'; '.join(str(v).replace('_',' ').lower() for v in missing) or status,'action':reason})
        if used and mass is None:issues.append({'ref':ref,'material':material['canonical_name'],'status':'Weight unavailable','details':'Reused mass cannot be determined for this transfer.','action':'Confirm a product-specific unit weight.'})
        dates={}
        for event in sorted(events[transfer['id']],key=lambda e:e['occurred_at']):dates[event['event_type']]=event['occurred_at']
        role='Supplied' if project_id==sid else 'Received' if project_id==did else 'Cross-project'
        row={'ref':ref,'transfer_id':transfer['id'],'material_id':material['id'],'material':material['canonical_name'],
            'specifications':material['specifications'],'source_id':sid,'source':indexes['projects'][sid]['name'],
            'recipient_id':did,'recipient':indexes['projects'][did]['name'],'role':role,'unit':proposal['unit'],
            'reserved':amount(transfer['reserved_quantity']),'dispatched':moved,'received':received,'used':used,
            'unused':received-used,'state':transfer['status'].replace('_',' ').title(),'confirmed_at':dates.get('RESERVED'),
            'dispatched_at':dates.get('DISPATCHED'),'received_at':transfer['delivered_at'],'used_at':transfer['reuse_confirmed_at'],
            'known_mass_tonnes':used*mass/1000 if mass is not None else None,'current_mass_kg_per_unit':mass,
            'assessment':assessment,'assessment_status':status,'factors':selected_factors,'factor_kind':factor_kind,'provenance':notes,
            'carbon_weight':1 if unit(material['standard_unit'])=='kg' else _input(assessment,'mass_kg_per_unit'),
            'distance':_input(assessment,'distance_km'),'revision':assessment.get('assumptions',{}).get('revision',{}).get('number',1) if assessment else None,
            'evidence':_evidence(supply,demand,snapshot,published,events[transfer['id']]) if include_evidence else []}
        rows.append(row)
        key=(material['id'],proposal['unit'],role)
        if key not in groups:groups[key]={'material':row['material'],'role':role,'unit':row['unit'],'dispatched':Decimal(0),'received':Decimal(0),'used':Decimal(0),'unused':Decimal(0),'known_mass_tonnes':Decimal(0),'unknown_mass_transfers':0,'known_net':Decimal(0),'complete':0}
        group=groups[key]
        for name in ('dispatched','received','used','unused'):group[name]+=row[name]
        if row['known_mass_tonnes'] is not None:group['known_mass_tonnes']+=row['known_mass_tonnes']
        elif used:group['unknown_mass_transfers']+=1
        if status=='Complete':group['known_net']+=_number(assessment['net_avoided_kgco2e']);group['complete']+=1
    used_rows=[r for r in rows if r['used']>0];complete=[r for r in used_rows if r['assessment_status']=='Complete']
    known_net=sum((_number(r['assessment']['net_avoided_kgco2e']) for r in complete),Decimal(0))
    net_by_basis={name:sum((_number(r['assessment']['net_avoided_kgco2e']) for r in complete if r['factor_kind']==name),Decimal(0)) for name in ('Demonstration','Mixed','Other factors')}
    unknown_mass=sum(r['known_mass_tonnes'] is None for r in used_rows)
    scope=indexes['projects'].get(project_id)
    return {'scope':{'project_id':project_id,'project_name':scope['name'] if scope else 'All projects','project_code':scope['code'] if scope else 'all-projects','transfer_id':transfer_id},
        'generated_at':(clock() if clock else datetime.now(ZONE)).astimezone(ZONE).isoformat(),
        'operational_revision':before['revision'] if before else None,'notice':NOTICE,
        'summary':{'transfers':len(rows),'used_transfers':len(used_rows),'complete_estimates':len(complete),
            'missing_estimates':len(used_rows)-len(complete),'unknown_mass_transfers':unknown_mass,
            'known_reuse_tonnes':sum((r['known_mass_tonnes'] for r in used_rows if r['known_mass_tonnes'] is not None),Decimal(0)),
            'known_net_kgco2e':known_net if complete or not used_rows else None,'net_by_factor_basis':net_by_basis,
            'demonstration_estimates':sum(r['factor_kind'] in ('Demonstration','Mixed') for r in complete)},
        'materials':sorted(groups.values(),key=lambda r:(r['material'],r['unit'],r['role'])),'transfers':rows,'issues':issues}
