"""Who is calling the Coach API.

Local development, with no Cursor app id, treats a header-less request as the
simulated viewer from cursor/identity.dev.js. A published app sets
CURSOR_APP_ID, and then every API call is checked with the Cursor identity
helper. The token never leaves this process.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

_HELPER = Path(__file__).resolve().parent / 'identity_check.mjs'
_LOCK = threading.Lock()
_PROCESS: subprocess.Popen | None = None


def _configured() -> bool:
    return bool(os.environ.get('CURSOR_APP_ID', '').strip() or os.environ.get('VERCEL', '').strip())


def _header(headers, name: str) -> str:
    value = headers.get(name)
    return value.strip() if isinstance(value, str) else ''


def _node_binary() -> str | None:
    for candidate in (os.environ.get('NODE_BINARY'), shutil.which('node'), '/usr/local/bin/node'):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    return None


def _worker() -> subprocess.Popen:
    global _PROCESS
    if _PROCESS is not None and _PROCESS.poll() is None:
        return _PROCESS
    node = _node_binary()
    if node is None:
        raise RuntimeError('node-missing')
    _PROCESS = subprocess.Popen(
        [node, str(_HELPER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    return _PROCESS


def _verified_with_helper(headers) -> dict:
    payload = json.dumps({
        'x-cursor-identity-v2': _header(headers, 'x-cursor-identity-v2'),
        'x-cursor-identity': _header(headers, 'x-cursor-identity'),
    })
    with _LOCK:
        try:
            worker = _worker()
            assert worker.stdin is not None and worker.stdout is not None
            worker.stdin.write(payload + '\n')
            worker.stdin.flush()
            line = worker.stdout.readline()
        except Exception:
            global _PROCESS
            if _PROCESS is not None:
                _PROCESS.kill()
            _PROCESS = None
            return {'verified': False, 'reason': 'identity_unavailable'}
    if not line:
        return {'verified': False, 'reason': 'identity_unavailable'}
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return {'verified': False, 'reason': 'identity_unavailable'}
    if record.get('verified') is True and record.get('sub'):
        return {
            'verified': True,
            'sub': record.get('sub'),
            'kind': record.get('kind') or 'person',
            'stage': record.get('stage') or 'production',
        }
    return {'verified': False, 'reason': record.get('reason') or 'missing_header'}


def viewer_for(headers) -> dict:
    """Return a verified viewer, or verified False. Never includes the token."""
    presented = _header(headers, 'x-cursor-identity-v2') or _header(headers, 'x-cursor-identity')
    if not _configured() and not presented:
        return {'verified': True, 'sub': 'user:dev', 'kind': 'person', 'stage': 'production', 'simulated': True}
    return _verified_with_helper(headers)
