"""OpenNeuro dataset browsing and guarded file download.

OpenNeuro is one DatasetProvider. Download URLs are taken from the GraphQL
`files.urls` field and accepted only when the host and path belong to that
dataset. Callers never supply an arbitrary URL.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import hashlib
import re
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from backend.bids_resolver import safe_component, split_relative

OPENNEURO_API = 'https://openneuro.org/crn/graphql'
ACCESSION = re.compile(r'^ds\d{6,8}$')
USER_AGENT = 'NeurobuddyCoach/0.3.1'
MAX_REDIRECTS = 4


def parse_accession(value: str) -> str:
    text = (value or '').strip()
    match = re.fullmatch(r'(?:https?://openneuro\.org/datasets/)?(ds\d{6,8})(?:/.*)?', text, re.I)
    if not match:
        raise HTTPException(422, 'Enter a valid OpenNeuro accession such as ds003061.')
    return match.group(1).lower()


def validate_snapshot_tag(tag: str) -> str:
    if not isinstance(tag, str) or not re.fullmatch(r'[0-9A-Za-z._-]{1,80}', tag):
        raise HTTPException(422, 'Invalid snapshot version.')
    return tag


def validate_download_url(url: str, dataset_id: str) -> str:
    """Allow only HTTPS objects for this dataset on the OpenNeuro or its S3 host."""
    dataset_id = parse_accession(dataset_id)
    if not isinstance(url, str) or not url or any(ch in url for ch in ' \r\n\t'):
        raise HTTPException(422, 'OpenNeuro did not provide a usable download URL.')
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443):
        raise HTTPException(422, 'Refusing a download URL that is not HTTPS on the trusted OpenNeuro host.')
    host = (parts.hostname or '').lower().rstrip('.')
    path = parts.path or ''
    allowed = (
        (host == 's3.amazonaws.com' and path.startswith(f'/openneuro.org/{dataset_id}/')),
        (host == 'openneuro.org.s3.amazonaws.com' and path.startswith(f'/{dataset_id}/')),
        (host == 'openneuro.org' and path.startswith(f'/crn/datasets/{dataset_id}/')),
    )
    if not any(allowed):
        raise HTTPException(422, 'Refusing a download URL outside this OpenNeuro dataset.')
    return url


class DatasetProvider:
    """Interface a future archive can implement. Only OpenNeuro is implemented."""

    name = 'dataset'

    async def get_dataset(self, dataset_id: str) -> dict:
        raise NotImplementedError

    async def list_directory(self, dataset_id: str, version: str, directory_id: str | None) -> list[dict]:
        raise NotImplementedError

    async def resolve_file(self, dataset_id: str, version: str, file_id: str) -> dict:
        raise NotImplementedError

    async def download_file(self, file_reference: dict, destination: Path, progress: Callable | None = None,
                            cancel: Callable | None = None) -> dict:
        raise NotImplementedError


async def graphql(query: str, variables: dict | None = None, client: httpx.AsyncClient | None = None) -> dict:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False)
    try:
        response = await client.post(OPENNEURO_API, json={'query': query, 'variables': variables or {}},
                                     headers={'User-Agent': USER_AGENT, 'Content-Type': 'application/json'})
        response.raise_for_status()
        payload = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, 'Cannot reach OpenNeuro right now. Verify your network connection.') from exc
    finally:
        if owns:
            await client.aclose()
    if payload.get('errors'):
        message = payload['errors'][0].get('message') if isinstance(payload['errors'][0], dict) else 'GraphQL error'
        lowered = str(message).lower()
        if any(token in lowered for token in ('does not exist', 'not found', 'no snapshot', 'unknown dataset')):
            raise HTTPException(404, 'Dataset unavailable or not public.')
        raise HTTPException(502, 'OpenNeuro returned a GraphQL error; check the dataset accession, snapshot, and API status.')
    return payload.get('data') or {}


class OpenNeuroProvider(DatasetProvider):
    name = 'openneuro'

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, retry_backoff: float = 0.4):
        self.transport = transport
        self.retry_backoff = retry_backoff
        self._cache: dict[tuple, list[dict]] = {}

    def _client(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        kwargs = {'timeout': timeout, 'follow_redirects': False, 'headers': {'User-Agent': USER_AGENT}}
        if self.transport is not None:
            kwargs['transport'] = self.transport
        return httpx.AsyncClient(**kwargs)

    async def get_dataset(self, dataset_id: str) -> dict:
        dataset_id = parse_accession(dataset_id)
        # OpenNeuro dataset/snapshot arguments are ID!, not String!.
        query = ('query($id:ID!){dataset(id:$id){id name latestSnapshot{tag description{Name DatasetDOI}}'
                 ' snapshots{tag}}}')
        async with self._client(20) as client:
            data = await graphql(query, {'id': dataset_id}, client)
        found = (data or {}).get('dataset')
        if not found:
            raise HTTPException(404, 'Dataset unavailable or not public.')
        latest = found.get('latestSnapshot') or {}
        tag = latest.get('tag')
        if not tag:
            raise HTTPException(404, 'Dataset has no public snapshot.')
        description = latest.get('description') or {}
        tags = [item.get('tag') for item in (found.get('snapshots') or []) if item.get('tag')]
        return {'id': found.get('id') or dataset_id, 'name': found.get('name') or dataset_id, 'tag': tag,
                'description': description.get('Name') or '', 'doi': description.get('DatasetDOI') or '',
                'tags': tags or [tag], 'provider': self.name}

    async def list_directory(self, dataset_id: str, version: str, directory_id: str | None = None,
                             refresh: bool = False) -> list[dict]:
        dataset_id = parse_accession(dataset_id)
        version = validate_snapshot_tag(version)
        if directory_id is not None and not re.fullmatch(r'[a-f0-9]{40,64}', directory_id):
            raise HTTPException(422, 'Invalid OpenNeuro directory id.')
        key = (dataset_id, version, directory_id or '')
        if not refresh and key in self._cache:
            return [dict(item) for item in self._cache[key]]
        query = ('query($id:ID!,$tag:String!,$tree:String){snapshot(datasetId:$id,tag:$tag)'
                 '{files(tree:$tree){id filename size directory annexed urls}}}')
        async with self._client(30) as client:
            data = await graphql(query, {'id': dataset_id, 'tag': version, 'tree': directory_id}, client)
        snapshot = (data or {}).get('snapshot')
        if not snapshot:
            raise HTTPException(404, 'Public snapshot not available.')
        items = snapshot.get('files') or []
        if len(items) > 3000:
            raise HTTPException(413, 'Folder too large to display at once.')
        cleaned = []
        for item in items:
            name = item.get('filename') or ''
            if not name or '/' in name or '\\' in name or name in {'.', '..'}:
                continue
            urls = [url for url in (item.get('urls') or []) if isinstance(url, str)]
            cleaned.append({'id': item.get('id') or '', 'filename': name,
                            'size': item.get('size'), 'directory': bool(item.get('directory')),
                            'annexed': bool(item.get('annexed')), 'urls': urls})
        self._cache[key] = cleaned
        return [dict(item) for item in cleaned]

    async def resolve_file(self, dataset_id: str, version: str, file_id: str) -> dict:
        """Find a file id that was already listed. OpenNeuro has no single-file query."""
        if not re.fullmatch(r'[a-f0-9]{40,64}', file_id or ''):
            raise HTTPException(422, 'Invalid OpenNeuro file id.')
        for (cached_id, cached_tag, _), entries in self._cache.items():
            if cached_id == parse_accession(dataset_id) and cached_tag == validate_snapshot_tag(version):
                for entry in entries:
                    if entry.get('id') == file_id and not entry.get('directory'):
                        return dict(entry)
        raise HTTPException(404, 'File id is not in a directory listing for this snapshot. Browse to its folder first.')

    async def walk(self, dataset_id: str, version: str, relative_path: str) -> dict:
        parts = split_relative(relative_path)
        directories: dict[str, list[dict]] = {}
        tree = None
        walked = ''
        entries = await self.list_directory(dataset_id, version, None, refresh=True)
        directories[''] = _with_paths('', entries)
        for index, part in enumerate(parts):
            match = next((item for item in entries if item['filename'] == part), None)
            if match is None:
                raise HTTPException(404, f'Snapshot path not found: {relative_path}')
            current = f'{walked}/{part}' if walked else part
            last = index == len(parts) - 1
            if last:
                if match.get('directory'):
                    raise HTTPException(422, 'Select an EEG file, not a folder.')
                signal = dict(match)
                signal['path'] = current
                signal['file_id'] = match.get('id') or ''
                return {'signal': signal, 'directories': directories}
            if not match.get('directory'):
                raise HTTPException(404, f'Snapshot path not found: {relative_path}')
            tree = match.get('id')
            entries = await self.list_directory(dataset_id, version, tree, refresh=True)
            walked = current
            directories[walked] = _with_paths(walked, entries)
        raise HTTPException(404, f'Snapshot path not found: {relative_path}')

    async def fetch_small(self, dataset_id: str, record: dict, limit: int = 1_500_000) -> bytes:
        size = record.get('size')
        if isinstance(size, (int, float)) and size > limit:
            return b''
        return await self._read_bytes(dataset_id, record, limit)

    async def _read_bytes(self, dataset_id: str, record: dict, limit: int) -> bytes:
        import asyncio
        url = _first_url(dataset_id, record)
        delay = self.retry_backoff
        last_error: Exception | None = None
        for attempt in range(3):
            buffer = bytearray()

            async def collect(chunk: bytes):
                if len(buffer) + len(chunk) > limit:
                    raise HTTPException(413, f"{record.get('filename')} is too large to inspect during dependency resolution.")
                buffer.extend(chunk)

            try:
                await self._transfer_once(dataset_id, url, collect, expected_size=None, max_bytes=limit, cancel=None)
                return bytes(buffer)
            except HTTPException:
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise HTTPException(502, 'Could not read a small OpenNeuro file needed to resolve companions.') from last_error

    async def download_file(self, file_reference: dict, destination: Path, progress: Callable | None = None,
                            cancel: Callable | None = None, expected_size: int | None = None,
                            max_bytes: int | None = None) -> dict:
        import asyncio
        dataset_id = file_reference.get('dataset_id')
        url = _first_url(dataset_id, file_reference)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.partial')
        delay = self.retry_backoff
        last_error: Exception | None = None
        for attempt in range(3):
            if cancel and cancel():
                raise HTTPException(409, 'Import cancelled.')
            digest = hashlib.sha256()
            written = 0
            try:
                with temporary.open('wb') as handle:
                    async def write(chunk: bytes):
                        nonlocal written
                        handle.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        if progress:
                            progress(written)
                    await self._transfer_once(dataset_id, url, write, expected_size=expected_size,
                                              max_bytes=max_bytes, cancel=cancel)
                if written <= 0:
                    raise HTTPException(422, f"Downloaded file is empty: {destination.name}")
                if expected_size is not None and written != expected_size:
                    raise HTTPException(422, f"Downloaded size {written} does not match OpenNeuro size {expected_size} for {destination.name}.")
                temporary.replace(destination)
                return {'bytes': written, 'sha256': digest.hexdigest(), 'url_host': urlsplit(url).hostname}
            except HTTPException:
                temporary.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        destination.unlink(missing_ok=True)
        raise HTTPException(502, 'Download from OpenNeuro failed after retries. The shelf was not changed.') from last_error

    async def _transfer_once(self, dataset_id: str, url: str, consume: Callable, expected_size: int | None,
                             max_bytes: int | None, cancel: Callable | None):
        current = validate_download_url(url, dataset_id)
        async with self._client(httpx.Timeout(60.0, connect=10.0)) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if cancel and cancel():
                    raise HTTPException(409, 'Import cancelled.')
                async with client.stream('GET', current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get('location')
                        if not location:
                            raise HTTPException(502, 'OpenNeuro redirect is missing a location.')
                        current = validate_download_url(httpx.URL(current).join(location).__str__(), dataset_id)
                        continue
                    if response.status_code in {502, 503, 504}:
                        raise httpx.TransportError(f'upstream {response.status_code}')
                    if response.status_code != 200:
                        raise HTTPException(502, f'OpenNeuro download returned HTTP {response.status_code}.')
                    announced = response.headers.get('content-length')
                    if announced is not None and announced.isdigit():
                        length = int(announced)
                        if expected_size is not None and length != expected_size:
                            raise HTTPException(422, 'OpenNeuro Content-Length does not match the snapshot file size.')
                        if max_bytes is not None and length > max_bytes:
                            raise HTTPException(413, 'File exceeds the configured download limit.')
                    received = 0
                    async for chunk in response.aiter_bytes(256 * 1024):
                        if cancel and cancel():
                            raise HTTPException(409, 'Import cancelled.')
                        if not chunk:
                            continue
                        received += len(chunk)
                        if max_bytes is not None and received > max_bytes:
                            raise HTTPException(413, 'File exceeds the configured download limit.')
                        result = consume(chunk)
                        if hasattr(result, '__await__'):
                            await result
                    if expected_size is not None and received != expected_size:
                        raise HTTPException(422, 'Download ended before the snapshot file size was reached.')
                    return
        raise HTTPException(502, 'Too many download redirects.')


def _with_paths(folder: str, entries: list[dict]) -> list[dict]:
    items = []
    for entry in entries:
        name = entry['filename']
        if not safe_component(name) and entry.get('directory'):
            # Directories such as ".datalad" stay visible for browsing but are not import paths.
            path = f'{folder}/{name}' if folder else name
        elif not safe_component(name):
            continue
        else:
            path = f'{folder}/{name}' if folder else name
        item = dict(entry)
        item['path'] = path
        item['file_id'] = entry.get('id') or ''
        items.append(item)
    return items


def _first_url(dataset_id: str, record: dict) -> str:
    urls = [url for url in (record.get('urls') or []) if isinstance(url, str)]
    if not urls:
        raise HTTPException(502, f"OpenNeuro did not provide a download URL for {record.get('filename') or 'this file'}.")
    return validate_download_url(urls[0], dataset_id or record.get('dataset_id'))
