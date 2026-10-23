"""Local operator intake endpoints; analysis, review and publication have separate routers."""

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from filelock import Timeout

from backend.app.repositories.ingestion_repository import ContextCollection
from backend.app.schemas.ingestion import CaptureProjectContext, ContextPatch, CreateBatch
from backend.app.services.ingestion_content import native_media_type
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.ingestion_service import IntakeService


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def error_response(error):
    return JSONResponse(status_code=error.status, content={"data": None, "meta": None,
        "error": {"code": error.code, "message": error.message, "details": {}}})


def local_operator(request: Request):
    # Single operator is not permission to expose a privileged database on the LAN.
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise IngestionError("LOCAL_ONLY", "Intake is restricted to the local operator.", 403)
    for header in ("host", "origin"):
        value = request.headers.get(header)
        if value and urlsplit(value if header == "origin" else "http://" + value).hostname not in LOCAL_HOSTS:
            raise IngestionError("LOCAL_ONLY", "Intake requires a loopback host and origin.", 403)


router = APIRouter(prefix="/api/ingestion", tags=["ingestion"], dependencies=[Depends(local_operator)])


def get_intake_service():
    try:
        return IntakeService()
    except ValueError as exc:
        raise IngestionError("INGESTION_UNAVAILABLE", "Local SQL Connect configuration is invalid.", 503) from exc
    except (OSError, Timeout) as exc:
        raise IngestionError("LOCAL_STORAGE_UNAVAILABLE", "Private intake storage is unavailable.", 503) from exc


def run(action: Callable, *, stage="DRAFT_INTAKE", operational_writes=False):
    try:
        from decimal import Decimal
        from terra.quantities import text
        return {"data": jsonable_encoder(action(),custom_encoder={Decimal:text}), "meta": {"stage": stage, "operational_writes": operational_writes}, "error": None}
    except IngestionError as exc:
        return error_response(exc)
    except (OSError, Timeout):
        return error_response(IngestionError("LOCAL_STORAGE_UNAVAILABLE", "Local source/checkpoint storage is unavailable. Reload the batch before retrying.", 503))


@router.post("/batches")
def create_batch(body: CreateBatch, service=Depends(get_intake_service)):
    return run(lambda: service.create(body.selected_project_id))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, service=Depends(get_intake_service)):
    return run(lambda: service.get(batch_id))


@router.post("/batches/{batch_id}/files")
def upload_files(batch_id: str, expected_revision: int = Form(ge=1), files: list[UploadFile] = File(), service=Depends(get_intake_service)):
    try:
        return run(lambda: service.add_files(batch_id, expected_revision,
                                             [(f.filename or "upload", f.file) for f in files]))
    finally:
        for upload in files:
            upload.file.close()


@router.patch("/batches/{batch_id}/context")
def patch_context(batch_id: str, body: ContextPatch, service=Depends(get_intake_service)):
    return run(lambda: service.patch_context(batch_id, body))


@router.get('/batches/{batch_id}/duplicates')
def identical_uploads(batch_id: str, service=Depends(get_intake_service)):
    return run(lambda: service.duplicates(batch_id))


@router.post("/batches/{batch_id}/context/projects")
def capture_context(batch_id: str, body: CaptureProjectContext, service=Depends(get_intake_service)):
    return run(lambda: service.capture_project(batch_id, body))


@router.post("/batches/{batch_id}/restore")
def restore_batch(batch_id: str, service=Depends(get_intake_service)):
    return run(lambda: service.restore(batch_id))


@router.get("/batches/{batch_id}/files/{submission_id}/source")
def whole_source(batch_id: str, submission_id: str, preview: bool = False, service=Depends(get_intake_service)):
    try:
        source, path = service.source(batch_id, submission_id)
        with Path(path).open("rb") as handle:
            media = native_media_type(handle.read(16)) if preview else None
        return FileResponse(path, filename=source.display_filename,
                            media_type=media or "application/octet-stream",
                            content_disposition_type="inline" if media else "attachment",
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": "sandbox; default-src 'none'"})
    except IngestionError as exc:
        return error_response(exc)
    except (OSError, Timeout):
        return error_response(IngestionError("SOURCE_UNAVAILABLE", "Local source storage is unavailable.", 503))


@router.get("/projects")
def projects(query: str = "", after: str = "", limit: int = Query(100, ge=1, le=200), service=Depends(get_intake_service)):
    return run(lambda: service.reads.page("projects", query=query, after=after, limit=limit))


@router.get("/materials")
def materials(query: str = "", after: str = "", limit: int = Query(100, ge=1, le=200), service=Depends(get_intake_service)):
    return run(lambda: service.reads.page("materials", query=query, after=after, limit=limit))


@router.get("/materials/{material_id}")
def material(material_id: str, service=Depends(get_intake_service)):
    def action():
        value = service.reads.get_entity("materials", material_id)
        if value is None:
            raise IngestionError("MATERIAL_NOT_FOUND", "The material does not exist.", 404)
        return value
    return run(action)


@router.get("/projects/{project_id}/records")
def project_records(project_id: str, collection: ContextCollection, after: str = "", limit: int = Query(100, ge=1, le=200), service=Depends(get_intake_service)):
    def action():
        if service.reads.get_entity("projects", project_id) is None:
            raise IngestionError("PROJECT_NOT_FOUND", "The project does not exist.", 404)
        return service.reads.page(collection, project_id=project_id, after=after, limit=limit)
    return run(action)


@router.get("/projects/{project_id}/context")
def project_context(project_id: str, service=Depends(get_intake_service)):
    return run(lambda: service.reads.project_context(project_id))
