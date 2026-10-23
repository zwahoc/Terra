"""Current application reads and display totals, independent of HTTP and seed rows."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from backend.app.domain.carbon import assessment_factor_units_valid
from terra.contract import FIELDS, camel
from terra.local_adapter import LocalDataConnect, map_entity_rows, AdapterError
from terra.validation import balances
from terra.quantities import unit
from backend.app.services.ingestion_errors import IngestionError


def workspace_data(adapter=None):
    adapter = adapter or LocalDataConnect()
    try:
        before = adapter.execute('GetOperationalVersion')['operationalVersion']
        raw = adapter.execute('GetPublicationState')
        heads = adapter.execute('ListImpactAssessmentHeads')['impactAssessmentHeads']
        after = adapter.execute('GetOperationalVersion')['operationalVersion']
    except AdapterError as exc:
        raise IngestionError('WORKSPACE_UNAVAILABLE', 'Current Terra data is unavailable. Retry after checking the local database.', 503) from exc
    if before != after or raw['operationalVersion'] != after:
        raise IngestionError('WORKSPACE_CHANGED', 'Terra data changed while loading. Refresh to read the current records.', 409)
    if any(len(value) >= 1000 for value in raw.values() if isinstance(value, list)) or len(heads) >= 1000:
        raise IngestionError('WORKSPACE_READ_CAPACITY', 'The current workspace read reached its capacity. No incomplete snapshot is displayed.', 409)
    records = {entity: map_entity_rows(entity, raw[camel(entity)]) for entity in FIELDS}
    records['materials'] += [row['payload'] for row in raw['registeredMaterials']]
    records['published_records'] = [row['payload'] for row in raw['projectMaterialRecords']]
    records['stock_heads'] = [row['payload'] for row in raw['projectStockHeads']]
    records['superseded_records'] = [
        {'id': row['id'], 'project_id': row['projectId'], 'successor_id': row['successorId']}
        for row in raw['supersededRecords']
    ]
    superseded = {row['id']: row['successor_id'] for row in records['superseded_records']}
    records['published_records'] = [
        {**row, 'is_effective': row['application'] != 'HISTORY_ONLY' and row['id'] not in superseded,
         'superseded_by': superseded.get(row['id'])}
        for row in records['published_records']
    ]
    current_ids = {h['currentAssessmentId'] for h in heads if h['currentAssessmentId']}
    records['impact_assessments'] = [r for r in records['impact_assessments'] if r['id'] in current_ids and assessment_factor_units_valid(r,records['emission_factors'])]
    if adapter.execute('GetQuantityEncoding').get('quantityEncoding'):
        from backend.app.services.matching_service import MatchingService
        view=MatchingService(adapter).view()
        live_runs={a['run_id'] for m in view['materials'] if m['status']=='CURRENT' for a in m['generation']['alternatives'] if a['plan']['objective']=='MAX_REUSE'}
        records['current_matching_run_ids']=live_runs
        records['matching_state']=view
        identity=adapter.execute('GetWorkspaceIdentity')['workspaceIdentity']
        records['workspace_epoch']=identity['epoch'] if identity else 'unassigned'
        from backend.app.services.matching_service import pages
        intents=list(pages(adapter,'PageImpactIntents'))
        records['impact_refresh_intents']=intents
        pending={r['id'] for r in intents if r['status']!='COMPLETED'}
        records['impact_assessments']=[r for r in records['impact_assessments'] if r['transfer_id'] not in pending]

        if adapter.execute('GetOperationalVersion')['operationalVersion'] != after:
            raise IngestionError('WORKSPACE_CHANGED','Terra changed while loading current recommendations. Refresh to read it again.',409)
    records.setdefault('workspace_epoch','legacy')
    return build_workspace(records, datetime.now(timezone(timedelta(hours=8))))


def build_workspace(records, observed_at):
    projects = {r['id']: r for r in records['projects']}
    materials = {r['id']: r for r in records['materials']}
    offers = {r['id']: r for r in records['supply_offers']}
    demands = {r['id']: r for r in records['demand_requests']}
    proposals = {r['id']: r for r in records['allocation_proposals']}
    incoming = balances(records)[3]
    today = observed_at.date().isoformat()
    supply_views = []
    for r in offers.values():
        ready = (r['surplus_status'] == 'CONFIRMED' and r['condition'] == 'UNUSED'
                 and r['available_from'] <= today and (r['available_until'] is None or r['available_until'] >= today))
        quantity = max(0, (r['confirmed_quantity'] or 0)-r['reserved_active_quantity']-r['transferred_out_quantity']) if ready else 0
        supply_views.append({**r, 'project_name': projects[r['source_project_id']]['name'],
                             'material_name': materials[r['material_id']]['canonical_name'], 'reservable_quantity': quantity,
                             'available_after_date':max(today,r['available_from']),
                             'is_future':r['available_from']>today})
    demand_views = [{**r, 'project_name': projects[r['destination_project_id']]['name'],
                     'material_name': materials[r['material_id']]['canonical_name'],
                     'committed_incoming_quantity':incoming[r['id']],
                     'remaining_unfulfilled_quantity': max(0,r['required_quantity']-r['fulfilled_quantity']),
                     'newly_allocatable_quantity': max(0,r['required_quantity']-r['fulfilled_quantity']-incoming[r['id']])}
                    for r in demands.values()]
    transfer_views = []
    known_mass = Decimal(0); missing_mass = []
    for r in records['transfers']:
        p=proposals[r['proposal_id']];s=offers[p['supply_offer_id']];d=demands[p['demand_request_id']];m=materials[s['material_id']]
        transfer_views.append({**r,'source_project_id':s['source_project_id'],'destination_project_id':d['destination_project_id'],'unit':p['unit'],'received_but_unused_quantity':r['received_quantity']-r['actually_used_quantity'], 'material_name':m['canonical_name'],'source_project_name':projects[s['source_project_id']]['name'],
                               'destination_project_name':projects[d['destination_project_id']]['name']})
        if r['actually_used_quantity']:
            mass=1 if unit(m['standard_unit'])=='kg' else m['mass_kg_per_unit']
            if mass is None: missing_mass.append(r['id'])
            else: known_mass += Decimal(str(mass))*r['actually_used_quantity']
    # Show saved proposals only. Never invent matching decisions in the browser.
    requested={r['proposal_id'] for r in records['transfers']}
    candidates=[]
    for p in proposals.values():
        if 'current_matching_run_ids' in records and p['run_id'] not in records['current_matching_run_ids']:continue
        if p['status'] not in ('PROPOSED','SELECTED') or p['compatibility_result']!='ELIGIBLE' or p['id'] in requested:continue
        s=offers[p['supply_offer_id']];d=demands[p['demand_request_id']]
        candidates.append({**p,'source_project_id':s['source_project_id'],'destination_project_id':d['destination_project_id'],'source_project_name':projects[s['source_project_id']]['name'],
                           'destination_project_name':projects[d['destination_project_id']]['name'],
                           'material_name':materials[s['material_id']]['canonical_name'],'maximum_preview_quantity':p['proposed_quantity']})
    def totals(rows,field):
        result={}
        for r in rows:result[r['unit']]=result.get(r['unit'],0)+r[field]
        return result
    by_project={}
    for pid in projects:
        project_transfers=[r for r in transfer_views if r['destination_project_id']==pid or r['source_project_id']==pid]
        mass=Decimal(0);unknown=[]
        for transfer in project_transfers:
            if not transfer['actually_used_quantity']:continue
            proposal=proposals[transfer['proposal_id']];material=materials[offers[proposal['supply_offer_id']]['material_id']]
            weight=1 if unit(material['standard_unit'])=='kg' else material['mass_kg_per_unit']
            if weight is None:unknown.append(transfer['id'])
            else:mass+=Decimal(str(weight))*transfer['actually_used_quantity']
        by_project[pid]={'confirmed_by_unit':totals([r for r in supply_views if r['source_project_id']==pid],'reservable_quantity'),
            'demand_by_unit':totals([r for r in demand_views if r['destination_project_id']==pid and r['request_status']=='OPEN'],'newly_allocatable_quantity'),
            'actual_reuse_tonnes':None if unknown else float(mass/1000),'known_reuse_tonnes':float(mass/1000),'unknown_mass_transfer_ids':unknown}
    public_records={k:v for k,v in records.items() if k not in ('current_matching_run_ids','matching_state','workspace_epoch')}

    return {'terra':{**public_records,'metadata':{'as_of_date':today,'observed_at':observed_at.isoformat(),'workspace_epoch':records.get('workspace_epoch','legacy')}},
            'supply_views':supply_views,'demand_views':demand_views,'transfer_views':transfer_views,'candidate_matches':candidates,
            'matching':records.get('matching_state',{'state':'AWAITING_LOCAL_CUTOVER','materials':[]}),
            'dashboard':{'by_project':by_project,'confirmed_by_unit':totals(supply_views,'reservable_quantity'),
                         'demand_by_unit':totals([d for d in demand_views if d['request_status']=='OPEN'],'newly_allocatable_quantity'),
                         'actual_reuse_tonnes': None if missing_mass else float(known_mass/1000),
                         'known_reuse_tonnes':float(known_mass/1000),'unknown_mass_transfer_ids':missing_mass}}
