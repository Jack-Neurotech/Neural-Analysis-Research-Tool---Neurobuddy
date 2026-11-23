"""ds004362 1.0.1 companions are events, channels, and electrodes, not sleep scores."""
import tempfile
from pathlib import Path

import mne
import numpy as np

from neurobuddy_v2.intake import discover
from neurobuddy_v2.pipeline import process
from neurobuddy_v2.routing import decide
from neurobuddy_v2.events import load_events


def _fif(path: Path, seconds=30, sf=160):
    t = np.arange(0, seconds, 1 / sf)
    data = np.vstack([8e-6 * np.sin(2 * np.pi * 10 * t), 8e-6 * np.sin(2 * np.pi * 12 * t)])
    raw = mne.io.RawArray(data, mne.create_info(['C3', 'C4'], sf, ['eeg', 'eeg']), verbose='ERROR')
    raw.save(path, verbose='ERROR')
    return raw


def test_ds004362_events_and_channels_are_accepted_with_the_set():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        signal = p / 'sub-001_task-motion_run-4_eeg.fif'
        _fif(signal)
        events = p / 'sub-001_task-motion_run-4_events.tsv'
        channels = p / 'sub-001_task-motion_run-4_channels.tsv'
        electrodes = p / 'sub-001_electrodes.tsv'
        events.write_text(
            'onset\tduration\tsample\tvalue\n'
            '0.0\tn/a\t0\tTASK2T0\n'
            '4.2\tn/a\t672\tTASK2T2\n'
            '8.3\tn/a\t1328\tTASK2T0\n'
            '12.5\tn/a\t2000\tTASK2T1\n', encoding='utf-8')
        channels.write_text('name\ttype\tunits\nC3\tEEG\tuV\nC4\tEEG\tuV\n', encoding='utf-8')
        electrodes.write_text('name\tx\ty\tz\nC3\t0.3\t0.5\t0.8\nC4\t0.3\t-0.5\t0.8\n', encoding='utf-8')
        (p / 'sub-001_task-motion_run-3_channels.tsv').write_text(
            'name\ttype\tunits\nC3\tEEG\tuV\n', encoding='utf-8')
        (p / 'sub-001_task-motion_run-1_events.tsv').write_text(
            'onset\tduration\tsample\tvalue\n0.0\tn/a\t0\tBASE1T0\n', encoding='utf-8')
        (p / 'sub-001_task-motion_run-4_eeg.json').write_text(
            '{"PowerLineFrequency":60}', encoding='utf-8')

        bundle = discover(signal)[0]
        assert [path.name for path in bundle.annotations] == [events.name]
        assert {path.name for path in bundle.channel_tables} == {channels.name, electrodes.name}
        loaded, warnings = load_events(bundle, _fif(p / 'unused.fif'))
        assert not any('channels' in warning.lower() or 'electrodes' in warning.lower() for warning in warnings)
        assert {event.semantic_label for event in loaded} == {'rest', 'left_hand', 'right_hand'}
        assert not any(event.family == 'sleep' for event in loaded)

        report, _ = process(signal, p / 'out', player_frames=4, large_threshold_mb=1024, chunk_seconds=30)[0]
        assert report['errors'] == []
        assert report['processing_status'] == 'COMPLETE', report['warnings']
        assert report['classification']['task_family'] == 'MOTOR'
        assert report['classification']['subtype'] == 'imagery'
        names = {item['name'] for item in report['input_manifest']}
        assert events.name in names and channels.name in names and electrodes.name in names


def test_imagery_and_execution_runs_stay_separate_from_baselines():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        cases = {
            4: ('TASK2T1', 'imagery'),
            3: ('TASK1T1', 'execution'),
            1: ('BASE1T0', 'rest'),
            2: ('BASE2T0', 'rest'),
        }
        for run, (marker, subtype) in cases.items():
            signal = p / f'sub-001_task-motion_run-{run}_eeg.fif'
            raw = _fif(signal, seconds=8)
            events = p / f'sub-001_task-motion_run-{run}_events.tsv'
            events.write_text(f'onset\tduration\tsample\tvalue\n1.0\tn/a\t160\t{marker}\n', encoding='utf-8')
            bundle = discover(signal)[0]
            loaded, _ = load_events(bundle, raw)
            decision = decide(bundle, loaded)
            assert decision.task_family == 'MOTOR'
            assert decision.subtype == subtype
            assert not any(event.family == 'sleep' for event in loaded)
