"""Low-memory large-EEG tests, independent of external datasets."""
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile
import numpy as np
import mne
from scipy.io import savemat
from neurobuddy_v2.intake import discover,load_eeg
from neurobuddy_v2.large_recordings import requires_streaming
from neurobuddy_v2.pipeline import process


def test_forced_streaming_sleep_end_to_end():
    with TemporaryDirectory() as tmp:
        p=Path(tmp); sf=100
        t=np.arange(0,75,1/sf)
        sig=np.vstack([4e-6*np.sin(2*np.pi*1.5*t),3e-6*np.sin(2*np.pi*11*t)])
        raw=mne.io.RawArray(sig,mne.create_info(['C3','C4'],sf,['eeg']*2),verbose='ERROR')
        eeg=p/'sub-001_task-sleep_acq-PSG_eeg.fif'
        raw.save(eeg,verbose='ERROR')
        (p/'sub-001_task-sleep_acq-PSGScoring_events.tsv').write_text(
            'onset\tduration\tvalue\n0\t30\tW\n30\t30\tN2\n60\t15\tREM\n')
        report,archive=process(eeg,p/'out',player_frames=8,large_threshold_mb=0,chunk_seconds=25)[0]
        assert report['processing_status']=='COMPLETE'
        assert report['classification']['task_family']=='SLEEP'
        assert report['shared_metrics']['preprocessing']['memory_strategy']=='bounded_chunk_streaming'
        assert report['specialized_metrics']['sleep']['total_sleep_time_s']==45
        assert len(report['shared_metrics']['channel_statistics'])==2
        assert (p/'out'/'sleep_hypnogram.png').is_file()
        html=(p/'out'/'report.html').read_text()
        assert 'Brain Activity Player' in html and 'Complete graph data table' in html
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            assert {'report.html','report.json','player_data.json','sleep_hypnogram_data.csv'} <= set(z.namelist())


def test_800mb_external_eeglab_fdt_is_read_lazily():
    """Sparse >800 MiB binary verifies true EEGLAB .set/.fdt loading.

    Only short windows are read here. Complete-file streaming is covered by
    test_forced_streaming_sleep_end_to_end with a smaller recording.
    """
    with TemporaryDirectory() as tmp:
        p=Path(tmp);sf=256; ch=16;n=13_300_000
        f=p/'sub-003_task-sleep_acq-PSG_eeg.fdt'
        with f.open('wb') as handle:handle.truncate(n*ch*4)
        name=f.with_suffix('.set')
        savemat(name,{'EEG':{'setname':'sparse external data test','nbchan':ch,'trials':1,
            'pnts':n,'srate':sf,'xmin':0.,'xmax':(n-1)/sf,'data':f.name,
            'chanlocs':np.array([{'labels':f'C{i+1}'} for i in range(ch)],dtype=object),
            'event':np.array([],dtype=object),'urevent':np.array([],dtype=object)}})
        assert f.stat().st_size > 800*1024**2
        b=discover(name)[0]
        assert b.companion == f
        raw=load_eeg(b)
        assert raw.preload is False
        assert requires_streaming(raw,b)
        assert raw.get_data(picks=['C1'],start=0,stop=100).shape == (1,100)
        assert raw.get_data(picks=['C16'],start=n-100,stop=n).shape == (1,100)
        raw.close()


def test_missing_fdt_keeps_sleep_classification():
    with TemporaryDirectory() as tmp:
        p=Path(tmp);n=1000;sf=100;ch=2
        eeg=p/'sub-003_task-sleep_acq-PSG_eeg.set'
        savemat(eeg,{'EEG':{'setname':'missing fdt','nbchan':ch,'trials':1,
            'pnts':n,'srate':sf,'xmin':0.,'xmax':(n-1)/sf,
            'data':'missing_companion.fdt','chanlocs':np.array([
                {'labels':'C3'},{'labels':'C4'}],dtype=object),
            'event':np.array([],dtype=object),'urevent':np.array([],dtype=object)}})
        report,_=process(eeg,p/'out',player_frames=5)[0]
        assert report['processing_status']=='INCOMPLETE'
        assert report['classification']['task_family']=='SLEEP'
        assert not report['routing']['shared_eeg_ionm_executed']


def test_merged_chunks_match_serial_accumulator():
    """Chunk moments folded in order match one accumulator walked serially."""
    from neurobuddy_v2.large_recordings import Accumulator
    rng = np.random.default_rng(4)
    chunks = [rng.normal(scale=20.0, size=(3, 40)) for _ in range(5)]
    chunks[1][0, 0] = np.nan
    chunks[2] = chunks[2][:, :1]
    chunks[3][2, -1] = np.inf
    stride = 7
    serial = Accumulator(['a', 'b', 'c'], 100.0, n_fft=8)
    merged = Accumulator(['a', 'b', 'c'], 100.0, n_fft=8)
    start = 0
    for chunk in chunks:
        serial.add(chunk, start=start, stride=stride)
        local = Accumulator(['a', 'b', 'c'], 100.0, n_fft=8)
        local.add(chunk, start=start, stride=stride)
        merged.merge_chunk(local)
        start += chunk.shape[1]
    for name in ('s', 's2', 's3', 's4', 'diff_sq', 'diff2_sq', 'low', 'high', 'abspeak', 'psd_sum'):
        assert np.array_equal(getattr(serial, name), getattr(merged, name), equal_nan=True), name
    assert serial.n == merged.n
    assert np.array_equal(serial.zc, merged.zc)
    assert serial.diff_n == merged.diff_n and serial.diff2_n == merged.diff2_n
    assert serial.psd_windows == merged.psd_windows
    assert serial.reservoir == merged.reservoir
    assert np.array_equal(serial.result()[0], merged.result()[0], equal_nan=True)
    assert np.array_equal(serial.psd(), merged.psd(), equal_nan=True)


def test_parallel_chunk_matches_the_serial_read_and_filter():
    """Threaded chunk prep must return the same samples and Welch spectra."""
    import threading
    from neurobuddy_v2.large_recordings import WindowFiltered, _read_chunk_pair, _welch_density
    from neurobuddy_v2.legacy_combined import Settings
    sf = 200
    n = int(90 * sf)
    rng = np.random.default_rng(11)
    data = rng.normal(0, 5e-6, size=(3, n))
    data[1, 4000:4010] = np.nan
    raw = mne.io.RawArray(data, mne.create_info(['C3', 'C4', 'Cz'], sf, ['eeg'] * 3), verbose='ERROR')
    cfg = Settings()
    filtered = WindowFiltered(raw, raw.ch_names, cfg, max_window_s=120)
    lock = threading.Lock()
    start, stop = int(20 * sf), int(20 * sf) + int(30 * sf)
    got_raw, got_filt = _read_chunk_pair(raw, raw.ch_names, filtered.sos, start, stop, int(8 * sf), lock)
    direct = raw.get_data(picks=raw.ch_names, start=start, stop=stop)
    via_filter = filtered.get_data(picks=raw.ch_names, start=start, stop=stop)
    assert np.array_equal(got_raw, direct, equal_nan=True)
    assert np.array_equal(got_filt, via_filter, equal_nan=True)
    nfft = min(int(4 * sf), stop - start)
    assert np.array_equal(_welch_density(got_raw, sf, nfft)[0], _welch_density(direct, sf, nfft)[0], equal_nan=True)
    raw.close()


def test_forced_streaming_oddball_erp_from_lazy_windows():
    with TemporaryDirectory() as tmp:
        p=Path(tmp);sf=100
        tt=np.arange(0,30,1/sf)
        sig=np.vstack([5e-6*np.sin(2*np.pi*8*tt),3e-6*np.sin(2*np.pi*10*tt)])
        raw=mne.io.RawArray(sig,mne.create_info(['Cz','Pz'],sf,['eeg']*2),verbose='ERROR')
        eeg=p/'sub-001_task-P300_run-1_eeg.fif'
        raw.save(eeg,verbose='ERROR')
        (p/'sub-001_task-P300_run-1_events.tsv').write_text(
            'onset\tvalue\n' + ''.join(f'{1+i*2}\t{("oddball" if i%2 else "standard")}\n' for i in range(12)))
        report,_=process(eeg,p/'out',player_frames=6,large_threshold_mb=0,chunk_seconds=15)[0]
        assert report['processing_status']=='COMPLETE'
        assert report['classification']['task_family']=='ODDBALL'
        assert 'oddball_erp.png' in [p.name for p in (p/'out').iterdir()]
        assert report['specialized_metrics']['oddball']['erp'] is not None
