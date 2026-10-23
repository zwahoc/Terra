"""Local current matching reads and explicit recovery; never approves transfers."""
from fastapi import APIRouter,Depends
from backend.app.routes.ingestion import local_operator,run
from backend.app.services.matching_service import MatchingService
from terra.local_adapter import AdapterError
from backend.app.services.ingestion_errors import IngestionError
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from backend.app.services.runtime_inputs import correct_inputs
from backend.app.services.matching_service import current_records
from terra.local_adapter import LocalDataConnect

router=APIRouter(prefix='/api/matching',tags=['matching'],dependencies=[Depends(local_operator)])
def call(action,**kwargs):
    def perform():
        try:return action()
        except AdapterError as exc:
            if 'STALE' in str(exc):raise IngestionError('MATCHING_INPUT_STALE','Inputs changed while updating matching. Refresh and review current values.',409) from exc
            raise IngestionError('MATCHING_UNAVAILABLE','Current matching data is unavailable. Retry after checking the local database.',503) from exc
    return run(perform,**kwargs)
@router.get('')
def current():return call(lambda:MatchingService().view(),stage='CURRENT_MATCHING')
@router.post('/refresh')
def refresh():return call(lambda:MatchingService().refresh(retry_failed=True),stage='MATCHING_REFRESH',operational_writes=True)

class InputCorrection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    idempotency_key:str=Field(min_length=1,max_length=128)
    kind:Literal['MATERIAL_MASS','ROUTE_DISTANCE','PROJECT_FACTS']
    material_id:str|None=None
    project_id:str|None=None
    source_project_id:str|None=None
    destination_project_id:str|None=None
    values:dict[str,str]
    basis:str=Field(default='',max_length=500)
    confirmed:bool

@router.get('/inputs')
def inputs():
    def read():
        rows,revision=current_records(LocalDataConnect())
        return {'revision':revision,'materials':rows['materials'],'projects':rows['projects'],'routes':rows['route_distances']}
    return call(read,stage='MATCHING_INPUTS')

@router.post('/inputs')
def correction(body:InputCorrection):
    def save():
        try:return correct_inputs(LocalDataConnect(),body)
        except ValueError as exc:raise IngestionError('INPUT_INVALID',str(exc),422) from exc
    return call(save,stage='CONFIRMED_INPUT_CORRECTION',operational_writes=True)
