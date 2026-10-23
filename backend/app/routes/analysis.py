"""Local Phase 2 model comparison API. UI, approval and publication are later phases."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from filelock import Timeout

from backend.app.routes.ingestion import get_intake_service, local_operator, run
from backend.app.schemas.analysis import AnalyseRequest, RetryAnalysisRequest, SelectPrimaryRequest
from backend.app.services.analysis_service import ComparisonService
from backend.app.services.ingestion_errors import IngestionError


router = APIRouter(prefix="/api/ingestion", tags=["analysis"], dependencies=[Depends(local_operator)])


def analysis_response(action):
    result = run(action)
    if not isinstance(result, JSONResponse):
        result["meta"]["stage"] = "DRAFT_ANALYSIS"
    return result


def get_comparison_service(intake=Depends(get_intake_service)):
    try:
        return ComparisonService(intake=intake)
    except (OSError, Timeout) as exc:
        raise IngestionError("BUDGET_STORAGE_UNAVAILABLE", "The local API budget ledger is unavailable; models cannot run.", 503) from exc


@router.get("/providers")
def providers(service=Depends(get_comparison_service)):
    return analysis_response(service.status)


@router.post("/providers/check")
def check_providers(service=Depends(get_comparison_service)):
    return analysis_response(service.check_providers)


@router.post("/batches/{batch_id}/primary-model")
def select_primary(batch_id: str, body: SelectPrimaryRequest, service=Depends(get_comparison_service)):
    return analysis_response(lambda: service.select_primary(batch_id, body))


@router.post("/batches/{batch_id}/analyse", status_code=202)
def analyse(batch_id: str, body: AnalyseRequest, service=Depends(get_comparison_service)):
    result = analysis_response(lambda: service.start(batch_id, body))
    return result if isinstance(result, JSONResponse) else JSONResponse(status_code=202, content=result)


@router.get("/batches/{batch_id}/comparisons/{comparison_id}")
def comparison(batch_id: str, comparison_id: str, service=Depends(get_comparison_service)):
    return analysis_response(lambda: service.get(batch_id, comparison_id))


@router.get("/batches/{batch_id}/runs/{run_id}")
def analysis_run(batch_id: str, run_id: str, service=Depends(get_comparison_service)):
    def action():
        batch = service.intake.get(batch_id)
        owner = next((c for c in batch.comparisons if any(r.id == run_id for r in c.runs)), None)
        if owner is None:
            raise IngestionError("ANALYSIS_RUN_NOT_FOUND", "This run does not belong to the batch.", 404)
        value = service.get(batch_id, owner.id)
        return {"comparison_id": owner.id, "batch_revision": value["batch_revision"],
                "input_manifest_current": value["input_manifest_current"],
                "run": next(r for r in value["runs"] if r["id"] == run_id),
                "worker_active": value["worker_active"][run_id]}
    return analysis_response(action)


@router.post("/batches/{batch_id}/comparisons/{comparison_id}/runs/{run_id}/retry", status_code=202)
def retry_analysis(batch_id: str, comparison_id: str, run_id: str, body: RetryAnalysisRequest, service=Depends(get_comparison_service)):
    result = analysis_response(lambda: service.retry(batch_id, comparison_id, run_id, body))
    return result if isinstance(result, JSONResponse) else JSONResponse(status_code=202, content=result)
