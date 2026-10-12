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
            with self.opener.open(request,timeout=30) as response: payload=json.loads(response.read())
        except HTTPError as exc:
            detail=exc.read().decode(errors='replace')
            exc.close()
            raise AdapterError(f'{operation}: HTTP {exc.code}: {detail}') from exc
        except (URLError,TimeoutError,OSError,json.JSONDecodeError) as exc:raise AdapterError(f'{operation}: emulator transport error: {exc}') from exc
        if payload.get('errors'):raise AdapterError(f'{operation}: GraphQL errors: {json.dumps(payload["errors"])}')
        if 'data' not in payload or payload['data'] is None:raise AdapterError(f'{operation}: response has no data')
        return payload['data']
    def snapshot(self):
        data=self.execute('SeedSnapshot')
        snapshot={e:[{name:row[camel(name)] for name,_,_ in fields(e)} for row in data[camel(e)]] for e in FIELDS}
        for entity,rows in snapshot.items():
            for row in rows:
                for name,spec,_ in fields(entity):
                    if spec=='timestamp' and row[name] is not None:
                        row[name]=datetime.fromisoformat(row[name].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))).isoformat()
        return snapshot

def variables(seed):
    return {camel(e):[{camel(name):row[name] for name,_,_ in fields(e)} for row in seed[e]] for e in FIELDS}

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
