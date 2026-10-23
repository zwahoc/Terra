"""Content preparation helpers. No material interpretation, OCR or provider calls."""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from backend.app.schemas.ingestion import SourceFile


@dataclass(frozen=True)
class PreparedContent:
    source_id: str
    kind: Literal["TEXT", "CELLS", "NATIVE_CANDIDATE", "UNSUPPORTED"]
    media_type: str
    text: str | None = None
    cells: list[list[str]] | None = None
    issues: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ContentReader(Protocol):
    def prepare(self, source: SourceFile, path: Path) -> PreparedContent: ...


def native_media_type(prefix: bytes) -> str | None:
    if prefix.startswith(b"%PDF-"):
        return "application/pdf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith((b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')):
        return 'image/tiff'
    if prefix.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if prefix.startswith(b'RIFF') and prefix[8:12] == b'WEBP':
        return 'image/webp'
    return None


class InitialContentReader:
    """UTF-8 text and delimited cells, with original binary candidates for Phase 2.

    A candidate is not a claim that any shortlisted model accepts its bytes.
    Unsupported types remain stored/viewable and can gain a reader later.
    """

    def prepare(self, source: SourceFile, path: Path) -> PreparedContent:
        with path.open("rb") as handle:
            prefix = handle.read(16)
        media = native_media_type(prefix)
        if media:
            return PreparedContent(source.id, "NATIVE_CANDIDATE", media,
                                   issues=["Provider input support requires Phase 2 validation."])
        suffix = Path(source.display_filename).suffix.lower()
        if suffix in ('.docx', '.xlsx', '.xlsm'):
            from backend.app.services.office_readers import office_content
            return office_content(source, path)
        if suffix not in (".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".log"):
            return PreparedContent(source.id, "UNSUPPORTED", "application/octet-stream",
                                   issues=["No content reader has been verified for this format yet."])
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return PreparedContent(source.id, "UNSUPPORTED", "application/octet-stream",
                                   issues=["This reader requires UTF-8. Original bytes are preserved."])
        if "\x00" in text:
            return PreparedContent(source.id, "UNSUPPORTED", "application/octet-stream",
                                   issues=["Binary content cannot be prepared as text."])
        if suffix in (".csv", ".tsv"):
            try:
                cells = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t" if suffix == ".tsv" else ",", strict=True))
            except csv.Error:
                return PreparedContent(source.id, "UNSUPPORTED", "text/plain",
                                       issues=["The delimited file could not be read reliably."])
            return PreparedContent(source.id, "CELLS", "text/tab-separated-values" if suffix == ".tsv" else "text/csv", cells=cells)
        return PreparedContent(source.id, "TEXT", "text/plain", text=text)
