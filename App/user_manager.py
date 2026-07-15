"""
User Manager - SQLite-backed user accounts, password hashing, and token
revocation for the optional authentication system (Phase 2).

Storage lives in a single SQLite database under /data so it persists on the
same volume as sessions/glossaries. bcrypt is used for password hashing. All
access uses short-lived per-operation connections (WAL mode) which is safe for
the app's low-concurrency auth workload.

The whole subsystem is inert unless ALLOW_AUTH is enabled by the application;
this module only manages storage and never enforces policy on its own.
"""

import os
import re
import time
import json
import uuid
import sqlite3
import logging
import threading
from datetime import datetime, timezone

import bcrypt

logger = logging.getLogger(__name__)

USERS_DB = os.environ.get('USERS_DB', '/data/users.db')
GUEST_ARCHIVE_DB = os.environ.get('GUEST_ARCHIVE_DB', '/data/tempuser_archive.db')
GUEST_TTL_HOURS = int(os.environ.get('GUEST_TTL_HOURS', '24'))

_write_lock = threading.Lock()

_USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,32}$')

VALID_ROLES = ('user', 'admin', 'guest')
VALID_STATUSES = ('active', 'banned')

def _connect():
    directory = os.path.dirname(USERS_DB)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(USERS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn

def init_db():
    """Create tables if they do not exist. Safe to call repeatedly."""
    with _write_lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
                email         TEXT,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'user',
                status        TEXT NOT NULL DEFAULT 'active',
                is_guest      INTEGER NOT NULL DEFAULT 0,
                expires_at    INTEGER,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti        TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id      TEXT PRIMARY KEY,
                settings_json TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )
        conn.commit()
    logger.info("User database initialized at %s", USERS_DB)

def validate_username(username):
    if not isinstance(username, str) or not _USERNAME_RE.match(username or ''):
        return 'Username must be 3-32 chars: letters, numbers, dot, underscore, or hyphen'
    return None

def validate_password(password):
    if not isinstance(password, str) or len(password) < 12:
        return 'Password must be at least 12 characters'
    if len(password) > 128:
        return 'Password must be at most 128 characters'
    if not re.search(r'[a-z]', password):
        return 'Password must include a lowercase letter'
    if not re.search(r'[A-Z]', password):
        return 'Password must include an uppercase letter'
    if not re.search(r'[0-9]', password):
        return 'Password must include a number'
    return None

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except (ValueError, TypeError):
        return False

def _public(row):
    """Return a user dict without the password hash."""
    if row is None:
        return None
    return {
        'user_id': row['user_id'],
        'username': row['username'],
        'email': row['email'],
        'role': row['role'],
        'status': row['status'],
        'is_guest': bool(row['is_guest']) if 'is_guest' in row.keys() else False,
        'expires_at': row['expires_at'] if 'expires_at' in row.keys() else None,
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }

def count_users():
    with _connect() as conn:
        return conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']

def get_user_by_username(username):
    if not username:
        return None
    with _connect() as conn:
        return conn.execute(
            'SELECT * FROM users WHERE username = ? COLLATE NOCASE', (username.strip(),)
        ).fetchone()

def get_user_by_id(user_id):
    if not user_id:
        return None
    with _connect() as conn:
        return conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()

def create_user(username, password, email=None, role='user'):
    """Create a user. Raises ValueError on validation failure or duplicate name."""
    username = (username or '').strip()
    err = validate_username(username)
    if err:
        raise ValueError(err)
    err = validate_password(password)
    if err:
        raise ValueError(err)
    if role not in VALID_ROLES:
        role = 'user'

    now = datetime.utcnow().isoformat() + 'Z'
    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)

    with _write_lock, _connect() as conn:
        try:
            conn.execute(
                'INSERT INTO users (user_id, username, email, password_hash, role, status, created_at, updated_at)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (user_id, username, (email or '').strip() or None, password_hash, role, 'active', now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError('Username already exists')

    logger.info("Created user '%s' (role=%s)", username, role)
    return {
        'user_id': user_id, 'username': username, 'email': (email or '').strip() or None,
        'role': role, 'status': 'active', 'created_at': now, 'updated_at': now,
    }

def authenticate(username, password):
    """Return the public user dict on success, else None. Timing-hardened."""
    row = get_user_by_username(username)
    if row is None:
        hash_password('timing~guard~000000')
        return None
    if row['status'] != 'active':
        return None
    if not verify_password(password, row['password_hash']):
        return None
    return _public(row)

def list_users(limit=50, offset=0):
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset)
        ).fetchall()
    return [_public(r) for r in rows]

def set_role(user_id, role):
    if role not in VALID_ROLES:
        raise ValueError('Invalid role')
    now = datetime.utcnow().isoformat() + 'Z'
    with _write_lock, _connect() as conn:
        cur = conn.execute(
            'UPDATE users SET role = ?, updated_at = ? WHERE user_id = ?', (role, now, user_id)
        )
        conn.commit()
    return cur.rowcount > 0

def set_status(user_id, status):
    if status not in VALID_STATUSES:
        raise ValueError('Invalid status')
    now = datetime.utcnow().isoformat() + 'Z'
    with _write_lock, _connect() as conn:
        cur = conn.execute(
            'UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?', (status, now, user_id)
        )
        conn.commit()
    return cur.rowcount > 0

def delete_user(user_id):
    with _write_lock, _connect() as conn:
        conn.execute('DELETE FROM user_settings WHERE user_id = ?', (user_id,))
        cur = conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()
    return cur.rowcount > 0

def revoke_token(jti, expires_at):
    if not jti:
        return
    with _write_lock, _connect() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)',
            (jti, int(expires_at or 0)),
        )
        conn.commit()

def is_token_revoked(jti):
    if not jti:
        return False
    with _connect() as conn:
        return conn.execute('SELECT 1 FROM revoked_tokens WHERE jti = ?', (jti,)).fetchone() is not None

def cleanup_expired_tokens():
    """Remove revocation entries whose tokens have already expired."""
    with _write_lock, _connect() as conn:
        cur = conn.execute('DELETE FROM revoked_tokens WHERE expires_at < ?', (int(time.time()),))
        conn.commit()
    return cur.rowcount

def create_guest_user():
    """Create a short-lived guest account. Returns the public user dict."""
    now_ts = int(time.time())
    expires_ts = now_ts + GUEST_TTL_HOURS * 3600
    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    display_name = 'Guest_' + uuid.uuid4().hex[:8]
    unusable_hash = '!!' + bcrypt.hashpw(uuid.uuid4().bytes, bcrypt.gensalt()).decode('utf-8')
    with _write_lock, _connect() as conn:
        conn.execute(
            'INSERT INTO users (user_id, username, email, password_hash, role, status, '
            'is_guest, expires_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (user_id, display_name, None, unusable_hash, 'guest', 'active', 1, expires_ts, now, now),
        )
        conn.commit()
    logger.info('Created guest user %s (expires %s)', display_name, expires_ts)
    return {
        'user_id': user_id, 'username': display_name, 'email': None,
        'role': 'guest', 'status': 'active', 'is_guest': True,
        'expires_at': expires_ts, 'created_at': now, 'updated_at': now,
    }

def list_expired_guests():
    """Return rows of guest users whose TTL has elapsed."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM users WHERE is_guest = 1 AND expires_at IS NOT NULL AND expires_at < ?',
            (int(time.time()),)
        ).fetchall()
    return [dict(r) for r in rows]

def _archive_connect():
    directory = os.path.dirname(GUEST_ARCHIVE_DB)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(GUEST_ARCHIVE_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def archive_and_purge_guests():
    """Copy expired guest rows to tempuser_archive.db, then delete them."""
    expired = list_expired_guests()
    if not expired:
        return 0

    archive_now = datetime.now(timezone.utc).isoformat()
    with _archive_connect() as arc:
        arc.execute(
            """
            CREATE TABLE IF NOT EXISTS archived_guests (
                user_id    TEXT PRIMARY KEY,
                username   TEXT,
                role       TEXT,
                status     TEXT,
                is_guest   INTEGER,
                expires_at INTEGER,
                created_at TEXT,
                updated_at TEXT,
                archived_at TEXT
            )
            """
        )
        for row in expired:
            arc.execute(
                'INSERT OR REPLACE INTO archived_guests '
                '(user_id, username, role, status, is_guest, expires_at, created_at, updated_at, archived_at) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (row['user_id'], row['username'], row['role'], row['status'],
                 row['is_guest'], row['expires_at'], row['created_at'],
                 row['updated_at'], archive_now),
            )
        arc.commit()

    ids = tuple(r['user_id'] for r in expired)
    with _write_lock, _connect() as conn:
        conn.execute(f"DELETE FROM user_settings WHERE user_id IN ({','.join('?'*len(ids))})", ids)
        conn.execute(f"DELETE FROM revoked_tokens WHERE jti IN ("
                     f"SELECT jti FROM revoked_tokens LIMIT 0)")
        conn.execute(f"DELETE FROM users WHERE user_id IN ({','.join('?'*len(ids))})", ids)
        conn.commit()

    logger.info('Archived and purged %d expired guest accounts', len(expired))
    return len(expired)

def get_user_settings(user_id):
    """Return the stored settings dict for a user, or None if none saved."""
    if not user_id:
        return None
    with _connect() as conn:
        row = conn.execute(
            'SELECT settings_json FROM user_settings WHERE user_id = ?', (user_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row['settings_json'])
    except (ValueError, TypeError):
        return None

def save_user_settings(user_id, settings):
    """Persist a settings dict (with secrets already encrypted) for a user."""
    if not user_id:
        return False
    now = datetime.utcnow().isoformat() + 'Z'
    payload = json.dumps(settings)
    with _write_lock, _connect() as conn:
        conn.execute(
            'INSERT INTO user_settings (user_id, settings_json, updated_at) VALUES (?, ?, ?) '
            'ON CONFLICT(user_id) DO UPDATE SET settings_json = excluded.settings_json, '
            'updated_at = excluded.updated_at',
            (user_id, payload, now),
        )
        conn.commit()
    return True
