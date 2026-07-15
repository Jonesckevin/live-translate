"""
Docs Manager - discover and render the Markdown documents in App/Docs for the
in-app documentation viewer (`/docs`).

Only files inside the Docs directory are served, matched against a strict slug
pattern to prevent path traversal. Markdown is converted to HTML server-side;
the documents are trusted project files (not user input).
"""

import os
import re
import logging

logger = logging.getLogger(__name__)

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Docs')

_SLUG_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

_ORDER = [
    'PRIVACY_POLICY', 'TERMS_OF_SERVICE', 'ACCEPTABLE_USE_POLICY',
    'SECURITY', 'LICENSE', 'CODE_OF_CONDUCT', 'CONTRIBUTING',
    'CONFIGURATION', 'DEPLOYMENT',
]

def _title(path, slug):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('# '):
                    return stripped[2:].strip()
    except Exception:
        pass
    return slug.replace('_', ' ').title()

def list_docs():
    """Return [{slug, title}] for every Markdown file in the Docs directory."""
    if not os.path.isdir(DOCS_DIR):
        return []
    items = []
    for fname in os.listdir(DOCS_DIR):
        if not fname.endswith('.md'):
            continue
        slug = fname[:-3]
        if not _SLUG_RE.match(slug):
            continue
        items.append({'slug': slug, 'title': _title(os.path.join(DOCS_DIR, fname), slug)})

    def sort_key(item):
        slug = item['slug']
        return (_ORDER.index(slug) if slug in _ORDER else len(_ORDER), item['title'].lower())

    items.sort(key=sort_key)
    return items

def render(slug):
    """Return rendered HTML for a doc slug, or None if missing/invalid."""
    if not slug or not _SLUG_RE.match(slug):
        return None
    path = os.path.join(DOCS_DIR, slug + '.md')
    if not os.path.isfile(path):
        return None
    base = os.path.realpath(DOCS_DIR)
    if os.path.commonpath([base, os.path.realpath(path)]) != base:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        logger.warning("Failed to read doc %s: %s", slug, e)
        return None

    import markdown
    html = markdown.markdown(
        text, extensions=['fenced_code', 'tables', 'sane_lists', 'toc'], output_format='html5',
    )
    return _rewrite_internal_links(html)

def _rewrite_internal_links(html):
    """Rewrite relative Markdown cross-links (e.g. FOO.md) to viewer routes (/docs/FOO)."""
    def repl(match):
        slug = os.path.basename(match.group(1))[:-3]
        return f'href="/docs/{slug}"'
    return re.sub(r'href="(?!https?://|/|#|mailto:)([^"]+\.md)"', repl, html)
