"""Oddball longitudinal jobs accept two baselines. Other families still need three."""
import importlib.util
import io
import json
import statistics
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neurobuddy_v2.comparative import ComparisonError, build_comparison

_fixture = importlib.util.spec_from_file_location(
    'athlete_comparative_fixtures',
    Path(__file__).resolve().parent / 'scientific' / 'test_athlete_comparative.py')
_module = importlib.util.module_from_spec(_fixture)
_fixture.loader.exec_module(_module)
fake_report = _module.fake_report


def test_two_oddball_baselines_keep_the_sample_sd_z_score():
    baselines = [fake_report(1, 10, fam='ODDBALL', subtype='oddball'),
                 fake_report(2, 14, fam='ODDBALL', subtype='oddball')]
    test = fake_report(3, 18, fam='ODDBALL', subtype='oddball')
    _, comp = build_comparison(baselines, test)
    row = next(item for item in comp['metrics'] if item['metric'] == 'shared.channel.C3.alpha_power')
    values = [10, 14]
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    assert row['baseline_n'] == 2
    assert row['baseline_mean'] == mean
    assert row['baseline_sd'] == sd
    assert row['test_value'] == 18
    assert row['z_score'] == (18 - mean) / sd
    assert sd > 0


def test_two_baselines_still_refused_for_other_families():
    families = (('SLEEP', 'scored_sleep'), ('MOTOR', 'imagery'), ('GENERAL', None))
    for family, subtype in families:
        baselines = [fake_report(1, 10, fam=family, subtype=subtype),
                     fake_report(2, 14, fam=family, subtype=subtype)]
        test = fake_report(3, 18, fam=family, subtype=subtype)
        with pytest.raises(ComparisonError, match='At least 3 distinct baseline'):
            build_comparison(baselines, test)


def test_mixed_family_is_not_accepted_as_oddball():
    baselines = [fake_report(1, 10, fam='ODDBALL', subtype='oddball'),
                 fake_report(2, 14, fam='ODDBALL', subtype='oddball')]
    test = fake_report(3, 18, fam='SLEEP', subtype='scored_sleep')
    with pytest.raises(ComparisonError, match='task family/subtype mismatch'):
        build_comparison(baselines, test)


def _upload(client, shelf_id, name):
    response = client.post(
        f'/api/v2/shelves/{shelf_id}/files',
        data={'slot': 'signal'},
        files={'uploads': (name, io.BytesIO(b'eeg-fixture'), 'application/octet-stream')},
    )
    assert response.status_code == 201, response.text


def _await_job(client, job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get('/api/v2/jobs/' + job_id).json()
        if result['status'] in ('completed', 'failed'):
            return result
        time.sleep(0.05)
    raise AssertionError('Job did not finish')


def test_oddball_job_with_two_baselines_is_accepted_and_other_jobs_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR', str(tmp_path / 'storage'))
    sys.modules.pop('backend.app', None)
    backend = __import__('backend.app', fromlist=['app'])
    client = TestClient(backend.app)

    def stub(path, dest, **kwargs):
        stub.n += 1
        value = (10, 14, 18)[stub.n - 1]
        report = fake_report(stub.n, value, fam='ODDBALL', subtype='oddball')
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'report.json').write_text(json.dumps(report))
        (dest / 'report.html').write_text('<html>oddball</html>')
        return [(report, dest / 'report.zip')]

    stub.n = 0
    monkeypatch.setattr('neurobuddy_v2.pipeline.process', stub)

    oddball = client.post('/api/v2/shelf-teams', json={'name': 'Oddball team'}).json()
    athlete = client.post(
        f"/api/v2/shelf-teams/{oddball['id']}/athletes?task_type=oddball",
        json={'name': 'Oddball athlete'},
    ).json()
    shelves = client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves']
    assert [item['classification'] for item in shelves] == ['baseline', 'baseline', 'baseline', 'testing']
    _upload(client, shelves[0]['id'], 'run-1.fif')
    _upload(client, shelves[1]['id'], 'run-2.fif')
    _upload(client, shelves[3]['id'], 'test.fif')
    accepted = client.post('/api/v2/shelf-jobs', json={'mode': 'athlete', 'target_id': athlete['id'], 'task_type': 'oddball'})
    assert accepted.status_code == 202, accepted.text

    for task in ('sleep', 'motor', 'unspecified'):
        team = client.post('/api/v2/shelf-teams', json={'name': task}).json()
        person = client.post(
            f"/api/v2/shelf-teams/{team['id']}/athletes?task_type={task}",
            json={'name': task},
        ).json()
        own = next(a for t in client.get('/api/v2/shelf-library').json()['teams'] if t['id'] == team['id'] for a in t['athletes'])
        slots = own['shelves']
        _upload(client, slots[0]['id'], 'run-1.fif')
        _upload(client, slots[1]['id'], 'run-2.fif')
        _upload(client, slots[3]['id'], 'test.fif')
        response = client.post('/api/v2/shelf-jobs', json={'mode': 'athlete', 'target_id': person['id'], 'task_type': task})
        assert response.status_code == 422, response.text
        assert '3' in response.json()['detail']
        assert task in response.json()['detail']

    finished = _await_job(client, accepted.json()['id'])
    assert finished['status'] == 'completed', finished.get('error')
    assert finished['result']['baseline']['baseline_recording_count'] == 2
    row = next(item for item in finished['result']['comparison']['metrics']
               if item['metric'] == 'shared.channel.C3.alpha_power')
    mean = statistics.mean([10, 14])
    sd = statistics.stdev([10, 14])
    assert row['baseline_sd'] == sd
    assert row['z_score'] == (18 - mean) / sd
