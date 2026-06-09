"""
Session Manager - Save and load translation/conversation session transcripts.
Stored as JSON files in /data/sessions/.
"""

import os
import json
import logging
import tempfile
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

SESSION_DIR = os.environ.get('SESSION_DIR', '/data/sessions')
SESSION_ICON_DIR = os.environ.get('SESSION_ICON_DIR', '/tmp/session-icons')
RETENTION_DAYS = int(os.environ.get('SESSION_RETENTION_DAYS', '30'))
_UNSET = object()


def _ensure_dir():
    os.makedirs(SESSION_DIR, exist_ok=True)


def _ensure_icon_dir():
    os.makedirs(SESSION_ICON_DIR, exist_ok=True)


def _atomic_write_json(path, data):
    directory = os.path.dirname(path)
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


def list_sessions():
    """List all sessions (metadata only)."""
    _ensure_dir()
    sessions = []
    for fname in sorted(os.listdir(SESSION_DIR), reverse=True):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(SESSION_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            sessions.append({
                'id': fname[:-5],
                'title': data.get('title', 'Untitled'),
                'type': data.get('type', 'translate'),
                'languages': data.get('languages', []),
                'icon_filename': data.get('icon_filename'),
                'message_count': len(data.get('messages', [])),
                'created_at': data.get('created_at', ''),
                'updated_at': data.get('updated_at', ''),
            })
        except Exception as e:
            logger.warning(f"Error reading session {fname}: {e}")
    return sessions


def get_session(session_id):
    """Get a full session by ID."""
    _ensure_dir()
    fpath = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_session(title, session_type='translate', languages=None):
    """Create a new session."""
    _ensure_dir()
    import uuid
    session_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '_' + str(uuid.uuid4())[:6]
    now = datetime.utcnow().isoformat() + 'Z'
    data = {
        'title': title,
        'type': session_type,
        'languages': languages or [],
        'icon_filename': None,
        'messages': [],
        'created_at': now,
        'updated_at': now,
    }
    fpath = os.path.join(SESSION_DIR, f"{session_id}.json")
    logger.debug(f"Creating new session: {session_id} with title '{title}'")
    _atomic_write_json(fpath, data)
    logger.info(f"Session created: {session_id} | Title: '{title}' | Type: {session_type}")
    return {'id': session_id, **data}


def add_message(session_id, message):
    """
    Add a message to a session.
    message: dict with keys like source_text, translated_text, source_lang, target_lang, engine, timestamp
    """
    _ensure_dir()
    fpath = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(fpath):
        logger.warning(f"Session {session_id} not found")
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'timestamp' not in message:
        message['timestamp'] = datetime.utcnow().isoformat() + 'Z'
    source_text_preview = message.get('source_text', '')[:30]
    translated_text_preview = message.get('translated_text', '')[:30]
    logger.debug(f"Adding message to session {session_id}: {source_text_preview}... -> {translated_text_preview}...")
    data['messages'].append(message)
    data['updated_at'] = datetime.utcnow().isoformat() + 'Z'
    _atomic_write_json(fpath, data)
    logger.info(f"Message saved to session {session_id} | Total messages: {len(data['messages'])}")
    return data


def update_session(session_id, title=None, icon_filename=_UNSET):
    """Update session metadata."""
    _ensure_dir()
    fpath = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(fpath):
        logger.warning(f"Session not found for update: {session_id}")
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    updates = []
    if title is not None:
        data['title'] = title
        updates.append(f"title='{title}'")
    if icon_filename is not _UNSET:
        data['icon_filename'] = icon_filename
        updates.append(f"icon='{icon_filename}'")
    data['updated_at'] = datetime.utcnow().isoformat() + 'Z'
    logger.debug(f"Updating session {session_id}: {', '.join(updates) if updates else 'no changes'}")
    _atomic_write_json(fpath, data)
    return data


def delete_icon_file(icon_filename):
    """Delete icon file by filename from the icon directory."""
    if not icon_filename:
        return False
    _ensure_icon_dir()
    fpath = os.path.join(SESSION_ICON_DIR, icon_filename)
    if not os.path.exists(fpath):
        return False
    os.remove(fpath)
    return True


def delete_session(session_id, delete_icon=True):
    """Delete a session."""
    _ensure_dir()
    fpath = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(fpath):
        logger.warning(f"Session not found for deletion: {session_id}")
        return False

    icon_filename = None
    if delete_icon:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            icon_filename = data.get('icon_filename')
        except Exception:
            icon_filename = None

    logger.debug(f"Deleting session file: {session_id}")
    os.remove(fpath)
    if delete_icon and icon_filename:
        try:
            logger.debug(f"Deleting session icon: {icon_filename}")
            delete_icon_file(icon_filename)
        except Exception as e:
            logger.warning(f"Failed to delete session icon {icon_filename}: {e}")
    logger.info(f"Session deleted: {session_id}")
    return True


def cleanup_old_sessions():
    """Remove sessions older than RETENTION_DAYS."""
    _ensure_dir()
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for fname in os.listdir(SESSION_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(SESSION_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            updated = data.get('updated_at', data.get('created_at', ''))
            if updated:
                ts = datetime.fromisoformat(updated.rstrip('Z'))
                if ts < cutoff:
                    os.remove(fpath)
                    removed += 1
        except Exception:
            continue
    return removed
