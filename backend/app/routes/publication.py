"""Explicit local-only batch publication and receipt read-back."""
from fastapi import APIRouter,Depends
from backend.app.routes.ingestion import local_operator,get_intake_service,run
from backend.app.schemas.publication import PublishBatch
from backend.app.services.publication_service import PublicationService,stable
from backend.app.services.review_service import require

router=APIRouter(prefix='/api/ingestion/batches',tags=['publication'],dependencies=[Depends(local_operator)])

def service(intake=Depends(get_intake_service)):return PublicationService(intake)

@router.get('/{batch_id}/publication-plan')
def plan(batch_id:str,publisher=Depends(service)):return run(lambda:publisher.plan(batch_id),stage='PUBLICATION_PLAN')

@router.post('/{batch_id}/publish')
def publish(batch_id:str,body:PublishBatch,publisher=Depends(service)):return run(lambda:publisher.publish(batch_id,body),stage='PUBLICATION',operational_writes=True)

@router.get('/{batch_id}/publication')
def receipt(batch_id:str,publisher=Depends(service)):return run(lambda:publisher.get_receipt(batch_id),stage='PUBLICATION_RECEIPT')

@router.post('/{batch_id}/publication/handoff/retry')
def handoff(batch_id:str,publisher=Depends(service)):
    def dispatch():
        prior=publisher.get_receipt(batch_id)
        require(prior is not None,'PUBLICATION_NOT_FOUND','There is no committed publication to hand off.')
        from backend.app.services.matching_service import MatchingService
        MatchingService(publisher.repository.adapter).refresh(retry_failed=True)
        return publisher.view_receipt(publisher.repository.dispatch(stable('PUB',batch_id)))
    return run(dispatch,stage='PUBLICATION_HANDOFF',operational_writes=True)
