"""Progressive, restartable disk preparation for DeepSeek. No document semantics."""

import hashlib
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread

from filelock import FileLock

from backend.app.services.ingestion_errors import IngestionError

ROOT = Path(__file__).resolve().parents[3]
VERSION = 'deepseek-disk-pages.v2'
PAGE_IDLE_TIMEOUT = 90


def file_digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def save_json(path, value):
    temp = Path(str(path) + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


class DiskDocument:
    def __init__(self, folder, manifest):
        self.folder, self.manifest = Path(folder), manifest
        self.pages = manifest['pages']

    def evidence(self):
        return {'version': VERSION, 'strategy': 'DISK_PAGES_WITH_FILE_REFERENCES',
                'page_count': len(self.pages), 'page_numbers': [p['page_number'] for p in self.pages],
                'pages_with_text': sum(bool(self.text(p['page_number']).strip()) for p in self.pages),
                'pages': [{key: p[key] for key in ('page_number', 'width_pixels', 'height_pixels', 'resized_to_limit')} for p in self.pages],
                'all_pages_included': True, 'local_ocr': False}

    def text(self, number):
        return (self.folder / f'page-{number}.txt').read_text(encoding='utf-8')

    def attachments(self, numbers):
        result = []
        for number in numbers:
            page = self.pages[number - 1]
            for image in page['images']:
                result.append({'media_type': 'image/png', 'path': self.folder / image['filename'],
                               'page_number': number, 'page_count': len(self.pages), 'region': image['region'],
                               'source_label': f'Original {"PDF page" if self.manifest.get("source_type") == "PDF" else "image page/frame"} {number} of {len(self.pages)}.',
                               'byte_size': image['bytes']})
        return result

    def text_for(self, numbers):
        return '\n\n'.join(f'--- PDF page {n} of {len(self.pages)} ---\n' +
                           (self.text(n) or '[No extractable text. Read the supplied page images.]') for n in numbers)


def prepare_document(path, *, root=None, progress=lambda value: None, timeout=PAGE_IDLE_TIMEOUT):
    path = Path(path).resolve()
    digest = file_digest(path)
    folder = Path(root or ROOT / '.local' / 'document-pages') / (digest + '-' + VERSION)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(folder) + '.lock', timeout=30):
        child = subprocess.Popen([sys.executable, '-m', 'backend.app.services.document_preparation', str(path), str(folder)],
                                 cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        queue = Queue()
        def consume():
            try:
                for line in child.stdout:
                    queue.put(line)
            finally:
                queue.put(None)
        thread = Thread(target=consume, daemon=True)
        thread.start()
        manifest = None
        try:
            while True:
                try:
                    line = queue.get(timeout=timeout)
                except Empty:
                    raise IngestionError('PDF_PREPARATION_TIMEOUT', 'Page preparation stopped making progress. Completed pages are retained for retry.') from None
                if line is None:
                    break
                event = json.loads(line)
                if 'error' in event:
                    raise IngestionError(event['error'], event['message'])
                if event.get('complete'):
                    manifest = event['manifest']
                else:
                    progress(event)
            child.wait(timeout=5)
            if child.returncode or manifest is None or not manifest['pages']:
                raise IngestionError('PDF_PREPARATION_FAILED', 'Document preparation did not finish. Completed pages and the original remain available.')
            if file_digest(path) != digest:
                raise IngestionError('SOURCE_INTEGRITY_ERROR', 'The original changed during preparation.')
            return DiskDocument(folder, manifest)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            child.stdout.close()
            thread.join(timeout=5)


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def valid_cached(folder, number, identity):
    try:
        page = json.loads((folder / f'page-{number}.json').read_text())
        if not page.get('complete') or page['identity'] != identity or file_digest(folder / f'page-{number}.txt') != page['text_sha256']:
            return None
        if any(file_digest(folder / image['filename']) != image['sha256'] for image in page['images']):
            return None
        return page
    except (OSError, ValueError, KeyError):
        return None


def save_page(folder, number, text, image, identity):
    """Keep a whole-page overview plus detail tiles for large drawings/scans."""
    from PIL import Image
    width, height = image.size
    images = []
    def write(part, name, region):
        target = folder / name
        temp = folder / (name + '.tmp')
        part.save(temp, format='PNG')
        os.replace(temp, target)
        images.append({'filename': name, 'region': region, 'bytes': target.stat().st_size, 'sha256': file_digest(target)})
    overview = image.copy()
    overview.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
    try:
        write(overview, f'page-{number}.png', 'whole page')
        if max(width, height) > 2400:
            # Overlap keeps characters at tile boundaries visible in at least one view.
            for y in range(0, height, 1900):
                for x in range(0, width, 1900):
                    tile = image.crop((x, y, min(width, x + 2048), min(height, y + 2048)))
                    try:
                        write(tile, f'page-{number}-{x}-{y}.png', f'detail x={x}, y={y}, width={tile.width}, height={tile.height}')
                    finally:
                        tile.close()
        text_path = folder / f'page-{number}.txt'
        temp = folder / f'page-{number}.txt.tmp'
        temp.write_text(text, encoding='utf-8')
        os.replace(temp, text_path)
        page = {'identity': identity, 'page_number': number, 'width_pixels': overview.width, 'height_pixels': overview.height,
                'resized_to_limit': overview.size != image.size, 'text_sha256': file_digest(text_path), 'images': images}
        save_json(folder / f'page-{number}.json', page)
        return page
    finally:
        overview.close()


def worker(path, folder):
    identity = file_digest(path)
    with path.open('rb') as source:
        pdf = source.read(5) == b'%PDF-'
    if not pdf:
        from PIL import Image, ImageOps
        pages = []
        with Image.open(path) as original:
            count = getattr(original, 'n_frames', 1)
            emit({'pages_prepared': 0, 'page_count': count})
            for index in range(count):
                number = index + 1
                cached = valid_cached(folder, number, identity)
                if cached is None:
                    original.seek(index)
                    transposed = ImageOps.exif_transpose(original)
                    image = transposed.convert('RGB')
                    transposed.close()
                    try:
                        cached = save_page(folder, number, '', image, identity)
                    finally:
                        image.close()
                    cached['complete'] = True
                    save_json(folder / f'page-{number}.json', cached)
                pages.append(cached)
                emit({'pages_prepared': number, 'page_count': count})
        return {'pages': pages, 'identity': identity, 'source_type': 'IMAGE'}
    import pypdfium2 as pdfium
    try:
        document = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        code = 'PDF_PASSWORD_REQUIRED' if exc.err_code == 4 else 'PDF_INVALID'
        raise IngestionError(code, 'Upload a readable unlocked PDF. Terra does not collect PDF passwords.') from None
    pages = []
    with document:
        document.init_forms()
        count = len(document)
        if not count:
            raise IngestionError('PDF_EMPTY', 'This PDF contains no pages.')
        emit({'pages_prepared': 0, 'page_count': count})
        for index in range(count):
            number = index + 1
            cached = valid_cached(folder, number, identity)
            if cached is None:
                page = document[index]
                try:
                    width, height = page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        raise IngestionError('PDF_INVALID', 'A PDF page has invalid dimensions.')
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_bounded(errors='strict')
                    finally:
                        text_page.close()
                    # Render one page at a time. Very large sheets use PDFium crops
                    # rather than allocating a full-resolution full-sheet bitmap.
                    scale = min(2.0, 4096 / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil()
                        try:
                            cached = save_page(folder, number, text, image, identity)
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                    # Additional native-scale crops retain small print on oversized sheets.
                    if scale < 2.0:
                        for y in range(0, math.ceil(height), 950):
                            for x in range(0, math.ceil(width), 950):
                                right, top = min(width, x + 1024), min(height, y + 1024)
                                bitmap = page.render(scale=2, crop=(x, y, width-right, height-top))
                                try:
                                    tile = bitmap.to_pil()
                                    try:
                                        name = f'page-{number}-native-{x}-{y}.png'
                                        target = folder / name
                                        tile.save(target, format='PNG')
                                        cached['images'].append({'filename': name, 'region': f'native detail left={x}, bottom={y}, right={right}, top={top} PDF units',
                                            'bytes': target.stat().st_size, 'sha256': file_digest(target)})
                                    finally:
                                        tile.close()
                                finally:
                                    bitmap.close()
                        save_json(folder / f'page-{number}.json', cached)
                finally:
                    page.close()
            cached['complete'] = True
            save_json(folder / f'page-{number}.json', cached)
            pages.append(cached)
            emit({'pages_prepared': number, 'page_count': count})
    return {'pages': pages, 'identity': identity, 'source_type': 'PDF'}


if __name__ == '__main__':
    try:
        manifest = worker(Path(sys.argv[1]), Path(sys.argv[2]))
        emit({'complete': True, 'manifest': manifest})
    except IngestionError as exc:
        emit({'error': exc.code, 'message': exc.message})
    except Exception:
        emit({'error': 'PDF_PREPARATION_FAILED', 'message': 'A page could not be prepared. Original and completed pages are retained; retry or inspect the source.'})
