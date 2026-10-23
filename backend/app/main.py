"""Terra FastAPI application composition."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.routes.transfers import router as transfers_router
from backend.app.routes.impact import router as impact_router
from backend.app.routes.ingestion import router as ingestion_router, error_response
from backend.app.routes.analysis import router as analysis_router
from backend.app.services.ingestion_errors import IngestionError
from contextlib import asynccontextmanager
from backend.app.services.matching_worker import MatchingWorker

@asynccontextmanager
async def lifespan(_app):
    worker=MatchingWorker();worker.start()
    try:yield
    finally:worker.stop()


app = FastAPI(title="Terra API", version="0.1.0",lifespan=lifespan)
app.include_router(transfers_router)
app.include_router(impact_router)
app.include_router(ingestion_router)
app.include_router(analysis_router)
from backend.app.routes.review import router as review_router
app.include_router(review_router)
from backend.app.routes.publication import router as publication_router
app.include_router(publication_router)


@app.exception_handler(IngestionError)
async def ingestion_error_envelope(_request: Request, exc: IngestionError):
    return error_response(exc)


@app.exception_handler(RequestValidationError)
async def validation_error_envelope(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Keep FastAPI request-validation failures in Terra's error envelope."""

    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "meta": None,
            "error": {
                "code": "REQUEST_VALIDATION_ERROR",
                "message": "The request did not match the API contract.",
                "details": {"validation_errors": jsonable_encoder(exc.errors())},
            },
        },
    )

from backend.app.routes.workspace import router as workspace_router
app.include_router(workspace_router)
from backend.app.routes.matching import router as matching_router
app.include_router(matching_router)
from backend.app.routes.history import router as history_router
app.include_router(history_router)
