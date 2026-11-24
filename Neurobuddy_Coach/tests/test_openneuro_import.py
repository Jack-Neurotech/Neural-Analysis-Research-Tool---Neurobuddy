"""Mocked OpenNeuro browsing, guarded downloads, and shelf import."""
from __future__ import annotations

import asyncio
import importlib
import io
import sys
import time

import httpx
import mne
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.openneuro_connector import OpenNeuroProvider, validate_download_url


def fif_bytes():
    import tempfile
    from pathlib import Path
    info = mne.create_info(['C3', 'C4'], 100, ['eeg', 'eeg'])
    signal = np.vstack([1e-6*np.sin(2*np.pi*10*np.arange(200)/100),
                        1e-6*np.cos(2*np.pi*8*np.arange(200)/100)])
    raw = mne.io.RawArray(signal, info, verbose='ERROR')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'recording.fif'
        raw.save(path, overwrite=True, verbose='ERROR')
        data = path.read_bytes()
    raw.close()
    return data


class FakeProvider:
    name = 'openneuro'

    def __init__(self, blobs, fail_downloads=0, block=False):
        self.blobs = blobs
        self.fail_downloads = fail_downloads
        self.calls = 0
        self.block = block

    async def get_dataset(self, dataset_id):
        if dataset_id == 'ds000000':
            raise HTTPException(404, 'Dataset unavailable or not public.')
        return {'id': dataset_id, 'name': 'Fake P300', 'tag': '1.2.0', 'description': 'Fake',
                'doi': '10.example', 'tags': ['1.2.0', '1.1.0'], 'provider': self.name}

    async def walk(self, dataset_id, version, relative_path):
        if version not in {'1.2.0', '1.1.0'}:
            raise HTTPException(404, 'Public snapshot not available.')
        signal = 'sub-01/eeg/sub-01_task-P300_eeg.fif'
        events = 'sub-01/eeg/sub-01_task-P300_events.tsv'
        if relative_path not in {signal, events}:
            raise HTTPException(404, f'Snapshot path not found: {relative_path}')
        def item(path, size, directory=False):
            return {'path': path, 'filename': path.rsplit('/', 1)[-1], 'size': size, 'directory': directory,
                    'file_id': 'ab'*20, 'id': 'ab'*20, 'urls': [f'https://s3.amazonaws.com/openneuro.org/{dataset_id}/{path}'],
                    'annexed': not directory}
        directories = {
            '': [item('dataset_description.json', len(self.blobs['dataset_description.json'])),
                 {'path': 'sub-01', 'filename': 'sub-01', 'size': 0, 'directory': True, 'file_id': 'cd'*20, 'id': 'cd'*20, 'urls': []}],
            'sub-01': [{'path': 'sub-01/eeg', 'filename': 'eeg', 'size': 0, 'directory': True, 'file_id': 'ef'*20, 'id': 'ef'*20, 'urls': []}],
            'sub-01/eeg': [
                item(signal, len(self.blobs[signal])),
                item('sub-01/eeg/sub-01_task-P300_events.tsv', len(self.blobs['sub-01/eeg/sub-01_task-P300_events.tsv'])),
                item('sub-01/eeg/sub-02_task-P300_events.tsv', 8),
            ],
        }
        chosen = next(entry for folder in directories.values() for entry in folder if entry.get('path') == relative_path)
        return {'signal': chosen, 'directories': directories}

    async def fetch_small(self, dataset_id, record, limit=1_500_000):
        return self.blobs.get(record['path'], b'')

    async def download_file(self, file_reference, destination, progress=None, cancel=None, expected_size=None, max_bytes=None):
        self.calls += 1
        if self.block:
            for _ in range(40):
                if cancel and cancel():
                    raise HTTPException(409, 'Import cancelled.')
                await asyncio.sleep(0.05)
        if self.fail_downloads:
            self.fail_downloads -= 1
            raise HTTPException(502, 'Download from OpenNeuro failed after retries. The shelf was not changed.')
        payload = self.blobs[file_reference['path']]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        if progress:
            progress(len(payload))
        import hashlib
        return {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'url_host': 's3.amazonaws.com'}


def boot(tmp_path, monkeypatch, provider):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR', str(tmp_path / 'storage'))
    sys.modules.pop('backend.app', None)
    app_module = importlib.import_module('backend.app')
    monkeypatch.setattr('backend.remote_imports.provider_factory', lambda: provider)
    return TestClient(app_module.app), app_module


def library_shelf(client):
    return client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves'][0]


def await_import(client, job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get('/api/v2/import-jobs/' + job_id).json()
        if job['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
            return job
        time.sleep(0.05)
    raise AssertionError('import did not finish')


def seed(client):
    team = client.post('/api/v2/shelf-teams', json={'name': 'Runners'}).json()
    athlete = client.post(f"/api/v2/shelf-teams/{team['id']}/athletes?task_type=oddball", json={'name': 'James'}).json()
    shelves = client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves']
    return athlete['id'], shelves[0]['id']


def blobs():
    signal = 'sub-01/eeg/sub-01_task-P300_eeg.fif'
    return {
        signal: fif_bytes(),
        'sub-01/eeg/sub-01_task-P300_events.tsv': b'onset\tduration\tvalue\n0.1\t0.1\tstandard\n0.4\t0.1\toddball\n',
        'dataset_description.json': b'{"Name":"Fake P300"}',
        'sub-01/eeg/sub-02_task-P300_events.tsv': b'onset\tvalue\n0\ttarget\n',
    }


def test_graphql_uses_id_scalar_and_invalid_accession(tmp_path, monkeypatch):
    client, _ = boot(tmp_path, monkeypatch, FakeProvider(blobs()))
    seen = []

    async def mock_gql(query, variables):
        seen.append(query)
        if 'latestSnapshot' in query:
            return {'dataset': {'id': 'ds000224', 'name': 'Test public EEG', 'latestSnapshot': {'tag': '1.0.3'}}}
        return {'snapshot': {'files': [{'id': 'a'*40, 'filename': 'sub-01', 'size': 0, 'directory': True, 'annexed': False}]}}

    import backend.shelves as shelves
    monkeypatch.setattr(shelves, 'graphql', mock_gql)
    assert client.get('/api/v2/openneuro/ds000224').json()['tag'] == '1.0.3'
    assert 'ID!' in seen[0]
    assert 'String!' not in seen[0]
    tree = client.get('/api/v2/openneuro/ds000224/tree?tag=1.0.3').json()
    assert tree['files'][0]['filename'] == 'sub-01'
    assert 'ID!' in seen[1]
    assert client.get('/api/v2/openneuro/invalid').status_code == 422


def test_download_url_allowlist_and_real_bytes(tmp_path):
    dataset = 'ds003061'
    good = f'https://s3.amazonaws.com/openneuro.org/{dataset}/sub-01/eeg/file.set?versionId=abc'
    assert validate_download_url(good, dataset) == good
    assert validate_download_url(f'https://openneuro.org/crn/datasets/{dataset}/objects/abc?filename=README', dataset)
    with pytest.raises(HTTPException):
        validate_download_url('http://169.254.169.254/latest/meta-data', dataset)
    with pytest.raises(HTTPException):
        validate_download_url('https://s3.amazonaws.com/other-bucket/file.set', dataset)
    with pytest.raises(HTTPException):
        validate_download_url('https://evil.example/openneuro.org/ds003061/file.set', dataset)

    payload = b'eeg-bytes'
    def handler(request: httpx.Request):
        if request.url.host == 'evil.example':
            raise AssertionError('SSRF host was contacted')
        if request.headers.get('x-test') == 'redirect':
            return httpx.Response(302, headers={'location': 'https://evil.example/secret'})
        assert request.url.host == 's3.amazonaws.com'
        return httpx.Response(200, content=payload, headers={'Content-Length': str(len(payload))})

    provider = OpenNeuroProvider(transport=httpx.MockTransport(handler), retry_backoff=0)
    record = {'dataset_id': dataset, 'filename': 'file.set', 'urls': [good], 'size': len(payload)}
    destination = tmp_path / 'file.set'
    result = asyncio.run(provider.download_file(record, destination, expected_size=len(payload)))
    assert destination.read_bytes() == payload
    assert result['bytes'] == len(payload)
    redirected = dict(record, urls=['https://s3.amazonaws.com/openneuro.org/ds003061/redirect'])
    # The mock keys off a header the client does not send; use a dedicated URL instead.
    def redirect_handler(request: httpx.Request):
        if 'redirect-me' in str(request.url):
            return httpx.Response(302, headers={'location': 'https://evil.example/secret'})
        return httpx.Response(200, content=payload)
    provider = OpenNeuroProvider(transport=httpx.MockTransport(redirect_handler), retry_backoff=0)
    with pytest.raises(HTTPException):
        asyncio.run(provider.download_file({'dataset_id': dataset, 'filename': 'file.set', 'urls': [
            'https://s3.amazonaws.com/openneuro.org/ds003061/redirect-me']}, tmp_path / 'nope.set'))


def test_provider_walks_nested_directories(monkeypatch):
    calls = []

    async def fake_graphql(query, variables, client=None):
        calls.append(variables)
        if 'latestSnapshot' in query:
            return {'dataset': {'id': 'ds003061', 'name': 'P300', 'latestSnapshot': {'tag': '1.1.2', 'description': {'Name': 'Oddball'}},
                                'snapshots': [{'tag': '1.1.2'}]}}
        tree = variables.get('tree')
        if tree is None:
            return {'snapshot': {'files': [{'id': '1'*40, 'filename': 'sub-01', 'size': 0, 'directory': True, 'annexed': False, 'urls': []}]}}
        if tree == '1'*40:
            return {'snapshot': {'files': [{'id': '2'*40, 'filename': 'eeg', 'size': 0, 'directory': True, 'annexed': False, 'urls': []}]}}
        return {'snapshot': {'files': [{'id': '3'*40, 'filename': 'sub-01_task-P300_eeg.set', 'size': 4,
                                       'directory': False, 'annexed': True,
                                       'urls': ['https://s3.amazonaws.com/openneuro.org/ds003061/sub-01/eeg/sub-01_task-P300_eeg.set']}]}}

    monkeypatch.setattr('backend.openneuro_connector.graphql', fake_graphql)
    provider = OpenNeuroProvider()
    walked = asyncio.run(provider.walk('ds003061', '1.1.2', 'sub-01/eeg/sub-01_task-P300_eeg.set'))
    assert walked['signal']['filename'] == 'sub-01_task-P300_eeg.set'
    assert '' in walked['directories'] and 'sub-01/eeg' in walked['directories']
    assert len(calls) >= 3


def test_import_saves_bundle_and_pipeline_reads_it(tmp_path, monkeypatch):
    provider = FakeProvider(blobs())
    client, _ = boot(tmp_path, monkeypatch, provider)
    athlete, shelf = seed(client)
    body = {'dataset_id': 'ds003061', 'tag': '1.2.0', 'path': 'sub-01/eeg/sub-01_task-P300_eeg.fif',
            'task_type': 'oddball', 'classification': 'baseline', 'shelf_id': shelf, 'athlete_id': athlete}
    resolved = client.post('/api/v2/openneuro/resolve-recording', json=body)
    assert resolved.status_code == 200, resolved.text
    manifest = resolved.json()
    assert manifest['status'] == 'ready'
    names = {item['filename'] for item in manifest['files'] if item['selected']}
    assert 'sub-01_task-P300_events.tsv' in names
    assert 'sub-02_task-P300_events.tsv' not in names
    assert 'urls' not in manifest['files'][0]
    started = client.post('/api/v2/openneuro/import-recording', json=body)
    assert started.status_code == 202, started.text
    job = await_import(client, started.json()['id'])
    assert job['status'] == 'completed', job.get('error')
    assert job['progress']['percent'] == 100.0
    assert job['progress']['saved'] is True
    shelf_row = library_shelf(client)
    assert shelf_row['ready']
    assert shelf_row['origin'] == 'openneuro'
    assert shelf_row['source']['dataset_id'] == 'ds003061'
    assert shelf_row['source']['snapshot'] == '1.2.0'
    stored = {item['name'] for item in shelf_row['files']}
    assert stored == {'sub-01/eeg/sub-01_task-P300_eeg.fif'}
    saved = client.post('/api/v2/openneuro/save-tsv', json={
        'dataset_id': 'ds003061', 'tag': '1.2.0', 'shelf_id': shelf,
        'path': 'sub-01/eeg/sub-01_task-P300_events.tsv'})
    assert saved.status_code == 201, saved.text
    stored = {item['name'] for item in library_shelf(client)['files']}
    assert stored == {'sub-01/eeg/sub-01_task-P300_eeg.fif', 'sub-01/eeg/sub-01_task-P300_events.tsv'}
    not_tsv = client.post('/api/v2/openneuro/save-tsv', json={
        'dataset_id': 'ds003061', 'tag': '1.2.0', 'shelf_id': shelf,
        'path': 'sub-01/eeg/sub-01_task-P300_eeg.fif'})
    assert not_tsv.status_code == 422
    other = client.post('/api/v2/openneuro/save-tsv', json={
        'dataset_id': 'ds003061', 'tag': '1.2.0', 'shelf_id': shelf,
        'path': 'sub-01/eeg/sub-02_task-P300_events.tsv'})
    assert other.status_code == 404
    stored = {item['name'] for item in library_shelf(client)['files']}
    assert 'sub-01/eeg/sub-02_task-P300_events.tsv' not in stored
    again = client.post('/api/v2/openneuro/import-recording', json=body)
    assert again.status_code == 409
    finished = client.post('/api/v2/shelf-jobs', json={'mode': 'single', 'target_id': shelf, 'task_type': 'oddball'})
    assert finished.status_code == 202, finished.text
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = client.get('/api/v2/jobs/' + finished.json()['id']).json()
        if result['status'] in {'completed', 'failed'}:
            break
        time.sleep(0.2)
    assert result['status'] == 'completed', result.get('error')
    assert client.get('/api/v2/artifacts/' + finished.json()['id'] + '/report.html').status_code == 200


def test_failed_download_does_not_mark_shelf_ready_and_retry_works(tmp_path, monkeypatch):
    provider = FakeProvider(blobs(), fail_downloads=1)
    client, _ = boot(tmp_path, monkeypatch, provider)
    _, shelf = seed(client)
    body = {'dataset_id': 'ds003061', 'tag': '1.2.0', 'path': 'sub-01/eeg/sub-01_task-P300_eeg.fif',
            'task_type': 'unspecified', 'classification': 'baseline', 'shelf_id': shelf}
    # unspecified still resolves the oddball-labeled file as compatible.
    client.patch(f'/api/v2/shelves/{shelf}', json={'task_type': 'unspecified'})
    started = client.post('/api/v2/openneuro/import-recording', json=body)
    assert started.status_code == 202, started.text
    failed = await_import(client, started.json()['id'])
    assert failed['status'] == 'failed'
    assert library_shelf(client)['ready'] is False
    retried = client.post(f"/api/v2/import-jobs/{started.json()['id']}/retry")
    assert retried.status_code == 202, retried.text
    done = await_import(client, started.json()['id'])
    assert done['status'] == 'completed', done.get('error')
    assert library_shelf(client)['ready'] is True


def test_cancel_cleans_up_and_restart_marks_job_interrupted(tmp_path, monkeypatch):
    provider = FakeProvider(blobs(), block=True)
    client, app_module = boot(tmp_path, monkeypatch, provider)
    athlete, _ = seed(client)
    body = {'dataset_id': 'ds003061', 'path': 'sub-01/eeg/sub-01_task-P300_eeg.fif',
            'task_type': 'oddball', 'classification': 'testing', 'athlete_id': athlete}
    # Omit tag so the locked snapshot is the provider's latest, then send it back.
    resolved = client.post('/api/v2/openneuro/resolve-recording', json=body)
    assert resolved.status_code == 200, resolved.text
    body['tag'] = resolved.json()['snapshot']
    started = client.post('/api/v2/openneuro/import-recording', json=body)
    assert started.status_code == 202, started.text
    job_id = started.json()['id']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if client.get('/api/v2/import-jobs/' + job_id).json()['status'] == 'running':
            break
        time.sleep(0.05)
    assert client.post('/api/v2/import-jobs/' + job_id + '/cancel').status_code == 200
    cancelled = await_import(client, job_id)
    assert cancelled['status'] == 'cancelled'
    shelves = client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves']
    assert not any(item['ready'] for item in shelves)
    # A job left running is interrupted when the process starts again. The cancelled shelf was removed.
    import sqlite3
    db_path = tmp_path / 'storage' / 'coach.sqlite3'
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO import_jobs(id,status,provider,dataset_id,snapshot,signal_path,shelf_id,athlete_id,created_shelf,task_type,classification,acknowledge_review,adopt_detected_task,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ('job-left', 'running', 'openneuro', 'ds003061', '1.2.0', 'sub-01/eeg/x.set', None, athlete, 0, 'oddball', 'baseline', 0, 0, 't', 't'))
    db.commit(); db.close()
    sys.modules.pop('backend.app', None)
    reloaded = importlib.import_module('backend.app')
    restarted = TestClient(reloaded.app)
    assert restarted.get('/api/v2/import-jobs/job-left').json()['status'] == 'interrupted'


def test_tsv_opens_without_a_separate_download(tmp_path, monkeypatch):
    client, _ = boot(tmp_path, monkeypatch, FakeProvider(blobs()))
    opened = client.get('/api/v2/openneuro/ds003061/file', params={
        'tag': '1.2.0', 'path': 'sub-01/eeg/sub-01_task-P300_events.tsv'})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert 'onset' in body['text'] and 'standard' in body['text'] and 'oddball' in body['text']
    assert body['truncated'] is False
    assert 'urls' not in body
    signal = client.get('/api/v2/openneuro/ds003061/file', params={
        'tag': '1.2.0', 'path': 'sub-01/eeg/sub-01_task-P300_eeg.fif'})
    assert signal.status_code == 422
    missing = client.get('/api/v2/openneuro/ds003061/file', params={
        'tag': '1.2.0', 'path': 'sub-01/eeg/sub-02_task-P300_events.tsv'})
    assert missing.status_code == 404
    traversal = client.get('/api/v2/openneuro/ds003061/file', params={'tag': '1.2.0', 'path': '../secret.tsv'})
    assert traversal.status_code == 422


def test_nonfinite_pipeline_values_can_be_stored():
    from backend.shelves import json_safe
    import json
    stored = json.dumps(json_safe({'metric': float('nan'), 'band': [1.0, float('inf')]}), allow_nan=False)
    assert json.loads(stored) == {'metric': None, 'band': [1.0, None]}


def test_motor_labels_come_from_the_events_tsv_only(tmp_path, monkeypatch):
    from backend.motor_labels import motor_subtype_from_events
    assert motor_subtype_from_events('onset\tvalue\n0\tTASK4T0\n1\tTASK4T1\n2\tTASK4T2\n') == 'imagery'
    assert motor_subtype_from_events('onset\tvalue\n0\tTASK2T1\n1\tTASK2T0\n') == 'imagery'
    assert motor_subtype_from_events('onset\tvalue\n0\tTASK1T1\n1\tTASK1T2\n') == 'execution'
    assert motor_subtype_from_events('onset\ttrial_type\n0\tTASK3T2\n1\tTASK3T0\n') == 'execution'
    assert motor_subtype_from_events('onset\ttrial_type\n0\tmotor_imagery\n1\trest\n') == 'imagery'
    assert motor_subtype_from_events('onset\tvalue\n0\tstandard\n1\toddball\n') is None
    assert motor_subtype_from_events('onset\tvalue\n0\tTASK1T1\n1\tTASK2T1\n') is None
    assert motor_subtype_from_events('onset\tvalue\n0\tTASK1T0\n1\tTASK4T0\n') is None

    class MotorProvider:
        def __init__(self):
            self.fetched = []
            self.downloaded = []
            eeg = '22' * 20
            self.trees = {
                '': [{'id': '11' * 20, 'filename': 'sub-001', 'size': 0, 'directory': True, 'annexed': False, 'urls': []}],
                '11' * 20: [{'id': eeg, 'filename': 'eeg', 'size': 0, 'directory': True, 'annexed': False, 'urls': []}],
                eeg: [
                    self._file('sub-001_task-motion_run-10_eeg.set', 5000),
                    self._file('sub-001_task-motion_run-10_events.tsv', 40),
                    self._file('sub-001_task-motion_run-11_eeg.set', 5000),
                    self._file('sub-001_task-motion_run-11_events.tsv', 40),
                    self._file('sub-001_task-motion_run-12_eeg.set', 5000),
                    self._file('sub-001_task-motion_run-12_events.tsv', 40),
                    self._file('sub-001_task-motion_run-13_eeg.set', 5000),
                    self._file('sub-001_task-motion_run-13_events.tsv', 40),
                    self._file('sub-001_task-motion_run-11_channels.tsv', 20),
                    self._file('sub-001_task-P300_eeg.set', 5000),
                    self._file('sub-001_task-P300_events.tsv', 30),
                ],
            }
            self.texts = {
                'sub-001/eeg/sub-001_task-motion_run-10_events.tsv': b'onset\tvalue\n0\tTASK4T1\n',
                'sub-001/eeg/sub-001_task-motion_run-11_events.tsv': b'onset\tvalue\n0\tTASK1T2\n',
                'sub-001/eeg/sub-001_task-motion_run-12_events.tsv': b'onset\ttrial_type\n0\tTASK2T1\n',
                'sub-001/eeg/sub-001_task-motion_run-13_events.tsv': b'onset\tvalue\n0\tTASK3T1\n',
                'sub-001/eeg/sub-001_task-P300_events.tsv': b'onset\tvalue\n0\tstandard\n1\toddball\n',
            }

        @staticmethod
        def _file(name, size):
            return {'id': 'ab' * 20, 'filename': name, 'size': size, 'directory': False, 'annexed': True,
                    'urls': ['https://s3.amazonaws.com/openneuro.org/ds004362/sub-001/eeg/' + name]}

        async def get_dataset(self, dataset_id):
            return {'id': dataset_id, 'name': 'EEGMMI', 'tag': '1.0.1', 'tags': ['1.0.1'], 'provider': 'openneuro'}

        async def list_directory(self, dataset_id, version, directory_id=None, refresh=False):
            return [dict(item) for item in self.trees[directory_id or '']]

        async def fetch_small(self, dataset_id, record, limit=1_500_000):
            self.fetched.append(record['path'])
            return self.texts[record['path']]

        async def download_file(self, *args, **kwargs):
            self.downloaded.append(args)
            raise AssertionError('motor labels must not download the EEG')

    provider = MotorProvider()
    client, _ = boot(tmp_path, monkeypatch, provider)
    listed = client.get('/api/v2/openneuro/ds004362/motor-labels', params={'tag': '1.0.1', 'path': 'sub-001/eeg'})
    assert listed.status_code == 200, listed.text
    labels = {item['filename']: item['label'] for item in listed.json()['labels']}
    assert labels == {
        'sub-001_task-motion_run-10_events.tsv': 'imagery',
        'sub-001_task-motion_run-11_events.tsv': 'execution',
        'sub-001_task-motion_run-12_events.tsv': 'imagery',
        'sub-001_task-motion_run-13_events.tsv': 'execution',
    }
    assert all(name.endswith('_events.tsv') for name in labels)
    assert not any(name.endswith(('.set', '_channels.tsv', '_electrodes.tsv')) for name in labels)
    assert all(path.endswith('_events.tsv') for path in provider.fetched)
    assert 'sub-001/eeg/sub-001_task-P300_events.tsv' not in provider.fetched
    assert provider.downloaded == []
    assert 'urls' not in listed.text
    escaped = client.get('/api/v2/openneuro/ds004362/motor-labels', params={'tag': '1.0.1', 'path': '../secret'})
    assert escaped.status_code == 422


def test_sleep_correspondence_labels_the_matching_scoring_tsv_only(tmp_path, monkeypatch):
    class SleepProvider:
        def __init__(self):
            self.downloaded = []
            self.fetched = []
            self.files = [
                'sub-001_ses-001_task-sleep_acq-PSG_eeg.set',
                'sub-001_ses-001_task-sleep_acq-scoring_events.tsv',
                'sub-001_ses-001_task-sleep_acq-PSGtrigger_events.tsv',
                'sub-001_ses-001_task-sleep_acq-PSG_channels.tsv',
                'sub-001_ses-001_task-sleep_acq-PSG_electrodes.tsv',
                'sub-001_ses-001_task-sleep_acq-earEEG_eeg.set',
                'sub-001_ses-001_task-sleep_acq-earEEGtrigger_events.tsv',
                'sub-001_ses-001_task-sleep_acq-earEEGRecordingFailures_events.tsv',
                'sub-001_ses-001_task-sleep_acq-earEEG_channels.tsv',
                'sub-001_ses-002_task-sleep_acq-PSG_eeg.set',
                'sub-001_ses-002_task-sleep_acq-scoring_events.tsv',
                'sub-001_ses-002_task-sleep_acq-earEEGtrigger_events.tsv',
            ]

        async def get_dataset(self, dataset_id):
            return {'id': dataset_id, 'name': 'EESM23', 'tag': '1.0.0', 'tags': ['1.0.0'], 'provider': 'openneuro'}

        async def list_directory(self, dataset_id, version, directory_id=None, refresh=False):
            return [{'id': 'cd' * 20, 'filename': name, 'size': 40, 'directory': False, 'annexed': False,
                     'urls': ['https://s3.amazonaws.com/openneuro.org/ds005178/' + name]} for name in self.files]

        async def fetch_small(self, dataset_id, record, limit=1_500_000):
            self.fetched.append(record['path'])
            return b'onset\tscoring\n0\tWake\n'

        async def download_file(self, *args, **kwargs):
            self.downloaded.append(args)
            raise AssertionError('correspondence labels must not download the EEG')

    provider = SleepProvider()
    client, _ = boot(tmp_path, monkeypatch, provider)
    listed = client.get('/api/v2/openneuro/ds005178/sleep-correspondence', params={'tag': '1.0.0', 'path': ''})
    assert listed.status_code == 200, listed.text
    labels = {item['filename']: item for item in listed.json()['labels']}
    assert labels['sub-001_ses-001_task-sleep_acq-scoring_events.tsv']['label'] == 'Corresponding'
    assert labels['sub-001_ses-001_task-sleep_acq-scoring_events.tsv']['signal'].endswith('sub-001_ses-001_task-sleep_acq-PSG_eeg.set')
    assert labels['sub-001_ses-001_task-sleep_acq-PSGtrigger_events.tsv']['signal'].endswith('sub-001_ses-001_task-sleep_acq-PSG_eeg.set')
    assert labels['sub-001_ses-002_task-sleep_acq-scoring_events.tsv']['signal'].endswith('sub-001_ses-002_task-sleep_acq-PSG_eeg.set')
    assert labels['sub-001_ses-001_task-sleep_acq-earEEGtrigger_events.tsv']['signal'].endswith('sub-001_ses-001_task-sleep_acq-earEEG_eeg.set')
    assert labels['sub-001_ses-001_task-sleep_acq-earEEGRecordingFailures_events.tsv']['signal'].endswith('sub-001_ses-001_task-sleep_acq-earEEG_eeg.set')
    assert 'sub-001_ses-002_task-sleep_acq-earEEGtrigger_events.tsv' not in labels
    for name, item in labels.items():
        signal = item['signal']
        if 'earEEG' in name:
            assert 'acq-earEEG_eeg.set' in signal
        if 'PSG' in name or 'scoring' in name:
            assert 'acq-PSG_eeg.set' in signal
            assert 'earEEG' not in signal
    assert not any(name.endswith(('.set', '_channels.tsv', '_electrodes.tsv')) for name in labels)
    assert provider.downloaded == []
    assert provider.fetched == []
    escaped = client.get('/api/v2/openneuro/ds005178/sleep-correspondence', params={'tag': '1.0.0', 'path': '../secret'})
    assert escaped.status_code == 422


def test_missing_fdt_keeps_the_downloaded_set(tmp_path):
    import hashlib
    from scipy.io import savemat
    from backend.remote_imports import _validate_bundle
    name = 'sub-001_ses-001_task-sleep_acq-PSG_eeg.set'
    eeg = tmp_path / name
    savemat(eeg, {'EEG': {'setname': 'external', 'nbchan': 1, 'trials': 1, 'pnts': 10,
                          'srate': 100, 'xmin': 0.0, 'xmax': 0.09,
                          'data': 'sub-001_ses-001_task-sleep_acq-PSG_eeg.fdt',
                          'chanlocs': np.array([{'labels': 'C3'}], dtype=object),
                          'event': np.array([], dtype=object),
                          'urevent': np.array([], dtype=object)}})
    chosen = [{'path': name, 'filename': name,
               'sha256': hashlib.sha256(eeg.read_bytes()).hexdigest()}]
    info = _validate_bundle(tmp_path, chosen)
    assert info['status'] == 'INCOMPLETE'
    assert 'fdt' in info['reason'].lower()
    assert eeg.is_file()


def test_named_fdt_is_added_beside_the_set_and_loads(tmp_path, monkeypatch):
    import hashlib
    import sqlite3
    from scipy.io import savemat
    name = 'sub-001_ses-001_task-sleep_acq-PSG_eeg'
    rel_set = f'sub-001/ses-001/eeg/{name}.set'
    rel_fdt = f'sub-001/ses-001/eeg/{name}.fdt'
    other = 'sub-001/ses-001/eeg/sub-001_ses-001_task-ASSR_acq-PSG_eeg.fdt'
    samples, channels, rate = 64, 2, 100

    class Provider:
        name = 'openneuro'
        downloaded = []

        def __init__(self):
            self.blobs = {rel_fdt: b'\x00' * (samples * channels * 4), other: b'\x00' * 32}

        async def get_dataset(self, dataset_id):
            return {'id': dataset_id, 'name': 'EESM19', 'tag': '1.0.2', 'tags': ['1.0.2'],
                    'description': '', 'doi': '', 'provider': self.name}

        async def walk(self, dataset_id, version, relative_path):
            if relative_path not in self.blobs:
                raise HTTPException(404, f'Snapshot path not found: {relative_path}')
            item = {'path': relative_path, 'filename': relative_path.rsplit('/', 1)[-1],
                    'size': len(self.blobs[relative_path]), 'directory': False, 'file_id': 'ab' * 20,
                    'id': 'ab' * 20, 'annexed': True,
                    'urls': [f'https://s3.amazonaws.com/openneuro.org/{dataset_id}/{relative_path}']}
            return {'signal': item, 'directories': {'sub-001/ses-001/eeg': [item]}}

        async def download_file(self, file_reference, destination, progress=None, cancel=None,
                                 expected_size=None, max_bytes=None):
            self.downloaded.append(file_reference['path'])
            payload = self.blobs[file_reference['path']]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            return {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'url_host': 's3.amazonaws.com'}

        async def fetch_small(self, dataset_id, record, limit=1_500_000):
            return b''

    provider = Provider()
    client, app = boot(tmp_path, monkeypatch, provider)
    _, shelf = seed(client)
    folder = app.FILES / shelf / 'sub-001' / 'ses-001' / 'eeg'
    folder.mkdir(parents=True)
    eeg = folder / f'{name}.set'
    savemat(eeg, {'EEG': {'setname': 'external', 'nbchan': channels, 'trials': 1, 'pnts': samples,
                          'srate': rate, 'xmin': 0.0, 'xmax': (samples - 1) / rate,
                          'data': f'{name}.fdt',
                          'chanlocs': np.array([{'labels': 'C3'}, {'labels': 'C4'}], dtype=object),
                          'event': np.array([], dtype=object), 'urevent': np.array([], dtype=object)}})
    with sqlite3.connect(app.DB_PATH) as db:
        db.execute('INSERT INTO recording_files VALUES(?,?,?,?)', ('set-file', shelf, rel_set, eeg.stat().st_size))
        db.execute('UPDATE recordings SET source_name=?, dataset_ref=? WHERE id=?', (
            rel_set, '{"provider":"openneuro","dataset_id":"ds005185","snapshot":"1.0.2","validation":"intake INCOMPLETE; None channels @ None Hz"}', shelf))
    saved = client.post('/api/v2/openneuro/save-fdt', json={
        'dataset_id': 'ds005185', 'tag': '1.0.2', 'shelf_id': shelf, 'path': rel_fdt})
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body['saved'] == rel_fdt
    assert body['status'] == 'READY'
    assert 'INCOMPLETE' not in body['status']
    assert (folder / f'{name}.fdt').is_file()
    assert provider.downloaded == [rel_fdt]
    shelf_row = library_shelf(client)
    assert {item['name'] for item in shelf_row['files']} == {rel_set, rel_fdt}
    assert shelf_row['source']['validation'].startswith('intake READY;')
    rejected = client.post('/api/v2/openneuro/save-fdt', json={
        'dataset_id': 'ds005185', 'tag': '1.0.2', 'shelf_id': shelf, 'path': other})
    assert rejected.status_code == 422
    assert provider.downloaded == [rel_fdt]
    not_fdt = client.post('/api/v2/openneuro/save-fdt', json={
        'dataset_id': 'ds005185', 'tag': '1.0.2', 'shelf_id': shelf, 'path': rel_set})
    assert not_fdt.status_code == 422


def test_unavailable_dataset_and_traversal_path(tmp_path, monkeypatch):
    client, _ = boot(tmp_path, monkeypatch, FakeProvider(blobs()))
    _, shelf = seed(client)
    missing = client.post('/api/v2/openneuro/resolve-recording', json={
        'dataset_id': 'ds000000', 'path': 'sub-01/eeg/a.set', 'task_type': 'oddball',
        'classification': 'baseline', 'shelf_id': shelf})
    assert missing.status_code == 404
    escaped = client.post('/api/v2/openneuro/resolve-recording', json={
        'dataset_id': 'ds003061', 'tag': '1.2.0', 'path': '../secret.set', 'task_type': 'oddball',
        'classification': 'baseline', 'shelf_id': shelf})
    assert escaped.status_code == 422
