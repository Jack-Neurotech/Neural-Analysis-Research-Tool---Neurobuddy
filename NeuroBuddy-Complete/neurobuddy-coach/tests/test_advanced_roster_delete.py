"""Advanced Analysis can delete one athlete or one team without taking reports with them."""
import importlib
import io
import json
import sqlite3
import sys
from uuid import uuid4

from fastapi.testclient import TestClient


def _upload(client, shelf_id, name):
    response = client.post(
        f'/api/v2/shelves/{shelf_id}/files',
        data={'slot': 'signal'},
        files={'uploads': (name, io.BytesIO(name.encode()), 'application/octet-stream')},
    )
    assert response.status_code == 201, response.text


def _completed(db, backend, *, athlete, team, shelf):
    key = str(uuid4())
    now = '2026-11-21T21:30:00+00:00'
    db.execute(
        '''INSERT INTO jobs(id,mode,target_id,test_recording_id,created_at,updated_at,status,error,result,result_dir,team_id,athlete_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (key, 'single', shelf, None, now, now, 'completed', None, json.dumps({'mode': 'single'}), key, team, athlete))
    db.commit()
    report = backend.REPORTS / key
    report.mkdir(parents=True, exist_ok=True)
    (report / 'report.html').write_text('keep this report', encoding='utf-8')
    return key


def _queued(db, *, mode, target, athlete, team):
    key = str(uuid4())
    now = '2026-11-21T21:31:00+00:00'
    db.execute(
        '''INSERT INTO jobs(id,mode,target_id,test_recording_id,created_at,updated_at,status,error,result,result_dir,team_id,athlete_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (key, mode, target, None, now, now, 'queued', None, None, key, team, athlete))
    db.commit()
    return key


def test_advanced_athlete_and_team_delete_keep_reports_and_other_rosters(tmp_path, monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR', str(tmp_path / 'storage'))
    sys.modules.pop('backend.app', None)
    backend = importlib.import_module('backend.app')
    client = TestClient(backend.app)
    home = client.post('/api/v2/shelf-teams', json={'name': 'Home'}).json()
    other = client.post('/api/v2/shelf-teams', json={'name': 'Other'}).json()
    first = client.post(f"/api/v2/shelf-teams/{home['id']}/athletes", json={'name': 'First'}).json()
    second = client.post(f"/api/v2/shelf-teams/{home['id']}/athletes", json={'name': 'Second'}).json()
    outsider = client.post(f"/api/v2/shelf-teams/{other['id']}/athletes", json={'name': 'Outsider'}).json()
    library = client.get('/api/v2/shelf-library').json()
    shelves = {a['id']: a['shelves'] for t in library['teams'] for a in t['athletes']}
    _upload(client, shelves[first['id']][0]['id'], 'first.fif')
    _upload(client, shelves[second['id']][0]['id'], 'second.fif')
    _upload(client, shelves[outsider['id']][0]['id'], 'other.fif')
    db = sqlite3.connect(backend.DB_PATH)
    first_report = _completed(db, backend, athlete=first['id'], team=home['id'], shelf=shelves[first['id']][0]['id'])
    second_report = _completed(db, backend, athlete=second['id'], team=home['id'], shelf=shelves[second['id']][0]['id'])
    other_report = _completed(db, backend, athlete=outsider['id'], team=other['id'], shelf=shelves[outsider['id']][0]['id'])

    listed = client.get('/api/v2/shelf-advanced').json()
    home_row = next(t for t in listed['teams'] if t['id'] == home['id'])
    assert {a['name'] for a in home_row['athletes']} == {'First', 'Second'}

    busy_athlete = _queued(db, mode='athlete', target=first['id'], athlete=first['id'], team=home['id'])
    blocked = client.delete(f"/api/v2/shelf-athletes/{first['id']}")
    assert blocked.status_code == 409, blocked.text
    assert 'finishes' in blocked.json()['detail']
    db.execute('DELETE FROM jobs WHERE id=?', (busy_athlete,))
    db.commit()

    busy_team = _queued(db, mode='team', target=home['id'], athlete=None, team=home['id'])
    blocked_team = client.delete(f"/api/v2/shelf-teams/{home['id']}")
    assert blocked_team.status_code == 409, blocked_team.text
    assert 'finishes' in blocked_team.json()['detail']
    blocked_member = client.delete(f"/api/v2/shelf-athletes/{first['id']}")
    assert blocked_member.status_code == 409, blocked_member.text
    db.execute('DELETE FROM jobs WHERE id=?', (busy_team,))
    db.commit()

    removed = client.delete(f"/api/v2/shelf-athletes/{first['id']}")
    assert removed.status_code == 200, removed.text
    library = client.get('/api/v2/shelf-library').json()
    by_team = {t['id']: t for t in library['teams']}
    home_athletes = {a['id'] for a in by_team[home['id']]['athletes']}
    assert first['id'] not in home_athletes
    assert second['id'] in home_athletes
    assert not (backend.FILES / shelves[first['id']][0]['id']).exists()
    assert (backend.FILES / shelves[second['id']][0]['id']).is_dir()
    assert (backend.REPORTS / first_report / 'report.html').read_text(encoding='utf-8') == 'keep this report'

    gone = client.delete(f"/api/v2/shelf-teams/{home['id']}")
    assert gone.status_code == 200, gone.text
    library = client.get('/api/v2/shelf-library').json()
    teams = {t['id']: t for t in library['teams']}
    assert home['id'] not in teams
    assert other['id'] in teams
    assert outsider['id'] in {a['id'] for a in teams[other['id']]['athletes']}
    assert not (backend.FILES / shelves[second['id']][0]['id']).exists()
    assert (backend.FILES / shelves[outsider['id']][0]['id']).is_dir()
    for report in (first_report, second_report, other_report):
        assert (backend.REPORTS / report / 'report.html').read_text(encoding='utf-8') == 'keep this report'
