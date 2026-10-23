"""Private, verified REST archives and explicit local cutover. No cloud access."""
import hashlib
import json
import os
import re
import shutil
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
from terra.local_adapter import LocalDataConnect,AdapterError,variables
from terra.quantities import json_default
from terra.workspace_provider import table_specs
from terra.seeding import seed_local
from terra.workspace_state import current_source_root,STATE_FILE

ROOT=Path(__file__).resolve().parents[1]
ZONE=timezone(timedelta(hours=8))
DEFAULT_ARCHIVES=ROOT/'.local'/'workspace-archives'


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=json_default),encoding='utf-8')


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def archive_workspace(adapter=None,*,destination=None,sources=None,label='Local workspace'):
    adapter=adapter or LocalDataConnect()
    destination=Path(destination or DEFAULT_ARCHIVES).resolve();destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    identity=datetime.now(ZONE).strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:10]
    folder=destination/identity;folder.mkdir(mode=0o700);(folder/'tables').mkdir();(folder/'batches').mkdir()
    before=adapter.execute('GetOperationalVersion')['operationalVersion']
    manifest={'id':identity,'label':label,'created_at':datetime.now(ZONE).isoformat(),'adapter':adapter.base,
        'quantity_encoding':adapter.execute('GetQuantityEncoding')['quantityEncoding'],'source_revision':before,
        'status':'INCOMPLETE','tables':{},'batches':[],'source_files':{}}
    write_json(folder/'manifest.json',manifest)
    schema=(ROOT/'dataconnect/schema/schema.gql').read_text(encoding='utf-8')
    for spec in table_specs(schema):
        after='';count=0;path=folder/'tables'/(spec['type']+'.jsonl')
        page_size=1 if any(name in spec['fields'] for name in ('payload','inputSnapshot')) else 100
        with path.open('w',encoding='utf-8') as stream:
            while True:
                rows=adapter.execute('PageArchive'+spec['type'],{'after':after,'limit':page_size})['records']
                if rows and (rows[0][spec['key']]<=after or any(a[spec['key']]>=b[spec['key']] for a,b in zip(rows,rows[1:]))):
                    raise ValueError('Archive cursor is not strictly ordered')
                for row in rows:
                    stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False,default=json_default)+'\n');count+=1
                    if spec['type']=='IngestionBatch':
                        payload=row['payload'];bid=row['id']
                        if not re.fullmatch(r'[A-Za-z0-9_-]+',bid):raise ValueError('Invalid archived batch identity')
                        batch_path=folder/'batches'/(bid+'.json');write_json(batch_path,payload)
                        manifest['batches'].append({'id':bid,'state':payload.get('state'),'revision':row['revision'],
                            'files':[s['source']['display_filename'] for s in payload.get('submissions',[])],
                            'sha256':file_hash(batch_path)})
                if len(rows)<page_size:break
                after=rows[-1][spec['key']]
        manifest['tables'][spec['type']]={'count':count,'sha256':file_hash(path),'key':spec['key'],'fields':spec['fields']}
    source_path=Path(sources or current_source_root()).resolve()
    if source_path.exists():
        shutil.copytree(source_path,folder/'sources',ignore=shutil.ignore_patterns('*.lock'))
        for path in sorted((folder/'sources').rglob('*')):
            if path.is_file():manifest['source_files'][path.relative_to(folder/'sources').as_posix()]={'size':path.stat().st_size,'sha256':file_hash(path)}
    heads=adapter.execute('GetCutoverBatchHeads')['ingestionBatches']
    if len(heads)>=1000 or sorted(heads,key=lambda r:r['id'])!=sorted([{'id':b['id'],'revision':b['revision']} for b in manifest['batches']],key=lambda r:r['id']):
        raise ValueError('Drafts changed while archiving or exceeded the cutover guard capacity. No reset was performed.')
    if adapter.execute('GetOperationalVersion')['operationalVersion']!=before:
        raise ValueError('Workspace changed while archiving; stop application writes and retry. No reset was performed.')
    manifest['status']='COMPLETE';write_json(folder/'manifest.json',manifest)
    verify_archive(folder)
    return manifest,folder


def verify_archive(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status']!='COMPLETE':raise ValueError('Archive is incomplete')
    for name,spec in manifest['tables'].items():
        path=folder/'tables'/(name+'.jsonl')
        if file_hash(path)!=spec['sha256']:raise ValueError('Archive table checksum mismatch')
        with path.open(encoding='utf-8') as stream:count=sum(1 for _ in stream)
        if count!=spec['count']:raise ValueError('Archive count mismatch')
    for spec in manifest['batches']:
        if file_hash(folder/'batches'/(spec['id']+'.json'))!=spec['sha256']:raise ValueError('Archive batch checksum mismatch')
    for relative,spec in manifest['source_files'].items():
        path=folder/'sources'/relative
        if path.stat().st_size!=spec['size'] or file_hash(path)!=spec['sha256']:raise ValueError('Archive source checksum mismatch')
    return manifest


def cutover_workspace(seed,archive_folder,adapter=None,*,confirmation,state_file=None):
    if confirmation!='demo-terra-local':raise ValueError('Explicit demo-terra-local confirmation is required')
    adapter=adapter or LocalDataConnect();manifest=verify_archive(archive_folder)
    if manifest['adapter']!=adapter.base:raise ValueError('Archive belongs to another local database')
    current=adapter.execute('GetOperationalVersion')['operationalVersion']
    if current!=manifest['source_revision']:raise ValueError('Data changed after the archive; take a fresh archive before reset')
    adapter.execute('ResetLocalWorkspace',{'expectedOperationalRevision':current['revision'],
        'expectedBatches':{'batches':[{'id':b['id'],'revision':b['revision']} for b in manifest['batches']]}},write=True)
    # A legacy adapter must switch only after old operational rows are empty.
    if not adapter.execute('GetQuantityEncoding')['quantityEncoding']:
        adapter.execute('InitializeExactQuantities',write=True)
    result=seed_local(seed,adapter)
    epoch='WORKSPACE-'+uuid4().hex
    adapter.execute('InitializeWorkspaceIdentity',{'epoch':epoch,'createdAt':datetime.now(ZONE).isoformat()},write=True)
    source_parent=Path(state_file).parent/'ingestion-workspaces' if state_file else ROOT/'.local/ingestion-workspaces'
    source_root=source_parent/epoch
    source_root.mkdir(parents=True,exist_ok=False,mode=0o700)
    state_path=Path(state_file or STATE_FILE)
    temporary=state_path.with_suffix('.tmp');write_json(temporary,{'epoch':epoch,'source_root':str(source_root),'archive_id':manifest['id']});os.replace(temporary,state_path)
    write_json(Path(archive_folder)/'cutover.json',{'epoch':epoch,'completed_at':datetime.now(ZONE).isoformat(),'baseline':result})
    return {'epoch':epoch,'archive_id':manifest['id'],'baseline':result}
