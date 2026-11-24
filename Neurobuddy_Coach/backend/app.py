"""Neurobuddy Coach Atlas v0.3 local FastAPI application.

The original three-panel website now contains a persistent central EEG shelf
repository and invokes the optimized Neurobuddy v0.7.1 scientific pipeline.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from neurobuddy_v2 import __version__ as PIPELINE_VERSION
from neurobuddy_v2.pipeline import process
from neurobuddy_v2.comparative import baseline_minimum, run_athlete_workflow

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(os.environ.get('NEUROBUDDY_DATA_DIR', str(ROOT / 'data'))).resolve()
FILES = STORAGE / 'recordings'
REPORTS = STORAGE / 'reports'
for folder in (STORAGE, FILES, REPORTS):
    folder.mkdir(parents=True, exist_ok=True)
DB_PATH = STORAGE / 'coach.sqlite3'
LOCK = threading.RLock()
WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix='neurobuddy-v071')

_REPORT_ID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
SIGNAL_SUFFIXES = ('.set', '.edf', '.bdf', '.vhdr', '.fif', '.fif.gz')
ALLOWED_SUFFIXES = SIGNAL_SUFFIXES + ('.fdt', '.eeg', '.vmrk', '.tsv', '.csv', '.txt', '.json')
MAX_FILE_BYTES = int(os.environ.get('NEUROBUDDY_MAX_FILE_BYTES', str(2 * 1024**3)))


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


@contextmanager
def database():
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


with database() as db:
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS athletes (
      id TEXT PRIMARY KEY, team_id TEXT NOT NULL REFERENCES teams(id),
      name TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS recordings (
      id TEXT PRIMARY KEY, athlete_id TEXT NOT NULL REFERENCES athletes(id),
      classification TEXT NOT NULL CHECK(classification IN ('baseline','testing')),
      source_name TEXT NOT NULL, directory TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS recording_files (
      id TEXT PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(id),
      name TEXT NOT NULL, size_bytes INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, mode TEXT NOT NULL, target_id TEXT NOT NULL,
      test_recording_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      status TEXT NOT NULL, error TEXT, result TEXT, result_dir TEXT NOT NULL,
      team_id TEXT, athlete_id TEXT);
    UPDATE jobs SET status='interrupted',error='Server stopped before processing completed. Retry this job.'
      WHERE status IN ('queued','running');
    ''')

app = FastAPI(title='Neurobuddy Coach Baseline', version='0.2.1')
app.mount('/v2', StaticFiles(directory=str(ROOT / 'v2')), name='v2')


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class JobRequest(BaseModel):
    mode: str
    target_id: str
    test_recording_id: str | None = None


def must_get(db, table, key):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
    if row is None:
        raise HTTPException(404, f'{table.rstrip("s").title()} not found')
    return dict(row)


def recording_path(row):
    p = (FILES / row['directory']).resolve()
    if not p.is_relative_to(FILES):
        raise ValueError('Unsafe recording folder')
    return p


def job_data(row, *, include_result=False):
    result = {k: row[k] for k in ('id','mode','target_id','test_recording_id','created_at','updated_at',
                                  'status','error','team_id','athlete_id')}
    if include_result:
        result['result'] = json.loads(row['result']) if row['result'] else None
    return result


@app.get('/')
@app.get('/Index.html', include_in_schema=False)
@app.get('/index.html', include_in_schema=False)
def root_index():
    return FileResponse(ROOT / 'Index.html')


@app.get('/favicon.svg', include_in_schema=False)
@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    # Both modern and fallback browser favicon requests resolve without 404.
    return FileResponse(ROOT / 'v2' / 'favicon.svg', media_type='image/svg+xml')


@app.get('/api/v2/health')
def health():
    return {'ok':True,'engine':'Neurobuddy v0.7.1','pipeline_version':PIPELINE_VERSION,
            'mode':'local-only','ai_connected':False,'repository_connected':True}


@app.post('/api/v2/teams', status_code=201)
def create_team(data: Named):
    key = str(uuid4())
    with LOCK, database() as db:
        db.execute('INSERT INTO teams VALUES(?,?,?)',(key,data.name.strip(),now()))
    return {'id':key,'name':data.name.strip()}


@app.post('/api/v2/teams/{team_id}/athletes', status_code=201)
def create_athlete(team_id: str, data: Named):
    key = str(uuid4())
    with LOCK, database() as db:
        must_get(db, 'teams', team_id)
        db.execute('INSERT INTO athletes VALUES(?,?,?,?)',(key,team_id,data.name.strip(),now()))
    return {'id':key,'team_id':team_id,'name':data.name.strip()}


@app.get('/api/v2/library')
def library():
    with database() as db:
        teams = [dict(r) for r in db.execute('SELECT * FROM teams ORDER BY name COLLATE NOCASE')]
        athletes = [dict(r) for r in db.execute('SELECT * FROM athletes ORDER BY name COLLATE NOCASE')]
        recordings = [dict(r) for r in db.execute('SELECT * FROM recordings ORDER BY created_at')]
        files = [dict(r) for r in db.execute('SELECT * FROM recording_files ORDER BY name COLLATE NOCASE')]
    for t in teams:
        t['athletes'] = []
        for a in athletes:
            if a['team_id'] != t['id']:
                continue
            item = {k:a[k] for k in ('id','name','team_id','created_at')}
            item['recordings'] = []
            for r in recordings:
                if r['athlete_id'] != a['id']:
                    continue
                rr = {k:r[k] for k in ('id','classification','created_at','source_name')}
                rr['files'] = [{k: f[k] for k in ('id','name','size_bytes')}
                               for f in files if f['recording_id'] == r['id']]
                rr['task'] = {'status':'ready' if any(f['name'].lower().endswith(SIGNAL_SUFFIXES)
                                                            for f in rr['files']) else 'needs_review',
                              'task':'unknown','warnings':[]}
                item['recordings'].append(rr)
            t['athletes'].append(item)
    return {'teams':teams,'revision':1,'created_at':now(),'publication_id':'local-direct-upload'}


def safe_name(name):
    if (not name or name.strip() != name or name in ('.','..') or '/' in name or '\\' in name
        or '\x00' in name or len(name) > 220):
        raise HTTPException(400, f'Unsafe filename: {name[:80]!r}')
    if not name.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(400, f'Unsupported file type: {name[:80]}')
    return name


@app.post('/api/v2/athletes/{athlete_id}/recordings', status_code=201)
async def upload_recording(athlete_id: str, classification: str = Form(...), uploads: list[UploadFile] = File(...)):
    if classification not in ('baseline','testing'):
        raise HTTPException(400, 'Classification must be baseline or testing.')
    if not uploads or len(uploads)>20:
        raise HTTPException(400, 'Choose 1 to 20 files representing exactly one EEG recording.')
    names = [safe_name(f.filename or '') for f in uploads]
    if len(set(n.casefold() for n in names)) != len(names):
        raise HTTPException(400,'Duplicate filenames in recording.')
    signals = [n for n in names if n.lower().endswith(SIGNAL_SUFFIXES)]
    if len(signals) != 1:
        raise HTTPException(400, 'Each upload must contain exactly one .set, .edf, .bdf, .vhdr, or .fif EEG signal file.')
    with database() as db:
        must_get(db, 'athletes', athlete_id)
    key = str(uuid4())
    dest = FILES / key
    dest.mkdir(parents=True, exist_ok=False)
    sizes=[]
    try:
        for upload, name in zip(uploads,names):
            size = 0
            with (dest / name).open('xb') as fh:
                while chunk := await upload.read(1024*1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(413,f'{name} exceeds configured per-file upload limit.')
                    fh.write(chunk)
            if size == 0:
                raise HTTPException(400,f'{name} is empty.')
            sizes.append(size)
        with LOCK, database() as db:
            must_get(db,'athletes',athlete_id)
            db.execute('INSERT INTO recordings(id,athlete_id,classification,source_name,directory,created_at) VALUES(?,?,?,?,?,?)',
                       (key,athlete_id,classification,signals[0],key,now()))
            for name,size in zip(names,sizes):
                db.execute('INSERT INTO recording_files VALUES(?,?,?,?)',
                           (str(uuid4()),key,name,size))
    except Exception:
        shutil.rmtree(dest,ignore_errors=True)
        raise
    return {'id':key,'classification':classification,'source_name':signals[0],
            'file_count':len(names),'status':'uploaded'}


@app.delete('/api/v2/recordings/{recording_id}')
def delete_recording(recording_id: str):
    with LOCK, database() as db:
        r = must_get(db,'recordings',recording_id)
        pending = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running','queued') AND "
                             "(target_id=? OR (mode='athlete' AND athlete_id=?))",
                             (recording_id,r['athlete_id'])).fetchone()[0]
        if pending:
            raise HTTPException(409,'A job is currently using this recording. Try again after it finishes.')
        db.execute('DELETE FROM recording_files WHERE recording_id=?',(recording_id,))
        db.execute('DELETE FROM recordings WHERE id=?',(recording_id,))
    shutil.rmtree(recording_path(r), ignore_errors=True)
    return {'deleted':True}


def _run_job(job_id):
    with LOCK, database() as db:
        job = must_get(db,'jobs',job_id)
        db.execute("UPDATE jobs SET status='running',updated_at=?,error=NULL WHERE id=?",(now(),job_id))
    dest = REPORTS / job_id
    dest.mkdir(exist_ok=True)
    try:
        with database() as db:
            if job['mode']=='single':
                rec = must_get(db,'recordings',job['target_id'])
                source = recording_path(rec)
            else:
                athlete = must_get(db,'athletes',job['target_id'])
                rows = [dict(r) for r in db.execute('SELECT * FROM recordings WHERE athlete_id=? ORDER BY created_at',
                                                    (athlete['id'],))]
                test = next((r for r in rows if r['id']==job['test_recording_id']),None)
                if not test or test['classification']!='testing':
                    raise ValueError('Testing recording unavailable. Select another testing recording.')
                task = test.get('task_type') or 'unspecified'
                baselines = [r for r in rows if r['classification']=='baseline' and (r.get('task_type') or 'unspecified')==task]
                needed = baseline_minimum(task)
                if len(baselines)<needed:
                    raise ValueError(f'At least {needed} baseline EEG recordings are required for {task}.')
                sources=[recording_path(r) for r in baselines]
                test_source=recording_path(test)
        if job['mode']=='single':
            delivered = process(source,dest)
            if len(delivered)!=1:
                raise ValueError(f'Expected one recording; received {len(delivered)}.')
            report,_ = delivered[0]
            result = {'mode':'single','recording_id':rec['id'],'analysis':report,
                      'entrypoint':'report.html','package':'report.zip'}
        else:
            struct = run_athlete_workflow(sources,test_source,dest,
                team_id=athlete['team_id'],athlete_id=athlete['id'],
                min_baselines=baseline_minimum(task))
            comparison = json.loads((dest/'comparative_analysis.json').read_text())
            baseline = json.loads((dest/'baseline'/'longitudinal.json').read_text())
            individual=[]
            for item in struct['baseline_reports']:
                individual.append({'classification':'baseline','result':json.loads((dest/item['report_json']).read_text()),
                                   'entrypoint':item['report_html']})
            individual.append({'classification':'testing','result':json.loads((dest/'test/report.json').read_text()),
                               'entrypoint':'test/report.html'})
            result = {'mode':'athlete','athlete_id':athlete['id'],'team_id':athlete['team_id'],
                      'comparison':comparison,'baseline':baseline,'individual':individual,
                      'summary':struct['comparison_summary'],'entrypoint':'athlete_report.html',
                      'package':'athlete_report.zip'}
        with LOCK, database() as db:
            db.execute('UPDATE jobs SET status=?,result=?,error=NULL,updated_at=? WHERE id=?',
                       ('completed',json.dumps(result,allow_nan=False),now(),job_id))
    except Exception as exc:
        with LOCK, database() as db:
            db.execute('UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?',
                       ('failed',f'{type(exc).__name__}: {str(exc)[:2000]}',now(),job_id))


@app.post('/api/v2/jobs',status_code=202)
def create_job(request:JobRequest):
    if request.mode not in ('single','athlete'):
        raise HTTPException(400,'Select a valid processing mode.')
    with LOCK, database() as db:
        if request.mode=='single':
            record = must_get(db,'recordings',request.target_id)
            athlete_id = record['athlete_id']
            athlete = must_get(db,'athletes',athlete_id)
            team_id = athlete['team_id']
            test_id = None
        else:
            athlete = must_get(db,'athletes',request.target_id)
            athlete_id = athlete['id']
            team_id = athlete['team_id']
            rows = [dict(r) for r in db.execute('SELECT * FROM recordings WHERE athlete_id=? ORDER BY created_at', (athlete_id,))]
            tests = [r for r in rows if r['classification']=='testing']
            chosen = next((r for r in tests if r['id']==request.test_recording_id), None) if request.test_recording_id else (tests[-1] if tests else None)
            if chosen is None:
                raise HTTPException(422,'Choose an existing testing EEG recording.')
            task = chosen.get('task_type') or 'unspecified'
            test_id = chosen['id']
            needed = baseline_minimum(task)
            baselines = [r for r in rows if r['classification']=='baseline' and (r.get('task_type') or 'unspecified')==task]
            if len(baselines)<needed:
                raise HTTPException(422, f'Athlete comparison requires at least {needed} {task} baseline recordings.')
        key = str(uuid4())
        db.execute('''INSERT INTO jobs(id,mode,target_id,test_recording_id,created_at,updated_at,status,error,result,result_dir,team_id,athlete_id)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (key,request.mode,request.target_id,test_id,now(),now(),'queued',None,None,key,team_id,athlete_id))
    WORKERS.submit(_run_job,key)
    return {'id':key,'mode':request.mode,'status':'queued'}


@app.get('/api/v2/jobs')
def get_jobs():
    with database() as db:
        rows=db.execute('SELECT * FROM jobs ORDER BY created_at DESC').fetchall()
    return {'jobs':[job_data(r) for r in rows]}


def _report_dir(job_id: str) -> Path:
    if not _REPORT_ID.fullmatch(job_id or ''):
        raise HTTPException(422, 'Unknown analysis report.')
    root = REPORTS.resolve()
    target = (REPORTS / job_id).resolve()
    if target == root or not target.is_relative_to(root):
        raise HTTPException(422, 'Unknown analysis report.')
    return target


def _remove_report_tree(path: Path):
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


@app.delete('/api/v2/jobs/{job_id}')
def delete_job(job_id: str, athlete_id: str | None = Query(default=None)):
    """Remove one analysis report. EEG shelf files and other jobs stay."""
    if athlete_id is not None and not _REPORT_ID.fullmatch(athlete_id):
        raise HTTPException(422, 'Unknown athlete report.')
    report_dir = _report_dir(job_id)
    with LOCK, database() as db:
        job = must_get(db, 'jobs', job_id)
        if job['status'] in ('queued', 'running'):
            raise HTTPException(409, 'Wait until this analysis finishes before deleting it.')
        if athlete_id:
            if job['mode'] != 'team':
                raise HTTPException(422, 'This report is not a team batch. Delete the report itself.')
            result = json.loads(job['result']) if job['result'] else {}
            members = list(result.get('members') or [])
            if not any(member.get('athlete_id') == athlete_id for member in members):
                raise HTTPException(404, 'Athlete report not found.')
            kept = [member for member in members if member.get('athlete_id') != athlete_id]
            member_dir = (report_dir / 'athletes' / athlete_id).resolve()
            if member_dir != report_dir and member_dir.is_relative_to(report_dir):
                _remove_report_tree(member_dir)
            if kept:
                result['members'] = kept
                db.execute('UPDATE jobs SET result=?, updated_at=? WHERE id=?',
                           (json.dumps(result, allow_nan=False), now(), job_id))
                return {'deleted': True, 'id': job_id, 'athlete_id': athlete_id, 'removed': 'athlete'}
        _remove_report_tree(report_dir)
        db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
    return {'deleted': True, 'id': job_id, 'removed': 'job'}


@app.get('/api/v2/jobs/{job_id}')
def get_job(job_id:str):
    with database() as db:
        row=must_get(db,'jobs',job_id)
    return job_data(row,include_result=True)


@app.post('/api/v2/jobs/{job_id}/retry',status_code=202)
def retry_job(job_id:str):
    with database() as db:
        job=must_get(db,'jobs',job_id)
    if job['status'] not in ('failed','interrupted'):
        raise HTTPException(409,'Only failed or interrupted jobs can be retried.')
    return create_job(JobRequest(mode=job['mode'],target_id=job['target_id'],
                                 test_recording_id=job['test_recording_id']))


@app.get('/api/v2/advanced')
def advanced():
    with database() as db:
        teams=[dict(r) for r in db.execute('SELECT id,name FROM teams ORDER BY name')]
        athletes=[dict(r) for r in db.execute('SELECT id,team_id,name FROM athletes ORDER BY name')]
        jobs=[dict(r) for r in db.execute("SELECT id,mode,athlete_id,team_id,created_at FROM jobs WHERE status='completed' ORDER BY created_at DESC")]
    groups=[]
    for t in teams:
        group={'id':t['id'],'name':t['name'],'athletes':[]}
        for a in athletes:
            if a['team_id']!=t['id']:
                continue
            ar=[{'id':j['id'],'mode':j['mode'],'created_at':j['created_at']} for j in jobs if j['athlete_id']==a['id']]
            if ar:
                group['athletes'].append({'id':a['id'],'name':a['name'],'reports':ar})
        if group['athletes']:
            groups.append(group)
    return {'teams':groups,'ai_connected':False,'pipeline_version':PIPELINE_VERSION}


@app.get('/api/v2/artifacts/{job_id}/{relative_path:path}')
def artifacts(job_id:str,relative_path:str):
    with database() as db:
        must_get(db,'jobs',job_id)
    root = (REPORTS/job_id).resolve()
    target = (root/relative_path).resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.is_symlink():
        raise HTTPException(404,'Report artifact not found')
    return FileResponse(target)

# Central Dataset Library is itself the repository. No separate EEG Collection app.
from . import shelves as _shelves
_shelves.install(app, __import__(__name__, fromlist=['*']))
