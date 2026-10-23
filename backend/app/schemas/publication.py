"""Explicit publication command, separate from review and model tools."""
from pydantic import Field
from backend.app.schemas.review import RevisionCommand

class PublishBatch(RevisionCommand):
    plan_digest: str
    idempotency_key: str = Field(min_length=1,max_length=160)
