"""Experimental quality layer: controlled cases, invariance, and safety checks."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import zipfile

import mne
import numpy as np
import pytest

from neurobuddy_v2.artifact_detection import ArtifactConfig, detect_artifacts
from neurobuddy_v2.pipeline import process
from neurobuddy_v2.comparative import build_comparison


def _raw(seed=7, sf=256, seconds=24, channels=2):
    t=np.arange(int(seconds*sf))/sf
    rng=np.random.default_rng(seed)
    data=np.array([8e-6*np.sin(2*np.pi*(9+i)*t) + rng.normal(0,0.7e-6,t.size)
                   for i in range(channels)])
    info=mne.create_info([f'C{i+1}' for i in range(channels)],sf,['eeg']*channels)
    return mne.io.RawArray(data,info,verbose='ERROR')


def _hits(result, kind, channel, start, end):
    return [e for e in result['events'] if e['artifact_type']==kind and e['channel']==channel
            and e['start_s']<end and e['end_s']>start]


def test_flatline_and_burst_have_localized_evidence_and_non_destructive():
    raw=_raw(); original=raw.get_data().copy(); sf=256
    raw._data[0,8*sf:12*sf]=0
    raw._data[0,15*sf:17*sf]*=10
    before=raw.get_data().copy()
    result=detect_artifacts(raw)
    assert _hits(result,'possible_local_dropout','C1',8,12)
    assert _hits(result,'high_rms_burst_candidate','C1',15,17)
    assert result['quality_mask_intervals']['C1']
    assert result['artifact_correction_performed'] is False
    assert result['downstream_mask_applied'] is False
    assert np.array_equal(raw.get_data(),before)
    assert not _hits(result,'possible_local_dropout','C2',8,12)
    assert not _hits(result,'high_rms_burst_candidate','C2',15,17)


def test_clean_periodic_eeg_not_falsely_flagged_as_flatline_or_burst():
    result=detect_artifacts(_raw(seed=1))
    assert not any(e['artifact_type'] in ('possible_local_dropout','high_rms_burst_candidate')
                   for e in result['events'])


def test_line_noise_configurable_and_nyquist_unassessable():
    sf=256
    raw=_raw(sf=sf)
    t=np.arange(raw.n_times)/sf
    raw._data[0]+=24e-6*np.sin(2*np.pi*50*t)
    c=ArtifactConfig(mains_frequency_hz=50)
    result=detect_artifacts(raw,config=c)
    assert _hits(result,'possible_mains_interference','C1',0,24)
    assert any(e['feature_values']['mains_frequency_hz']==50 for e in result['events'] if e['artifact_type']=='possible_mains_interference')
    low=_raw(sf=100)
    r=detect_artifacts(low,config=ArtifactConfig(mains_frequency_hz=60))
    assert any(x['detector']=='mains_spectral_prominence' for x in r['unassessable'])
    assert not any(x['artifact_type']=='possible_mains_interference' for x in r['events'])


def test_window_boundaries_independent_of_reader_chunk_and_preload():
    r=_raw(seconds=27);r._data[0,12*256:16*256]=0
    c=ArtifactConfig(read_chunk_seconds=5)
    expected=detect_artifacts(r,config=c)
    other=detect_artifacts(r,config=replace(c,read_chunk_seconds=18))
    assert [(e['channel'], e['artifact_type'], e['start_s'], e['end_s']) for e in expected['events']] == [(e['channel'], e['artifact_type'], e['start_s'], e['end_s']) for e in other['events']]
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'sub-001_task-rest_eeg.fif'
        r.save(path,verbose='ERROR')
        lazy=mne.io.read_raw_fif(path,preload=False,verbose='ERROR')
        actual=detect_artifacts(lazy,config=c)
        assert [(a['channel'],a['artifact_type'],a['start_s'],a['end_s']) for a in actual['events']] == [
            (a['channel'],a['artifact_type'],a['start_s'],a['end_s']) for a in expected['events']]
        lazy.close()


def test_short_recording_explicitly_unassessable():
    r=_raw(seconds=1)
    x=detect_artifacts(r)
    assert any(x['detector']=='windowed_amplitude' for x in x['unassessable'])
    assert any(x['detector']=='mains_spectral_prominence' for x in x['unassessable'])


def test_pipeline_legacy_still_default_and_experimental_exports():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);sf=128;t=np.arange(0,12,1/sf)
        sig=np.vstack([10e-6*np.sin(2*np.pi*9*t),7e-6*np.sin(2*np.pi*11*t)])
        sig[0,4*sf:6*sf]=0
        raw=mne.io.RawArray(sig,mne.create_info(['C3','C4'],sf,['eeg','eeg']),verbose='ERROR')
        f=root/'sub-001_task-rest_eeg.fif';raw.save(f,verbose='ERROR')
        legacy,_=process(f,root/'legacy',player_frames=8)[0]
        enhanced,archive=process(f,root/'enhanced',player_frames=8,
                                  artifact_mode='experimental',mains_frequency_hz=50)[0]
        assert legacy['processing_status']=='COMPLETE' and enhanced['processing_status']=='COMPLETE'
        assert 'artifact_detection' not in legacy['quality']
        det=enhanced['quality']['artifact_detection']
        assert _hits(det,'possible_local_dropout','C3',4,6)
        assert enhanced['shared_metrics']['channel_statistics']==legacy['shared_metrics']['channel_statistics']
        assert enhanced['provenance']['artifact_mode']=='experimental'
        assert enhanced['provenance']['mains_frequency_hz']==50
        assert (root/'enhanced'/'artifact_events.csv').exists()
        html=(root/'enhanced'/'report.html').read_text()
        assert 'Experimental localized artifact screening' in html
        assert 'artifact_events.csv' in html
        with zipfile.ZipFile(archive) as z:
            assert 'artifact_events.csv' in z.namelist()
            assert z.testzip() is None


def test_pipeline_streaming_and_regular_same_candidate_intervals():
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp);r=_raw(seconds=18);r._data[0,6*256:8*256]=0
        f=p/'sub-001_task-rest_eeg.fif';r.save(f,verbose='ERROR')
        a,_=process(f,p/'regular',player_frames=5,artifact_mode='experimental')[0]
        b,_=process(f,p/'stream',player_frames=5,large_threshold_mb=0,
                    chunk_seconds=14,artifact_mode='experimental')[0]
        get=lambda result:[(x['channel'],x['start_s'],x['end_s'],x['artifact_type']) for x in
                           result['quality']['artifact_detection']['events']]
        assert get(a)==get(b)


def test_configuration_rejects_invalid_values():
    with pytest.raises(ValueError,match='mains'):
        detect_artifacts(_raw(),config=ArtifactConfig(mains_frequency_hz=55))
    with pytest.raises(ValueError,match='hop'):
        detect_artifacts(_raw(),config=ArtifactConfig(hop_seconds=10))


def test_slow_wave_control_not_misclassified_as_burst():
    """A challenging clean control, not a substitute for expert-scored PSG."""
    from scipy.signal import windows
    sf=256
    raw=_raw(seconds=24)
    n=int(2*sf)
    wave=65e-6*np.sin(np.linspace(0,2*np.pi,n))
    raw._data[0,9*sf:11*sf]+=wave
    detected=detect_artifacts(raw)
    assert not _hits(detected,'high_rms_burst_candidate','C1',9,11)
    assert not _hits(detected,'possible_local_dropout','C1',9,11)


def test_comparative_provenance_is_advisory_and_leaves_zscores_unchanged():
    from test_athlete_comparative import fake_report
    # Add quality manually to otherwise identical synthetic report dictionaries.
    clean=[fake_report(i,v) for i,v in enumerate([10,11,12],1)]
    test=fake_report(4,15)
    _,before=build_comparison(clean,test)
    for r in clean+[test]:
        r['quality']={'artifact_detection':{'detector_version':'window-eeg-0.1.0',
            'channel_summary':{'C3':{'flagged_fraction':.75}}}}
    _,after=build_comparison(clean,test)
    assert after['metrics']==before['metrics']


def test_mains_needs_two_valid_spectral_windows():
    out=detect_artifacts(_raw(seconds=5))
    assert out['status']=='partial_unassessable'
    assert any(x['detector']=='mains_spectral_prominence' for x in out['unassessable'])
