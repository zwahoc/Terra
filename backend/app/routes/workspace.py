"""Loopback-only current application view. No operational writes."""
from fastapi import APIRouter, Depends
from backend.app.routes.ingestion import local_operator, run
from backend.app.services.workspace_service import workspace_data

router = APIRouter(prefix='/api', tags=['workspace'], dependencies=[Depends(local_operator)])

@router.get('/workspace')
def workspace():
    return run(workspace_data, stage='WORKSPACE_READ')
