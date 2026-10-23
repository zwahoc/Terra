"""Legacy whole-PDF preparation retained for Gemini coverage and diagnostic compatibility.

Selected DeepSeek runs use document_preparation.py with disk pages and file references.

PDFium runs in an isolated child process: its native API is not thread-safe and
malformed inputs must not take down FastAPI's shared analysis worker process.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.ingestion_errors import IngestionError


ROOT = Path(__file__).resolve().parents[3]
PREPARATION_VERSION = "deepseek-pdf-pages.v1"
# Resource/transport limits for one complete request, not row-count restrictions.
MAX_SOURCE_BYTES = 48 * 1024 * 1024
MAX_PREPARED_BYTES = 24 * 1024 * 1024
MAX_LONG_EDGE_PIXELS = 2400
RENDER_SCALE = 2.0  # 144 DPI at the usual PDF unit of 1/72 inch.
PREPARATION_TIMEOUT_SECONDS = 90
MAX_PROVIDER_IMAGES = 600


@dataclass(frozen=True)
class PreparedPdf:
    text: str
    attachments: list[dict]
    evidence: dict
    page_texts: dict[int, str]


class PdfPreparer:
    def __init__(self, root: Path | None = None, timeout=PREPARATION_TIMEOUT_SECONDS):
        self.root = Path(root) if root is not None else ROOT / ".local" / "ingestion-preparation"
        self.timeout = timeout

    def prepare(self, path: Path) -> PreparedPdf:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise IngestionError("PDF_PREPARATION_LIMIT", "This PDF exceeds the current 48 MiB preparation limit. No pages were sent; the original is retained.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="pdf-", dir=self.root) as directory:
            output = Path(directory)
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "backend.app.services.pdf_preparation", str(path.resolve()), str(output.resolve())],
                    cwd=ROOT, capture_output=True, timeout=self.timeout, check=False,
                )
            except subprocess.TimeoutExpired:
                raise IngestionError("PDF_PREPARATION_TIMEOUT", "PDF preparation exceeded 90 seconds. No partial pages were analysed; the original is retained.") from None
            except OSError:
                raise IngestionError("PDF_PREPARATION_UNAVAILABLE", "The local PDF preparer could not start. Refresh backend dependencies and retry.", 503) from None
            try:
                manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
                if not manifest.get("ok"):
                    raise IngestionError(manifest["code"], manifest["message"])
                pages = manifest["pages"]
                if (result.returncode != 0 or not pages or len(pages) != manifest["page_count"]
                        or [p["page_number"] for p in pages] != list(range(1, len(pages) + 1))):
                    raise ValueError("Incomplete page coverage")
                attachments, texts = [], []
                for page in pages:
                    number = page["page_number"]
                    image = (output / f"page-{number}.png").read_bytes()
                    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("Invalid page image")
                    attachments.append({"media_type": "image/png", "data": image,
                                        "page_number": number, "page_count": len(pages)})
                    texts.append(f"--- PDF page {number} of {len(pages)} ---\n" +
                                 (page["text"] if page["text"].strip() else "[No extractable text. Read this page's image; no local OCR was run.]"))
                evidence = {"version": PREPARATION_VERSION, "strategy": "ALL_PAGE_IMAGES_WITH_AVAILABLE_TEXT",
                            "page_count": len(pages), "pages_with_text": sum(bool(p["text"].strip()) for p in pages),
                            "page_numbers": [p["page_number"] for p in pages],
                            "pages": [{key: page[key] for key in ("page_number", "width_pixels", "height_pixels", "resized_to_limit")} for page in pages],
                            "local_ocr": False, "all_pages_included": True}
                return PreparedPdf(text="\n\n".join(texts), attachments=attachments, evidence=evidence,
                                   page_texts={page["page_number"]: page["text"] for page in pages})
            except IngestionError:
                raise
            except (OSError, KeyError, ValueError, TypeError):
                raise IngestionError("PDF_PREPARATION_FAILED", "The complete PDF could not be prepared. No partial pages were analysed; the original is retained.") from None


def _prepare_document(path: Path, output: Path):
    # Imported in the dedicated subprocess only. No PDFium calls in the shared workers.
    import pypdfium2 as pdfium
    try:
        document = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        if exc.err_code == 4:  # PDFium FPDF_ERR_PASSWORD
            raise IngestionError("PDF_PASSWORD_REQUIRED", "This PDF needs a password. Upload an unlocked copy; Terra does not collect PDF passwords.") from None
        raise IngestionError("PDF_INVALID", "This PDF is unreadable or damaged. Upload a readable copy; the original is retained.") from None
    with document:
        document.init_forms()
        count = len(document)
        if count < 1:
            raise IngestionError("PDF_EMPTY", "This PDF has no pages to analyse.")
        if count > MAX_PROVIDER_IMAGES:
            raise IngestionError("PDF_PREPARATION_LIMIT", "This PDF exceeds DeepSeek's 600-image request limit. No pages were sent; automatic document chunking is not implemented yet.")
        pages, byte_count = [], 0
        for index in range(count):
            page = document[index]
            try:
                width, height = page.get_size()
                if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                    raise IngestionError("PDF_INVALID", f"PDF page {index + 1} has invalid dimensions. No partial document was analysed.")
                # Always retain the full page. Large sheets are scaled down, never cropped.
                scale = min(RENDER_SCALE, MAX_LONG_EDGE_PIXELS / max(width, height))
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded(errors="strict")
                finally:
                    text_page.close()
                byte_count += len(text.encode("utf-8"))
                if byte_count > MAX_PREPARED_BYTES:
                    raise IngestionError("PDF_PREPARATION_LIMIT", "This PDF's prepared text/images exceed the current 24 MiB allowance. No pages were sent; use a smaller document.")
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    try:
                        image.save(output / f"page-{index + 1}.png", format="PNG")
                        image_width, image_height = image.size
                    finally:
                        image.close()
                finally:
                    bitmap.close()
                byte_count += (output / f"page-{index + 1}.png").stat().st_size
                if byte_count > MAX_PREPARED_BYTES:
                    raise IngestionError("PDF_PREPARATION_LIMIT", "This PDF's prepared text/images exceed the current 24 MiB allowance. No pages were sent; use a smaller document.")
                pages.append({"page_number": index + 1, "text": text, "width_pixels": image_width,
                              "height_pixels": image_height, "resized_to_limit": scale < RENDER_SCALE})
            finally:
                page.close()
    return {"ok": True, "page_count": count, "pages": pages}


if __name__ == "__main__":
    output_path = Path(sys.argv[2])
    try:
        result = _prepare_document(Path(sys.argv[1]), output_path)
    except IngestionError as error:
        result = {"ok": False, "code": error.code, "message": error.message}
    except Exception:
        result = {"ok": False, "code": "PDF_PREPARATION_FAILED", "message": "The complete PDF could not be rendered/read. No partial document was analysed; the original is retained."}
    (output_path / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
