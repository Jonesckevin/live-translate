"""
Crypto Manager - signing and tokenization utilities backed by the SECRETS key.

Uses itsdangerous (bundled with Flask) for signed, time-limited tokens such as
session share codes and access tokens, plus the stdlib `secrets` module for
cryptographically-secure random codes and constant-time comparisons. No extra
dependencies are required.

If the SECRETS environment variable is unset, an ephemeral key is generated so
local/development use keeps working; the application logs a warning and can be
configured to fail hard in production via REQUIRE_SECRETS=true.
"""

import os
import base64
import hashlib
import logging
import secrets as _secrets

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

_SHARE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

_SECRETS_KEY = os.environ.get('SECRETS', '').strip()
_EPHEMERAL = False
if not _SECRETS_KEY:
    _SECRETS_KEY = _secrets.token_hex(32)
    _EPHEMERAL = True

_serializer = URLSafeTimedSerializer(_SECRETS_KEY, salt='live-translate.v1')

def is_ephemeral():
    """Return True when SECRETS was not provided and a throwaway key is in use."""
    return _EPHEMERAL

def has_secrets():
    """Return True when a persistent SECRETS key is configured."""
    return not _EPHEMERAL

def generate_share_code(length=8):
    """Return a cryptographically-secure, unambiguous alphanumeric share code."""
    return ''.join(_secrets.choice(_SHARE_ALPHABET) for _ in range(length))

def generate_token(nbytes=32):
    """Return a URL-safe cryptographically-secure random token."""
    return _secrets.token_urlsafe(nbytes)

def sign(payload):
    """Serialize and sign a payload (str or JSON-serializable) into a token."""
    return _serializer.dumps(payload)

def verify(token, max_age=None):
    """Return the payload if the token is valid and unexpired, else None.

    max_age is in seconds; when provided, tokens older than that are rejected.
    """
    if not token or not isinstance(token, str):
        return None
    try:
        return _serializer.loads(token, max_age=max_age)
    except SignatureExpired:
        logger.info("Rejected expired token")
        return None
    except BadSignature:
        logger.warning("Rejected token with invalid signature")
        return None

def constant_time_compare(a, b):
    """Timing-attack-resistant comparison of two strings."""
    return _secrets.compare_digest(str(a), str(b))

_fernet = None

def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(_SECRETS_KEY.encode('utf-8')).digest())
        _fernet = Fernet(key)
    return _fernet

def encrypt(plaintext):
    """Return a URL-safe ciphertext string for the given plaintext ('' for empty)."""
    if plaintext is None or plaintext == '':
        return ''
    try:
        return _get_fernet().encrypt(str(plaintext).encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error("Encryption failed: %s", e)
        return ''

def decrypt(ciphertext):
    """Return the decrypted plaintext, or None if the token is invalid/unreadable."""
    if not ciphertext:
        return ''
    try:
        return _get_fernet().decrypt(str(ciphertext).encode('utf-8')).decode('utf-8')
    except Exception:
        return None
