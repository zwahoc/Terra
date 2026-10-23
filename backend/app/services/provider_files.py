"""Private, expiring DeepSeek image uploads owned by a single analysis worker."""

import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from backend.app.services.ingestion_errors import IngestionError


MAX_FILE_BYTES = 64 * 1024 * 1024
FILE_LIFETIME_SECONDS = 86400
FILE_ID = re.compile(r'^file-api-[A-Za-z0-9_-]+$')


class MultipartImage:
    def __init__(self, path):
        self.path = Path(path)
        if not 0 < self.path.stat().st_size <= MAX_FILE_BYTES:
            raise IngestionError('PROVIDER_IMAGE_LIMIT', 'A prepared image exceeds the documented 64 MiB file limit.')
        boundary = 'terra-' + uuid4().hex
        self.content_type = 'multipart/form-data; boundary=' + boundary
        fields = {'purpose': 'user_data', 'expires_after[anchor]': 'created_at',
                  'expires_after[seconds]': str(FILE_LIFETIME_SECONDS)}
        self.prefix = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                              for key, value in fields.items()).encode()
        self.prefix += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="terra-image{self.path.suffix}"\r\n'
                        'Content-Type: application/octet-stream\r\n\r\n').encode()
        self.suffix = f'\r\n--{boundary}--\r\n'.encode()
        self.length = len(self.prefix) + self.path.stat().st_size + len(self.suffix)

    def __iter__(self):
        yield self.prefix
        with self.path.open('rb') as source:
            while chunk := source.read(1024 * 1024):
                yield chunk
        yield self.suffix


class ProviderFiles:
    def __init__(self, adapter):
        self.adapter = adapter
        account = hashlib.sha256(adapter.spec.key.get_secret_value().encode()).hexdigest()
        self.root = adapter.ledger.root / 'provider-files' / account
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / (uuid4().hex + '.json')
        self.lock = FileLock(str(self.path) + '.lock')
        self.lock.acquire()
        self.entries = []
        self.upload_count = 0
        self.recover_orphans()

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.entries), encoding='utf-8')
        temp.replace(self.path)

    def recover_orphans(self):
        # Never enumerate/delete arbitrary account files or another active job's uploads.
        for path in self.root.glob('*.json'):
            if path == self.path:
                continue
            try:
                with FileLock(str(path) + '.lock', timeout=0):
                    entries = json.loads(path.read_text())
                    remaining = self._delete(entries)
                    if not remaining:
                        path.unlink(missing_ok=True)
            except (Timeout, OSError, ValueError, IngestionError):
                continue  # Expiration remains the fallback; next worker can try cleanup.

    def reference(self, path):
        path = Path(path)
        with path.open('rb') as source:
            sha = hashlib.file_digest(source, 'sha256').hexdigest()
        for entry in self.entries:
            if entry.get('sha256') == sha and entry.get('id') and entry['expires_at'] > time.time() + 60:
                return entry['id']
        entry = {'sha256': sha, 'expires_at': time.time() + FILE_LIFETIME_SECONDS, 'status': 'UPLOADING'}
        self.entries.append(entry)
        self.save()  # Unknown-outcome uploads still expire even if the process dies.
        callback = getattr(self.adapter, 'file_progress', lambda event: None)
        callback({'uploading': True})
        value = self.adapter.transport.request('POST', 'https://api.deepseek.com/files', self.adapter.headers,
                                               MultipartImage(path), timeout=600)
        file_id = value.get('id', '')
        if not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id):
            raise IngestionError('PROVIDER_FILE_INVALID', 'The image upload returned an invalid file identifier.', 502)
        entry.update(id=file_id, status='UPLOADED', expires_at=value.get('expires_at', entry['expires_at']))
        self.save()
        self.upload_count += 1
        callback({'uploading': False, 'uploaded_in_run': self.upload_count})
        return file_id

    def retain(self, paths):
        keep = set()
        for path in paths:
            with Path(path).open('rb') as source:
                keep.add(hashlib.file_digest(source, 'sha256').hexdigest())
        retained = [entry for entry in self.entries if entry.get('sha256') in keep]
        self.entries = retained + self._delete([entry for entry in self.entries if entry.get('sha256') not in keep])
        self.save()

    def _delete(self, entries):
        remaining = []
        for entry in entries:
            file_id = entry.get('id', '')
            if not file_id:
                if entry.get('expires_at', 0) > time.time():
                    remaining.append(entry)
                continue
            if not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id):
                continue
            try:
                value = self.adapter.transport.request('DELETE', 'https://api.deepseek.com/files/' + file_id, self.adapter.headers)
                if value.get('id') != file_id or value.get('deleted') is not True:
                    remaining.append(entry)
            except IngestionError as exc:
                if getattr(exc, 'details', {}).get('http_status') != 404:
                    remaining.append(entry)
        return remaining

    def close(self):
        try:
            self.entries = self._delete(self.entries)
            self.save()
            if not self.entries:
                self.path.unlink(missing_ok=True)
            return {'pending_cleanup': len(self.entries), 'expiration_seconds': FILE_LIFETIME_SECONDS}
        finally:
            self.lock.release()
