"""
Analytics - lightweight, privacy-preserving in-memory usage counters.

Only aggregate counts are tracked (never user content, text, or credentials).
Exposed to admins via /api/admin/analytics. Optional Google Analytics is handled
separately in the template and is disabled unless GOOGLE_ANALYTICS_KEY is set.
"""

import os
import time
import threading

# Only track counters when server analytics are enabled. This makes the
# documented ENABLE_SERVER_ANALYTICS switch (and admin toggle) actually take
# effect instead of always counting.
ENABLED = os.environ.get('ENABLE_SERVER_ANALYTICS', 'false').lower() == 'true'

_lock = threading.Lock()
_counters = {
    'translations': 0,
    'transcriptions': 0,
    'sessions_created': 0,
    'logins': 0,
}
_started_at = time.time()


def set_enabled(value):
    """Dynamically enable/disable analytics collection (e.g. from admin settings)."""
    global ENABLED
    ENABLED = bool(value)


def incr(key, n=1):
    if not ENABLED:
        return
    with _lock:
        _counters[key] = _counters.get(key, 0) + n

def snapshot():
    with _lock:
        data = dict(_counters)
    data['uptime_seconds'] = int(time.time() - _started_at)
    return data
