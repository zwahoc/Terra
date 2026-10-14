"""FastAPI routes for calculation, revision reads, and controlled exports."""

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from backend.app.schemas.impact import (
    ImpactCalculationRequest, ForecastPreviewRequest, OptimisationPreviewRequest,
)
from backend.app.repositories.impact_repository import ImpactRepository, ImpactRepositoryError
from backend.app.services.forecast_preview_service import ForecastPreviewCalculator
from backend.app.services.optimisation_preview_service import preview_optimisation, preview_json
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


router = APIRouter(prefix="/api", tags=["impact"])
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
        return calculate_impact(
            basis,
            entity_id,
            ImpactCalculationInput(**body.model_dump()),
        )
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
        return list_assessments(basis=basis, current_only=current_only)
    except ImpactError as exc:
        return _error(exc)


@router.get("/impact-assessments/{assessment_id}", response_model=None)
def read_assessment(assessment_id: str):
    try:
        return get_assessment(assessment_id)
    except ImpactError as exc:
        return _error(exc)


@router.get("/exports/impact", response_model=None)
def impact_export(
    basis: Basis = Query(...), format: Literal["json", "csv"] = Query(...)
):
    try:
        if format == "json":
            return export_json(basis)
        content = export_csv(basis)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="terra-impact-{basis.lower()}.csv"'},
        )
    except ImpactError as exc:
        return _error(exc)
