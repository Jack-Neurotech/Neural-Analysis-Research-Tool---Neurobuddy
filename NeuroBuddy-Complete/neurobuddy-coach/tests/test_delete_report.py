"""Deleting one analysis report leaves other reports and EEG shelf files."""
import importlib
import json
import sys
from uuid import uuid4

from fastapi.testclient import TestClient


def _insert(app, job_id, mode, status, result):
    with app.database() as db:
        db.execute(
            '''INSERT INTO jobs(id,mode,target_id,test_recording_id,created_at,updated_at,
               status,error,result,result_dir,team_id,athlete_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (job_id, mode, 'target', None, app.now(), app.now(), status, None,
             json.dumps(result) if result else None, job_id, None, None))


def test_delete_report_leaves_other_reports_and_shelves(tmp_path, monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR', str(tmp_path / 'db'))
    sys.modules.pop('backend.shelves', None)
    sys.modules.pop('backend.app', None)
    app = importlib.import_module('backend.app')
    cli = TestClient(app.app)
    keep, gone, team, running = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    athlete_a, athlete_b = str(uuid4()), str(uuid4())
    shelf = app.FILES / 'shelf-keep'
    shelf.mkdir(parents=True)
    (shelf / 'signal.set').write_text('eeg', encoding='utf-8')
    for job_id in (gone, keep, team, running):
        dest = app.REPORTS / job_id
        dest.mkdir()
        (dest / 'report.html').write_text(job_id, encoding='utf-8')
    for athlete_id in (athlete_a, athlete_b):
        member = app.REPORTS / team / 'athletes' / athlete_id
        member.mkdir(parents=True)
        (member / 'athlete_report.html').write_text(athlete_id, encoding='utf-8')
    _insert(app, gone, 'single', 'completed', None)
    _insert(app, keep, 'athlete', 'failed', None)
    _insert(app, team, 'team', 'completed', {'mode': 'team', 'members': [
        {'athlete_id': athlete_a, 'athlete_name': 'A', 'status': 'completed'},
        {'athlete_id': athlete_b, 'athlete_name': 'B', 'status': 'completed'},
    ]})
    _insert(app, running, 'single', 'running', None)

    blocked = cli.delete(f'/api/v2/jobs/{running}')
    assert blocked.status_code == 409
    assert (app.REPORTS / running / 'report.html').is_file()

    removed = cli.delete(f'/api/v2/jobs/{gone}')
    assert removed.status_code == 200, removed.text
    assert removed.json()['removed'] == 'job'
    assert not (app.REPORTS / gone).exists()
    listed = {job['id'] for job in cli.get('/api/v2/jobs').json()['jobs']}
    assert gone not in listed
    assert keep in listed and team in listed
    assert (app.REPORTS / keep / 'report.html').read_text(encoding='utf-8') == keep
    assert (shelf / 'signal.set').read_text(encoding='utf-8') == 'eeg'
    assert cli.get(f'/api/v2/jobs/{gone}').status_code == 404

    partial = cli.delete(f'/api/v2/jobs/{team}', params={'athlete_id': athlete_a})
    assert partial.status_code == 200, partial.text
    assert partial.json()['removed'] == 'athlete'
    assert not (app.REPORTS / team / 'athletes' / athlete_a).exists()
    assert (app.REPORTS / team / 'athletes' / athlete_b / 'athlete_report.html').read_text(encoding='utf-8') == athlete_b
    members = cli.get(f'/api/v2/jobs/{team}').json()['result']['members']
    assert [member['athlete_id'] for member in members] == [athlete_b]
    assert (shelf / 'signal.set').is_file()
    assert (app.REPORTS / keep).is_dir()

    assert cli.delete(f'/api/v2/jobs/{team}', params={'athlete_id': '../' + keep}).status_code == 422
    assert (app.REPORTS / keep / 'report.html').is_file()

    whole = cli.delete(f'/api/v2/jobs/{team}')
    assert whole.status_code == 200, whole.text
    assert whole.json()['removed'] == 'job'
    assert 'athlete_id' not in whole.json()
    assert not (app.REPORTS / team).exists()
    assert team not in {job['id'] for job in cli.get('/api/v2/jobs').json()['jobs']}
    assert (shelf / 'signal.set').read_text(encoding='utf-8') == 'eeg'
    assert (app.REPORTS / keep / 'report.html').is_file()
