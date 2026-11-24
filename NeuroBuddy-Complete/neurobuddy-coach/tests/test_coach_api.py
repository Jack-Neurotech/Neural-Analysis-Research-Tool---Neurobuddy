"""End-to-end checks with synthetic, non-human EEG. No external network required."""
import importlib
import io
import os
import sys
import time
from pathlib import Path

import mne
import numpy as np
from fastapi.testclient import TestClient


def make_fif(filename):
    info=mne.create_info(['C3','C4'],100,['eeg','eeg'])
    t=np.arange(900)/100
    raw=mne.io.RawArray(np.vstack([10e-6*np.sin(t*2*np.pi*10),
                                    7e-6*np.sin(t*2*np.pi*16)]),info,verbose='ERROR')
    raw.save(filename,overwrite=True,verbose='ERROR')
    raw.close()


def test_single_run_and_persistence(tmp_path,monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR',str(tmp_path/'db'))
    sys.modules.pop('backend.app',None)
    app_module=importlib.import_module('backend.app')
    cli=TestClient(app_module.app)
    assert cli.get('/').status_code==200
    for address in ('/Index.html', '/index.html', '/favicon.svg', '/favicon.ico'):
        assert cli.get(address).status_code==200
    assert 'test-recording-select' not in cli.get('/').text
    assert '0.7.1' in cli.get('/api/v2/health').json()['engine']
    team=cli.post('/api/v2/teams',json={'name':'Coaching Demo'}).json()
    ath=cli.post(f'/api/v2/teams/{team["id"]}/athletes',json={'name':'Athlete A'}).json()
    eeg=tmp_path/'sub-001_task-rest_run-1_eeg.fif'
    make_fif(eeg)
    with eeg.open('rb') as fh:
        record=cli.post(f'/api/v2/athletes/{ath["id"]}/recordings',
             data={'classification':'testing'},files=[('uploads',(eeg.name,fh,'application/octet-stream'))])
    assert record.status_code==201,record.text
    rec=record.json()
    tree=cli.get('/api/v2/library').json()['teams']
    assert tree[0]['athletes'][0]['recordings'][0]['id']==rec['id']
    j=cli.post('/api/v2/jobs',json={'mode':'single','target_id':rec['id']})
    assert j.status_code==202,j.text
    job=j.json()['id']
    deadline=time.time()+100
    while time.time()<deadline:
        record=cli.get('/api/v2/jobs/'+job).json()
        if record['status'] in ('completed','failed'):break
        time.sleep(.3)
    assert record['status']=='completed',record.get('error')
    assert record['result']['analysis']['pipeline_version']=='0.7.1-optimized'
    assert record['result']['analysis']['processing_status']=='COMPLETE'
    assert cli.get(f'/api/v2/artifacts/{job}/report.html').status_code==200
    assert cli.get(f'/api/v2/artifacts/{job}/report.zip').status_code==200
    assert cli.get(f'/api/v2/artifacts/{job}/../../coach.sqlite3').status_code!=200
    assert len(cli.get('/api/v2/advanced').json()['teams'])==1
    assert cli.get('/api/v2/jobs').json()['jobs'][0]['status']=='completed'
