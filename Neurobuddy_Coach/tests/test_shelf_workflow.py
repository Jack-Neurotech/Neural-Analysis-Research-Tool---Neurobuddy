"""Live FastAPI adapter regression checks, including actual optimized EEG processing."""
from __future__ import annotations
import io
import time
import mne
import numpy as np
import pytest
from fastapi.testclient import TestClient


def create_synthetic_fif(tmp_path,index):
    t=np.arange(900)/100
    info=mne.create_info(['C3','C4'],100,['eeg','eeg'])
    signal=np.vstack([(6+index)*1e-6*np.sin(2*np.pi*10*t),
                      (4+index)*1e-6*np.sin(2*np.pi*15*t)])
    raw=mne.io.RawArray(signal,info,verbose='ERROR')
    path=tmp_path/f'sub-01_task-rest_run-{index+1}_eeg.fif'
    raw.save(path,overwrite=True,verbose='ERROR');raw.close()
    return path


def await_job(client,job_id,timeout=90):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        result=client.get('/api/v2/jobs/'+job_id).json()
        if result['status'] in ('completed','failed'):
            return result
        time.sleep(.25)
    raise AssertionError('Job did not finish')


def test_shelf_lifecycle_and_latest_pipeline(tmp_path,monkeypatch):
    # Import fresh application with isolated persistent storage.
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR',str(tmp_path/'storage'))
    import importlib,sys
    sys.modules.pop('backend.app',None)
    backend=importlib.import_module('backend.app')
    client=TestClient(backend.app)
    team=client.post('/api/v2/shelf-teams',json={'name':'Runners'}).json()
    athlete=client.post(f'/api/v2/shelf-teams/{team["id"]}/athletes?task_type=unspecified',json={'name':'James'}).json()
    a=athlete['id']
    lib=client.get('/api/v2/shelf-library').json()
    assert len(lib['teams'])==1
    shelves=lib['teams'][0]['athletes'][0]['shelves']
    assert [s['classification'] for s in shelves]==['baseline','baseline','baseline','testing']
    assert not any(s['ready'] for s in shelves)
    assert client.post('/api/v2/shelf-jobs',json={'mode':'athlete','target_id':a}).status_code==422
    for i,shelf in enumerate(shelves):
        path=create_synthetic_fif(tmp_path,i)
        with path.open('rb') as fh:
            resp=client.post(f'/api/v2/shelves/{shelf["id"]}/files',data={'slot':'signal'},
                files={'uploads':(path.name,fh,'application/octet-stream')})
        assert resp.status_code==201,resp.text
    job=client.post('/api/v2/shelf-jobs',json={'mode':'athlete','target_id':a,
            'artifact_mode':'experimental','mains_frequency_hz':60})
    assert job.status_code==202,job.text
    result=await_job(client,job.json()['id']);assert result['status']=='completed',result['error']
    assert result['result']['baseline']['baseline_recording_count']==3
    assert result['result']['individual'][-1]['result']['pipeline_version']=='0.7.1-optimized'
    assert result['result']['individual'][-1]['result']['provenance']['artifact_mode']=='experimental'
    assert client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves'][0]['ready']
    assert client.get('/api/v2/artifacts/'+job.json()['id']+'/athlete_report.html').status_code==200
    # A team object can schedule separate athlete baselines; results become Advanced packages.
    batch=client.post('/api/v2/shelf-jobs',json={'mode':'team','target_id':team['id'],'task_type':'unspecified'})
    assert batch.status_code==202,batch.text
    batch_result=await_job(client,batch.json()['id'])
    assert batch_result['status']=='completed',batch_result.get('error')
    assert batch_result['result']['members'][0]['status']=='completed'
    advanced=client.get('/api/v2/shelf-advanced').json()
    items=advanced['teams'][0]['athletes'][0]['reports']
    assert any(item['mode']=='team' and item['id']==batch.json()['id'] for item in items)
    # File / shelf operations, deletion and storage separation.
    r=client.post(f'/api/v2/shelves/{shelves[0]["id"]}/files',data={'slot':'companion'},
        files={'uploads':('part.fdt',io.BytesIO(b'companion'),'application/octet-stream')})
    assert r.status_code==201
    r=client.post(f'/api/v2/shelves/{shelves[0]["id"]}/files',data={'slot':'signal'},
        files={'uploads':('extra.fif',io.BytesIO(b'extra'),'application/octet-stream')})
    assert r.status_code==422
    delete=client.delete(f'/api/v2/shelves/{shelves[0]["id"]}')
    assert delete.status_code==200
    deleted=client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves']
    assert len(deleted)==3


def test_file_validation_and_team_persistence(tmp_path,monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR',str(tmp_path/'storage'))
    import importlib,sys
    sys.modules.pop('backend.app',None)
    backend=importlib.import_module('backend.app');client=TestClient(backend.app)
    team=client.post('/api/v2/shelf-teams',json={'name':'Team B'}).json();t=team['id']
    athlete=client.post(f'/api/v2/shelf-teams/{t}/athletes?task_type=oddball',json={'name':'S'}).json();aid=athlete['id']
    shelves=client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves'];sid=shelves[0]['id']
    r=client.post(f'/api/v2/shelves/{sid}/files',data={'slot':'signal'},files={'uploads':('events.tsv',io.BytesIO(b'a'),'text/plain')})
    assert r.status_code==422
    assert client.patch(f'/api/v2/shelves/{sid}',json={'task_type':'not-a-task'}).status_code==422
    r=client.post(f'/api/v2/shelves/{sid}/files',data={'slot':'events'},files={'uploads':('task-events.tsv',io.BytesIO(b'onset\tduration\n0\t1'),'text/plain')})
    assert r.status_code==201
    # Upload separately and mark metadata present before signal exists.
    assert not client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves'][0]['ready']
    assert client.get('/api/v2/shelf-library').json()['teams'][0]['athletes'][0]['shelves'][0]['files'][0]['name']=='task-events.tsv'
    assert client.delete(f'/api/v2/shelf-athletes/{aid}').status_code==200
    assert client.get('/api/v2/shelf-library').json()['teams'][0]['athletes']==[]
    assert client.delete(f'/api/v2/shelf-teams/{t}').status_code==200
    assert client.get('/api/v2/shelf-library').json()['teams']==[]


def test_openneuro_tree_mocked(tmp_path,monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR',str(tmp_path/'storage'))
    import importlib,sys
    sys.modules.pop('backend.app',None)
    backend=importlib.import_module('backend.app');client=TestClient(backend.app)
    import backend.shelves as shelves
    async def mock_gql(query,params):
        if 'latestSnapshot' in query:return {'dataset':{'id':'ds000224','name':'Test public EEG','latestSnapshot':{'tag':'1.0.3'}}}
        return {'snapshot':{'files':[
            {'id':'a'*40,'filename':'sub-01','size':0,'directory':True,'annexed':False},
            {'id':'b'*40,'filename':'sub-01_task-P300_events.tsv','size':40,'directory':False,'annexed':True},
            {'id':'c'*40,'filename':'tone.wav','size':80,'directory':False,'annexed':True},
            {'id':'d'*40,'filename':'.datalad','size':0,'directory':True,'annexed':False},
        ]}}
    monkeypatch.setattr(shelves,'graphql',mock_gql)
    assert client.get('/api/v2/openneuro/ds000224').json()['tag']=='1.0.3'
    listed=client.get('/api/v2/openneuro/ds000224/tree?tag=1.0.3').json()['files']
    assert [item['filename'] for item in listed]==['sub-01','sub-01_task-P300_events.tsv','tone.wav','.datalad']
    assert client.get('/api/v2/openneuro/invalid').status_code==422
