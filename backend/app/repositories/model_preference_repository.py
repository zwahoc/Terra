"""Local model choice configuration, independent of operational database contents."""

import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock
from pydantic import ValidationError

from backend.app.schemas.analysis import ModelPreference
from backend.app.services.analysis_settings import ROOT
from backend.app.services.ingestion_errors import IngestionError


class ModelPreferenceRepository:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else ROOT / ".local" / "ingestion-model-choice"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "preference.json"
        self.lock = FileLock(str(self.root / "preference.lock"), timeout=30)

    def get(self):
        if not self.path.exists():
            return ModelPreference()
        try:
            return ModelPreference.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as exc:
            raise IngestionError("MODEL_PREFERENCE_INVALID", "The saved model preference is invalid. Inspect local configuration before analysing.", 503) from exc

    def save(self, value):
        """Caller owns the preference lock for its read/check/write sequence."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(value.model_dump(mode="json"), handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
