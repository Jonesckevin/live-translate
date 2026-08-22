"""
Shared file-system helpers used across managers.

Provides a strict identifier validator (path-traversal guard) and an atomic
JSON writer (write-to-temp-then-replace) so the same hardened logic is not
duplicated in every manager.
"""

import os
import re
import json
import tempfile

_VALID_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')


def is_safe_id(value):
    """Return True only for identifiers safe to interpolate into a file path."""
    return (
        isinstance(value, str)
        and bool(value)
        and '..' not in value
        and _VALID_ID_RE.match(value) is not None
    )


def atomic_write_json(path, data):
    """Atomically write ``data`` as JSON to ``path`` (temp file + os.replace)."""
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
