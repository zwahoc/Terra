"""Read-only private workspace archives, never operational restore/publication."""
import json
import os
import re
from pathlib import Path
from fastapi import APIRouter,Depends
from fastapi.responses import FileResponse
from backend.app.routes.ingestion import local_operator,run
from backend.app.services.ingestion_content import native_media_type
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_storage import SourceStore
from backend.app.schemas.ingestion import IngestionBatch
from terra.workspace_archive import DEFAULT_ARCHIVES,file_hash

router=APIRouter(prefix='/api/history',tags=['history'],dependencies=[Depends(local_operator)])

def root():return Path(os.environ.get('TERRA_WORKSPACE_ARCHIVES',str(DEFAULT_ARCHIVES))).resolve()
def checked_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',value):raise IngestionError('ARCHIVE_NOT_FOUND','Historical workspace not found.',404)
    return value

def manifest(archive_id):
    path=root()/checked_id(archive_id)/'manifest.json'
    if not path.is_file():raise IngestionError('ARCHIVE_NOT_FOUND','Historical workspace not found.',404)
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('status')!='COMPLETE':raise IngestionError('ARCHIVE_INCOMPLETE','This archive is not available.',409)
    return data

def batch(archive_id,batch_id):
    m=manifest(archive_id);bid=checked_id(batch_id)
    entry=next((b for b in m['batches'] if b['id']==bid),None)
    path=root()/archive_id/'batches'/(bid+'.json')
    if entry is None or not path.is_file():raise IngestionError('HISTORY_BATCH_NOT_FOUND','Historical analysis not found.',404)
    if file_hash(path)!=entry['sha256']:raise IngestionError('HISTORY_INTEGRITY_ERROR','Historical analysis integrity check failed.',409)
    return json.loads(path.read_text(encoding='utf-8'))

@router.get('')
def index():
    def read():
        rows=[]
        if not root().exists():return rows
        for path in sorted(root().glob('*/manifest.json'),reverse=True):
            m=json.loads(path.read_text(encoding='utf-8'))
            if m.get('status')!='COMPLETE':continue
            rows.append({k:m[k] for k in ('id','label','created_at','batches')})
        return rows
    return run(read,stage='HISTORY_READ')

@router.get('/{archive_id}/batches/{batch_id}')
def read_batch(archive_id:str,batch_id:str):return run(lambda:batch(archive_id,batch_id),stage='HISTORY_READ_ONLY')

@router.get('/{archive_id}/batches/{batch_id}/files/{submission_id}/source')
def source(archive_id:str,batch_id:str,submission_id:str):
    saved=IngestionBatch.model_validate(batch(archive_id,batch_id))
    submission=next((s for s in saved.submissions if s.id==submission_id),None)
    if submission is None:raise IngestionError('SOURCE_NOT_FOUND','Historical source not found.',404)
    store=SourceStore(root()/archive_id/'sources')
    path=store.path(submission.source)
    with path.open('rb') as handle:media=native_media_type(handle.read(16))
    return FileResponse(path,filename=submission.source.display_filename,media_type=media or 'application/octet-stream',
        content_disposition_type='inline' if media else 'attachment',
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox; default-src 'none'"})
