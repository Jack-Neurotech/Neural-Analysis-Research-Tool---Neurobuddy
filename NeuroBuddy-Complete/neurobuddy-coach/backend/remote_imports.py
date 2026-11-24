"""Background import of one resolved EEG bundle into an existing shelf.

Downloads stay in a temporary directory until intake validation succeeds.
A failed or cancelled import does not mark the shelf ready.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import asyncio
import hashlib
import json
import shutil
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.bids_resolver import (
    TASKS, bids_entities, build_manifest, entities_compatible, is_signal_name,
    public_manifest, referenced_fdt, brainvision_refs, sidecar_role, split_relative,
)
from backend.motor_labels import motor_subtype_from_events
from backend.openneuro_connector import OpenNeuroProvider, parse_accession, validate_snapshot_tag

EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='openneuro-import')
CANCELS: dict[str, threading.Event] = {}
STATE: dict = {}
TEXT_SUFFIXES = ('.vhdr', '.tsv', '.csv', '.json', '.txt', '.vmrk', '.md')
PREVIEW_NAMES = {'readme', 'changes', 'license', 'citation'}
PREVIEW_BYTES = 1_500_000
PREVIEW_CHARS = 48_000
IMPORT_FILE_CAP = 24


class ResolveBody(BaseModel):
    dataset_id: str
    tag: str | None = None
    path: str = Field(min_length=1, max_length=420)
    task_type: str
    classification: str = 'baseline'
    shelf_id: str | None = None
    athlete_id: str | None = None


class ImportBody(ResolveBody):
    tag: str = Field(min_length=1, max_length=80)
    acknowledge_review: bool = False
    adopt_detected_task: bool = False


class TsvBody(BaseModel):
    dataset_id: str
    tag: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=420)
    shelf_id: str


class FdtBody(TsvBody):
    """One .fdt chosen for the .set already on a shelf."""


def provider_factory():
    return OpenNeuroProvider()


_MOTOR_TASKS = {'motion', 'motor', 'imagery', 'eegmmidb', 'motorimagery', 'motorloc', 'execution'}


def _motor_filename(filename: str) -> bool:
    task = bids_entities(filename).get('task', '').lower()
    return task in _MOTOR_TASKS or 'motor' in task or 'imagery' in task


def _acquisition_family(filename: str) -> str | None:
    acq = bids_entities(filename).get('acq', '').lower()
    if not acq:
        return None
    if acq == 'scoring' or acq.startswith('psg'):
        return 'psg'
    if 'eareeg' in acq:
        return 'eareeg'
    return acq


def _chosen_for_signal(tsv_name: str, signal_name: str) -> bool:
    """Same subject, session, and task, and the same acquisition family.

    acq-scoring and acq-PSGtrigger belong with a PSG .set. An earEEG TSV does not.
    """
    sidecar, signal = bids_entities(tsv_name), bids_entities(signal_name)
    for key in ('sub', 'ses', 'task', 'run'):
        if key in sidecar and key in signal and sidecar[key].lower() != signal[key].lower():
            return False
    if not any(key in sidecar for key in ('sub', 'ses', 'task', 'acq')):
        return False
    side_family, signal_family = _acquisition_family(tsv_name), _acquisition_family(signal_name)
    if side_family and signal_family:
        return side_family == signal_family
    return entities_compatible(tsv_name, signal_name)


def _corresponding_tsvs(signal_name: str, entries: list[dict]) -> list[dict]:
    """Events or scoring tables the coach can choose for one .set."""
    matches = []
    for item in entries:
        name = item.get('filename') or ''
        lower = name.lower()
        if item.get('directory') or not lower.endswith(('.tsv', '.csv')):
            continue
        if sidecar_role(name, 'eeg') not in {'events', 'sleep_scoring'}:
            continue
        if _chosen_for_signal(name, signal_name):
            matches.append(item)
    return matches


def _events_for(signal_name: str, entries: list[dict]) -> dict | None:
    matches = []
    for item in entries:
        name = item.get('filename') or ''
        if item.get('directory') or sidecar_role(name, 'eeg') != 'events':
            continue
        if entities_compatible(name, signal_name):
            matches.append(item)
    if not matches:
        return None
    best = max(len(bids_entities(item['filename'])) for item in matches)
    chosen = [item for item in matches if len(bids_entities(item['filename'])) == best]
    if len(chosen) != 1:
        return None
    return chosen[0]


async def _entries_at(provider, dataset_id: str, tag: str, folder: str) -> list[dict]:
    parts = split_relative(folder) if folder else []
    entries = await provider.list_directory(dataset_id, tag, None)
    for part in parts:
        match = next((item for item in entries if item.get('filename') == part and item.get('directory')), None)
        if match is None:
            raise HTTPException(404, f'Snapshot path not found: {folder}')
        entries = await provider.list_directory(dataset_id, tag, match.get('id'))
    labeled = []
    for item in entries:
        row = dict(item)
        name = row.get('filename') or ''
        row['path'] = f'{folder}/{name}' if folder else name
        labeled.append(row)
    return labeled


def register(router: APIRouter, base):
    STATE['base'] = base
    _ensure_table(base)
    with base.LOCK, base.database() as db:
        rows = [dict(r) for r in db.execute("SELECT id, shelf_id, created_shelf FROM import_jobs WHERE status IN ('queued','running')")]
        db.execute("UPDATE import_jobs SET status='interrupted', error=?, updated_at=? WHERE status IN ('queued','running')",
                   ('Server stopped before the import finished. Retry the import.', base.now()))
    for row in rows:
        if row['created_shelf']:
            _drop_empty_shelf(base, row['shelf_id'])

    @router.get('/openneuro/{dataset_id}/file')
    async def open_file(dataset_id: str, tag: str = Query(min_length=1, max_length=80),
                        path: str = Query(min_length=1, max_length=420)):
        """Open a text file so the coach can read it. Opening does not save the file."""
        try:
            split_relative(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        filename = path.rsplit('/', 1)[-1]
        if not _previewable(filename):
            raise HTTPException(422, 'This file is not opened as text. Download saves only the EEG file you click. A TSV is saved only when you choose Add this TSV.')
        provider = provider_factory()
        dataset = await provider.get_dataset(dataset_id)
        snapshot = validate_snapshot_tag(tag)
        if snapshot not in set(dataset.get('tags') or [dataset['tag']]):
            raise HTTPException(404, f'Snapshot {snapshot} is not a published version of {dataset["id"]}.')
        try:
            walked = await provider.walk(dataset['id'], snapshot, path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        record = dict(walked['signal'])
        if record.get('directory') or record.get('filename') != filename:
            raise HTTPException(422, 'Select a file, not a folder.')
        size = record.get('size')
        if isinstance(size, (int, float)) and size > PREVIEW_BYTES:
            raise HTTPException(413, 'This file is too large to open in the connector.')
        record['dataset_id'] = dataset['id']
        blob = await provider.fetch_small(dataset['id'], record, limit=PREVIEW_BYTES)
        text, truncated = _clip_preview(blob.decode('utf-8', errors='replace'))
        return {'dataset_id': dataset['id'], 'snapshot': snapshot, 'path': path,
                'filename': record['filename'], 'size': size, 'truncated': truncated, 'text': text}

    @router.get('/openneuro/{dataset_id}/motor-labels')
    async def motor_labels(dataset_id: str, tag: str = Query(min_length=1, max_length=80),
                           path: str = Query(default='', max_length=420)):
        """Label the events TSV that belongs to each motor .set. The .set stays unlabeled and is not downloaded."""
        folder = (path or '').strip().strip('/')
        if folder:
            try:
                split_relative(folder)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        provider = provider_factory()
        dataset = await provider.get_dataset(dataset_id)
        snapshot = validate_snapshot_tag(tag)
        if snapshot not in set(dataset.get('tags') or [dataset['tag']]):
            raise HTTPException(404, f'Snapshot {snapshot} is not a published version of {dataset["id"]}.')
        try:
            entries = await _entries_at(provider, dataset['id'], snapshot, folder)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        labels = []
        if any(_motor_filename(item.get('filename') or '') for item in entries):
            for signal in entries:
                name = signal.get('filename') or ''
                if signal.get('directory') or not name.lower().endswith('.set') or not _motor_filename(name):
                    continue
                events = _events_for(name, entries)
                if events is None:
                    continue
                try:
                    blob = await provider.fetch_small(dataset['id'], events, limit=PREVIEW_BYTES)
                except HTTPException:
                    continue
                if not blob:
                    continue
                label = motor_subtype_from_events(blob.decode('utf-8', errors='replace'))
                if label in {'imagery', 'execution'}:
                    labels.append({'path': events['path'], 'filename': events['filename'], 'label': label,
                                   'signal': signal['path']})
        return {'dataset_id': dataset['id'], 'snapshot': snapshot, 'path': folder, 'labels': labels}

    @router.get('/openneuro/{dataset_id}/sleep-correspondence')
    async def sleep_correspondence(dataset_id: str, tag: str = Query(min_length=1, max_length=80),
                                   path: str = Query(default='', max_length=420)):
        """Label the events or scoring TSV that matches each .set. The .set is not downloaded."""
        folder = (path or '').strip().strip('/')
        if folder:
            try:
                split_relative(folder)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        provider = provider_factory()
        dataset = await provider.get_dataset(dataset_id)
        snapshot = validate_snapshot_tag(tag)
        if snapshot not in set(dataset.get('tags') or [dataset['tag']]):
            raise HTTPException(404, f'Snapshot {snapshot} is not a published version of {dataset["id"]}.')
        try:
            entries = await _entries_at(provider, dataset['id'], snapshot, folder)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        labels = []
        seen = set()
        for signal in entries:
            name = signal.get('filename') or ''
            if signal.get('directory') or not name.lower().endswith('.set'):
                continue
            for events in _corresponding_tsvs(name, entries):
                key = events['path']
                if key in seen:
                    continue
                seen.add(key)
                labels.append({'path': events['path'], 'filename': events['filename'], 'label': 'Corresponding',
                               'signal': signal['path']})
        return {'dataset_id': dataset['id'], 'snapshot': snapshot, 'path': folder, 'labels': labels}

    @router.post('/openneuro/resolve-recording')
    async def resolve_recording(body: ResolveBody):
        _check_task(body.task_type)
        _check_class(body.classification)
        manifest = await _resolve(provider_factory(), body.dataset_id, body.tag, body.path, body.task_type)
        _guard_destination(base, body, manifest, enqueue=False)
        return public_manifest(manifest)

    @router.post('/openneuro/save-tsv', status_code=201)
    async def save_tsv(body: TsvBody):
        """Save exactly one chosen TSV onto an existing shelf. Nothing else is written."""
        filename = body.path.rsplit('/', 1)[-1]
        if not filename.lower().endswith('.tsv'):
            raise HTTPException(422, 'Choose one .tsv file. Reading a file does not save it.')
        provider = provider_factory()
        one = await _one_remote(provider, body.dataset_id, body.tag, body.path, kind='tsv')
        with base.LOCK, base.database() as db:
            shelf = base.must_get(db, 'recordings', body.shelf_id)
            existing = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (body.shelf_id,))]
        if one.signal_path in existing:
            raise HTTPException(409, 'That TSV is already on this shelf.')
        if len(existing) >= 24:
            raise HTTPException(422, 'This EEG shelf already has its file limit.')
        staging_id = str(uuid4())
        staging = _staging(base, staging_id)
        staging.mkdir(parents=True, exist_ok=True)
        moved = False
        target = None
        try:
            remote = dict(one.remote)
            remote['dataset_id'] = one.dataset_id
            destination = _contained(staging, one.signal_path)
            size = one.files[0].get('size')
            expected = int(size) if isinstance(size, int) and size > 0 else None
            await provider.download_file(remote, destination, expected_size=expected, max_bytes=base.MAX_FILE_BYTES)
            root = base.recording_path(shelf)
            root.mkdir(parents=True, exist_ok=True)
            target = _contained(root, one.signal_path)
            if target.exists():
                raise HTTPException(409, 'That TSV is already on this shelf.')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(target))
            moved = True
            with base.LOCK, base.database() as db:
                base.must_get(db, 'recordings', body.shelf_id)
                again = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (body.shelf_id,))]
                if one.signal_path in again:
                    raise HTTPException(409, 'That TSV is already on this shelf.')
                db.execute('INSERT INTO recording_files VALUES(?,?,?,?)',
                           (str(uuid4()), body.shelf_id, one.signal_path, target.stat().st_size))
        except Exception:
            if moved and target is not None:
                target.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(_job_dir(base, staging_id), ignore_errors=True)
        return {'shelf_id': body.shelf_id, 'saved': one.signal_path, 'filename': filename}

    @router.post('/openneuro/save-fdt', status_code=201)
    async def save_fdt(body: FdtBody):
        """Save the one .fdt named by the .set already on this shelf. Nothing else is written."""
        filename = body.path.rsplit('/', 1)[-1]
        if not filename.lower().endswith('.fdt'):
            raise HTTPException(422, 'Choose the .fdt named by the .set already on this shelf.')
        provider = provider_factory()
        with base.LOCK, base.database() as db:
            shelf = base.must_get(db, 'recordings', body.shelf_id)
            existing = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (body.shelf_id,))]
        sets = [name for name in existing if name.lower().endswith('.set')]
        if len(sets) != 1:
            raise HTTPException(422, 'Add the .set to this shelf before its .fdt.')
        signal_rel = sets[0]
        signal_file = _contained(base.recording_path(shelf), signal_rel)
        if not signal_file.is_file():
            raise HTTPException(422, 'The .set on this shelf is missing, so its .fdt cannot be added.')
        named = _scan_fdt(signal_file)
        if not named:
            raise HTTPException(422, 'The .set on this shelf does not name an external .fdt.')
        if filename != named:
            raise HTTPException(422, f'The .set on this shelf names {named}. This file is not added.')
        set_parent = signal_rel.rsplit('/', 1)[0] if '/' in signal_rel else ''
        fdt_parent = body.path.rsplit('/', 1)[0] if '/' in body.path else ''
        if fdt_parent != set_parent:
            raise HTTPException(422, 'The .fdt has to be the companion in the same folder as the .set.')
        relative = f'{set_parent}/{named}' if set_parent else named
        if relative in existing or body.path in existing:
            raise HTTPException(409, 'That .fdt is already on this shelf.')
        if len(existing) >= 24:
            raise HTTPException(422, 'This EEG shelf already has its file limit.')
        one = await _one_remote(provider, body.dataset_id, body.tag, body.path, kind='fdt')
        if one.files[0]['filename'] != named:
            raise HTTPException(422, f'The .set on this shelf names {named}. This file is not added.')
        staging_id = str(uuid4())
        staging = _staging(base, staging_id)
        staging.mkdir(parents=True, exist_ok=True)
        moved = False
        target = None
        try:
            remote = dict(one.remote)
            remote['dataset_id'] = one.dataset_id
            destination = _contained(staging, relative)
            size = one.files[0].get('size')
            expected = int(size) if isinstance(size, int) and size > 0 else None
            await provider.download_file(remote, destination, expected_size=expected, max_bytes=base.MAX_FILE_BYTES)
            root = base.recording_path(shelf)
            root.mkdir(parents=True, exist_ok=True)
            target = _contained(root, relative)
            if target.exists():
                raise HTTPException(409, 'That .fdt is already on this shelf.')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(target))
            moved = True
            with base.LOCK, base.database() as db:
                base.must_get(db, 'recordings', body.shelf_id)
                again = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (body.shelf_id,))]
                if relative in again:
                    raise HTTPException(409, 'That .fdt is already on this shelf.')
                db.execute('INSERT INTO recording_files VALUES(?,?,?,?)',
                           (str(uuid4()), body.shelf_id, relative, target.stat().st_size))
            loaded = _load_shelf_set(root, signal_file)
            _note_loaded(base, body.shelf_id, loaded)
        except Exception:
            if moved and target is not None:
                target.unlink(missing_ok=True)
                with base.LOCK, base.database() as db:
                    db.execute('DELETE FROM recording_files WHERE recording_id=? AND name=?', (body.shelf_id, relative))
            raise
        finally:
            shutil.rmtree(_job_dir(base, staging_id), ignore_errors=True)
        return {'shelf_id': body.shelf_id, 'saved': relative, 'filename': named,
                'status': loaded['status'], 'sfreq': loaded['sfreq'],
                'n_channels': loaded['n_channels'], 'n_times': loaded['n_times']}

    @router.post('/openneuro/import-recording', status_code=202)
    async def import_recording(body: ImportBody):
        _check_task(body.task_type)
        _check_class(body.classification)
        provider = provider_factory()
        manifest = await _one_remote(provider, body.dataset_id, body.tag, body.path, kind='signal')
        shelf_id, created = _guard_destination(base, body, manifest, enqueue=True)
        key = str(uuid4())
        progress = _initial_progress(manifest)
        with base.LOCK, base.database() as db:
            db.execute('''INSERT INTO import_jobs(id,status,provider,dataset_id,snapshot,signal_path,shelf_id,athlete_id,
                created_shelf,task_type,classification,acknowledge_review,adopt_detected_task,created_at,updated_at,manifest,progress,error,result)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (key, 'queued', 'openneuro', manifest.dataset_id, manifest.snapshot, manifest.signal_path, shelf_id,
                 body.athlete_id, 1 if created else 0, body.task_type, body.classification,
                 1 if body.acknowledge_review else 0, 1 if body.adopt_detected_task else 0,
                 base.now(), base.now(), json.dumps(public_manifest(manifest)), json.dumps(progress), None, None))
        CANCELS[key] = threading.Event()
        EXECUTOR.submit(run_import, key)
        return {'id': key, 'status': 'queued', 'shelf_id': shelf_id, 'snapshot': manifest.snapshot}

    @router.get('/import-jobs/{job_id}')
    def import_job(job_id: str):
        return _public_job(base, job_id)

    @router.post('/import-jobs/{job_id}/cancel')
    def cancel_job(job_id: str):
        with base.LOCK, base.database() as db:
            row = _must_job(db, job_id)
            if row['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
                raise HTTPException(409, f"Import is already {row['status']}.")
            db.execute("UPDATE import_jobs SET status='cancelled', error=?, updated_at=? WHERE id=?",
                       ('Import cancelled. The EEG shelf was not marked ready.', base.now(), job_id))
        event = CANCELS.get(job_id)
        if event:
            event.set()
        return {'id': job_id, 'status': 'cancelled'}

    @router.post('/import-jobs/{job_id}/retry', status_code=202)
    def retry_job(job_id: str):
        with base.LOCK, base.database() as db:
            row = _must_job(db, job_id)
            if row['status'] not in {'failed', 'cancelled', 'interrupted'}:
                raise HTTPException(409, 'Only a failed, cancelled, or interrupted import can be retried.')
            if row['shelf_id'] and not row['created_shelf']:
                shelf = db.execute('SELECT id FROM recordings WHERE id=?', (row['shelf_id'],)).fetchone()
                if shelf is None:
                    raise HTTPException(404, 'The destination EEG shelf no longer exists.')
            if row['shelf_id']:
                names = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (row['shelf_id'],))]
                if any(is_signal_name(name) for name in names):
                    raise HTTPException(409, 'That shelf already has an EEG signal. Remove it before retrying the import.')
            db.execute("UPDATE import_jobs SET status='queued', error=NULL, result=NULL, updated_at=? WHERE id=?",
                       (base.now(), job_id))
        CANCELS[job_id] = threading.Event()
        EXECUTOR.submit(run_import, job_id)
        return {'id': job_id, 'status': 'queued', 'shelf_id': row['shelf_id']}


def run_import(job_id: str):
    try:
        asyncio.run(_execute(job_id))
    except Exception as exc:
        _fail(job_id, _error_text(exc))


async def _execute(job_id: str):
    base = STATE['base']
    row = _fetch(base, job_id)
    if row['status'] == 'cancelled':
        return
    row['shelf_id'] = _ensure_shelf(base, row)
    _update(base, job_id, status='running', phase='downloading')
    provider = provider_factory()
    task = row['task_type']
    try:
        manifest = await _one_remote(provider, row['dataset_id'], row['snapshot'], row['signal_path'], kind='signal')
    except HTTPException as exc:
        _fail(job_id, _error_text(exc))
        return
    if _cancelled(job_id):
        _cleanup_failure(base, job_id, row, 'Import cancelled. The EEG shelf was not marked ready.')
        return
    if manifest.snapshot != row['snapshot']:
        _fail(job_id, 'The published snapshot changed before download. Start the import again to lock the new snapshot.')
        return
    chosen = [item for item in manifest.files if item.get('selected') and item.get('path') == row['signal_path']]
    if len(chosen) != 1 or not is_signal_name(chosen[0]['filename']):
        _fail(job_id, 'Download saves only the one EEG file that was clicked.')
        return
    staging = _staging(base, job_id)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    total = sum(int(item['size']) for item in chosen if isinstance(item.get('size'), int) and item['size'] > 0)
    _check_disk(staging, total)
    progress = _initial_progress(manifest)
    progress['bytes_total'] = total
    done = {item['path']: 0 for item in chosen}
    try:
        fresh = await provider.walk(row['dataset_id'], row['snapshot'], row['signal_path'])
        located = {item['path']: item for folder in fresh['directories'].values() for item in folder if not item.get('directory')}
        located[fresh['signal']['path']] = fresh['signal']
        for item in chosen:
            if _cancelled(job_id):
                raise HTTPException(409, 'Import cancelled.')
            remote = located.get(item['path'])
            if remote is None:
                raise HTTPException(502, f"Snapshot no longer contains {item['path']}.")
            if item.get('file_id') and remote.get('file_id') and item['file_id'] != remote.get('file_id'):
                raise HTTPException(409, f"File content id changed for {item['filename']}. Import was stopped.")
            _mark_file(progress, item['path'], 'downloading')
            _save_progress(base, job_id, progress, done)
            remote = dict(remote)
            remote['dataset_id'] = row['dataset_id']
            expected = int(item['size']) if isinstance(item.get('size'), int) and item['size'] > 0 else None

            def _progress(amount, path=item['path']):
                done[path] = amount
                progress['bytes_done'] = sum(done.values())
                _mark_file(progress, path, 'downloading', amount)
                _save_progress(base, job_id, progress, done, throttle=True)

            destination = _contained(staging, item['path'])
            result = await provider.download_file(remote, destination, progress=_progress, cancel=lambda: _cancelled(job_id),
                                                  expected_size=expected, max_bytes=base.MAX_FILE_BYTES)
            item['sha256'] = result['sha256']
            item['size'] = result['bytes']
            done[item['path']] = result['bytes']
            _mark_file(progress, item['path'], 'done', result['bytes'])
            progress['bytes_done'] = sum(done.values())
            _save_progress(base, job_id, progress, done, force=True)
        progress['phase'] = 'validating'
        _save_progress(base, job_id, progress, done, force=True)
        validation = _validate_bundle(staging, chosen)
        if _cancelled(job_id):
            raise HTTPException(409, 'Import cancelled.')
        progress['phase'] = 'saving'
        progress['validated'] = True
        _save_progress(base, job_id, progress, done, force=True)
        _commit(base, row, manifest, chosen, staging, task, validation)
        progress['phase'] = 'completed'
        progress['saved'] = True
        _save_progress(base, job_id, progress, done, force=True)
        result_doc = {'shelf_id': row['shelf_id'], 'validation': validation, 'task_type': task,
                      'task_detected': manifest.task_detected, 'files': chosen}
        with base.LOCK, base.database() as db:
            db.execute("UPDATE import_jobs SET status='completed', task_type=?, result=?, error=NULL, manifest=?, updated_at=? WHERE id=?",
                       (task, json.dumps(result_doc), json.dumps(public_manifest(manifest)), base.now(), job_id))
        shutil.rmtree(_job_dir(base, job_id), ignore_errors=True)
    except Exception as exc:
        if _cancelled(job_id):
            _cleanup_failure(base, job_id, row, 'Import cancelled. The EEG shelf was not marked ready.')
            return
        _fail(job_id, _error_text(exc))


def _previewable(filename: str) -> bool:
    lower = filename.lower()
    return lower in PREVIEW_NAMES or lower.endswith(TEXT_SUFFIXES)


def _clip_preview(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    truncated = len(text) > PREVIEW_CHARS or len(lines) > 4000
    if len(lines) > 4000:
        lines = lines[:4000]
    clipped = '\n'.join(lines)
    if len(clipped) > PREVIEW_CHARS:
        clipped = clipped[:PREVIEW_CHARS]
    return clipped, truncated


class OneFile:
    """One chosen OpenNeuro file. Download and shelf writes use this list and nothing else."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def as_dict(self):
        return {key: value for key, value in self.__dict__.items() if key != 'remote'}


async def _one_remote(provider, dataset_id: str, tag: str | None, path: str, kind: str) -> OneFile:
    try:
        split_relative(path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    dataset = await provider.get_dataset(dataset_id)
    snapshot = validate_snapshot_tag(tag) if tag else dataset['tag']
    if snapshot not in set(dataset.get('tags') or [dataset['tag']]):
        raise HTTPException(404, f'Snapshot {snapshot} is not a published version of {dataset["id"]}.')
    try:
        walked = await provider.walk(dataset['id'], snapshot, path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record = dict(walked['signal'])
    filename = record.get('filename') or ''
    if record.get('directory') or record.get('path') != path:
        raise HTTPException(422, 'Select one file, not a folder.')
    if kind == 'signal' and not is_signal_name(filename):
        raise HTTPException(422, 'Download saves only the EEG file you clicked. Choose a .set, .edf, .bdf, .vhdr, .fif, or .fif.gz.')
    if kind == 'tsv' and not filename.lower().endswith('.tsv'):
        raise HTTPException(422, 'Choose one .tsv file. Reading a file does not save it.')
    if kind == 'fdt' and not filename.lower().endswith('.fdt'):
        raise HTTPException(422, 'Choose the .fdt named by the .set already on this shelf.')
    if kind == 'signal':
        reason, role = 'Only this EEG file was chosen.', 'signal'
    elif kind == 'fdt':
        reason, role = 'Only this .fdt was chosen.', 'companion'
    else:
        reason, role = 'Only this TSV was chosen.', 'events'
    return OneFile(
        provider='openneuro', dataset_id=dataset['id'], snapshot=snapshot,
        dataset_name=dataset.get('name') or '', signal_path=path, remote=record,
        task_detected='', task_selected='', warnings=[], task_evidence=[], conflicts=[],
        status='ready', can_auto_import=True, allow_acknowledge=False, summary=reason,
        files=[{'path': path, 'filename': filename, 'file_id': record.get('file_id') or record.get('id') or '',
                'size': record.get('size'), 'role': role,
                'category': 'required', 'reason': reason, 'selected': True}])


async def _resolve(provider, dataset_id: str, tag: str | None, path: str, task: str):
    try:
        split_relative(path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    dataset = await provider.get_dataset(dataset_id)
    snapshot = validate_snapshot_tag(tag) if tag else dataset['tag']
    if snapshot not in set(dataset.get('tags') or [dataset['tag']]):
        raise HTTPException(404, f'Snapshot {snapshot} is not a published version of {dataset["id"]}.')
    try:
        walked = await provider.walk(dataset['id'], snapshot, path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    texts = await _collect_texts(provider, dataset['id'], walked)
    return build_manifest(provider=provider.name, dataset_id=dataset['id'], snapshot=snapshot,
                          dataset_name=dataset.get('name') or '', signal_path=path, task=task,
                          directories=walked['directories'], texts=texts)


async def _collect_texts(provider, dataset_id: str, walked: dict) -> dict[str, str]:
    signal = walked['signal']
    wanted = []
    size = signal.get('size') or 0
    if signal['filename'].lower().endswith('.vhdr') or (signal['filename'].lower().endswith('.set') and size <= 2_000_000):
        wanted.append(signal)
    for entries in walked['directories'].values():
        for entry in entries:
            if entry.get('directory'):
                continue
            name = entry['filename'].lower()
            interesting = ('_events.', '_channels.', '_electrodes.', '_coordsystem.', '_eeg.json',
                           '_ieeg.json', '_meg.json', 'dataset_description.json', 'scoring', 'hypnogram', 'stages')
            if name.endswith(TEXT_SUFFIXES) and (entry.get('size') or 0) <= 1_500_000 and any(token in name for token in interesting):
                wanted.append(entry)
    texts = {}
    seen = set()
    for entry in wanted:
        if entry['path'] in seen:
            continue
        seen.add(entry['path'])
        record = dict(entry)
        record['dataset_id'] = dataset_id
        blob = await provider.fetch_small(dataset_id, record)
        if not blob:
            continue
        texts[entry['path']] = blob.decode('latin-1', errors='ignore') if entry['filename'].lower().endswith('.set') else blob.decode('utf-8', errors='replace')
    return texts


def _validate_bundle(staging: Path, chosen: list[dict]) -> dict:
    from neurobuddy_v2.intake import discover, load_eeg
    for item in chosen:
        path = _contained(staging, item['path'])
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Required file missing after download: {item['filename']}")
        amount = path.stat().st_size
        if amount <= 0:
            raise ValueError(f"Downloaded file is empty: {item['filename']}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if item.get('sha256') and item['sha256'] != digest:
            raise ValueError(f"Checksum changed before validation: {item['filename']}")
    bundles = discover(staging)
    if len(bundles) != 1:
        raise ValueError(f'Expected exactly one EEG recording in the bundle, found {len(bundles)}.')
    bundle = bundles[0]
    try:
        raw = load_eeg(bundle)
    except RuntimeError as exc:
        # A single chosen .set can name an external .fdt. That companion is not
        # part of this download, so keep the .set and record the real load error.
        if bundle.status == 'INCOMPLETE' and 'fdt' in str(exc).lower():
            return {'sfreq': None, 'n_times': None, 'n_channels': None,
                    'status': 'INCOMPLETE', 'reason': str(exc)}
        raise
    try:
        info = {'sfreq': float(raw.info['sfreq']), 'n_times': int(raw.n_times),
                'n_channels': int(len(raw.ch_names)), 'status': bundle.status}
    finally:
        raw.close()
    if bundle.status not in {'READY', 'NEEDS_REVIEW'}:
        raise ValueError(f'Recording intake status is {bundle.status}.')
    return info


def _scan_fdt(signal: Path) -> str | None:
    """Return the .fdt filename only when this .set file itself contains that name."""
    if not signal.name.lower().endswith('.set'):
        return None
    named = signal.name[:-4] + '.fdt'
    needles = [named.encode('ascii', errors='ignore'), named.encode('utf-16le'), named.encode('utf-16be')]
    needles = [item for item in needles if item]
    width = max(len(item) for item in needles)
    previous = b''
    with signal.open('rb') as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            window = previous + block
            if any(needle in window for needle in needles):
                return named
            previous = window[-width:]
    # A small header can name a non-stem companion. Large embedded sets are not regex-scanned;
    # random binary matches would invent a companion that does not exist.
    if signal.stat().st_size <= 2_000_000:
        return referenced_fdt(signal.name, signal.read_bytes())
    return None


def _load_shelf_set(root: Path, signal: Path) -> dict:
    from neurobuddy_v2.intake import discover, load_eeg
    bundles = discover(root)
    bundle = next((item for item in bundles if item.signal.resolve() == signal.resolve()), None)
    if bundle is None or bundle.companion is None:
        raise HTTPException(422, f'{signal.name} still has no .fdt beside it.')
    try:
        raw = load_eeg(bundle)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        if bundle.status == 'INCOMPLETE':
            raise HTTPException(422, f'{signal.name} is still incomplete after the .fdt was added.')
        return {'status': bundle.status, 'sfreq': float(raw.info['sfreq']),
                'n_times': int(raw.n_times), 'n_channels': int(len(raw.ch_names))}
    finally:
        raw.close()


def _note_loaded(base, shelf_id: str, loaded: dict):
    text = f"intake {loaded['status']}; {loaded['n_channels']} channels @ {loaded['sfreq']} Hz"
    with base.LOCK, base.database() as db:
        row = db.execute('SELECT dataset_ref FROM recordings WHERE id=?', (shelf_id,)).fetchone()
        if row is None or not row['dataset_ref']:
            return
        try:
            ref = json.loads(row['dataset_ref'])
        except (TypeError, ValueError):
            return
        if not isinstance(ref, dict):
            return
        ref['validation'] = text
        db.execute('UPDATE recordings SET dataset_ref=? WHERE id=?', (json.dumps(ref), shelf_id))


def _commit(base, row, manifest, chosen, staging: Path, task: str, validation: dict):
    with base.LOCK, base.database() as db:
        shelf = base.must_get(db, 'recordings', row['shelf_id'])
        existing = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (row['shelf_id'],))]
        if any(is_signal_name(name) for name in existing):
            raise ValueError('This EEG shelf already has a signal. The download was not saved over it.')
        root = base.recording_path(shelf)
        root.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for item in chosen:
                source = _contained(staging, item['path'])
                target = _contained(root, item['path'])
                if target.exists():
                    raise ValueError(f"{item['filename']} is already in this EEG shelf.")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append(item['path'])
                db.execute('INSERT INTO recording_files VALUES(?,?,?,?)', (str(uuid4()), row['shelf_id'], item['path'], target.stat().st_size))
            signal = next(item['path'] for item in chosen if item['role'] == 'signal')
            provenance = {'provider': 'openneuro', 'dataset_id': manifest.dataset_id, 'snapshot': manifest.snapshot,
                          'dataset_name': manifest.dataset_name, 'primary_path': signal, 'imported_at': base.now(),
                          'task_selected': row['task_type'], 'task_detected': manifest.task_detected,
                          'validation': f"intake {validation['status']}; {validation['n_channels']} channels @ {validation['sfreq']} Hz",
                          'files': [{k: item.get(k) for k in ('path', 'file_id', 'size', 'sha256', 'role', 'category', 'reason')} for item in chosen],
                          'warnings': manifest.warnings, 'evidence': manifest.task_evidence}
            db.execute('UPDATE recordings SET source_name=?, origin=?, dataset_ref=?, task_type=? WHERE id=?',
                       (signal, 'openneuro', json.dumps(provenance), task, row['shelf_id']))
        except Exception:
            db.rollback()
            for relative in moved:
                _contained(root, relative).unlink(missing_ok=True)
            raise


def _guard_destination(base, body, manifest, enqueue: bool):
    with base.database() as db:
        if body.shelf_id:
            shelf = base.must_get(db, 'recordings', body.shelf_id)
            athlete = base.must_get(db, 'athletes', shelf['athlete_id'])
            if body.athlete_id and body.athlete_id != shelf['athlete_id']:
                raise HTTPException(422, 'The selected shelf does not belong to this athlete.')
            if shelf['task_type'] != body.task_type:
                raise HTTPException(409, f"This shelf is {shelf['task_type']}. The open selector is {body.task_type}. Open the shelf so they match before importing.")
            if shelf['classification'] != body.classification:
                raise HTTPException(409, 'The shelf File Type does not match the selected Baseline or Testing value.')
            names = [r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?', (shelf['id'],))]
            if any(is_signal_name(name) for name in names):
                raise HTTPException(409, 'This EEG shelf already has a signal. Remove it or choose another shelf.')
            _reject_active(db, shelf['id'], None, manifest)
            return shelf['id'], False
        if not body.athlete_id:
            raise HTTPException(422, 'Choose an athlete or an EEG shelf for the import.')
        base.must_get(db, 'athletes', body.athlete_id)
        _reject_active(db, None, body.athlete_id, manifest)
        if not enqueue:
            return None, False
        key = str(uuid4())
        db.execute('INSERT INTO recordings(id,athlete_id,classification,source_name,directory,created_at,task_type,origin) VALUES(?,?,?,?,?,?,?,?)',
                   (key, body.athlete_id, body.classification, '', key, base.now(), body.task_type, 'openneuro'))
        return key, True


def _reject_active(db, shelf_id, athlete_id, manifest):
    row = db.execute("""SELECT id FROM import_jobs WHERE status IN ('queued','running') AND dataset_id=? AND snapshot=? AND signal_path=?
                        AND ((? IS NOT NULL AND shelf_id=?) OR (? IS NOT NULL AND athlete_id=?))""",
                     (manifest.dataset_id, manifest.snapshot, manifest.signal_path, shelf_id, shelf_id, athlete_id, athlete_id)).fetchone()
    if row:
        raise HTTPException(409, 'An import of this recording is already running.')


def _ensure_table(base):
    with base.LOCK, base.database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS import_jobs (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, provider TEXT NOT NULL, dataset_id TEXT NOT NULL,
            snapshot TEXT NOT NULL, signal_path TEXT NOT NULL, shelf_id TEXT, athlete_id TEXT,
            created_shelf INTEGER NOT NULL DEFAULT 0, task_type TEXT NOT NULL, classification TEXT NOT NULL,
            acknowledge_review INTEGER NOT NULL DEFAULT 0, adopt_detected_task INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, manifest TEXT, progress TEXT, error TEXT, result TEXT)''')


def _initial_progress(manifest) -> dict:
    files = []
    for item in manifest.files:
        if not item.get('selected'):
            continue
        files.append({'path': item['path'], 'filename': item['filename'], 'role': item['role'],
                      'category': item['category'], 'reason': item['reason'], 'status': 'pending',
                      'bytes': 0, 'size': item.get('size')})
    total = sum(int(item['size']) for item in files if isinstance(item.get('size'), int) and item['size'] > 0)
    return {'phase': 'queued', 'bytes_done': 0, 'bytes_total': total, 'files': files,
            'validated': False, 'saved': False, 'summary': manifest.summary, 'warnings': manifest.warnings,
            'task_detected': manifest.task_detected, 'task_selected': manifest.task_selected}


def _mark_file(progress, path, status, amount=None):
    for item in progress['files']:
        if item['path'] == path:
            item['status'] = status
            if amount is not None:
                item['bytes'] = amount


_LAST_WRITE: dict[str, float] = {}


def _save_progress(base, job_id: str, progress: dict, done: dict, throttle: bool = False, force: bool = False):
    now = time.monotonic()
    if throttle and not force and now - _LAST_WRITE.get(job_id, 0) < 0.35:
        return
    _LAST_WRITE[job_id] = now
    progress['bytes_done'] = sum(done.values()) if done else progress.get('bytes_done') or 0
    with base.LOCK, base.database() as db:
        current = db.execute('SELECT status FROM import_jobs WHERE id=?', (job_id,)).fetchone()
        if current and current['status'] == 'cancelled':
            return
        db.execute('UPDATE import_jobs SET progress=?, updated_at=? WHERE id=?', (json.dumps(progress), base.now(), job_id))


def _public_job(base, job_id: str) -> dict:
    with base.database() as db:
        row = _must_job(db, job_id)
        athlete_name = shelf_label = None
        if row['shelf_id']:
            shelf = db.execute('SELECT classification, athlete_id FROM recordings WHERE id=?', (row['shelf_id'],)).fetchone()
            if shelf:
                shelf_label = shelf['classification']
                athlete = db.execute('SELECT name FROM athletes WHERE id=?', (shelf['athlete_id'],)).fetchone()
                athlete_name = athlete['name'] if athlete else None
    progress = json.loads(row['progress']) if row['progress'] else {}
    total = progress.get('bytes_total') or 0
    done = progress.get('bytes_done') or 0
    progress['percent'] = round(100.0 * done / total, 1) if total else None
    manifest = json.loads(row['manifest']) if row['manifest'] else None
    return {'id': row['id'], 'status': row['status'], 'provider': row['provider'], 'dataset_id': row['dataset_id'],
            'snapshot': row['snapshot'], 'signal_path': row['signal_path'], 'shelf_id': row['shelf_id'],
            'athlete_id': row['athlete_id'], 'athlete_name': athlete_name, 'classification': row['classification'],
            'shelf_label': shelf_label, 'task_type': row['task_type'], 'error': row['error'], 'progress': progress,
            'manifest': manifest, 'result': json.loads(row['result']) if row['result'] else None}


def _cleanup_failure(base, job_id: str, row, message: str, delete_staging: bool = True):
    if delete_staging:
        shutil.rmtree(_job_dir(base, job_id), ignore_errors=True)
    if row.get('created_shelf') and row.get('shelf_id'):
        _drop_empty_shelf(base, row['shelf_id'])
    with base.LOCK, base.database() as db:
        db.execute("UPDATE import_jobs SET status=?, error=?, updated_at=? WHERE id=? AND status!='completed'",
                   ('cancelled' if 'cancelled' in message.lower() else 'failed', message[:1600], base.now(), job_id))


def _ensure_shelf(base, row) -> str:
    with base.LOCK, base.database() as db:
        if row.get('shelf_id'):
            found = db.execute('SELECT id FROM recordings WHERE id=?', (row['shelf_id'],)).fetchone()
            if found:
                return row['shelf_id']
            if not row.get('created_shelf'):
                raise HTTPException(404, 'The destination EEG shelf no longer exists.')
        elif not row.get('athlete_id'):
            raise HTTPException(422, 'Import has no destination athlete or shelf.')
        key = str(uuid4())
        db.execute('INSERT INTO recordings(id,athlete_id,classification,source_name,directory,created_at,task_type,origin) VALUES(?,?,?,?,?,?,?,?)',
                   (key, row['athlete_id'], row['classification'], '', key, base.now(), row['task_type'], 'openneuro'))
        db.execute('UPDATE import_jobs SET shelf_id=?, created_shelf=1 WHERE id=?', (key, row['id']))
        return key


def _drop_empty_shelf(base, shelf_id: str | None):
    if not shelf_id:
        return
    with base.LOCK, base.database() as db:
        shelf = db.execute('SELECT * FROM recordings WHERE id=?', (shelf_id,)).fetchone()
        if shelf is None:
            return
        count = db.execute('SELECT COUNT(*) AS n FROM recording_files WHERE recording_id=?', (shelf_id,)).fetchone()['n']
        if count:
            return
        db.execute('DELETE FROM recordings WHERE id=?', (shelf_id,))
        path = base.recording_path(dict(shelf))
    shutil.rmtree(path, ignore_errors=True)


def _fail(job_id: str, message: str):
    base = STATE['base']
    row = _fetch(base, job_id)
    if row['status'] == 'completed':
        return
    _cleanup_failure(base, job_id, row, message)


def _cancelled(job_id: str) -> bool:
    event = CANCELS.get(job_id)
    if event and event.is_set():
        return True
    base = STATE['base']
    with base.database() as db:
        row = db.execute('SELECT status FROM import_jobs WHERE id=?', (job_id,)).fetchone()
    return bool(row and row['status'] == 'cancelled')


def _fetch(base, job_id: str) -> dict:
    with base.database() as db:
        return _must_job(db, job_id)


def _must_job(db, job_id: str) -> dict:
    row = db.execute('SELECT * FROM import_jobs WHERE id=?', (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Import job not found.')
    return dict(row)


def _update(base, job_id: str, status: str, phase: str):
    with base.LOCK, base.database() as db:
        row = db.execute('SELECT progress, status FROM import_jobs WHERE id=?', (job_id,)).fetchone()
        if row and row['status'] == 'cancelled':
            return
        progress = json.loads(row['progress']) if row and row['progress'] else {}
        progress['phase'] = phase
        db.execute('UPDATE import_jobs SET status=?, progress=?, updated_at=? WHERE id=?',
                   (status, json.dumps(progress), base.now(), job_id))


def _job_dir(base, job_id: str) -> Path:
    root = (base.STORAGE / 'imports' / job_id).resolve()
    imports = (base.STORAGE / 'imports').resolve()
    if not root.is_relative_to(imports):
        raise ValueError('Unsafe import directory')
    return root


def _staging(base, job_id: str) -> Path:
    return _job_dir(base, job_id) / 'staging'


def _contained(root: Path, relative: str) -> Path:
    parts = relative.split('/')
    if not parts or any(part in {'', '.', '..'} for part in parts):
        raise ValueError('Unsafe recording path')
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Unsafe recording path')
    return path


def _check_disk(directory: Path, total: int):
    free = shutil.disk_usage(directory).free
    if total and free < total + 64 * 1024 * 1024:
        raise HTTPException(507, 'Not enough free disk space for this EEG import.')


def _check_task(task: str):
    if task not in TASKS:
        raise HTTPException(422, 'Test Type must be Oddball, Motor-imagery, Sleep, or Unspecified.')


def _check_class(value: str):
    if value not in {'baseline', 'testing'}:
        raise HTTPException(422, 'File Type must be Baseline or Testing.')


def _error_text(exc: Exception) -> str:
    detail = getattr(exc, 'detail', None)
    if isinstance(detail, str) and detail:
        return detail[:1600]
    text = str(exc).strip() or type(exc).__name__
    return text[:1600]
