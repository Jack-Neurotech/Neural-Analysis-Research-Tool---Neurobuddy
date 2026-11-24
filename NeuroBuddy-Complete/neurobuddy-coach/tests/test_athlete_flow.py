"""Four real synthetic EEG analyses and athlete comparison. Optional slow E2E check."""
import importlib
import sys
import time
import numpy as np
import mne
from fastapi.testclient import TestClient


def test_baseline_three_plus_test(tmp_path,monkeypatch):
    monkeypatch.setenv('NEUROBUDDY_DATA_DIR',str(tmp_path/'data'))
    sys.modules.pop('backend.app',None)
    module=importlib.import_module('backend.app')
    client=TestClient(module.app)
    team=client.post('/api/v2/teams',json={'name':'Team B'}).json()
    athlete=client.post(f'/api/v2/teams/{team["id"]}/athletes',json={'name':'Runner B'}).json()
    recordings=[]
    for i in range(4):
        t=np.arange(900)/100
        info=mne.create_info(['C3','C4'],100,['eeg','eeg'])
        amplitude=(6+i)*1e-6
        signal=np.vstack([amplitude*np.sin(2*np.pi*10*t),amplitude*.6*np.sin(2*np.pi*15*t)])
        raw=mne.io.RawArray(signal,info,verbose='ERROR')
        fn=tmp_path/f'sub-001_task-rest_run-{i+1}_eeg.fif'
        raw.save(fn,overwrite=True,verbose='ERROR');raw.close()
        with fn.open('rb') as fh:
            r=client.post(f'/api/v2/athletes/{athlete["id"]}/recordings',
              data={'classification':'baseline' if i<3 else 'testing'},
              files=[('uploads',(fn.name,fh,'application/octet-stream'))])
        assert r.status_code==201,r.text
        recordings.append(r.json()['id'])
    # No separate frontend testing dropdown: backend picks latest testing EEG.
    response=client.post('/api/v2/jobs',json={'mode':'athlete','target_id':athlete['id']})
    assert response.status_code==202,response.text
    job=response.json()['id']
    assert client.get('/api/v2/jobs/'+job).json()['test_recording_id']==recordings[-1]
    end=time.time()+120
    while time.time()<end:
        result=client.get('/api/v2/jobs/'+job).json()
        if result['status'] in ('completed','failed'):break
        time.sleep(.5)
    assert result['status']=='completed',result.get('error')
    assert result['result']['baseline']['baseline_recording_count']==3
    assert result['result']['comparison']['summary']['total']>0
    assert result['result']['individual'][-1]['result']['pipeline_version']=='0.7.1-optimized'
    assert client.get(f'/api/v2/artifacts/{job}/athlete_report.html').status_code==200
    assert client.get(f'/api/v2/artifacts/{job}/comparative_analysis.csv').status_code==200
