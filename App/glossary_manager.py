"""
Glossary Manager - Manage custom translation glossaries (term mappings).
Stored as JSON files in /data/glossaries/.
"""

import os
import re
import json
import logging
import csv
from io import StringIO
from datetime import datetime, timezone

from storage_utils import is_safe_id as _is_safe_id, atomic_write_json as _atomic_write_json

logger = logging.getLogger(__name__)

GLOSSARY_DIR = os.environ.get('GLOSSARY_DIR', '/data/glossaries')
SINGLE_GLOSSARY_ID = 'Glossary'
SINGLE_GLOSSARY_NAME = 'Glossary'

def _ensure_dir():
    os.makedirs(GLOSSARY_DIR, exist_ok=True)

def list_glossaries():
    """List legacy pair-based glossaries.

    Concept-based glossaries (top-level "concepts" array) are excluded here;
    they are surfaced separately via list_concept_glossaries() for the viewer.
    """
    _ensure_dir()
    glossaries = []
    for fname in os.listdir(GLOSSARY_DIR):
        if fname.endswith('.json'):
            fpath = os.path.join(GLOSSARY_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get('concepts'), list):
                    continue
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
    if not _is_safe_id(glossary_id):
        logger.warning("Rejected unsafe glossary id in get_glossary")
        return None
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
    elif not _is_safe_id(glossary_id):
        raise ValueError('Invalid glossary id')
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
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
    if not _is_safe_id(glossary_id):
        logger.warning("Rejected unsafe glossary id in update_glossary")
        return None
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
    data['updated_at'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    _atomic_write_json(fpath, data)
    return data

def delete_glossary(glossary_id):
    """Delete a glossary."""
    if not _is_safe_id(glossary_id):
        logger.warning("Rejected unsafe glossary id in delete_glossary")
        return False
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


def _load_concept_glossaries():
    """Load all concept-based glossary files from GLOSSARY_DIR.

    Concept-based files have a top-level "concepts" list. Each concept has a
    concept_id and a "terms" list of language-tagged records
    ({language, term, description, part_of_speech, ...}). Returns a list of
    glossary dicts (id/name/domain/canonical_language/top_description/concepts).
    """
    _ensure_dir()
    glossaries = []
    for fname in os.listdir(GLOSSARY_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(GLOSSARY_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict) or not isinstance(data.get('concepts'), list):
            continue
        glossaries.append({
            'id': fname[:-5],
            'name': data.get('name', fname[:-5]),
            'domain': data.get('domain', ''),
            'canonical_language': data.get('canonical_language', 'en'),
            'top_description': data.get('top_description', ''),
            'concepts': data['concepts'],
        })
    return glossaries


def _concepts_to_term_map(glossaries, source_lang, target_lang):
    """Build {source_term: target_term} by resolving each concept across the
    given source/target languages. Resolving by concept makes this work in
    either direction (source term -> concept -> target term)."""
    entries = {}
    for g in glossaries:
        for concept in g.get('concepts', []):
            terms = concept.get('terms') or []
            by_lang = {}
            for t in terms:
                if isinstance(t, dict) and t.get('language'):
                    by_lang[t['language']] = t
            src = by_lang.get(source_lang)
            tgt = by_lang.get(target_lang)
            if src and tgt and src.get('term') and tgt.get('term'):
                entries[src['term']] = tgt['term']
    return entries


def get_entries_for(source_lang, target_lang):
    """Return {source_term: target_term} for a language pair.

    Concept-based glossaries are resolved bidirectionally (one file supports
    both directions); legacy pair-based glossaries are still merged for
    backward compatibility.
    """
    if not source_lang or not target_lang:
        return {}
    entries = _concepts_to_term_map(_load_concept_glossaries(), source_lang, target_lang)
    entries.update(get_entries_for_pair(source_lang, target_lang))
    return entries


def list_concept_glossaries():
    """Return concept-based glossaries (for the glossary viewer)."""
    return _load_concept_glossaries()


def save_concept_glossary(data, glossary_id=None):
    """Persist a concept-based glossary dict (with a 'concepts' list) to disk.

    Returns {'id', 'name', 'concept_count'}. If glossary_id is omitted it is
    derived from the glossary name (slugified) or a random id when unsafe.
    """
    if not isinstance(data, dict) or not isinstance(data.get('concepts'), list) or not data['concepts']:
        raise ValueError('Concept glossary must be a JSON object with a non-empty "concepts" list')
    _ensure_dir()
    if glossary_id is None:
        name = (data.get('name') or '').strip()
        slug = re.sub(r'[^A-Za-z0-9._-]+', '-', name.lower()).strip('-') if name else ''
        glossary_id = slug or 'glossary'
        if not _is_safe_id(glossary_id):
            import uuid
            glossary_id = 'glossary-' + str(uuid.uuid4())[:6]
    elif not _is_safe_id(glossary_id):
        raise ValueError('Invalid glossary id')
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    payload = dict(data)
    payload.setdefault('created_at', now)
    payload['updated_at'] = now
    _atomic_write_json(os.path.join(GLOSSARY_DIR, f"{glossary_id}.json"), payload)
    return {
        'id': glossary_id,
        'name': payload.get('name', glossary_id),
        'concept_count': len(payload['concepts']),
        'entry_count': len(payload['concepts']),
    }


def get_concept_glossary(glossary_id):
    """Return a single concept-based glossary dict, or None."""
    if not _is_safe_id(glossary_id):
        return None
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get('concepts'), list):
        return None
    return data


def update_concept_glossary(glossary_id, data):
    """Update top-level fields and/or the concepts list of a concept glossary."""
    if not _is_safe_id(glossary_id):
        return None
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    for key in ('name', 'domain', 'canonical_language', 'top_description'):
        if isinstance(data, dict) and key in data:
            existing[key] = data[key]
    if isinstance(data, dict) and isinstance(data.get('concepts'), list):
        existing['concepts'] = data['concepts']
    existing['updated_at'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    _atomic_write_json(fpath, existing)
    return existing


def add_concept(glossary_id, concept):
    """Append a concept (dict with concept_id + terms) to a concept glossary."""
    if not _is_safe_id(glossary_id):
        return None
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    if not isinstance(existing.get('concepts'), list):
        return None
    if not isinstance(concept, dict) or not concept.get('concept_id'):
        raise ValueError('Concept must include a concept_id')
    for c in existing['concepts']:
        if c.get('concept_id') == concept['concept_id']:
            raise ValueError(f"Concept '{concept['concept_id']}' already exists")
    if not isinstance(concept.get('terms'), list) or not concept['terms']:
        raise ValueError('Concept must include a non-empty terms list')
    existing['concepts'].append(concept)
    existing['updated_at'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    _atomic_write_json(fpath, existing)
    return existing


def delete_concept(glossary_id, concept_id):
    """Remove a concept from a concept glossary by concept_id."""
    if not _is_safe_id(glossary_id):
        return False
    _ensure_dir()
    fpath = os.path.join(GLOSSARY_DIR, f"{glossary_id}.json")
    if not os.path.exists(fpath):
        return False
    with open(fpath, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    if not isinstance(existing.get('concepts'), list):
        return False
    before = len(existing['concepts'])
    existing['concepts'] = [c for c in existing['concepts'] if c.get('concept_id') != concept_id]
    if len(existing['concepts']) == before:
        return False
    existing['updated_at'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    _atomic_write_json(fpath, existing)
    return True
