"""Local review actions; no publication or matching endpoints."""
from fastapi import APIRouter, Depends
from backend.app.routes.ingestion import local_operator, get_intake_service, run as intake_run
from backend.app.schemas.review import SelectReview, RowEdit, ProjectEdit, EntityEdit, ManualSubmission, ScopeConfirmation, ApproveSubmission, BulkDecision, ResolveFile, RevisionCommand, EditorPreview
from backend.app.services.review_service import ReviewService

router = APIRouter(prefix='/api/ingestion/batches', tags=['review'], dependencies=[Depends(local_operator)])


def run(action):
    result = intake_run(action)
    if isinstance(result, dict):
        result['meta']['stage'] = 'DRAFT_REVIEW'
    return result


def service(intake=Depends(get_intake_service)):
    return ReviewService(intake)


@router.get('/{batch_id}/review')
def get_review(batch_id: str, review=Depends(service)):
    return run(lambda: review.get(batch_id))


@router.post('/{batch_id}/review/select')
def select_review(batch_id: str, body: SelectReview, review=Depends(service)):
    return run(lambda: review.select(batch_id, body))


@router.post('/{batch_id}/review/prepare')
def prepare_review(batch_id: str, body: SelectReview, review=Depends(service)):
    return run(lambda: review.prepare(batch_id, body))


@router.post('/{batch_id}/review/editor-preview')
def material_editor_preview(batch_id: str, body: EditorPreview, review=Depends(service)):
    from backend.app.services.material_editor import editor_preview
    return run(lambda: editor_preview(review, batch_id, body))


@router.post('/{batch_id}/review/rebase')
def rebase_review(batch_id: str, body: SelectReview, review=Depends(service)):
    return run(lambda: review.rebase(batch_id, body))


@router.post('/{batch_id}/review/refresh-context')
def refresh_manual_context(batch_id: str, body: RevisionCommand, review=Depends(service)):
    return run(lambda: review.refresh_manual_context(batch_id, body))


@router.post('/{batch_id}/files/{submission_id}/resolution')
def resolve_file(batch_id: str, submission_id: str, body: ResolveFile, review=Depends(service)):
    return run(lambda: review.resolve_file(batch_id, submission_id, body))


@router.post('/{batch_id}/manual-submissions')
def manual(batch_id: str, body: ManualSubmission, review=Depends(service)):
    return run(lambda: review.manual(batch_id, body))


@router.patch('/{batch_id}/review/submissions/{submission_id}/rows/{row_id}')
def edit_row(batch_id: str, submission_id: str, row_id: str, body: RowEdit, review=Depends(service)):
    return run(lambda: review.row(batch_id, submission_id, row_id, body))


@router.patch('/{batch_id}/review/submissions/{submission_id}/projects/{project_id}')
def edit_project(batch_id: str, submission_id: str, project_id: str, body: ProjectEdit, review=Depends(service)):
    return run(lambda: review.project(batch_id, submission_id, project_id, body))


@router.put('/{batch_id}/review/entities/{entity_id}')
def edit_entity(batch_id: str, entity_id: str, body: EntityEdit, review=Depends(service)):
    return run(lambda: review.entity(batch_id, entity_id, body))


@router.put('/{batch_id}/review/stock-scopes')
def stock_scopes(batch_id: str, body: ScopeConfirmation, review=Depends(service)):
    return run(lambda: review.scopes(batch_id, body))


@router.post('/{batch_id}/review/submissions/{submission_id}/approve')
def approve(batch_id: str, submission_id: str, body: ApproveSubmission, review=Depends(service)):
    return run(lambda: review.approve(batch_id, submission_id, body))


@router.post('/{batch_id}/review/submissions/{submission_id}/decisions')
def bulk_decision(batch_id: str, submission_id: str, body: BulkDecision, review=Depends(service)):
    return run(lambda: review.bulk(batch_id, submission_id, body))
