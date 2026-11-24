"""Dependency decisions for oddball, motor, sleep, and unspecified EEG bundles."""
from backend.bids_resolver import build_manifest


def entry(path, size=10, directory=False, file_id='a'*40):
    return {'path': path, 'filename': path.rsplit('/', 1)[-1], 'size': size, 'directory': directory,
            'file_id': file_id, 'id': file_id, 'urls': []}


def manifest(signal, directories, task, texts=None):
    return build_manifest(provider='openneuro', dataset_id='ds003061', snapshot='1.1.2',
                          dataset_name='Example', signal_path=signal, task=task,
                          directories=directories, texts=texts or {})


def selected(result, role=None):
    files = [item for item in result.files if item['selected']]
    return [item for item in files if role is None or item['role'] == role]


def test_set_with_external_fdt_and_exact_run_events():
    signal = 'sub-01/eeg/sub-01_task-P300_run-1_eeg.set'
    folder = 'sub-01/eeg'
    directories = {
        '': [entry('dataset_description.json', 40), entry('task-P300_events.json', 80), entry('sub-01', 0, True)],
        'sub-01': [entry('sub-01/eeg', 0, True)],
        folder: [
            entry(signal, 2000),
            entry(f'{folder}/sub-01_task-P300_run-1_eeg.fdt', 5000),
            entry(f'{folder}/sub-01_task-P300_run-1_events.tsv', 100),
            entry(f'{folder}/sub-01_task-P300_run-1_events.json', 80),
            entry(f'{folder}/sub-01_task-P300_run-2_events.tsv', 100),
            entry(f'{folder}/sub-02_task-P300_run-1_events.tsv', 100),
            entry(f'{folder}/sub-01_task-P300_run-1_channels.tsv', 50),
        ],
    }
    texts = {f'{folder}/sub-01_task-P300_run-1_events.tsv': 'onset\tvalue\n0\tstandard\n1\toddball\n'}
    result = manifest(signal, directories, 'oddball', texts)
    assert result.status == 'ready'
    assert result.can_auto_import
    assert result.task_detected == 'oddball'
    names = {item['filename'] for item in selected(result)}
    assert 'sub-01_task-P300_run-1_eeg.fdt' in names
    assert 'sub-01_task-P300_run-1_events.tsv' in names
    assert 'sub-01_task-P300_run-2_events.tsv' not in names
    assert 'sub-02_task-P300_run-1_events.tsv' not in names
    assert any(item['filename'] == 'task-P300_events.json' and not item['selected'] for item in result.files)
    companion = selected(result, 'companion')[0]
    assert companion['category'] == 'required'
    assert 'same-stem' in companion['reason']


def test_embedded_set_does_not_require_missing_fdt():
    signal = 'sub-01/eeg/sub-01_task-rest_eeg.set'
    directories = {'sub-01/eeg': [entry(signal, 800)]}
    result = manifest(signal, directories, 'unspecified', {signal: 'MATLAB header without an external data file'})
    assert result.status == 'ready'
    assert not any(item['role'] == 'companion' and item['selected'] for item in result.files)
    assert any('embedded' in warning.lower() or 'not invented' in warning.lower() for warning in result.warnings)


def test_set_reference_without_fdt_is_blocked():
    signal = 'sub-01/eeg/sub-01_task-rest_eeg.set'
    directories = {'sub-01/eeg': [entry(signal, 400)]}
    text = 'data points to sub-01_task-rest_eeg.fdt for the samples'
    result = manifest(signal, directories, 'unspecified', {signal: text})
    assert result.status == 'blocked'
    assert result.can_auto_import is False
    assert any('.fdt' in item for item in result.conflicts)


def test_brainvision_header_requires_named_companions():
    signal = 'sub-xp101/eeg/sub-xp101_task-motorloc_eeg.vhdr'
    folder = 'sub-xp101/eeg'
    header = 'DataFile=sub-xp101_task-motorloc_eeg.eeg\nMarkerFile=sub-xp101_task-motorloc_eeg.vmrk\n'
    directories = {
        '': [entry('task-motorloc_channels.tsv', 40), entry('task-MIpost_channels.tsv', 40), entry('task-motorloc_events.tsv', 60)],
        folder: [
            entry(signal, 100),
            entry(f'{folder}/sub-xp101_task-motorloc_eeg.eeg', 1000),
            entry(f'{folder}/sub-xp101_task-motorloc_eeg.vmrk', 20),
            entry(f'{folder}/sub-xp101_task-other_eeg.eeg', 1000),
        ],
    }
    events = 'onset\ttrial_type\n0\tleft_hand\n1\trest\n'
    result = manifest(signal, directories, 'motor', {signal: header, 'task-motorloc_events.tsv': events,
                                                     'task-motorloc_channels.tsv': 'name\ttype\nC3\tEEG\nC4\tEEG\n'})
    assert result.status == 'ready'
    companions = {item['filename'] for item in selected(result, 'companion')}
    assert companions == {'sub-xp101_task-motorloc_eeg.eeg', 'sub-xp101_task-motorloc_eeg.vmrk'}
    assert 'task-motorloc_channels.tsv' in {item['filename'] for item in selected(result)}
    assert 'task-MIpost_channels.tsv' not in {item['filename'] for item in selected(result)}
    assert result.task_detected == 'motor'
    assert any('C3' in item and 'C4' in item for item in result.task_evidence)


def test_brainvision_missing_data_file_blocks():
    signal = 'sub-01/eeg/sub-01_task-rest_eeg.vhdr'
    directories = {'sub-01/eeg': [entry(signal, 80)]}
    result = manifest(signal, directories, 'unspecified', {signal: 'DataFile=missing.eeg\nMarkerFile=missing.vmrk\n'})
    assert result.status == 'blocked'
    assert any(not item['selected'] and item['category'] == 'required' for item in result.files)


def test_sleep_stage_table_is_manual_and_not_fabricated():
    signal = 'sub-06/eeg/sub-06_task-sleep_acq-PSG_eeg.edf'
    events = 'sub-06/eeg/sub-06_task-sleep_acq-PSG_events.tsv'
    directories = {'sub-06/eeg': [entry(signal, 100), entry(events, 40),
                                  entry('sub-06/eeg/sub-06_task-sleep_acq-PSG_eeg.json', 20)]}
    text = 'onset\tduration\tstage\n0\t30\tW\n30\t30\tN2\n60\t30\tREM\n'
    result = manifest(signal, directories, 'sleep', {events: text})
    assert result.status == 'ready'
    scoring = selected(result, 'sleep_scoring')
    assert scoring and scoring[0]['category'] == 'analysis_required'
    assert any('not generated' in item['reason'].lower() or 'not an estimate' in ' '.join(result.task_evidence).lower()
               or 'supplied scoring' in ' '.join(result.task_evidence).lower() for item in scoring)
    assert not any('fabricat' in warning.lower() and 'created stage' in warning.lower() for warning in result.warnings)


def test_unspecified_does_not_require_events():
    signal = 'sub-01/eeg/sub-01_task-rest_eeg.edf'
    directories = {'sub-01/eeg': [entry(signal, 100), entry('sub-01/eeg/sub-01_task-rest_events.tsv', 20)]}
    result = manifest(signal, directories, 'unspecified')
    assert result.status == 'ready'
    assert result.can_auto_import
    events = selected(result, 'events')
    assert events and events[0]['category'] == 'recommended'
    bare = manifest(signal, {'sub-01/eeg': [entry(signal, 100)]}, 'unspecified')
    assert bare.status == 'ready'
    assert not any(item['role'] == 'events' and item['selected'] for item in bare.files)


def test_oddball_without_events_needs_review_and_sleep_conflict_is_explicit():
    signal = 'sub-06/eeg/sub-06_task-sleep_acq-PSG_eeg.edf'
    events = 'sub-06/eeg/sub-06_task-sleep_acq-PSG_events.tsv'
    directories = {'sub-06/eeg': [entry(signal, 100), entry(events, 40)]}
    text = 'onset\tstage\n0\tW\n30\tN2\n'
    conflict = manifest(signal, directories, 'oddball', {events: text})
    assert conflict.status == 'needs_review'
    assert conflict.allow_acknowledge
    assert conflict.task_detected == 'sleep'
    assert any('not relabeled' in item.lower() or 'indicates sleep' in item.lower() for item in conflict.conflicts)
    missing = manifest('sub-01/eeg/sub-01_task-rest_eeg.set',
                       {'sub-01/eeg': [entry('sub-01/eeg/sub-01_task-rest_eeg.set', 100)]}, 'oddball')
    assert missing.status == 'needs_review'
    assert any('events' in warning.lower() for warning in missing.warnings)


def test_equal_specificity_is_not_chosen_arbitrarily():
    signal = 'sub-01/eeg/sub-01_task-P300_eeg.set'
    directories = {'sub-01/eeg': [
        entry(signal, 100),
        entry('sub-01/eeg/sub-01_task-P300_events.tsv', 10, file_id='b'*40),
        entry('sub-01/eeg/sub-01_task-P300_events.tsv'.replace('events', 'desc-extra_events') if False else 'sub-01/eeg/sub-01_task-P300_proc-events.tsv', 10, file_id='c'*40),
    ]}
    # Two events tables with the same sub/task entities and the same directory depth.
    directories = {'sub-01/eeg': [
        entry(signal, 100),
        entry('sub-01/eeg/sub-01_task-P300_run-1_events.tsv', 10, file_id='b'*40),
        entry('sub-01/eeg/sub-01_task-P300_run-1_proc-copy_events.tsv', 12, file_id='c'*40),
    ]}
    result = manifest(signal, directories, 'oddball', {
        'sub-01/eeg/sub-01_task-P300_run-1_events.tsv': 'onset\tvalue\n0\tstandard\n',
        'sub-01/eeg/sub-01_task-P300_run-1_proc-copy_events.tsv': 'onset\tvalue\n0\ttarget\n',
    })
    # proc-copy has an extra entity the signal lacks, so it is not a candidate.
    # Build a true tie with two files that share the exact entity set.
    directories = {'sub-01/eeg': [
        entry(signal, 100),
        entry('sub-01/eeg/sub-01_task-P300_events.tsv', 10, file_id='b'*40),
        entry('sub-01/eeg/sub-01_task-P300_events.tsv', 12, file_id='c'*40),
    ]}
    directories['sub-01/eeg'][2]['path'] = 'sub-01/eeg/sub-01_task-P300_events.tsv'
    directories['sub-01/eeg'][2]['filename'] = 'sub-01_task-P300_beh_events.tsv'
    directories['sub-01/eeg'][2]['path'] = 'sub-01/eeg/sub-01_task-P300_beh_events.tsv'
    result = manifest(signal, directories, 'unspecified')
    assert result.status == 'blocked'
    assert not any(item['selected'] and item['role'] == 'events' for item in result.files)
    assert any('equal specificity' in item for item in result.conflicts)


def test_companion_data_file_is_not_a_primary_signal():
    signal = 'sub-01/eeg/sub-01_task-rest_eeg.eeg'
    result = manifest(signal, {'sub-01/eeg': [entry(signal, 100)]}, 'unspecified')
    assert result.status == 'blocked'
    assert 'vhdr' in result.summary.lower() or 'header' in result.summary.lower()
