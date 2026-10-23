"""Private originals and confirmed draft checkpoints; no operational JSON database."""

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from filelock import FileLock

from backend.app.schemas.ingestion import IngestionBatch, SourceFile
from backend.app.services.ingestion_errors import IngestionError


DEFAULT_ROOT = Path(__file__).resolve().parents[3] / ".local" / "ingestion"


def digest_json(value) -> str:
    from terra.quantities import json_default
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,default=json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SourceStore:
    def __init__(self, root: Path | None = None):
        from terra.workspace_state import current_source_root
        self.root = Path(root or current_source_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("objects", "checkpoints", "locks"):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)

    @contextmanager
    def batch_lock(self, batch_id: str):
        self._id(batch_id)
        with FileLock(str(self.root / "locks" / f"{batch_id}.lock"), timeout=30):
            yield

    @staticmethod
    def _id(value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise IngestionError("INVALID_ID", "Invalid intake resource ID.", 422)

    @staticmethod
    def filename(value: str) -> str:
        # Accept browser Windows paths as display names on every OS.
        name = value.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127)
        return name if name and name not in (".", "..") else "upload"

    def put(self, stream: BinaryIO, filename: str) -> SourceFile:
        hasher = hashlib.sha256()
        size = 0
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root / "objects", delete=False) as handle:
                temporary = Path(handle.name)
                while chunk := stream.read(1024 * 1024):
                    hasher.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
        sha = hasher.hexdigest()
        target = self.root / "objects" / sha
        try:
            with FileLock(str(self.root / "locks" / f"{sha}.lock"), timeout=30):
                if target.is_symlink():
                    raise IngestionError("SOURCE_INTEGRITY_ERROR", "Stored original is invalid.")
                if not target.exists():
                    os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        source = SourceFile(id=f"SRC-{sha}", sha256=sha, byte_size=size,
                            display_filename=self.filename(filename))
        self.path(source)
        return source

    def path(self, source: SourceFile) -> Path:
        path = self.root / "objects" / source.sha256
        if source.id != f"SRC-{source.sha256}" or path.is_symlink() or not path.is_file():
            raise IngestionError("SOURCE_UNAVAILABLE", "The original file is missing or invalid.", 409)
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        if path.stat().st_size != source.byte_size or hasher.hexdigest() != source.sha256:
            raise IngestionError("SOURCE_INTEGRITY_ERROR", "The original file has changed.")
        return path

    def checkpoint(self, batch: IngestionBatch):
        """Only called after the SQL transaction succeeds, or on a SQL-backed read."""
        self._id(batch.id)
        folder = self.root / "checkpoints" / batch.id
        folder.mkdir(exist_ok=True, mode=0o700)
        payload = batch.model_dump(mode="json")
        contents = {"batch": payload, "sha256": digest_json(payload)}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(contents, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
        try:
            os.replace(temporary, folder / f"{batch.revision}.json")
        finally:
            temporary.unlink(missing_ok=True)

    def recoverable(self, batch_id: str) -> IngestionBatch | None:
        self._id(batch_id)
        folder = self.root / "checkpoints" / batch_id
        versions = sorted((int(p.stem), p) for p in folder.glob("*.json") if p.stem.isdigit())
        if not versions:
            return None
        try:
            raw = json.loads(versions[-1][1].read_text(encoding="utf-8"))
            batch = IngestionBatch.model_validate(raw["batch"])
            if batch.id != batch_id or batch.revision != versions[-1][0] or digest_json(raw["batch"]) != raw["sha256"]:
                raise ValueError("Checkpoint identity/digest mismatch")
            for submission in batch.submissions:
                self.path(submission.source)
            return batch
        except (KeyError, ValueError, OSError) as exc:
            raise IngestionError("CHECKPOINT_INVALID", "The latest checkpoint cannot be restored.") from exc

    def candidate_batches(self, sha256):
        """Local discovery hints only. Callers must verify every result in SQL."""
        result = []
        for folder in (self.root / 'checkpoints').iterdir():
            if not folder.is_dir() or folder.is_symlink(): continue
            versions = [(int(p.stem),p) for p in folder.glob('*.json') if p.stem.isdigit()]
            if not versions: continue
            try:
                raw = json.loads(max(versions)[1].read_text(encoding='utf-8'))
                if digest_json(raw['batch']) != raw['sha256']: continue
                if any(s['source']['sha256'] == sha256 for s in raw['batch']['submissions']): result.append(folder.name)
            except (ValueError, KeyError, OSError):
                continue  # A damaged hint is never a substitute for SQL evidence.
        return result
