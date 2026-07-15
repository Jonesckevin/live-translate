"""
Admin Settings Manager - persistent server-level toggles managed from the admin
panel (Phase 4). Stored as JSON under /data so it persists across restarts.

These settings are only consulted when authentication is enabled; they let an
admin adjust runtime policy (public listing, sharing, per-user limits, etc.)
without editing environment variables or restarting the container.
"""

import os
import json
import logging
import tempfile
import threading

logger = logging.getLogger(__name__)

ADMIN_SETTINGS_FILE = os.environ.get('ADMIN_SETTINGS_FILE', '/data/admin_settings.json')

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    'allow_public_sessions': True,
    'allow_session_sharing': True,
    'enable_analytics': False,
    'max_sessions_per_user': 0,
    'cache_retention_days': 30,
}

_ALLOWED_TYPES = {
    'allow_public_sessions': bool,
    'allow_session_sharing': bool,
    'enable_analytics': bool,
    'max_sessions_per_user': int,
    'cache_retention_days': int,
}

def _atomic_write(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=directory or None)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def get_settings():
    """Return merged settings (defaults overlaid with any persisted values)."""
    merged = DEFAULT_SETTINGS.copy()
    try:
        if os.path.exists(ADMIN_SETTINGS_FILE):
            with open(ADMIN_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                stored = json.load(f)
            for key in DEFAULT_SETTINGS:
                if key in stored:
                    merged[key] = stored[key]
    except Exception as e:
        logger.error("Error reading admin settings: %s", e)
    return merged

def save_settings(partial):
    """Validate and persist a partial settings update. Returns a result dict."""
    if not isinstance(partial, dict):
        return {'success': False, 'error': 'Settings payload must be an object'}
    current = get_settings()
    for key, value in partial.items():
        if key not in _ALLOWED_TYPES:
            continue
        expected = _ALLOWED_TYPES[key]
        if expected is bool:
            if not isinstance(value, bool):
                return {'success': False, 'error': f'{key} must be a boolean'}
        elif expected is int:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return {'success': False, 'error': f'{key} must be a non-negative integer'}
        current[key] = value
    with _lock:
        try:
            _atomic_write(ADMIN_SETTINGS_FILE, current)
        except Exception as e:
            logger.error("Error saving admin settings: %s", e)
            return {'success': False, 'error': 'Failed to persist settings'}
    return {'success': True}

def reset_settings():
    with _lock:
        _atomic_write(ADMIN_SETTINGS_FILE, DEFAULT_SETTINGS.copy())
    return {'success': True, 'settings': DEFAULT_SETTINGS.copy()}
