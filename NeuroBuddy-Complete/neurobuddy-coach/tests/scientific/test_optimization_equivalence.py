"""Performance-related implementation checks with no changes to science."""
from dataclasses import replace

import mne
import numpy as np
import pytest

from neurobuddy_v2.artifact_detection import (
    ArtifactConfig, _window_batches, _window_data,
    _line_prominence, _line_prominences_batch, detect_artifacts,
)
from neurobuddy_v2.reporting import schema_check


def _recording(sfreq=256, seconds=11, inject_nonfinite=False):
    rng=np.random.default_rng(724)
    times=np.arange(int(sfreq*seconds))/sfreq
    x=12e-6*np.sin(2*np.pi*9*times)+rng.normal(0,1e-6,len(times))
    if inject_nonfinite:
        x[200:205]=np.nan
    info=mne.create_info(['C3'],sfreq,['eeg'])
    return mne.io.RawArray(x[np.newaxis,:],info,verbose='ERROR')


@pytest.mark.parametrize('window,hop,chunk',[(256,128,1536),(1024,512,2560),(100,25,200)])
def test_batched_windows_preserve_absolute_samples(window,hop,chunk):
    raw=_recording(inject_nonfinite=True)
    original=list(_window_data(raw,'C3',window,hop,chunk))
    optimized=[]
    for starts,views in _window_batches(raw,'C3',window,hop,chunk):
        optimized.extend((int(a),int(a)+window,row.copy()) for a,row in zip(starts,views))
    assert len(original)==len(optimized)
    for (start_a,end_a,signal_a),(start_b,end_b,signal_b) in zip(original,optimized):
        assert (start_a,end_a)==(start_b,end_b)
        np.testing.assert_array_equal(signal_a,signal_b)


@pytest.mark.parametrize('mains', [50.,60.])
def test_batched_line_spectral_detector_preserves_values(mains):
    raw=_recording(seconds=21)
    x=raw.get_data(picks=['C3'])[0]
    windows=np.stack([x[i:i+1024] for i in range(0,len(x)-1024+1,512)])
    expected=[_line_prominence(window,256,mains) for window in windows]
    actual=_line_prominences_batch(windows,256,mains)
    np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-12)


def test_batched_line_handles_nonfinite_and_unassessable():
    a=np.arange(1024,dtype=float)
    data=np.stack([a,a.copy()]);data[1,0]=np.nan
    assert _line_prominences_batch(data,100,60.)==[None,None]
    assert _line_prominences_batch(data,256,60.)==[
        _line_prominence(a,256,60),None]


def test_reference_configuration_does_not_change_detection_intervals():
    raw=_recording(seconds=27)
    raw._data[0,256*9:256*11]=0
    cfg=ArtifactConfig(read_chunk_seconds=5)
    a=detect_artifacts(raw,config=cfg)
    b=detect_artifacts(raw,config=replace(cfg,read_chunk_seconds=21))
    assert [(i['channel'],i['artifact_type'],i['start_s'],i['end_s'],i['feature_values'])
            for i in a['events']] == [(i['channel'],i['artifact_type'],i['start_s'],i['end_s'],i['feature_values'])
                                   for i in b['events']]


def test_fast_report_validation_rejects_schema_violations():
    report={
        'schema_version':'2.0.0', 'pipeline_version':'0.7.0-research','report_id':'nb-abcde',
        'processing_status':'COMPLETE','input_manifest':[],
        'classification':{'task_family':'GENERAL','status':'READY','evidence':[],
                          'analysis_readiness':{'shared_eeg':True}},
        'routing':{},'recording':{'file':'test.fif','sample_rate_hz':256},
        'quality':{},'shared_metrics':{},'specialized_metrics':{},'statistics':{},
        'visualizations':{},'events':{'count':0,'normalized':[]},
        'warnings':[],'errors':[],
        'provenance':{'created_utc':'2026-01-01T00:00:00+00:00','mne_version':'1.11.0'}
    }
    assert schema_check(report) is True
    altered={**report,'processing_status':'NOT_A_STATUS'}
    with pytest.raises(Exception):
        schema_check(altered)
    altered={**report,'input_manifest':[{'name':'x','bytes':2,'sha256':'invalid'}]}
    with pytest.raises(Exception):
        schema_check(altered)
    altered={**report,'events':{'count':-1,'normalized':[]}}
    with pytest.raises(Exception):
        schema_check(altered)
