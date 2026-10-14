"""Local-only REST adapter; cloud credentials and deployment are intentionally absent.

The emulator supports named administrative impersonateQuery/impersonateMutation.
Omitting extensions uses its privileged local execution context. Ordinary execute*
operations still enforce @auth. Production authentication must be proven separately.
"""
import json,os
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from datetime import datetime,timezone,timedelta
from terra.contract import FIELDS,fields,camel

class AdapterError(RuntimeError):pass

class AdapterUnavailableError(AdapterError):pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise AdapterError('Redirect refused by local adapter')

class LocalDataConnect:
    def __init__(self,host=None,project='demo-terra-local'):
        host=host or os.environ.get('DATA_CONNECT_EMULATOR_HOST','127.0.0.1:9399')
        parsed=urlsplit('http://'+host)
        if parsed.hostname!='127.0.0.1' or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.port:
            raise ValueError('Only an explicit IPv4 loopback emulator host:port is permitted')
        if project!='demo-terra-local':raise ValueError('This adapter only supports demo-terra-local')
        self.base=f'http://{host}/v1/projects/{project}/locations/us-central1/services/terra-local/connectors/terra:'
        self.opener=build_opener(ProxyHandler({}),NoRedirect())
    def execute(self,operation,variables=None,write=False,admin=True):
        method=('impersonate' if admin else 'execute')+('Mutation' if write else 'Query')
        body=json.dumps({'operationName':operation,'variables':variables or {}},allow_nan=False).encode()
        request=Request(self.base+method,body,{'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=30) as response: raw=response.read()
        except HTTPError as exc:
            detail=exc.read().decode(errors='replace')
            exc.close()
            raise AdapterError(f'{operation}: HTTP {exc.code}: {detail}') from exc
        except (URLError,TimeoutError,OSError) as exc:raise AdapterUnavailableError(f'{operation}: emulator transport error: {exc}') from exc
        try:payload=json.loads(raw)
        except json.JSONDecodeError as exc:raise AdapterError(f'{operation}: emulator returned invalid JSON') from exc
        if payload.get('errors'):raise AdapterError(f'{operation}: GraphQL errors: {json.dumps(payload["errors"])}')
        if 'data' not in payload or payload['data'] is None:raise AdapterError(f'{operation}: response has no data')
        return payload['data']
    def snapshot(self):
        data=self.execute('SeedSnapshot')
        return {entity:map_entity_rows(entity,data[camel(entity)]) for entity in FIELDS}

def map_entity_rows(entity,rows):
    """Map provider camelCase rows to Terra fields and local snapshot timestamps."""
    if entity not in FIELDS:raise AdapterError(f'Unknown Terra entity mapping: {entity}')
    if not isinstance(rows,list):raise AdapterError(f'{entity}: provider result is not a list')
    mapped=[]
    try:
        for provider_row in rows:
            if not isinstance(provider_row,dict):raise TypeError
            row={name:provider_row[camel(name)] for name,_,_ in fields(entity)}
            for name,spec,_ in fields(entity):
                if spec=='timestamp' and row[name] is not None:
                    row[name]=datetime.fromisoformat(row[name].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))).isoformat()
            mapped.append(row)
    except (KeyError,TypeError,ValueError) as exc:raise AdapterError(f'{entity}: invalid provider record shape') from exc
    return mapped

def variables(seed):
    result={camel(e):[{camel(name):row[name] for name,_,_ in fields(e)} for row in seed[e]] for e in FIELDS}
    # SQL Connect maintains this provider-only counter so reservations can check
    # recipient capacity with a row-locked, atomic increment. The canonical JSON
    # remains the source of truth; its value is derived from transfer histories.
    from terra.validation import balances
    incoming=balances(seed)[3]
    result['demandCommitmentBalances']=[
        {'demandRequestId':row['id'],'committedQuantity':incoming[row['id']]}
        for row in seed['demand_requests']
    ]
    # Runtime carbon revisions use provider-only scope heads.  Seed assessments
    # remain unchanged; each existing one is revision 1 for its scope, while
    # unassessed proposals/transfers begin with an empty revision-0 head.
    current={}
    for assessment in seed['impact_assessments']:
        entity_id=(assessment['proposal_id'] if assessment['basis']=='PROPOSAL_FORECAST'
                   else assessment['transfer_id'])
        current[f"{assessment['basis']}:{entity_id}"]=assessment
    heads=[]
    for basis,entity,field in (
        ('PROPOSAL_FORECAST','allocation_proposals','proposalId'),
        ('ACTUAL_CONFIRMED_USE','transfers','transferId'),
    ):
        for row in seed[entity]:
            scope=f"{basis}:{row['id']}"; assessment=current.get(scope)
            head={'id':scope,'basis':basis,'proposalId':None,'transferId':None,
                  'currentAssessmentId':assessment['id'] if assessment else None,
                  'revision':1 if assessment else 0,'inputFingerprint':None,
                  'updatedAt':assessment['calculated_at'] if assessment else None}
            head[field]=row['id']; heads.append(head)
    result['impactAssessmentHeads']=heads
    return result

def normalized(snapshot):
    out={}
    for e in FIELDS:
        rows=[]
        for row in snapshot[e]:
            value=dict(row)
            for name,spec,_ in fields(e):
                if value[name] is not None and spec=='timestamp':value[name]=datetime.fromisoformat(value[name].replace('Z','+00:00')).isoformat()
                if value[name] is not None and spec=='timestamp':value[name]=datetime.fromisoformat(value[name]).timestamp()
            rows.append(value)
        out[e]=sorted(rows,key=lambda x:x['id'])
    return out

def equivalent(left,right):return normalized(left)==normalized(right)
