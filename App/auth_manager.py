"""
Auth Manager - JWT issuing/verification, request decorators, and in-memory login
rate limiting for the optional authentication system (Phase 2).

Tokens are stateless JWTs (HS256) signed with the app's SECRETS/SECRET_KEY.
Logout is supported via a server-side revocation list (see user_manager). The
whole subsystem is inert unless the application enables ALLOW_AUTH.
"""

import os
import time
import uuid
import logging
import threading
from functools import wraps

import jwt
from flask import request, g, jsonify

import user_manager

logger = logging.getLogger(__name__)

JWT_SECRET = (
    os.environ.get('SECRETS', '').strip()
    or os.environ.get('SECRET_KEY', '').strip()
    or os.urandom(32).hex()
)
JWT_ALGORITHM = 'HS256'
JWT_ISSUER = 'live-translate'
JWT_TTL_SECONDS = int(os.environ.get('JWT_TTL_SECONDS', str(24 * 3600)))

# Only trust X-Forwarded-For when running behind a trusted reverse proxy.
# Otherwise clients can spoof the header to bypass login/register rate limits.
TRUST_PROXY = os.environ.get('TRUST_PROXY', 'false').lower() == 'true'

LOGIN_RATE_MAX = int(os.environ.get('LOGIN_RATE_MAX', '5'))
LOGIN_RATE_WINDOW = int(os.environ.get('LOGIN_RATE_WINDOW', '900'))
REGISTER_RATE_MAX = int(os.environ.get('REGISTER_RATE_MAX', '3'))
REGISTER_RATE_WINDOW = int(os.environ.get('REGISTER_RATE_WINDOW', '3600'))

_login_attempts = {}
_register_attempts = {}
_rl_lock = threading.Lock()

def create_access_token(user_id, role, username, extra_claims=None):
    now = int(time.time())
    payload = {
        'sub': user_id,
        'username': username,
        'role': role,
        'token_version': user_manager.get_token_version(user_id),
        'iat': now,
        'exp': now + JWT_TTL_SECONDS,
        'iss': JWT_ISSUER,
        'jti': uuid.uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, payload['exp']

def decode_token(token):
    """Return claims for a valid, unexpired, non-revoked token, else None."""
    if not token or not isinstance(token, str):
        return None
    try:
        claims = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer=JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    if user_manager.is_token_revoked(claims.get('jti', '')):
        return None
    # Reject tokens for deleted or banned users, and tokens whose version no
    # longer matches the user's current token_version (e.g. after a ban).
    row = user_manager.get_user_by_id(claims.get('sub', ''))
    if row is None or row['status'] != 'active':
        return None
    if int(row['token_version']) != int(claims.get('token_version', 0)):
        return None
    return claims

def _extract_token():
    auth = request.headers.get('Authorization', '') or ''
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    return None

def get_current_user():
    """Return claims of the authenticated user, or None if unauthenticated."""
    return decode_token(_extract_token())

def optional_auth(view):
    """Attach g.current_user (may be None); never blocks the request."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        g.current_user = get_current_user()
        return view(*args, **kwargs)
    return wrapper

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapper

def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': 'Admin privileges required'}), 403
        g.current_user = user
        return view(*args, **kwargs)
    return wrapper

def client_ip():
    if TRUST_PROXY:
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.remote_addr or '-'

def login_rate_ok(ip):
    now = time.time()
    with _rl_lock:
        attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_RATE_WINDOW]
        _login_attempts[ip] = attempts
        return len(attempts) < LOGIN_RATE_MAX

def record_login_failure(ip):
    with _rl_lock:
        _login_attempts.setdefault(ip, []).append(time.time())

def reset_login_attempts(ip):
    with _rl_lock:
        _login_attempts.pop(ip, None)

def register_rate_ok(ip):
    now = time.time()
    with _rl_lock:
        attempts = [t for t in _register_attempts.get(ip, []) if now - t < REGISTER_RATE_WINDOW]
        _register_attempts[ip] = attempts
        return len(attempts) < REGISTER_RATE_MAX

def record_register_attempt(ip):
    with _rl_lock:
        _register_attempts.setdefault(ip, []).append(time.time())
