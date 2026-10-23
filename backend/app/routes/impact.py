"""FastAPI routes for calculation, revision reads, and controlled exports."""

from typing import Literal

from fastapi import APIRouter, Query, Depends
from backend.app.routes.ingestion import local_operator
from fastapi.responses import JSONResponse, Response

from backend.app.schemas.impact import (
    ImpactCalculationRequest, ForecastPreviewRequest, OptimisationPreviewRequest, OptimisationRunCreateRequest,
    OptimisationComparisonRequest, OptimisationComparisonCreateRequest,
)
from backend.app.repositories.impact_repository import ImpactRepository, ImpactRepositoryError
from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
from backend.app.services.optimisation_preview_service import preview_optimisation, preview_json, preview_comparison
from backend.app.services.optimisation_comparison_service import (
    OptimisationComparisonInput, persist_optimisation_comparison,
)
from backend.app.services.optimisation_run_service import (
    OptimisationRunConflict, OptimisationRunError, OptimisationRunInput, OptimisationRunInvalid,
    OptimisationRunNotFound, OptimisationRunUnavailable, get_optimisation_run, persist_optimisation_run,
)
from backend.app.services.transfer_read_service import load_baseline_metadata
from backend.app.services.impact_export_service import export_csv, export_json
from backend.app.services.impact_service import (
    ImpactCalculationInput,
    ImpactConflict,
    ImpactError,
    ImpactInvalid,
    ImpactNotFound,
    ImpactUnavailable,
    calculate_impact,
    get_assessment,
    list_assessments,
    _load,
)


router = APIRouter(prefix="/api", tags=["impact"],dependencies=[Depends(local_operator)])
Basis = Literal["PROPOSAL_FORECAST", "ACTUAL_CONFIRMED_USE"]


def _error(exc: ImpactError) -> JSONResponse:
    status = (
        404 if isinstance(exc, ImpactNotFound)
        else 400 if isinstance(exc, ImpactInvalid)
        else 409 if isinstance(exc, ImpactConflict)
        else 503 if isinstance(exc, ImpactUnavailable)
        else 500
    )
    return JSONResponse(
        status_code=status,
        content={"data": None, "meta": None, "error": {
            "code": exc.code, "message": exc.message, "details": exc.details}},
    )


def _calculation(basis: str, entity_id: str, body: ImpactCalculationRequest):
    try:
        if basis=='ACTUAL_CONFIRMED_USE':
            from terra.local_adapter import LocalDataConnect
            from backend.app.services.automatic_impact_service import AutomaticImpactService
            adapter=LocalDataConnect()
            if adapter.execute('GetQuantityEncoding')['quantityEncoding'] and adapter.execute('GetImpactIntent',{'id':entity_id})['impactRefreshIntent']:
                AutomaticImpactService(adapter).refresh(retry_failed=True)
                head=ImpactRepository(adapter).persistence_state('ACTUAL_CONFIRMED_USE:'+entity_id,'none').head
                intent=adapter.execute('GetImpactIntent',{'id':entity_id})['impactRefreshIntent']
                if intent['status']!='COMPLETED':raise ImpactConflict('IMPACT_UPDATE_PENDING','Use is saved. The current impact update is not complete.')
                response=get_assessment(head['current_assessment_id'],ImpactRepository(adapter))
                return preview_json({'data':{'assessment':response['data'],'current':True,'replayed':True},'meta':response['meta'],'error':None})
        return preview_json(calculate_impact(
            basis,
            entity_id,
            ImpactCalculationInput(**body.model_dump()),
        ))
    except ImpactError as exc:
        return _error(exc)


def _preview_records():
    try:
        repository = ImpactRepository()
    except ImpactRepositoryError as exc:
        raise ImpactError('IMPACT_DATA_ERROR', 'Preview repository configuration is invalid.') from exc
    return _load(repository)


@router.post('/impact-assessments/forecast-preview', response_model=None)
def forecast_preview(body: ForecastPreviewRequest):
    """Read one emulator snapshot and calculate; never create an assessment."""
    try:
        calculator = ForecastPreviewCalculator(_preview_records(),
            planning_date=body.planning_date, factor_dataset_version=body.factor_dataset_version)
        result = calculator.assess_forecast_preview(body.supply_offer_id,
                                                    body.demand_request_id, body.quantity)
        return {'data': preview_json(result), 'meta': load_baseline_metadata(), 'error': None}
    except ImpactError as exc:
        return _error(exc)


@router.post('/optimisation-runs/preview', response_model=None)
def optimisation_preview(body: OptimisationPreviewRequest):
    """Allocate and forecast on shared inputs without persisting a run/proposal."""
    try:
        result = preview_optimisation(_preview_records(), **body.model_dump())
        return {'data': result, 'meta': load_baseline_metadata(), 'error': None}
    except ImpactError as exc:
        return _error(exc)


def _optimisation_error(exc: OptimisationRunError):
    status = 404 if isinstance(exc, OptimisationRunNotFound) else 400 if isinstance(exc, OptimisationRunInvalid) else 409 if isinstance(exc, OptimisationRunConflict) else 503 if isinstance(exc, OptimisationRunUnavailable) else 500
    return JSONResponse(status_code=status, content={"data": None, "meta": None, "error": {"code": exc.code, "message": exc.message, "details": exc.details}})


@router.post('/optimisation-comparisons/preview', response_model=None)
def comparison_preview(body: OptimisationComparisonRequest):
    try:
        result = preview_comparison(_preview_records(), **body.model_dump())
        return {'data': result, 'meta': load_baseline_metadata(), 'error': None}
    except ImpactError as exc:
        return _error(exc)


@router.post('/optimisation-comparisons', status_code=201, response_model=None)
def create_comparison(body: OptimisationComparisonCreateRequest):
    try:
        return preview_json(persist_optimisation_comparison(OptimisationComparisonInput(**body.model_dump())))
    except OptimisationRunError as exc:
        return _optimisation_error(exc)


@router.post('/optimisation-runs', status_code=201, response_model=None)
def persist_optimisation(body: OptimisationRunCreateRequest):
    """Save one selected plan and linked forecasts; no transfers/reservations."""
    try:
        return preview_json(persist_optimisation_run(OptimisationRunInput(**body.model_dump())))
    except OptimisationRunError as exc:
        return _optimisation_error(exc)


@router.get('/optimisation-runs/{run_id}', response_model=None)
def read_optimisation_run(run_id: str):
    try:
        return preview_json(get_optimisation_run(run_id))
    except OptimisationRunError as exc:
        return _optimisation_error(exc)


@router.post("/impact-assessments/proposals/{proposal_id}/calculate", response_model=None)
def calculate_forecast(proposal_id: str, body: ImpactCalculationRequest):
    return _calculation("PROPOSAL_FORECAST", proposal_id, body)


@router.post("/impact-assessments/transfers/{transfer_id}/calculate", response_model=None)
def calculate_actual(transfer_id: str, body: ImpactCalculationRequest):
    return _calculation("ACTUAL_CONFIRMED_USE", transfer_id, body)


@router.get("/impact-assessments", response_model=None)
def read_assessments(
    basis: Basis | None = None, current_only: bool = Query(default=True)
):
    try:
        return preview_json(list_assessments(basis=basis, current_only=current_only))
    except ImpactError as exc:
        return _error(exc)


@router.get("/impact-assessments/{assessment_id}", response_model=None)
def read_assessment(assessment_id: str):
    try:
        return preview_json(get_assessment(assessment_id))
    except ImpactError as exc:
        return _error(exc)


@router.get("/exports/impact", response_model=None)
def impact_export(
    basis: Basis = Query(...), format: Literal["json", "csv", "xlsx"] = Query(...),
    project_id: str | None = Query(default=None), transfer_id: str | None = Query(default=None),
):
    try:
        if format == 'xlsx':
            if basis != 'ACTUAL_CONFIRMED_USE':
                raise ImpactInvalid('REPORT_BASIS_INVALID','The Excel reuse report contains actual use only. Forecasts remain available as technical exports.')
            from backend.app.services.reuse_workbook import export_reuse_excel, MIME
            content,filename=export_reuse_excel(project_id=project_id,transfer_id=transfer_id)
            return Response(content=content,media_type=MIME,headers={
                'Content-Disposition':f'attachment; filename="{filename}"',
                'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        if format == "json":
            return preview_json(export_json(basis, project_id=project_id, transfer_id=transfer_id))
        content = export_csv(basis, project_id=project_id, transfer_id=transfer_id)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="terra-impact-{basis.lower()}.csv"'},
        )
    except ImpactError as exc:
        return _error(exc)


@router.get('/reports/reuse')
def reuse_report_summary(project_id: str | None = Query(default=None)):
    try:
        from backend.app.services.reuse_report import build_reuse_report
        report=build_reuse_report(project_id=project_id,include_evidence=False)
        return JSONResponse(preview_json({'data':{'scope':report['scope'],'summary':report['summary'],
            'generated_at':report['generated_at']},'error':None}),headers={'Cache-Control':'no-store'})
    except ImpactError as exc:
        return _error(exc)


@router.get('/impact-refresh')
def impact_refresh_status():
    from backend.app.routes.ingestion import run
    from backend.app.services.automatic_impact_service import AutomaticImpactService
    return run(lambda:AutomaticImpactService().view(),stage='IMPACT_STATUS')

@router.post('/impact-refresh/retry')
def retry_automatic_impact():
    from backend.app.routes.ingestion import run
    from backend.app.services.automatic_impact_service import AutomaticImpactService
    return run(lambda:AutomaticImpactService().refresh(retry_failed=True),stage='IMPACT_RETRY',operational_writes=True)
