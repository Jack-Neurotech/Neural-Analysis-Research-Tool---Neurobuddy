"""Deleting one EEG shelf from Advanced analysis leaves reports, teammates, and the team."""
import importlib
import io
import json
import sqlite3
import sys
from uuid import uuid4

from fastapi.testclient import TestClient


def _upload(client, shelf_id):
    response = client.post(
        f'/api/v2/shelves/{shelf_id}/files',
        data={'slot': 'signal'},
        files={'uploads': ('keep.fif', io.BytesIO(b'disposable-eeg'), 'application/octet-stream')},
    )
    assert response.status_code == 201, response.text


def _job(db, backend, *, mode, target, athlete, team, status, test=None):
    key = str(uuid4())
    now = '2026-11-21T21:00:00+00:00'
    db.execute(
        '''INSERT INTO jobs(id,mode,target_id,test_recording_id,created_at,updated_at,status,error,result,result_dir,team_id,athlete_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (key, mode, target, test, now, now, status, None,
         json.dumps({'mode': mode}), key, team, athlete))
    db.commit()
    report = backend.REPORTS / key
    report.mkdir(parents=True, exist_ok=True)
    (report / 'report.html').write_text('keep this report', encoding='utf-8')
    return key


def test_advanced_delete_removes_one_shelf_and_refuses_a_busy_one(tmp_path, monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR', str(tmp_path / 'storage'))
    sys.modules.pop('backend.app', None)
    backend = importlib.import_module('backend.app')
    client = TestClient(backend.app)
    team = client.post('/api/v2/shelf-teams', json={'name': 'Disposable'}).json()
    other = client.post('/api/v2/shelf-teams', json={'name': 'Other team'}).json()
    athlete = client.post(f"/api/v2/shelf-teams/{team['id']}/athletes", json={'name': 'Disposable athlete'}).json()
    stranger = client.post(f"/api/v2/shelf-teams/{other['id']}/athletes", json={'name': 'Other athlete'}).json()
    library = client.get('/api/v2/shelf-library').json()
    by_athlete = {a['id']: a['shelves'] for t in library['teams'] for a in t['athletes']}
    own = by_athlete[athlete['id']]
    theirs = by_athlete[stranger['id']]
    _upload(client, own[0]['id'])
    _upload(client, theirs[0]['id'])
    db = sqlite3.connect(backend.DB_PATH)
    kept_report = _job(db, backend, mode='single', target=own[0]['id'], athlete=athlete['id'],
                       team=team['id'], status='completed')
    listed = client.get('/api/v2/shelf-advanced').json()
    shown = next(a for t in listed['teams'] if t['id'] == team['id'] for a in t['athletes'])
    assert own[0]['id'] in {item['id'] for item in shown['shelves']}
    assert all(item['id'] != shelf['id'] for item in shown['shelves'] for shelf in theirs)

    busy = _job(db, backend, mode='single', target=own[0]['id'], athlete=athlete['id'],
                team=team['id'], status='queued')
    blocked = client.delete(f"/api/v2/shelves/{own[0]['id']}")
    assert blocked.status_code == 409, blocked.text
    assert 'finishes' in blocked.json()['detail']
    spared = client.delete(f"/api/v2/shelves/{own[1]['id']}")
    assert spared.status_code == 200, spared.text

    db.execute("UPDATE jobs SET mode='athlete', target_id=?, athlete_id=? WHERE id=?",
               (athlete['id'], athlete['id'], busy))
    db.commit()
    assert client.delete(f"/api/v2/shelves/{own[0]['id']}").status_code == 409

    db.execute("UPDATE jobs SET mode='team', target_id=?, team_id=?, athlete_id=NULL WHERE id=?",
               (team['id'], team['id'], busy))
    db.commit()
    assert client.delete(f"/api/v2/shelves/{own[0]['id']}").status_code == 409
    other_ok = client.delete(f"/api/v2/shelves/{theirs[1]['id']}")
    assert other_ok.status_code == 200, other_ok.text

    db.execute('DELETE FROM jobs WHERE id=?', (busy,))
    db.commit()
    removed = client.delete(f"/api/v2/shelves/{own[0]['id']}")
    assert removed.status_code == 200, removed.text
    assert removed.json()['deleted'] is True

    library = client.get('/api/v2/shelf-library').json()
    by_athlete = {a['id']: a['shelves'] for t in library['teams'] for a in t['athletes']}
    assert own[0]['id'] not in {item['id'] for item in by_athlete[athlete['id']]}
    assert theirs[0]['id'] in {item['id'] for item in by_athlete[stranger['id']]}
    assert client.get('/api/v2/shelf-teams').status_code in (404, 405)
    teams = {item['id'] for item in client.get('/api/v2/shelf-library').json()['teams']}
    assert team['id'] in teams and other['id'] in teams
    assert (backend.REPORTS / kept_report / 'report.html').read_text(encoding='utf-8') == 'keep this report'
    assert not (backend.FILES / own[0]['id']).exists()
    assert (backend.FILES / theirs[0]['id']).is_dir()
