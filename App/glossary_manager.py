"""
Glossary Manager - Manage custom translation glossaries (term mappings).
Stored as JSON files in /data/glossaries/.
"""

import os
import json
import logging
import csv
import tempfile
from io import StringIO
from datetime import datetime

logger = logging.getLogger(__name__)

GLOSSARY_DIR = os.environ.get('GLOSSARY_DIR', '/data/glossaries')
SINGLE_GLOSSARY_ID = 'Glossary'
SINGLE_GLOSSARY_NAME = 'Glossary'


def _ensure_dir():
    os.makedirs(GLOSSARY_DIR, exist_ok=True)


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


def list_glossaries():
    """List all glossaries."""
    _ensure_dir()
    glossaries = []
    for fname in os.listdir(GLOSSARY_DIR):
        if fname.endswith('.json'):
            fpath = os.path.join(GLOSSARY_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                glossaries.append({
                    'id': fname[:-5],
                    'name': data.get('name', fname[:-5]),
                    'source_language': data.get('source_language', ''),
                    'target_language': data.get('target_language', ''),
                    'entry_count': len(data.get('entries', {})),
                    'created_at': data.get('created_at', ''),
                    'updated_at': data.get('updated_at', ''),
                })
            except Exception as e:
                logger.warning(f"Error reading glossary {fname}: {e}")
    return glossaries


def get_glossary(glossary_id):
    """Get a glossary by ID."""
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_glossary(name, source_language, target_language, entries=None, glossary_id=None):
    """Create a new glossary. entries: dict of {source_term: target_term}."""
    _ensure_dir()
    if glossary_id is None:
        import uuid
        glossary_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat() + 'Z'
    existing_created_at = None
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            existing_created_at = existing.get('created_at')
        except Exception:
            existing_created_at = None
    data = {
        'name': name,
        'source_language': source_language,
        'target_language': target_language,
        'entries': entries or {},
        'created_at': existing_created_at or now,
        'updated_at': now,
    }
    _atomic_write_json(fpath, data)
    return {'id': glossary_id, **data}


def import_glossary_from_text(name, source_language, target_language, text, filename=''):
    """Import glossary entries from JSON/CSV/TSV/TXT text and create a glossary."""
    if not text or not text.strip():
        raise ValueError('Glossary file is empty')

    lower_name = (filename or '').lower()
    if lower_name.endswith('.json'):
        fmt = 'json'
    elif lower_name.endswith('.tsv'):
        fmt = 'tsv'
    elif lower_name.endswith('.csv'):
        fmt = 'csv'
    else:
        fmt = 'txt'

    entries = _parse_entries(text, fmt)
    if not entries:
        raise ValueError('No valid glossary entries were found')

    final_name = (name or '').strip() or _default_name_from_filename(filename)
    return create_glossary(
        name=final_name,
        source_language=source_language,
        target_language=target_language,
        entries=entries,
    )


def replace_single_glossary_from_text(source_language, target_language, text, filename=''):
    """Replace all glossary data with a single glossary named 'Glossary'."""
    if not text or not text.strip():
        raise ValueError('Glossary file is empty')

    lower_name = (filename or '').lower()
    if lower_name.endswith('.json'):
        fmt = 'json'
    elif lower_name.endswith('.tsv'):
        fmt = 'tsv'
    elif lower_name.endswith('.csv'):
        fmt = 'csv'
    else:
        fmt = 'txt'

    entries = _parse_entries(text, fmt)
    if not entries:
        raise ValueError('No valid glossary entries were found')

    _ensure_dir()
    for fname in os.listdir(GLOSSARY_DIR):
        if not fname.endswith('.json'):
            continue
        if fname == f'{SINGLE_GLOSSARY_ID}.json':
            continue
        try:
            os.remove(os.path.join(GLOSSARY_DIR, fname))
        except Exception as e:
            logger.warning(f'Failed to remove old glossary {fname}: {e}')

    return create_glossary(
        name=SINGLE_GLOSSARY_NAME,
        source_language=source_language,
        target_language=target_language,
        entries=entries,
        glossary_id=SINGLE_GLOSSARY_ID,
    )


def _default_name_from_filename(filename):
    base = os.path.basename(filename or '')
    if not base:
        return f"Glossary {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    return os.path.splitext(base)[0] or 'Imported Glossary'


def _parse_entries(text, fmt):
    if fmt == 'json':
        return _parse_json_entries(text)
    if fmt == 'csv':
        return _parse_delimited_entries(text, ',')
    if fmt == 'tsv':
        return _parse_delimited_entries(text, '\t')
    return _parse_text_entries(text)


def _parse_json_entries(text):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f'Invalid JSON: {e}')

    entries = {}
    if isinstance(payload, dict):
        for source, target in payload.items():
            source_term = str(source).strip()
            target_term = str(target).strip()
            if source_term and target_term:
                entries[source_term] = target_term
        return entries

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            source_term = str(
                item.get('source') or item.get('source_term') or item.get('from') or ''
            ).strip()
            target_term = str(
                item.get('target') or item.get('target_term') or item.get('to') or ''
            ).strip()
            if source_term and target_term:
                entries[source_term] = target_term
        return entries

    raise ValueError('JSON format must be an object map or an array of objects')


def _parse_delimited_entries(text, delimiter):
    entries = {}
    reader = csv.reader(StringIO(text), delimiter=delimiter)

    for idx, row in enumerate(reader):
        if not row:
            continue

        source_term = (row[0] if len(row) > 0 else '').strip()
        target_term = (row[1] if len(row) > 1 else '').strip()

        # Skip header row when it looks like labels.
        if idx == 0:
            lhs = source_term.lower()
            rhs = target_term.lower()
            if lhs in ('source', 'source_term', 'from') and rhs in ('target', 'target_term', 'to'):
                continue

        if source_term and target_term:
            entries[source_term] = target_term

    return entries


def _parse_text_entries(text):
    entries = {}
    separators = ('=>', '->', '\t', ',', '=')

    for line in text.splitlines():
        current = line.strip()
        if not current or current.startswith('#'):
            continue

        source_term = ''
        target_term = ''
        for sep in separators:
            if sep in current:
                parts = current.split(sep, 1)
                source_term = parts[0].strip()
                target_term = parts[1].strip()
                break

        if source_term and target_term:
            entries[source_term] = target_term

    return entries


def update_glossary(glossary_id, name=None, entries=None):
    """Update an existing glossary."""
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if name is not None:
        data['name'] = name
    if entries is not None:
        data['entries'] = entries
    data['updated_at'] = datetime.utcnow().isoformat() + 'Z'
    _atomic_write_json(fpath, data)
    return data


def delete_glossary(glossary_id):
    """Delete a glossary."""
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return False
    os.remove(fpath)
    return True


def get_entries_for_pair(source_lang, target_lang):
    """Get merged glossary entries for a language pair."""
    _ensure_dir()
    merged = {}
    for fname in os.listdir(GLOSSARY_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(GLOSSARY_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if (data.get('source_language') == source_lang and
                    data.get('target_language') == target_lang):
                merged.update(data.get('entries', {}))
        except Exception:
            continue
    return merged
