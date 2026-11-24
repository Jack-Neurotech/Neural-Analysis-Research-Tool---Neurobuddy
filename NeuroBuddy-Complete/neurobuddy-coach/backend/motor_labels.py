"""Imagery versus execution from an events table, before any EEG download.

EEGMMI motion runs record the task in the events TSV. TASK2 and TASK4 are
imagery. TASK1 and TASK3 are execution. A T0 row is rest and does not decide
the file. Explicit trial_type words imagery and execution count the same way.
This does not change the comparison rule that refuses a mixed pair.
"""
from __future__ import annotations

import csv
import io
import re

_TASK = re.compile(r'^TASK([1-4])T([0-2])$', re.I)
_COLUMNS = {'value', 'trial_type', 'trialtype'}
_IMAGERY = {'imagery', 'motor_imagery', 'imagine', 'imagined'}
_EXECUTION = {'execution', 'motor_execution', 'executed'}


def motor_subtype_from_events(text: str) -> str | None:
    """Return imagery, execution, or None when the table does not decide."""
    rows = _rows(text)
    if len(rows) < 2:
        return None
    header = [cell.strip().lower() for cell in rows[0]]
    indexes = [index for index, name in enumerate(header) if name in _COLUMNS]
    if not indexes:
        return None
    kinds: set[str] = set()
    for row in rows[1:]:
        if not row or all(not cell.strip() for cell in row):
            continue
        for index in indexes:
            if index >= len(row):
                continue
            kind = _cue_kind(row[index])
            if kind:
                kinds.add(kind)
    kinds.discard('rest')
    if kinds == {'imagery'}:
        return 'imagery'
    if kinds == {'execution'}:
        return 'execution'
    return None


def _rows(text: str) -> list[list[str]]:
    sample = (text or '').lstrip('\ufeff')
    if not sample.strip():
        return []
    first = sample.splitlines()[0]
    delimiter = '\t' if '\t' in first else ','
    return [row for row in csv.reader(io.StringIO(sample), delimiter=delimiter)]


def _cue_kind(raw: str) -> str | None:
    text = (raw or '').strip()
    if not text or text.lower() in {'n/a', 'na', 'none'}:
        return None
    match = _TASK.fullmatch(text)
    if match:
        task_id = int(match.group(1))
        code = int(match.group(2))
        if code == 0:
            return 'rest'
        if task_id in (2, 4):
            return 'imagery'
        if task_id in (1, 3):
            return 'execution'
        return None
    token = text.lower().replace('-', '_').replace(' ', '_')
    if token in _IMAGERY or token.endswith('_imagery'):
        return 'imagery'
    if token in _EXECUTION or token.endswith('_execution'):
        return 'execution'
    return None
