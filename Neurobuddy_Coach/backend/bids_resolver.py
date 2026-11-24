"""BIDS-aware dependency resolution for one remote EEG recording.

This module does not download files and does not call the scientific pipeline.
It decides which files belong in one recording bundle, why, and whether the
coach's selected Test Type is compatible with the evidence in those files.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re

SIGNALS = ('.set', '.edf', '.bdf', '.vhdr', '.fif', '.fif.gz')
ENTITIES = ('sub', 'ses', 'task', 'acq', 'run', 'rec', 'recording', 'space', 'desc')
SUBSET_KEYS = ('sub', 'ses', 'task', 'acq', 'run', 'rec', 'recording', 'space', 'desc')
TASKS = ('oddball', 'motor', 'sleep', 'unspecified')

_COMPONENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+\-]{0,180}$')
_FDT = re.compile(r'(?<![A-Za-z0-9._+\-])([A-Za-z0-9][A-Za-z0-9._+\-]{0,180}\.fdt)')


def safe_component(name: str) -> bool:
    return bool(name and _COMPONENT.fullmatch(name) and name not in ('.', '..'))


def split_relative(path: str) -> list[str]:
    if (not isinstance(path, str) or not path or path.startswith('/') or '\\' in path
            or '\x00' in path or len(path) > 420):
        raise ValueError('Recording path is empty or unsafe.')
    parts = path.split('/')
    if len(parts) > 12 or any(not safe_component(part) for part in parts):
        raise ValueError('Recording path contains an unsafe component.')
    return parts


def bids_entities(filename: str) -> dict[str, str]:
    return {key: match.group(1) for key in ENTITIES
            if (match := re.search(rf'(?:^|_){key}-([A-Za-z0-9]+)(?:_|\.|$)', filename))}


def is_signal_name(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith(SIGNALS)


def signal_modality(filename: str) -> str:
    stem = filename.lower()
    for ext in ('.fif.gz', '.set', '.edf', '.bdf', '.vhdr', '.fif'):
        if stem.endswith(ext):
            stem = stem[:-len(ext)]
            break
    match = re.search(r'_(eeg|ieeg|meg)$', stem)
    return match.group(1) if match else 'eeg'


def sidecar_role(filename: str, modality: str) -> str | None:
    name = filename.lower()
    if name.endswith('.fdt') or name.endswith('.vmrk') or name.endswith('.eeg'):
        return 'companion'
    if any(token in name for token in ('scoring', 'hypnogram', 'stages')) and name.endswith(('.tsv', '.csv', '.json', '.txt')):
        return 'sleep_scoring'
    if name.endswith('_events.tsv') or name.endswith('_events.csv'):
        return 'events'
    if name.endswith('_events.json'):
        return 'dictionary'
    if name.endswith('_channels.tsv'):
        return 'channels'
    if name.endswith('_electrodes.tsv'):
        return 'electrodes'
    if name.endswith('_coordsystem.json'):
        return 'coordsystem'
    if name.endswith(f'_{modality}.json'):
        return 'modality_metadata'
    if name == 'dataset_description.json':
        return 'provenance'
    return None


def entities_compatible(sidecar_name: str, signal_name: str) -> bool:
    """BIDS inheritance: every sidecar entity must be present and equal on the signal."""
    sidecar, signal = bids_entities(sidecar_name), bids_entities(signal_name)
    if not any(key in sidecar for key in ('sub', 'ses', 'task', 'acq', 'run', 'rec', 'recording')):
        return False
    for key in SUBSET_KEYS:
        if key not in sidecar:
            continue
        if key not in signal:
            return False
        if key == 'acq' and sidecar[key].lower() == 'scoring' and signal[key].lower() == 'psg':
            continue
        if sidecar[key].lower() != signal[key].lower():
            return False
    return True


def brainvision_refs(header: str) -> tuple[str | None, str | None]:
    data = marker = None
    for raw in header.splitlines():
        line = raw.strip()
        lower = line.lower()
        if lower.startswith('datafile='):
            data = line.split('=', 1)[1].strip()
        elif lower.startswith('markerfile='):
            marker = line.split('=', 1)[1].strip()
    return _blank(data), _blank(marker)


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    if not cleaned or cleaned.lower() in {'none', 'off', '""', "''"}:
        return None
    return cleaned


def join_reference(signal_path: str, reference: str) -> str:
    reference = reference.replace('\\', '/').strip()
    if (not reference or reference.startswith('/') or reference.startswith('../')
            or '/../' in f'/{reference}/' or '\\' in reference):
        raise ValueError(f'Companion reference is not a safe relative path: {reference[:80]}')
    parts = [part for part in reference.split('/') if part not in ('', '.')]
    if any(part == '..' or not safe_component(part) for part in parts):
        raise ValueError(f'Companion reference is not a safe relative path: {reference[:80]}')
    parent = signal_path.rsplit('/', 1)[0] if '/' in signal_path else ''
    return '/'.join(([parent] if parent else []) + parts)


def referenced_fdt(filename: str, payload: str | bytes | None) -> str | None:
    """Return an .fdt name only when this .set names that exact companion."""
    if not payload:
        return None
    text = payload.decode('latin-1', errors='ignore') if isinstance(payload, (bytes, bytearray)) else payload
    stem = filename[:-4] if filename.lower().endswith('.set') else filename
    needle = stem + '.fdt'
    if needle in text:
        return needle
    # External EEGLAB sets sometimes store a different basename. Accept a single
    # explicit .fdt token, never a guess invented from the directory listing.
    found = list(dict.fromkeys(_FDT.findall(text)))
    if len(found) == 1:
        return found[0]
    return None


def _table_values(text: str, filename: str) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    separator = '\t' if filename.lower().endswith('.tsv') or '\t' in lines[0] else ','
    header = [cell.strip().lower() for cell in lines[0].split(separator)]
    keys = ('value', 'trial_type', 'scoring', 'stage', 'staging', 'sleep_stage')
    indexes = [header.index(key) for key in keys if key in header]
    values = []
    for line in lines[1:5000]:
        cells = line.split(separator)
        for index in indexes:
            if index >= len(cells):
                continue
            token = cells[index].strip().lower()
            if token and token not in {'n/a', 'na', 'none'}:
                values.append(token)
    return values


def _json_levels(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    found = []
    if isinstance(data, dict):
        for spec in data.values():
            levels = spec.get('Levels') if isinstance(spec, dict) else None
            if isinstance(levels, dict):
                found.extend(str(key).strip().lower() for key in levels if str(key).strip())
    return found


def _has_stage_column(text: str, filename: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    separator = '\t' if filename.lower().endswith('.tsv') or '\t' in lines[0] else ','
    header = {cell.strip().lower() for cell in lines[0].split(separator)}
    return bool(header & {'scoring', 'stage', 'staging', 'sleep_stage'})


def directory_of(path: str) -> str:
    return path.rsplit('/', 1)[0] if '/' in path else ''


def _by_path(directories: dict[str, list[dict]]) -> dict[str, dict]:
    found = {}
    for folder, entries in directories.items():
        for entry in entries:
            if entry.get('directory'):
                continue
            path = entry.get('path')
            if not path:
                name = entry.get('filename') or ''
                path = f'{folder}/{name}' if folder else name
            item = dict(entry)
            item['path'] = path
            item['filename'] = item.get('filename') or path.rsplit('/', 1)[-1]
            found[path] = item
    return found


def _specificity(filename: str, path: str) -> tuple[int, int]:
    return (len(bids_entities(filename)), path.count('/'))


@dataclass
class Manifest:
    provider: str
    dataset_id: str
    snapshot: str
    dataset_name: str
    signal_path: str
    task_selected: str
    task_detected: str
    task_evidence: list[str]
    status: str
    can_auto_import: bool
    allow_acknowledge: bool
    warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    summary: str = ''
    files: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def build_manifest(*, provider: str, dataset_id: str, snapshot: str, dataset_name: str,
                   signal_path: str, task: str, directories: dict[str, list[dict]],
                   texts: dict[str, str] | None = None) -> Manifest:
    if task not in TASKS:
        raise ValueError('Test Type must be oddball, motor, sleep, or unspecified.')
    split_relative(signal_path)
    texts = texts or {}
    known = _by_path(directories)
    signal = known.get(signal_path)
    if signal is None:
        return _blocked(provider, dataset_id, snapshot, dataset_name, signal_path, task,
                        'The selected file is not in this published snapshot.')
    filename = signal['filename']
    if not is_signal_name(filename):
        hint = ''
        if filename.lower().endswith(('.eeg', '.vmrk', '.fdt')):
            hint = ' Select the .vhdr or .set header instead of a companion data file.'
        return _blocked(provider, dataset_id, snapshot, dataset_name, signal_path, task,
                        f'{filename} is not a supported primary EEG signal.{hint}')

    modality = signal_modality(filename)
    selected: list[dict] = []
    considered: list[dict] = []
    warnings: list[str] = []
    conflicts: list[str] = []
    blocked = False
    ambiguous = False

    selected.append(_entry(signal, 'required', 'signal',
                           'Primary EEG signal selected by the coach.', True))

    folder = directory_of(signal_path)
    siblings = [item for item in known.values() if directory_of(item['path']) == folder]

    if filename.lower().endswith('.vhdr'):
        header = texts.get(signal_path, '')
        if not header.strip():
            blocked = True
            warnings.append('The BrainVision header could not be read, so DataFile and MarkerFile are unknown.')
        else:
            try:
                data_ref, marker_ref = brainvision_refs(header)
                _require_brainvision(selected, known, signal_path, data_ref, 'DataFile', warnings, conflicts)
                if marker_ref:
                    _require_brainvision(selected, known, signal_path, marker_ref, 'MarkerFile', warnings, conflicts)
                else:
                    warnings.append('The BrainVision header does not reference a marker file.')
            except ValueError as exc:
                blocked = True
                conflicts.append(str(exc))
            if any(item['role'] == 'companion' and item['category'] == 'required' and not item['selected']
                   for item in selected):
                blocked = True
    elif filename.lower().endswith('.set'):
        stem_fdt = filename[:-4] + '.fdt'
        sibling = next((item for item in siblings if item['filename'] == stem_fdt), None)
        named = referenced_fdt(filename, texts.get(signal_path))
        if sibling is not None:
            selected.append(_entry(sibling, 'required', 'companion',
                                   'EEGLAB .set has a same-stem .fdt in this folder, so the external data file is required.',
                                   True))
        elif named:
            match = next((item for item in known.values() if item['filename'] == named and directory_of(item['path']) == folder), None)
            if match is None:
                blocked = True
                conflicts.append(f'The .set references {named}, and that file is not in the recording folder.')
                selected.append({'path': join_reference(signal_path, named) if safe_component(named) else named,
                                 'filename': named, 'file_id': '', 'size': None, 'category': 'required',
                                 'role': 'companion', 'reason': 'Referenced by the EEGLAB .set data field.',
                                 'selected': False})
            else:
                selected.append(_entry(match, 'required', 'companion',
                                       'EEGLAB .set data field names this .fdt companion.', True))
        else:
            warnings.append('No external .fdt companion is in this folder. The .set is treated as embedded EEG data and a missing .fdt is not invented.')

    candidates = []
    for item in known.values():
        if item['path'] == signal_path:
            continue
        role = sidecar_role(item['filename'], modality)
        if role in (None, 'companion'):
            continue
        if role == 'provenance':
            if item['path'] == 'dataset_description.json':
                candidates.append((item, role, (0, 0)))
            continue
        if entities_compatible(item['filename'], filename):
            candidates.append((item, role, _specificity(item['filename'], item['path'])))

    grouped: dict[str, list[tuple[dict, tuple[int, int]]]] = {}
    for item, role, rank in candidates:
        if role == 'provenance':
            selected.append(_entry(item, 'recommended', 'provenance',
                                   'Dataset description preserved so the BIDS root and citation stay with the recording.', True))
            continue
        grouped.setdefault(role, []).append((item, rank))

    for role, group in grouped.items():
        best = max(rank for _, rank in group)
        winners = [item for item, rank in group if rank == best]
        losers = [item for item, rank in group if rank != best]
        if len(winners) > 1:
            ambiguous = True
            conflicts.append('More than one ' + role + ' sidecar has equal specificity: '
                             + ', '.join(item['filename'] for item in winners) + '.')
            for item in winners:
                selected.append(_entry(item, 'optional', role,
                                       'Not imported: another sidecar has equal specificity, so none was chosen automatically.',
                                       False))
        else:
            role_name = _promote_role(winners[0], role, texts)
            selected.append(_entry(winners[0], _category(role_name, task), role_name,
                                   'Most specific matching BIDS sidecar for this recording.', True))
        for item in losers:
            selected.append(_entry(item, 'unrelated', role,
                                   f"Superseded by a more specific BIDS sidecar ({winners[0]['filename']}).", False))

    for item in siblings:
        if any(item['path'] == entry['path'] for entry in selected):
            continue
        role = sidecar_role(item['filename'], modality)
        reason = ('BIDS entities belong to a different subject, session, task, or run.'
                  if role and role != 'companion' else
                  'Not required to read this recording or to document its events and metadata.')
        considered.append(_entry(item, 'unrelated', role or 'other', reason, False))

    promoted = []
    for entry in selected:
        if entry['selected'] and entry['role'] == 'events' and _has_stage_column(texts.get(entry['path'], ''), entry['filename']):
            entry = dict(entry)
            entry['role'] = 'sleep_scoring'
            entry['category'] = _category('sleep_scoring', task)
            entry['reason'] = 'Event table contains a sleep-stage column supplied with the dataset. Stages were not generated by Neurobuddy.'
        promoted.append(entry)
    selected = promoted

    evidence, detected = _assess(task, filename, selected, texts, warnings)
    if any(not entry['selected'] and entry['category'] == 'required' for entry in selected):
        blocked = True
    if ambiguous:
        blocked = True

    analysis_missing = _missing_analysis(task, selected, texts, warnings, detected)
    status = 'blocked' if blocked else 'needs_review' if conflicts or analysis_missing or _task_conflict(task, detected) else 'ready'
    if _task_conflict(task, detected):
        conflicts.append(f'Selected {task}, but the recording evidence indicates {detected}. The shelf was not relabeled.')
    allow = status == 'needs_review' and not blocked and not any('equal specificity' in item for item in conflicts)
    can_auto = status == 'ready'
    summary = _summary(status, task, detected, filename, warnings, conflicts)
    files = selected + considered[:30]
    return Manifest(provider, dataset_id, snapshot, dataset_name or dataset_id, signal_path, task,
                    detected, evidence, status, can_auto, allow, warnings, conflicts, summary, files)


def _require_brainvision(selected, known, signal_path, reference, label, warnings, conflicts):
    if not reference:
        conflicts.append(f'BrainVision header is missing {label}.')
        selected.append({'path': '', 'filename': label, 'file_id': '', 'size': None, 'category': 'required',
                         'role': 'companion', 'reason': f'{label} is not set in the header.', 'selected': False})
        return
    try:
        path = join_reference(signal_path, reference)
    except ValueError as exc:
        conflicts.append(str(exc))
        selected.append({'path': reference, 'filename': reference, 'file_id': '', 'size': None,
                         'category': 'required', 'role': 'companion', 'reason': str(exc), 'selected': False})
        return
    match = known.get(path)
    if match is None:
        conflicts.append(f'BrainVision {label} references {reference}, which is not in the snapshot.')
        selected.append({'path': path, 'filename': path.rsplit('/', 1)[-1], 'file_id': '', 'size': None,
                         'category': 'required', 'role': 'companion',
                         'reason': f'Referenced by BrainVision {label}.', 'selected': False})
        return
    selected.append(_entry(match, 'required', 'companion', f'Referenced by BrainVision {label}.', True))


def _category(role: str, task: str) -> str:
    if role in {'channels', 'electrodes', 'coordsystem', 'modality_metadata', 'metadata', 'dictionary', 'provenance'}:
        return 'recommended'
    if role == 'sleep_scoring':
        return 'analysis_required' if task == 'sleep' else 'recommended' if task == 'unspecified' else 'optional'
    if role == 'events':
        if task in {'oddball', 'motor'}:
            return 'analysis_required'
        return 'recommended'
    return 'optional'


def _promote_role(item: dict, role: str, texts: dict[str, str]) -> str:
    if role == 'events' and _has_stage_column(texts.get(item['path'], ''), item['filename']):
        return 'sleep_scoring'
    return role


def _entry(item: dict, category: str, role: str, reason: str, chosen: bool) -> dict:
    size = item.get('size')
    return {'path': item['path'], 'filename': item['filename'], 'file_id': item.get('file_id') or item.get('id') or '',
            'size': int(size) if isinstance(size, (int, float)) and size else (int(size) if size == 0 else None),
            'category': category, 'role': role, 'reason': reason, 'selected': chosen}


def _assess(task: str, signal_name: str, files: list[dict], texts: dict[str, str], warnings: list[str]):
    entities = bids_entities(signal_name)
    meta = entities.get('task', '').lower()
    values: list[str] = []
    evidence = []
    if meta:
        evidence.append(f'BIDS task entity is {entities["task"]}.')
    manual_scoring = False
    for entry in files:
        if not entry['selected']:
            continue
        text = texts.get(entry['path'], '')
        if not text:
            continue
        if entry['filename'].lower().endswith('.json'):
            values.extend(_json_levels(text))
        elif entry['filename'].lower().endswith(('.tsv', '.csv', '.txt')):
            values.extend(_table_values(text, entry['filename']))
        if entry['role'] == 'sleep_scoring':
            manual_scoring = True
    unique = list(dict.fromkeys(values))
    oddball = _strong_oddball(unique, meta)
    motor = _strong_motor(unique, meta)
    sleep = _strong_sleep(unique, meta, [entry['filename'] for entry in files if entry['selected']])
    families = [name for name, flag in (('oddball', oddball), ('motor', motor), ('sleep', sleep)) if flag]
    if 'standard' in unique and any(token in unique for token in ('target', 'oddball', 'deviant', 'oddball_with_reponse', 'oddball_with_response')):
        evidence.append('Event values include both standard and target/oddball labels from the file. Labels were not invented.')
    elif any(token in unique for token in ('left_hand', 'right_hand', 'both_hands', 'both_feet', 'motor_imagery')):
        evidence.append('Event values include documented motor cue labels.')
    if manual_scoring or (sleep and any(token in unique for token in ('w', 'n1', 'n2', 'n3', 'rem', 'wake'))):
        evidence.append('Sleep-stage labels are present in a dataset file. This is supplied scoring, not an estimate created during import.')
    if sleep and not manual_scoring and 'sleep' in meta and not any(token in unique for token in ('w', 'n1', 'n2', 'n3', 'rem', 'wake')):
        evidence.append('BIDS task indicates sleep, and no stage table was found. No sleep stages were fabricated.')
    if task == 'motor' and motor and not any(token in unique for token in ('left_hand', 'right_hand', 'both_hands', 'both_feet', 'motor_imagery')):
        warnings.append('Motor metadata is present, but the event table has no documented left/right-hand cue labels. ERD/ERS laterality is incomplete, and no cue labels were invented.')
    if task == 'oddball' and not oddball:
        warnings.append('Specialized Oddball analysis is incomplete: target and standard stimulus labels were not both found.')
    if task == 'sleep' and not manual_scoring:
        warnings.append('No manual sleep-stage scoring file was found. Import will not create stages.')
    channel_text = '\n'.join(texts.get(entry['path'], '') for entry in files if entry['selected'] and entry['role'] in {'channels', 'electrodes', 'coordsystem', 'companion', 'signal', 'modality_metadata', 'metadata'})
    if re.search(r'(^|[^A-Za-z0-9])C3([^A-Za-z0-9]|$)', channel_text) and re.search(r'(^|[^A-Za-z0-9])C4([^A-Za-z0-9]|$)', channel_text):
        evidence.append('Channel metadata includes C3 and C4.')
    if len(families) > 1:
        evidence.append('Conflicting task evidence: ' + ', '.join(families) + '.')
        return evidence, 'conflict'
    if len(families) == 1:
        return evidence, families[0]
    return evidence or ['No specialized task evidence was found in the selected files.'], 'unspecified'


def _strong_oddball(values: list[str], meta: str) -> bool:
    pool = set(values)
    labels = bool(pool & {'standard', 'standard_with_reponse', 'standard_with_response'}) and bool(
        pool & {'target', 'oddball', 'deviant', 'oddball_with_reponse', 'oddball_with_response'})
    return labels or 'p300' in meta or 'oddball' in meta


def _strong_motor(values: list[str], meta: str) -> bool:
    pool = set(values)
    return bool(pool & {'left_hand', 'right_hand', 'both_hands', 'both_feet', 'left_fist', 'right_fist', 'motor_imagery'}) or any(
        token in meta for token in ('motor', 'imagery', 'motion', 'exercise'))


def _strong_sleep(values: list[str], meta: str, names: list[str]) -> bool:
    stages = set(values) & {'w', 'n1', 'n2', 'n3', 'rem', 'wake'}
    named = any(any(token in name.lower() for token in ('scoring', 'hypnogram', 'stages')) for name in names)
    return 'sleep' in meta or len(stages) >= 2 or named


def _task_conflict(selected: str, detected: str) -> bool:
    return selected in {'oddball', 'motor', 'sleep'} and detected in {'oddball', 'motor', 'sleep', 'conflict'} and detected != selected


def _missing_analysis(task: str, files: list[dict], texts: dict[str, str], warnings: list[str], detected: str) -> bool:
    if task == 'unspecified':
        return False
    chosen = [item for item in files if item['selected']]
    if task == 'oddball' and not any(item['role'] == 'events' for item in chosen):
        warnings.append('No matching events table was found. Shared EEG import can continue after review; Oddball ERP results would be incomplete.')
        return True
    if task == 'motor' and not any(item['role'] == 'events' for item in chosen):
        warnings.append('No matching motor event table was found. Shared EEG import can continue after review; ERD/ERS results would be incomplete.')
        return True
    if task == 'sleep' and detected not in {'sleep', 'conflict'} and not any(item['role'] == 'sleep_scoring' for item in chosen):
        # Absence of scoring is a warning already. It does not block an unambiguous sleep-labeled EEG,
        # and it must not be turned into invented stages. Review only when the coach asked for sleep
        # and nothing identifies the file as sleep.
        if detected == 'unspecified':
            warnings.append('The selected Test Type is Sleep, but the file names and annotations do not document a sleep recording.')
            return True
    return False


def _summary(status: str, task: str, detected: str, filename: str, warnings: list[str], conflicts: list[str]) -> str:
    if status == 'blocked':
        return conflicts[0] if conflicts else (warnings[0] if warnings else f'{filename} cannot be imported as a complete EEG recording.')
    if status == 'needs_review':
        return conflicts[0] if conflicts else (warnings[0] if warnings else f'Review the {task} bundle before import.')
    if warnings:
        return f'{filename} can be imported for {task}. ' + warnings[0]
    return f'{filename} is ready to import for {task}. Detected evidence: {detected}.'


def _blocked(provider, dataset_id, snapshot, dataset_name, signal_path, task, message) -> Manifest:
    return Manifest(provider, dataset_id, snapshot, dataset_name or dataset_id, signal_path, task,
                    'unspecified', [], 'blocked', False, False, [message], [message], message, [])


def public_manifest(manifest: Manifest | dict) -> dict:
    if isinstance(manifest, Manifest) or hasattr(manifest, 'as_dict'):
        data = manifest.as_dict()
    else:
        data = dict(manifest)
    files = []
    for item in data.get('files') or []:
        copy = dict(item)
        copy.pop('urls', None)
        files.append(copy)
    data['files'] = files
    return data
