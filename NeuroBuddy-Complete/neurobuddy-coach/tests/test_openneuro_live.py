"""Live OpenNeuro checks. Skipped unless NEUROBUDDY_LIVE_OPENNEURO=1."""
from __future__ import annotations

import importlib
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.environ.get('NEUROBUDDY_LIVE_OPENNEURO') != '1',
                                reason='Set NEUROBUDDY_LIVE_OPENNEURO=1 to call public OpenNeuro')

ODDBALL = 'sub-001/eeg/sub-001_task-P300_run-1_eeg.set'
MOTOR = 'sub-xp101/eeg/sub-xp101_task-motorloc_eeg.vhdr'
SLEEP = 'sub-06/eeg/sub-06_task-sleep_acq-PSG_eeg.edf'


def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR', str(tmp_path / 'storage'))
    sys.modules.pop('backend.app', None)
    app_module = importlib.import_module('backend.app')
    return TestClient(app_module.app)


def test_live_dataset_snapshot_and_nested_tree(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    dataset = api.get('/api/v2/openneuro/ds003061')
    assert dataset.status_code == 200, dataset.text
    body = dataset.json()
    assert body['id'] == 'ds003061'
    assert body['tag']
    root = api.get(f"/api/v2/openneuro/ds003061/tree?tag={body['tag']}")
    assert root.status_code == 200, root.text
    sub = next(item for item in root.json()['files'] if item['filename'] == 'sub-001')
    assert sub['directory'] is True
    nested = api.get(f"/api/v2/openneuro/ds003061/tree?tag={body['tag']}&tree={sub['id']}")
    assert nested.status_code == 200
    assert any(item['filename'] == 'eeg' and item['directory'] for item in nested.json()['files'])
    assert api.get('/api/v2/openneuro/ds000000').status_code == 404


def _resolve(api, dataset_id, path, task):
    dataset = api.get(f'/api/v2/openneuro/{dataset_id}').json()
    response = api.post('/api/v2/openneuro/resolve-recording', json={
        'dataset_id': dataset_id, 'tag': dataset['tag'], 'path': path, 'task_type': task,
        'classification': 'baseline', 'athlete_id': _athlete(api)})
    assert response.status_code == 200, response.text
    return response.json()


def _athlete(api):
    cached = getattr(api, '_live_athlete', None)
    if cached:
        return cached
    team = api.post('/api/v2/shelf-teams', json={'name': 'Live'}).json()
    athlete = api.post(f"/api/v2/shelf-teams/{team['id']}/athletes?task_type=oddball", json={'name': 'Live'}).json()
    api._live_athlete = athlete['id']
    return athlete['id']


def test_live_task_resolution_without_downloading_large_signals(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    oddball = _resolve(api, 'ds003061', ODDBALL, 'oddball')
    assert oddball['snapshot']
    assert oddball['status'] == 'ready', oddball['summary']
    chosen = {item['filename']: item for item in oddball['files'] if item['selected']}
    assert 'sub-001_task-P300_run-1_eeg.set' in chosen
    assert not any(name.endswith('.fdt') for name in chosen)
    assert 'sub-001_task-P300_run-1_events.tsv' in chosen
    assert 'sub-001_task-P300_run-2_events.tsv' not in chosen
    assert oddball['task_detected'] == 'oddball'
    conflict = _resolve(api, 'ds003061', ODDBALL, 'sleep')
    assert conflict['status'] == 'needs_review'
    assert conflict['task_detected'] == 'oddball'
    motor = _resolve(api, 'ds002336', MOTOR, 'motor')
    motor_names = {item['filename'] for item in motor['files'] if item['selected']}
    assert 'sub-xp101_task-motorloc_eeg.eeg' in motor_names
    assert 'sub-xp101_task-motorloc_eeg.vmrk' in motor_names
    assert 'task-MIpost_channels.tsv' not in motor_names
    sleep = _resolve(api, 'ds007181', SLEEP, 'sleep')
    sleep_chosen = [item for item in sleep['files'] if item['selected']]
    signal = next(item for item in sleep_chosen if item['filename'].endswith('.edf'))
    assert signal['size'] > 100_000_000
    assert any(item['role'] == 'sleep_scoring' for item in sleep_chosen)
    assert not any('fabricat' in (item.get('reason') or '').lower() for item in sleep_chosen)


def test_live_oddball_download_is_readable(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    team = api.post('/api/v2/shelf-teams', json={'name': 'Download'}).json()
    athlete = api.post(f"/api/v2/shelf-teams/{team['id']}/athletes?task_type=oddball", json={'name': 'Case'}).json()
    dataset = api.get('/api/v2/openneuro/ds003061').json()
    started = api.post('/api/v2/openneuro/import-recording', json={
        'dataset_id': 'ds003061', 'tag': dataset['tag'], 'path': ODDBALL, 'task_type': 'oddball',
        'classification': 'baseline', 'athlete_id': athlete['id']})
    assert started.status_code == 202, started.text
    job_id = started.json()['id']
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = api.get('/api/v2/import-jobs/' + job_id).json()
        if job['status'] in {'completed', 'failed', 'cancelled'}:
            break
        time.sleep(0.5)
    assert job['status'] == 'completed', job.get('error')
    assert job['result']['validation']['n_channels'] >= 64
    assert job['result']['validation']['n_times'] > 1000
    names = {item['path'] for item in job['result']['files']}
    assert names == {ODDBALL}
    signal = next(item for item in job['result']['files'] if item['path'] == ODDBALL)
    assert signal['sha256'] and signal['size'] > 1_000_000
    shelf = started.json()['shelf_id']
    run = api.post('/api/v2/shelf-jobs', json={'mode': 'single', 'target_id': shelf, 'task_type': 'oddball'})
    assert run.status_code == 202, run.text
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        result = api.get('/api/v2/jobs/' + run.json()['id']).json()
        if result['status'] in {'completed', 'failed'}:
            break
        time.sleep(0.5)
    assert result['status'] == 'completed', result.get('error')
    report = api.get('/api/v2/artifacts/' + run.json()['id'] + '/report.html')
    assert report.status_code == 200
    assert b'report' in report.content.lower() or b'html' in report.content[:200].lower()
