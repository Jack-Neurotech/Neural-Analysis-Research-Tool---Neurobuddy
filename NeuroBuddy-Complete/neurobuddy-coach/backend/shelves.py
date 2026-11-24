"""Persistent EEG shelves and task-aware uploads for the single three-tab Coach Atlas.

An EEG shelf is ONE recording bundle with optional companion files. The 'object' slot
in the UI represents event/annotation sidecars, not a fictitious .object format.
"""
from __future__ import annotations
import json
import math
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel, Field

from backend.openneuro_connector import graphql as _openneuro_graphql
from backend import remote_imports
from neurobuddy_v2.comparative import baseline_minimum

TASKS = ('oddball','motor','sleep','unspecified')
TYPES = ('baseline','testing')
SIGNALS = ('.set','.edf','.bdf','.vhdr','.fif','.fif.gz')
SIDECARS = ('.fdt','.eeg','.vmrk','.tsv','.csv','.json','.txt')
MAX_FILES = 24
OPENNEURO_API = 'https://openneuro.org/crn/graphql'


def shelf_file(root, name: str):
    parts = Path(name).parts
    if not name or not parts or any(part in {'', '.', '..'} for part in parts):
        raise HTTPException(400, 'Unsafe file path')
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HTTPException(400, 'Unsafe file path')
    return path

class NameRequest(BaseModel):
    name: str = Field(min_length=1,max_length=120)

class ShelfRequest(BaseModel):
    task_type: str = 'unspecified'
    classification: str = 'baseline'

class ShelfPatch(BaseModel):
    task_type: str | None = None
    classification: str | None = None

class BatchRequest(BaseModel):
    mode: str
    target_id: str
    task_type: str | None = None
    test_recording_id: str | None = None
    artifact_mode: str = 'legacy'
    mains_frequency_hz: float = 60


def install(app, base):
    router = APIRouter(prefix='/api/v2')
    remote_imports.register(router, base)
    dbconn, LOCK, FILES = base.database, base.LOCK, base.FILES

    # Additive migration: do not discard data from the pre-Repository website.
    with LOCK, dbconn() as db:
        cols={r['name'] for r in db.execute('PRAGMA table_info(recordings)')}
        if 'task_type' not in cols:
            db.execute("ALTER TABLE recordings ADD COLUMN task_type TEXT NOT NULL DEFAULT 'unspecified'")
        if 'origin' not in cols:
            db.execute("ALTER TABLE recordings ADD COLUMN origin TEXT NOT NULL DEFAULT 'downloads'")
        if 'dataset_ref' not in cols:
            db.execute("ALTER TABLE recordings ADD COLUMN dataset_ref TEXT")
        db.execute('CREATE INDEX IF NOT EXISTS ix_athlete_shelves ON recordings(athlete_id,classification,task_type)')

    def ensure_task(task):
        if task not in TASKS: raise HTTPException(422,'Test Type must be Oddball, Motor-imagery, Sleep, or Unspecified.')
    def ensure_type(value):
        if value not in TYPES: raise HTTPException(422,'File Type must be Baseline or Testing.')
    def create_shelf(db, athlete_id, kind, task):
        key=str(uuid4())
        db.execute('INSERT INTO recordings(id,athlete_id,classification,source_name,directory,created_at,task_type,origin) VALUES(?,?,?,?,?,?,?,?)',
                   (key,athlete_id,kind,'',key,base.now(),task,'downloads'))
        return key
    def as_library():
        with dbconn() as db:
            teams=[dict(r) for r in db.execute('SELECT * FROM teams ORDER BY created_at,id')]
            athletes=[dict(r) for r in db.execute('SELECT * FROM athletes ORDER BY created_at,id')]
            recordings=[dict(r) for r in db.execute('SELECT * FROM recordings ORDER BY created_at,rowid')]
            files=[dict(r) for r in db.execute('SELECT * FROM recording_files ORDER BY rowid')]
        fby={}
        for f in files:fby.setdefault(f['recording_id'],[]).append({k:f[k] for k in ('id','name','size_bytes')})
        aby={}
        for a in athletes:
            a['shelves']=[];a['recordings']=a['shelves'];aby.setdefault(a['team_id'],[]).append(a)
        for r in recordings:
            athlete=next((a for a in athletes if a['id']==r['athlete_id']),None)
            if athlete is None: continue
            rr={k:r[k] for k in ('id','classification','task_type','origin','source_name','created_at')}
            rr['source']=_source_summary(r.get('dataset_ref'))
            rr['files']=fby.get(r['id'],[])
            signal=next((f for f in rr['files'] if f['name'].lower().endswith(SIGNALS)),None)
            rr['ready']=bool(signal)
            rr['task']={'task':r['task_type'],'status':'ready' if signal else 'empty','warnings':[]}
            athlete['shelves'].append(rr)
        for team in teams:team['athletes']=aby.get(team['id'],[])
        return {'teams':teams,'pipeline_version':base.PIPELINE_VERSION}

    @router.get('/shelf-library')
    def library():return as_library()

    @router.post('/shelf-teams',status_code=201)
    def add_team(body:NameRequest):
        key=str(uuid4());name=body.name.strip()
        if not name:raise HTTPException(422,'Team name is required.')
        with LOCK,dbconn() as db:db.execute('INSERT INTO teams VALUES(?,?,?)',(key,name,base.now()))
        return {'id':key,'name':name}

    @router.post('/shelf-teams/{team_id}/athletes',status_code=201)
    def add_athlete(team_id:str,body:NameRequest,task_type:str='unspecified'):
        ensure_task(task_type);key=str(uuid4());name=body.name.strip()
        if not name:raise HTTPException(422,'Athlete name is required.')
        with LOCK,dbconn() as db:
            base.must_get(db,'teams',team_id)
            db.execute('INSERT INTO athletes VALUES(?,?,?,?)',(key,team_id,name,base.now()))
            for c in ['baseline']*3+['testing']:create_shelf(db,key,c,task_type)
        return {'id':key,'team_id':team_id,'name':name,'created_shelves':4}

    @router.post('/shelf-athletes/{athlete_id}/shelves',status_code=201)
    def add_shelf(athlete_id:str,body:ShelfRequest):
        ensure_task(body.task_type);ensure_type(body.classification)
        with LOCK,dbconn() as db:
            base.must_get(db,'athletes',athlete_id)
            key=create_shelf(db,athlete_id,body.classification,body.task_type)
        return {'id':key,'task_type':body.task_type,'classification':body.classification}

    @router.patch('/shelves/{shelf_id}')
    def update_shelf(shelf_id:str,body:ShelfPatch):
        with LOCK,dbconn() as db:
            shelf=base.must_get(db,'recordings',shelf_id)
            changes={}
            if body.task_type is not None:
                ensure_task(body.task_type);changes['task_type']=body.task_type
            if body.classification is not None:
                ensure_type(body.classification);changes['classification']=body.classification
            for field,value in changes.items():db.execute(f'UPDATE recordings SET {field}=? WHERE id=?',(value,shelf_id))
        return {'id':shelf_id,**changes}

    @router.delete('/shelves/{shelf_id}')
    def remove_shelf(shelf_id:str):
        with LOCK,dbconn() as db:
            shelf=base.must_get(db,'recordings',shelf_id)
            athlete=base.must_get(db,'athletes',shelf['athlete_id'])
            busy=db.execute("""SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND (
                    target_id=? OR test_recording_id=?
                    OR (mode='athlete' AND athlete_id=?)
                    OR (mode='team' AND team_id=?))""",
                (shelf_id,shelf_id,shelf['athlete_id'],athlete['team_id'])).fetchone()[0]
            if busy:
                raise HTTPException(409,'Wait until the analysis using this shelf finishes before deleting it.')
            db.execute('DELETE FROM recording_files WHERE recording_id=?',(shelf_id,))
            db.execute('DELETE FROM recordings WHERE id=?',(shelf_id,))
        shutil.rmtree(base.recording_path(shelf),ignore_errors=True)
        return {'deleted':True,'id':shelf_id}

    @router.delete('/shelf-athletes/{athlete_id}')
    def remove_athlete(athlete_id:str):
        with LOCK,dbconn() as db:
            athlete=base.must_get(db,'athletes',athlete_id)
            busy=db.execute("""SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND (
                    athlete_id=? OR target_id=? OR (mode='team' AND team_id=?))""",
                (athlete_id,athlete_id,athlete['team_id'])).fetchone()[0]
            if busy:
                raise HTTPException(409,'Wait until the analysis using this athlete finishes before deleting them.')
            shelves=[dict(r) for r in db.execute('SELECT * FROM recordings WHERE athlete_id=?',(athlete_id,))]
            for r in shelves:
                db.execute('DELETE FROM recording_files WHERE recording_id=?',(r['id'],))
                db.execute('DELETE FROM recordings WHERE id=?',(r['id'],))
            db.execute('DELETE FROM athletes WHERE id=?',(athlete_id,))
        for r in shelves:shutil.rmtree(base.recording_path(r),ignore_errors=True)
        return {'deleted':True,'id':athlete_id}

    @router.delete('/shelf-teams/{team_id}')
    def remove_team(team_id:str):
        with LOCK,dbconn() as db:
            base.must_get(db,'teams',team_id)
            aids=[r['id'] for r in db.execute('SELECT id FROM athletes WHERE team_id=?',(team_id,))]
            shelves=[]
            for aid in aids:
                shelves.extend(dict(r) for r in db.execute('SELECT * FROM recordings WHERE athlete_id=?',(aid,)))
            shelf_ids=[r['id'] for r in shelves]
            marks=','.join('?'*len(aids)) if aids else ''
            shelf_marks=','.join('?'*len(shelf_ids)) if shelf_ids else ''
            clauses=['team_id=?','target_id=?']
            params=[team_id,team_id]
            if aids:
                clauses.append(f'athlete_id IN ({marks})')
                clauses.append(f'target_id IN ({marks})')
                params.extend(aids);params.extend(aids)
            if shelf_ids:
                clauses.append(f'target_id IN ({shelf_marks})')
                clauses.append(f'test_recording_id IN ({shelf_marks})')
                params.extend(shelf_ids);params.extend(shelf_ids)
            busy=db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND ("+' OR '.join(clauses)+')',params).fetchone()[0]
            if busy:
                raise HTTPException(409,'Wait until the analysis using this team finishes before deleting it.')
            for r in shelves:
                db.execute('DELETE FROM recording_files WHERE recording_id=?',(r['id'],))
                db.execute('DELETE FROM recordings WHERE id=?',(r['id'],))
            db.execute('DELETE FROM athletes WHERE team_id=?',(team_id,))
            db.execute('DELETE FROM teams WHERE id=?',(team_id,))
        for r in shelves:shutil.rmtree(base.recording_path(r),ignore_errors=True)
        return {'deleted':True,'id':team_id}

    @router.delete('/shelves/{shelf_id}/files/{file_id}')
    def remove_file(shelf_id:str,file_id:str):
        with LOCK,dbconn() as db:
            shelf=base.must_get(db,'recordings',shelf_id)
            row=db.execute('SELECT * FROM recording_files WHERE id=? AND recording_id=?',(file_id,shelf_id)).fetchone()
            if not row:raise HTTPException(404,'File not in EEG shelf.')
            busy=db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND target_id=?",(shelf_id,)).fetchone()[0]
            if busy:raise HTTPException(409,'EEG shelf is currently in processing.')
            db.execute('DELETE FROM recording_files WHERE id=?',(file_id,))
            remains=[r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?',(shelf_id,))]
            signal=next((n for n in remains if n.lower().endswith(SIGNALS)),'')
            db.execute('UPDATE recordings SET source_name=? WHERE id=?',(signal,shelf_id))
        shelf_file(base.recording_path(shelf), row['name']).unlink(missing_ok=True)
        return {'deleted':True}

    @router.post('/shelves/{shelf_id}/files',status_code=201)
    async def append_files(shelf_id:str, uploads:list[UploadFile]=File(...), slot:str=Form('signal')):
        if slot not in ('signal','companion','events'):raise HTTPException(422,'Select signal, companion, or events.')
        if not uploads or len(uploads)>MAX_FILES:raise HTTPException(422,'Select 1–24 files.')
        names=[base.safe_name(f.filename or '') for f in uploads]
        if len({n.casefold() for n in names})!=len(names):raise HTTPException(422,'Duplicate file names in upload.')
        with dbconn() as db:
            shelf=base.must_get(db,'recordings',shelf_id)
            existing=[r['name'] for r in db.execute('SELECT name FROM recording_files WHERE recording_id=?',(shelf_id,))]
        if set(n.casefold() for n in existing)&set(n.casefold() for n in names):
            raise HTTPException(409,'That file already exists in this EEG shelf. Remove it first to replace.')
        if len(existing)+len(names)>MAX_FILES:raise HTTPException(422,'Too many files in EEG shelf.')
        existing_signal=sum(n.lower().endswith(SIGNALS) for n in existing)
        new_signals=sum(n.lower().endswith(SIGNALS) for n in names)
        if existing_signal+new_signals>1:raise HTTPException(422,'Each EEG shelf holds one signal recording. Add a second shelf for another EEG.')
        if slot=='signal' and any(not n.lower().endswith(SIGNALS) for n in names):
            raise HTTPException(422,'The signal slot accepts .set, .edf, .bdf, .vhdr, .fif or .fif.gz only.')
        if slot=='companion' and any(not n.lower().endswith(('.fdt','.eeg','.vmrk')) for n in names):
            raise HTTPException(422,'Companion slot accepts .fdt, .eeg or .vmrk.')
        if slot=='events' and any(not n.lower().endswith(('.tsv','.csv','.json','.txt')) for n in names):
            raise HTTPException(422,'Annotation slot accepts .tsv, .csv, .json or .txt.')
        dest=base.recording_path(shelf)
        dest.mkdir(parents=True,exist_ok=True)
        saved=[]
        try:
            for upload,name in zip(uploads,names):
                amount=0
                with (dest/name).open('xb') as out:
                    while block:=await upload.read(1024*1024):
                        amount+=len(block)
                        if amount>base.MAX_FILE_BYTES:raise HTTPException(413,'File too large.')
                        out.write(block)
                if not amount:raise HTTPException(422,'Empty file: '+name)
                saved.append((name,amount))
            with LOCK,dbconn() as db:
                base.must_get(db,'recordings',shelf_id)
                for name,amount in saved:db.execute('INSERT INTO recording_files VALUES(?,?,?,?)',(str(uuid4()),shelf_id,name,amount))
                all_names=existing+names
                primary=next((n for n in all_names if n.lower().endswith(SIGNALS)),'')
                db.execute('UPDATE recordings SET source_name=? WHERE id=?',(primary,shelf_id))
        except Exception:
            for name,_ in saved:(dest/name).unlink(missing_ok=True)
            for name in names:(dest/name).unlink(missing_ok=True)
            raise
        return {'id':shelf_id,'uploaded':[n for n,_ in saved],'file_count':len(existing)+len(saved)}

    def ready_shelves(db,athlete_id,task=None):
        records=[dict(r) for r in db.execute('SELECT * FROM recordings WHERE athlete_id=? ORDER BY created_at,rowid',(athlete_id,))]
        if task:records=[r for r in records if r['task_type']==task]
        files={r['recording_id']:[] for r in db.execute('SELECT recording_id FROM recording_files')}
        for f in db.execute('SELECT recording_id,name FROM recording_files'):
            files.setdefault(f['recording_id'],[]).append(f['name'])
        return [r for r in records if any(n.lower().endswith(SIGNALS) for n in files.get(r['id'],[]))]

    def choose_comparison(db,athlete_id,task,selected_test=None):
        records=ready_shelves(db,athlete_id,task)
        tests=[r for r in records if r['classification']=='testing']
        test=next((r for r in tests if r['id']==selected_test),None) if selected_test else (tests[-1] if tests else None)
        if test is None:raise ValueError('Upload at least one Testing EEG for the selected task.')
        task=test['task_type']
        bases=[r for r in records if r['classification']=='baseline' and r['task_type']==task]
        needed=baseline_minimum(task)
        if len(bases)<needed:
            raise ValueError(f'At least {needed} uploaded Baseline EEG shelves with the same Test Type ({task}) are needed; found {len(bases)}.')
        return bases,test

    def run_single(rec,dest,req):
        out=base.process(base.recording_path(rec),dest,artifact_mode=req.get('artifact_mode','legacy'),mains_frequency_hz=req.get('mains_frequency_hz',60))
        if len(out)!=1:raise ValueError('Expected exactly one EEG recording.')
        report=out[0][0]
        actual=report.get('classification',{}).get('task_family','UNKNOWN').lower()
        selected=rec.get('task_type','unspecified')
        mismatch=selected!='unspecified' and actual!='unknown' and actual!=selected
        return {'mode':'single','recording_id':rec['id'],'analysis':report,
                'task_selected':selected,'task_detected':actual,
                'task_warning':f'Selected {selected}, but EEG events/metadata indicate {actual}. Review the task object/annotations.' if mismatch else None,
                'entrypoint':'report.html','package':'report.zip'}

    def run_comparison(db,aid,task,dest,req,test_recording_id=None):
        athlete=base.must_get(db,'athletes',aid)
        bases,test=choose_comparison(db,aid,task,test_recording_id)
        paths=[base.recording_path(r) for r in bases]
        struct=base.run_athlete_workflow(paths,base.recording_path(test),dest,team_id=athlete['team_id'],athlete_id=aid,
                artifact_mode=req.get('artifact_mode','legacy'),mains_frequency_hz=req.get('mains_frequency_hz',60),
                min_baselines=baseline_minimum(test['task_type']))
        comparison=json.loads((dest/'comparative_analysis.json').read_text())
        baseline=json.loads((dest/'baseline'/'longitudinal.json').read_text())
        individual=[{'classification':'baseline','result':json.loads((dest/i['report_json']).read_text()),
                     'entrypoint':i['report_html']} for i in struct['baseline_reports']]
        individual.append({'classification':'testing','result':json.loads((dest/'test'/'report.json').read_text()),'entrypoint':'test/report.html'})
        return {'mode':'athlete','athlete_id':aid,'team_id':athlete['team_id'],
                'task_type':test['task_type'],'comparison':comparison,'baseline':baseline,'individual':individual,
                'summary':struct['comparison_summary'],'entrypoint':'athlete_report.html','package':'athlete_report.zip'}

    def run_job(job_id,req):
        with LOCK,dbconn() as db:
            db.execute("UPDATE jobs SET status='running',updated_at=?,error=NULL WHERE id=?",(base.now(),job_id))
        dest=base.REPORTS/job_id;dest.mkdir(parents=True,exist_ok=True)
        try:
            if req['mode']=='single':
                with dbconn() as db:rec=base.must_get(db,'recordings',req['target_id'])
                result=run_single(rec,dest,req)
            elif req['mode']=='athlete':
                with dbconn() as db:result=run_comparison(db,req['target_id'],req.get('task_type'),dest,req,req.get('test_recording_id'))
            else:
                with dbconn() as db:
                    base.must_get(db,'teams',req['target_id'])
                    athletes=[dict(r) for r in db.execute('SELECT * FROM athletes WHERE team_id=? ORDER BY name',(req['target_id'],))]
                members=[]
                for a in athletes:
                    member_dest=dest/'athletes'/a['id'];member_dest.mkdir(parents=True,exist_ok=True)
                    try:
                        with dbconn() as db:one=run_comparison(db,a['id'],req.get('task_type'),member_dest,req)
                        members.append({'athlete_id':a['id'],'athlete_name':a['name'],'status':'completed',
                            'relative_report':f'athletes/{a["id"]}/athlete_report.html','result':one})
                    except Exception as exc:
                        members.append({'athlete_id':a['id'],'athlete_name':a['name'],'status':'skipped','message':str(exc)})
                if not any(m['status']=='completed' for m in members):
                    raise ValueError('No athletes have enough compatible uploaded baseline EEGs and 1 testing EEG for this task. Oddball needs 2 baselines; sleep, motor, and unspecified need 3.')
                result={'mode':'team','team_id':req['target_id'],'members':members,'task_type':req.get('task_type'),'entrypoint':None}
            with LOCK,dbconn() as db:
                db.execute("UPDATE jobs SET status='completed',result=?,error=NULL,updated_at=? WHERE id=?",
                    (json.dumps(json_safe(result),allow_nan=False),base.now(),job_id))
        except Exception as exc:
            with LOCK,dbconn() as db:
                db.execute("UPDATE jobs SET status='failed',error=?,updated_at=? WHERE id=?",
                    (f'{type(exc).__name__}: {str(exc)[:1600]}',base.now(),job_id))

    @router.post('/shelf-jobs',status_code=202)
    def create_job(req:BatchRequest):
        if req.mode not in ('single','athlete','team'):raise HTTPException(422,'Select Single EEG, Test Athlete, or Test Team.')
        if req.artifact_mode not in ('legacy','experimental') or req.mains_frequency_hz not in (50,60):
            raise HTTPException(422,'Unsupported EEG processing settings.')
        if req.task_type:ensure_task(req.task_type)
        with LOCK,dbconn() as db:
            if req.mode=='single':
                rec=base.must_get(db,'recordings',req.target_id)
                if not rec['source_name']:raise HTTPException(422,'Upload an EEG signal to this shelf first.')
                athlete=base.must_get(db,'athletes',rec['athlete_id']);aid=athlete['id'];tid=athlete['team_id']
            elif req.mode=='athlete':
                athlete=base.must_get(db,'athletes',req.target_id);aid=athlete['id'];tid=athlete['team_id']
                try:choose_comparison(db,aid,req.task_type,req.test_recording_id)
                except ValueError as exc:raise HTTPException(422,str(exc))
            else:
                base.must_get(db,'teams',req.target_id);tid=req.target_id;aid=None
            key=str(uuid4())
            db.execute('INSERT INTO jobs(id,mode,target_id,test_recording_id,created_at,updated_at,status,error,result,result_dir,team_id,athlete_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (key,req.mode,req.target_id,req.test_recording_id,base.now(),base.now(),'queued',None,None,key,tid,aid))
        base.WORKERS.submit(run_job,key,req.model_dump())
        return {'id':key,'status':'queued','mode':req.mode}

    @router.get('/shelf-advanced')
    def advanced_packages():
        """Index per-athlete result packages, including analyses from a team batch."""
        with dbconn() as db:
            teams=[dict(r) for r in db.execute('SELECT id,name FROM teams ORDER BY name')]
            athletes=[dict(r) for r in db.execute('SELECT id,team_id,name FROM athletes ORDER BY name')]
            jobs=[dict(r) for r in db.execute("SELECT id,mode,athlete_id,team_id,created_at,result FROM jobs WHERE status='completed' ORDER BY created_at DESC")]
            recordings=[dict(r) for r in db.execute('SELECT id,athlete_id,classification,task_type,source_name,created_at FROM recordings ORDER BY created_at,rowid')]
            file_rows=[dict(r) for r in db.execute('SELECT recording_id,name,size_bytes FROM recording_files ORDER BY rowid')]
        groups=[]
        for t in teams:
            members=[]
            for a in athletes:
                if a['team_id']!=t['id']:continue
                reports=[]
                for j in jobs:
                    if j['mode'] in ('single','athlete') and j['athlete_id']==a['id']:
                        reports.append({'id':j['id'],'mode':j['mode'],'created_at':j['created_at'],'member_athlete_id':None})
                    elif j['mode']=='team' and j['team_id']==t['id'] and j['result']:
                        data=json.loads(j['result'])
                        if any(m.get('status')=='completed' and m.get('athlete_id')==a['id'] for m in data.get('members',[])):
                            reports.append({'id':j['id'],'mode':'team','created_at':j['created_at'],'member_athlete_id':a['id']})
                shelves=[]
                for rec in recordings:
                    if rec['athlete_id']!=a['id']:continue
                    names=[item['name'] for item in file_rows if item['recording_id']==rec['id']]
                    shelves.append({'id':rec['id'],'classification':rec['classification'],'task_type':rec['task_type'],
                        'source_name':rec['source_name'] or '','file_count':len(names),
                        'bytes':sum(item['size_bytes'] for item in file_rows if item['recording_id']==rec['id'])})
                if reports:members.append({'id':a['id'],'name':a['name'],'reports':reports,'shelves':shelves})
            if members:groups.append({'id':t['id'],'name':t['name'],'athletes':members})
        return {'teams':groups,'ai_connected':False,'pipeline_version':base.PIPELINE_VERSION}

    # Public metadata browser. Fixed upstream host, validated dataset IDs, read-only GraphQL.
    @router.get('/openneuro/{dataset_id}')
    async def openneuro_dataset(dataset_id:str):
        ds=parse_dataset_id(dataset_id)
        # Dataset and snapshot ids are GraphQL ID!, not String!.
        query='query($id:ID!){dataset(id:$id){id name latestSnapshot{tag description{Name DatasetDOI}}}}'
        data=await graphql(query,{'id':ds})
        found=data.get('dataset')
        if not found:raise HTTPException(404,'Dataset unavailable or not public.')
        snap=found.get('latestSnapshot') or {}
        tag=snap.get('tag')
        if not tag:raise HTTPException(404,'Dataset has no public snapshot.')
        description=snap.get('description') or {}
        return {'id':found['id'],'name':found.get('name') or ds,'tag':tag,
                'description':description.get('Name') or '','doi':description.get('DatasetDOI') or ''}

    @router.get('/openneuro/{dataset_id}/tree')
    async def openneuro_tree(dataset_id:str,tag:str=Query(...,min_length=1,max_length=80),tree:str|None=None):
        ds=parse_dataset_id(dataset_id)
        if not re.fullmatch(r'[0-9A-Za-z._-]{1,80}',tag):raise HTTPException(422,'Invalid snapshot version.')
        if tree and not re.fullmatch(r'[a-f0-9]{40,64}',tree):raise HTTPException(422,'Invalid tree ID.')
        query='query($id:ID!,$tag:String!,$tree:String){snapshot(datasetId:$id,tag:$tag){files(tree:$tree){id filename size directory annexed}}}'
        data=await graphql(query,{'id':ds,'tag':tag,'tree':tree})
        if not data.get('snapshot'):raise HTTPException(404,'Public snapshot not available.')
        items=data['snapshot'].get('files') or []
        if len(items)>3000:raise HTTPException(413,'Folder too large to display at once.')
        return {'dataset_id':ds,'tag':tag,'tree':tree,'files':items}

    app.include_router(router)


def parse_dataset_id(value):
    m=re.fullmatch(r'(?:https?://openneuro\.org/datasets/)?(ds\d{6,8})(?:/.*)?',value.strip(),re.I)
    if not m:raise HTTPException(422,'Enter a valid OpenNeuro accession such as ds000224.')
    return m.group(1).lower()

def json_safe(value):
    """Store pipeline JSON without changing calculations. Non-finite floats cannot be strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def _source_summary(raw):
    if not raw:
        return None
    try:
        ref = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(ref, dict):
        return None
    keys = ('provider','dataset_id','snapshot','dataset_name','task_selected','task_detected','validation','primary_path','imported_at')
    return {key: ref.get(key) for key in keys}


async def graphql(query,variables):
    """Patched by the existing connector test. Delegates to the OpenNeuro provider client."""
    return await _openneuro_graphql(query, variables)
