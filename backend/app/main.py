"""Terra FastAPI application composition."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.routes.transfers import router as transfers_router
from backend.app.routes.impact import router as impact_router


app = FastAPI(title="Terra API", version="0.1.0")
app.include_router(transfers_router)
app.include_router(impact_router)


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
