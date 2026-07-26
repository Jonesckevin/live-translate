"""
Live Translate - Real-time translation webapp with speech, text, and AI support.
Flask backend with SocketIO for real-time communication.
"""

import os
import time
import re
import hmac
import hashlib
import json
import logging
import socket
import uuid
import secrets
import threading
from logging.handlers import RotatingFileHandler
from datetime import datetime
from functools import wraps
import requests

try:
    import webauthn as _webauthn
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        ResidentKeyRequirement,
        UserVerificationRequirement,
        RegistrationCredential,
        AuthenticatorAttestationResponse,
        AuthenticationCredential,
        AuthenticatorAssertionResponse,
        AuthenticatorTransport,
    )
    from webauthn.helpers import (
        base64url_to_bytes as _b64url_to_bytes,
        bytes_to_base64url as _bytes_to_b64url,
    )
    PASSKEY_SUPPORT = True
except ImportError:
    PASSKEY_SUPPORT = False

from flask import Flask, request, jsonify, render_template, send_from_directory, Response, g, has_request_context
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

from llm_manager import LLMManager
from translation_manager import TranslationManager
import whisper_manager
import glossary_manager
import session_manager
import settings_manager
import crypto_manager
import user_manager
import auth_manager
import admin_settings_manager
import analytics
import docs_manager

app = Flask(__name__, static_folder='static', template_folder='templates')

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32).hex()

MAX_UPLOAD_MB = int(os.environ.get('MAX_UPLOAD_MB', '25'))
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

_cors_origins_raw = os.environ.get('CORS_ALLOWED_ORIGINS', '').strip()
CORS_ALLOW_ALL = _cors_origins_raw == '*'
if CORS_ALLOW_ALL:
    CORS_ALLOWED_ORIGINS = '*'
    _socketio_cors_origins = '*'
elif _cors_origins_raw:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins_raw.split(',') if o.strip()]
    _socketio_cors_origins = CORS_ALLOWED_ORIGINS
else:
    CORS_ALLOWED_ORIGINS = []
    _socketio_cors_origins = None
CORS_SAME_ORIGIN_ONLY = not CORS_ALLOW_ALL and not CORS_ALLOWED_ORIGINS

if CORS_ALLOW_ALL:
    CORS(app, resources={r"/api/*": {"origins": "*"}})
elif CORS_ALLOWED_ORIGINS:
    CORS(app, resources={r"/api/*": {"origins": CORS_ALLOWED_ORIGINS}})

SOCKETIO_PING_TIMEOUT = int(os.environ.get('SOCKETIO_PING_TIMEOUT', '60'))
SOCKETIO_PING_INTERVAL = int(os.environ.get('SOCKETIO_PING_INTERVAL', '25'))
SOCKETIO_ASYNC_HANDLERS = os.environ.get('SOCKETIO_ASYNC_HANDLERS', 'true').lower() == 'true'
SOCKETIO_CORS_CREDENTIALS = os.environ.get('SOCKETIO_CORS_CREDENTIALS', 'true').lower() == 'true'

socketio = SocketIO(
    app,
    cors_allowed_origins=_socketio_cors_origins,
    async_mode='eventlet',
    ping_timeout=SOCKETIO_PING_TIMEOUT,
    ping_interval=SOCKETIO_PING_INTERVAL,
    logger=True,
    engineio_logger=False,
    cors_credentials=SOCKETIO_CORS_CREDENTIALS
)

if os.environ.get('TRUST_PROXY', 'false').lower() == 'true':
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

LOGS_ACCESS_TOKEN = os.environ.get('LOGS_ACCESS_TOKEN', '').strip()

CONTENT_SECURITY_POLICY = os.environ.get(
    'CONTENT_SECURITY_POLICY',
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'",
).strip()

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
LOG_DIR = os.environ.get('LOG_DIR', '/data/logs')

ALLOW_CLIENT_API_KEYS = os.environ.get('ALLOW_CLIENT_API_KEYS', 'true').lower() == 'true'
WHISPER_PRELOAD_ON_STARTUP = os.environ.get('WHISPER_PRELOAD_ON_STARTUP', 'true').lower() == 'true'
STARTUP_FAIL_ON_CHECKS = os.environ.get('STARTUP_FAIL_ON_CHECKS', 'false').lower() == 'true'
REQUIRE_SECRETS = os.environ.get('REQUIRE_SECRETS', 'true').lower() == 'true'
IS_PRODUCTION = (os.environ.get('FLASK_ENV', '') or os.environ.get('APP_ENV', '')).lower() == 'production'
ALLOW_AUTH = os.environ.get('ALLOW_AUTH', 'true').lower() == 'true'
ALLOW_USER_REGISTRATION = os.environ.get('ALLOW_USER_REGISTRATION', 'true').lower() == 'true'
REQUIRE_AUTH = ALLOW_AUTH and (os.environ.get('REQUIRE_AUTH', 'true').lower() == 'true')
ALLOW_GUEST_LOGIN = ALLOW_AUTH and (os.environ.get('ALLOW_GUEST_LOGIN', 'true').lower() == 'true')
SHARE_CODE_TTL = int(os.environ.get('SHARE_CODE_TTL', str(24 * 3600)))
GOOGLE_ANALYTICS_KEY = os.environ.get('GOOGLE_ANALYTICS_KEY', '').strip()
ENABLE_SERVER_ANALYTICS = os.environ.get('ENABLE_SERVER_ANALYTICS', 'false').lower() == 'true'
ALLOWED_SESSION_ICON_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif'}
ALLOWED_SESSION_ICON_MIME_TYPES = {
    'image/png',
    'image/jpeg',
    'image/gif',
}

SERVER_API_KEYS = {
    'openai': os.environ.get('OPENAI_API_KEY', ''),
    'anthropic': os.environ.get('ANTHROPIC_API_KEY', ''),
    'gemini': os.environ.get('GOOGLE_API_KEY', ''),
    'deepseek': os.environ.get('DEEPSEEK_API_KEY', ''),
    'cohere': os.environ.get('COHERE_API_KEY', ''),
    'groq': os.environ.get('GROQ_API_KEY', ''),
    'grok': os.environ.get('GROK_API_KEY', ''),
    'mistral': os.environ.get('MISTRAL_API_KEY', ''),
    'perplexity': os.environ.get('PERPLEXITY_API_KEY', ''),
}

class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = '-'
        record.client_ip = '-'
        record.session_id = '-'

        if has_request_context():
            record.request_id = getattr(g, 'request_id', '-')
            record.client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '-')
            record.session_id = getattr(request, 'sid', '-')

        return True

os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, 'live-translate.log')
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s [req=%(request_id)s ip=%(client_ip)s sid=%(session_id)s]: %(message)s'
))
file_handler.setLevel(logging.INFO)
file_handler.addFilter(RequestContextFilter())

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s [req=%(request_id)s ip=%(client_ip)s sid=%(session_id)s]: %(message)s'
))
console_handler.setLevel(logging.INFO)
console_handler.addFilter(RequestContextFilter())

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

app_logger = logging.getLogger('live-translate')

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

config = load_config()

# --- Passkey / WebAuthn config --------------------------------------------
# RP_ID must match the hostname only (no port, no scheme). It is permanent —
# changing it invalidates all existing passkeys.
# ORIGIN is a comma-separated list. Supported values:
#   localhost           → accept any http://localhost:PORT
#   yarn                → accept any http(s)://yarn.<DOMAIN>[:<PORT>]
#   https://example.com → accept that exact origin
RP_ID = os.environ.get('RP_ID', 'localhost')
RP_NAME = os.environ.get('RP_NAME', config.get('app', {}).get('title', 'Live Translate'))

_PK_EXACT_ORIGINS: set = set()
_PK_ALLOW_LOCALHOST = False
_PK_ALLOW_YARN = False

for _tok in os.environ.get('ORIGIN', 'localhost').split(','):
    _tok = _tok.strip()
    if _tok.lower() == 'localhost':
        _PK_ALLOW_LOCALHOST = True
    elif _tok.lower() == 'yarn':
        _PK_ALLOW_YARN = True
    elif _tok:
        _PK_EXACT_ORIGINS.add(_tok)

_RE_LOCALHOST = re.compile(r'^https?://localhost(:\d+)?$')
_RE_YARN = re.compile(r'^https?://yarn\.[a-zA-Z0-9.-]+(:\d+)?$')


def _passkey_origin() -> str:
    """Resolve the expected WebAuthn origin from the incoming request Origin header."""
    origin = (request.headers.get('Origin') or '').strip()
    if origin:
        if _PK_ALLOW_LOCALHOST and _RE_LOCALHOST.match(origin):
            return origin
        if _PK_ALLOW_YARN and _RE_YARN.match(origin):
            return origin
        if origin in _PK_EXACT_ORIGINS:
            return origin
    return next(iter(_PK_EXACT_ORIGINS), 'http://localhost')

_pk_challenges: dict = {}
_pk_lock = threading.Lock()


def _pk_put(data: dict) -> str:
    cid = secrets.token_urlsafe(16)
    now = time.time()
    with _pk_lock:
        stale = [k for k, v in list(_pk_challenges.items()) if v['_exp'] < now]
        for k in stale:
            del _pk_challenges[k]
        _pk_challenges[cid] = {**data, '_exp': now + 300}
    return cid


def _pk_take(cid: str):
    with _pk_lock:
        c = _pk_challenges.pop(cid, None)
    if not c or c.get('_exp', 0) < time.time():
        return None
    return c


def mask_api_key(key):
    if not key or len(key) < 10:
        return None
    return f"●●●●●●{key[-6:]}"

def is_offline_mode():
    """Detect if app should run in offline mode."""
    env_offline = os.environ.get('OFFLINE_MODE', 'auto').lower()
    if env_offline == 'true':
        return True
    elif env_offline == 'false':
        return False
    
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return False
    except (socket.error, socket.timeout):
        return True

def get_runtime_offline_state():
    """Resolve effective offline policy from persisted settings + env/auto checks."""
    settings = settings_manager.get_settings()
    force_offline = bool(settings.get('force_offline', False))
    detected_offline = is_offline_mode()
    effective_offline = force_offline or detected_offline
    return {
        'offline': effective_offline,
        'force_offline': force_offline,
        'detected_offline': detected_offline,
        'edge_fallback_allowed': not effective_offline,
        'cloud_llm_available': not effective_offline,
        'local_llm_required': effective_offline,
    }

def is_cloud_provider(provider):
    if not provider:
        return False
    provider_cfg = LLMManager.PROVIDER_CONFIGS.get(provider, {})
    return provider_cfg.get('type') != 'local'

def apply_offline_translation_policy(engine, provider, model):
    """Normalize translation request according to effective offline policy."""
    mode_state = get_runtime_offline_state()
    policy_warning = None

    if mode_state['offline'] and engine == 'llm' and is_cloud_provider(provider):
        engine = 'libretranslate'
        provider = None
        model = None
        policy_warning = 'Force/local offline policy active: cloud LLM translation disabled, switched to LibreTranslate.'

    return engine, provider, model, policy_warning, mode_state

def get_api_key(provider, request_headers):
    key_source = request_headers.get('X-API-Key-Source', 'client')
    client_key = request_headers.get('X-API-Key', '')
    server_key = SERVER_API_KEYS.get(provider, '')

    if key_source == 'server' and server_key:
        return server_key, 'server'
    elif key_source == 'client' and client_key and ALLOW_CLIENT_API_KEYS:
        return client_key, 'client'
    elif client_key and ALLOW_CLIENT_API_KEYS:
        return client_key, 'client'
    elif server_key:
        return server_key, 'server'
    return None, None

def _build_session_icon_url(session_id, session_data):
    icon_filename = (session_data or {}).get('icon_filename')
    if not icon_filename:
        return None
    updated_at = (session_data or {}).get('updated_at', '')
    version = updated_at.replace(':', '').replace('-', '').replace('.', '') if updated_at else ''
    if version:
        return f"/api/sessions/{session_id}/icon?v={version}"
    return f"/api/sessions/{session_id}/icon"

def _serialize_session(session_id, session_data):
    payload = dict(session_data or {})
    payload['id'] = session_id
    payload['icon_url'] = _build_session_icon_url(session_id, payload)
    payload['has_password'] = bool(payload.get('join_password_hash'))
    payload.pop('join_password_hash', None)
    return payload

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})

@app.before_request
def attach_request_id():
    request_id = (request.headers.get('X-Request-ID') or '').strip()
    if not request_id:
        request_id = f"req-{uuid.uuid4().hex[:12]}"
    g.request_id = request_id

@app.after_request
def add_request_id_header(response):
    request_id = getattr(g, 'request_id', '')
    if request_id:
        response.headers['X-Request-ID'] = request_id
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    csp = CONTENT_SECURITY_POLICY
    ga_nonce = getattr(g, 'csp_nonce', '')
    if GOOGLE_ANALYTICS_KEY and ga_nonce:
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{ga_nonce}' https://www.googletagmanager.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://www.google-analytics.com https://www.googletagmanager.com; "
            "connect-src 'self' ws: wss: https://www.google-analytics.com https://www.googletagmanager.com; "
            "font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        )
    if csp:
        response.headers.setdefault('Content-Security-Policy', csp)
    return response

@app.errorhandler(413)
def handle_request_entity_too_large(_error):
    return jsonify({'error': f'Upload exceeds the {MAX_UPLOAD_MB} MB limit'}), 413

@app.route('/')
def index():
    nonce = secrets.token_urlsafe(16) if GOOGLE_ANALYTICS_KEY else ''
    if nonce:
        g.csp_nonce = nonce
    return render_template('index.html', ga_key=GOOGLE_ANALYTICS_KEY, csp_nonce=nonce,
                           require_auth=REQUIRE_AUTH, join_code=None)

@app.route('/docs')
def docs_index():
    return render_template('docs.html', docs=docs_manager.list_docs(),
                           doc=None, content=None, doc_title=None)

@app.route('/docs/<slug>')
def docs_view(slug):
    docs = docs_manager.list_docs()
    html = docs_manager.render(slug)
    if html is None:
        return render_template('docs.html', docs=docs, doc=None, content=None,
                               not_found=True, doc_title=None), 404
    title = next((d['title'] for d in docs if d['slug'] == slug), slug)
    return render_template('docs.html', docs=docs, doc=slug, content=html, doc_title=title)

@app.route('/join/<path:code>')
def join_session_page(code):
    """Render the main app with a pending share code injected as a data attribute.
    App-side JS calls the join API once authenticated and loads the session.
    On any host/domain — the code lives in the path so no CORS issues.
    """
    nonce = secrets.token_urlsafe(16) if GOOGLE_ANALYTICS_KEY else ''
    if nonce:
        g.csp_nonce = nonce
    return render_template('index.html', ga_key=GOOGLE_ANALYTICS_KEY, csp_nonce=nonce,
                           require_auth=REQUIRE_AUTH, join_code=code)

@app.route('/api/config')
def get_app_config():
    api_keys_info = {}
    for provider, key in SERVER_API_KEYS.items():
        if key:
            api_keys_info[provider] = {'available': True, 'masked': mask_api_key(key)}
        else:
            api_keys_info[provider] = {'available': False, 'masked': None}

    return jsonify({
        'app': config.get('app', {}),
        'translation': config.get('translation', {}),
        'libretranslate': config.get('libretranslate', {}),
        'llm': {
            'default_provider': config.get('llm', {}).get('default_provider', 'ollama'),
            'providers': config.get('llm', {}).get('providers', {}),
        },
        'speech': config.get('speech', {}),
        'glossary': config.get('glossary', {}),
        'session': config.get('session', {}),
        'features': {
            'allow_client_api_keys': ALLOW_CLIENT_API_KEYS,
            'whisper_enabled': whisper_manager.WHISPER_ENABLED,
            'auth_enabled': ALLOW_AUTH,
            'registration_enabled': ALLOW_AUTH and ALLOW_USER_REGISTRATION,
            'require_auth': REQUIRE_AUTH,
            'guest_login_enabled': ALLOW_GUEST_LOGIN,
        },
        'current_user': (lambda u: {'user_id': u.get('sub'), 'role': u.get('role'),
                                    'is_guest': u.get('is_guest', False)}
                         )(auth_manager.get_current_user()) if ALLOW_AUTH and auth_manager.get_current_user() else None,
        'server_api_keys': api_keys_info,
    })

@app.route('/auth/register', methods=['POST'])
def auth_register():
    if not ALLOW_AUTH or not ALLOW_USER_REGISTRATION:
        return jsonify({'error': 'Registration is disabled'}), 404
    ip = auth_manager.client_ip()
    if not auth_manager.register_rate_ok(ip):
        return jsonify({'error': 'Too many registration attempts, please try again later'}), 429
    auth_manager.record_register_attempt(ip)
    data = request.get_json() or {}
    try:
        role = 'admin' if user_manager.count_users() == 0 else 'user'
        user = user_manager.create_user(
            data.get('username'), data.get('password'), data.get('email'), role=role,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    token, _exp = auth_manager.create_access_token(user['user_id'], user['role'], user['username'])
    app_logger.info(f"AUTH: registered '{user['username']}' (role={user['role']})")
    return jsonify({'user': user, 'token': token}), 201

@app.route('/auth/login', methods=['POST'])
def auth_login():
    if not ALLOW_AUTH:
        return jsonify({'error': 'Authentication is disabled'}), 404
    ip = auth_manager.client_ip()
    if not auth_manager.login_rate_ok(ip):
        return jsonify({'error': 'Too many login attempts, please try again later'}), 429
    data = request.get_json() or {}
    user = user_manager.authenticate(data.get('username'), data.get('password'))
    if not user:
        auth_manager.record_login_failure(ip)
        app_logger.warning(f"AUTH: failed login for '{data.get('username')}' from {ip}")
        return jsonify({'error': 'Invalid credentials'}), 401
    auth_manager.reset_login_attempts(ip)
    analytics.incr('logins')
    token, _exp = auth_manager.create_access_token(user['user_id'], user['role'], user['username'])
    app_logger.info(f"AUTH: login success '{user['username']}'")
    return jsonify({'user': user, 'token': token})

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    if not ALLOW_AUTH:
        return jsonify({'error': 'Authentication is disabled'}), 404
    token = auth_manager._extract_token()
    if token:
        claims = auth_manager.decode_token(token)
        if claims and claims.get('jti'):
            user_manager.revoke_token(claims['jti'], claims.get('exp', 0))
    return jsonify({'success': True})

@app.route('/auth/me')
def auth_me():
    if not ALLOW_AUTH:
        return jsonify({'error': 'Authentication is disabled'}), 404
    user = auth_manager.get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify({'user': {
        'user_id': user.get('sub'),
        'username': user.get('username'),
        'role': user.get('role'),
        'is_guest': user.get('is_guest', False),
    }})

@app.route('/auth/guest', methods=['POST'])
def auth_guest():
    """Create an ephemeral guest account and return a short-lived JWT.
    Guest sessions are archived and purged after GUEST_TTL_HOURS (default 24h).
    """
    if not ALLOW_AUTH or not ALLOW_GUEST_LOGIN:
        return jsonify({'error': 'Guest login is disabled'}), 404
    user = user_manager.create_guest_user()
    token, _exp = auth_manager.create_access_token(
        user['user_id'], user['role'], user['username'],
        extra_claims={'is_guest': True}
    )
    app_logger.info(f"AUTH: guest session created for {user['username']}")
    analytics.incr('logins')
    return jsonify({'user': user, 'token': token}), 201


# ============================================================================
# Passkey (WebAuthn) routes
# ============================================================================

@app.route('/auth/passkey/register/options', methods=['POST'])
def passkey_register_options():
    if not ALLOW_AUTH or not ALLOW_USER_REGISTRATION:
        return jsonify({'error': 'Registration is disabled'}), 404
    if not PASSKEY_SUPPORT:
        return jsonify({'error': 'Passkey support not available on this server'}), 501
    ip = auth_manager.client_ip()
    if not auth_manager.register_rate_ok(ip):
        return jsonify({'error': 'Too many registration attempts, please try again later'}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip() or None
    err = user_manager.validate_username(username)
    if err:
        return jsonify({'error': err}), 400
    existing = user_manager.get_user_by_username(username)
    if existing:
        uid_str = existing['user_id']
        is_new_user = False
    else:
        uid_str = str(uuid.uuid4())
        is_new_user = True
    user_id_bytes = bytes.fromhex(uid_str.replace('-', ''))
    options = _webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=user_id_bytes,
        user_name=username,
        user_display_name=username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    cid = _pk_put({'challenge': options.challenge, 'username': username,
                   'email': email, 'uid': uid_str, 'is_new_user': is_new_user})
    return jsonify({'cid': cid, 'options': json.loads(_webauthn.options_to_json(options))})


@app.route('/auth/passkey/register/verify', methods=['POST'])
def passkey_register_verify():
    if not ALLOW_AUTH or not ALLOW_USER_REGISTRATION:
        return jsonify({'error': 'Registration is disabled'}), 404
    if not PASSKEY_SUPPORT:
        return jsonify({'error': 'Passkey support not available on this server'}), 501
    ip = auth_manager.client_ip()
    data = request.get_json(silent=True) or {}
    c = _pk_take(data.get('cid'))
    if not c:
        return jsonify({'error': 'Challenge expired — please try again'}), 400
    cred_data = data.get('credential')
    if not cred_data or not isinstance(cred_data, dict):
        return jsonify({'error': 'Missing credential'}), 400
    try:
        resp = cred_data.get('response', {})
        transports = []
        for t in (resp.get('transports') or []):
            try:
                transports.append(AuthenticatorTransport(t))
            except ValueError:
                pass
        cred = RegistrationCredential(
            id=cred_data['id'],
            raw_id=_b64url_to_bytes(cred_data['rawId']),
            response=AuthenticatorAttestationResponse(
                client_data_json=_b64url_to_bytes(resp['clientDataJSON']),
                attestation_object=_b64url_to_bytes(resp['attestationObject']),
                transports=transports,
            ),
        )
    except Exception as exc:
        app_logger.warning('Passkey register parse error: %s', exc)
        return jsonify({'error': 'Invalid credential format'}), 400
    try:
        verification = _webauthn.verify_registration_response(
            credential=cred,
            expected_challenge=c['challenge'],
            expected_rp_id=RP_ID,
            expected_origin=_passkey_origin(),
            require_user_verification=False,
        )
    except Exception as exc:
        app_logger.warning('Passkey register verify error: %s', exc)
        return jsonify({'error': 'Passkey verification failed: ' + str(exc)}), 400
    cred_id = _bytes_to_b64url(verification.credential_id)
    pub_key = _bytes_to_b64url(verification.credential_public_key)
    sign_count = verification.sign_count
    transports_list = [t.value if hasattr(t, 'value') else str(t) for t in transports]
    if c['is_new_user']:
        auth_manager.record_register_attempt(ip)
        try:
            role = 'admin' if user_manager.count_users() == 0 else 'user'
            user = user_manager.create_user_passwordless(
                c['username'], c.get('email'), role=role, forced_id=c['uid'])
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    else:
        row = user_manager.get_user_by_id(c['uid'])
        if not row:
            return jsonify({'error': 'User not found'}), 404
        user = user_manager._public(row)
    try:
        user_manager.add_passkey(user['user_id'], cred_id, pub_key, sign_count, transports_list)
    except Exception as exc:
        app_logger.error('Passkey store error: %s', exc)
        return jsonify({'error': 'Failed to store passkey'}), 500
    token, _exp = auth_manager.create_access_token(
        user['user_id'], user['role'], user['username'])
    app_logger.info("AUTH: passkey registered for '%s'", user['username'])
    return jsonify({'user': user, 'token': token}), (201 if c['is_new_user'] else 200)


@app.route('/auth/passkey/login/options', methods=['POST'])
def passkey_login_options():
    if not ALLOW_AUTH:
        return jsonify({'error': 'Authentication is disabled'}), 404
    if not PASSKEY_SUPPORT:
        return jsonify({'error': 'Passkey support not available on this server'}), 501
    options = _webauthn.generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=[],
    )
    cid = _pk_put({'challenge': options.challenge})
    return jsonify({'cid': cid, 'options': json.loads(_webauthn.options_to_json(options))})


@app.route('/auth/passkey/login/verify', methods=['POST'])
def passkey_login_verify():
    if not ALLOW_AUTH:
        return jsonify({'error': 'Authentication is disabled'}), 404
    if not PASSKEY_SUPPORT:
        return jsonify({'error': 'Passkey support not available on this server'}), 501
    ip = auth_manager.client_ip()
    if not auth_manager.login_rate_ok(ip):
        return jsonify({'error': 'Too many login attempts, please try again later'}), 429
    data = request.get_json(silent=True) or {}
    c = _pk_take(data.get('cid'))
    if not c:
        return jsonify({'error': 'Challenge expired — please try again'}), 400
    cred_data = data.get('credential')
    if not cred_data or not isinstance(cred_data, dict):
        return jsonify({'error': 'Missing credential'}), 400
    passkey = user_manager.get_passkey(cred_data.get('id'))
    if not passkey:
        return jsonify({'error': 'Unknown passkey — please register first'}), 404
    try:
        resp = cred_data.get('response', {})
        cred = AuthenticationCredential(
            id=cred_data['id'],
            raw_id=_b64url_to_bytes(cred_data['rawId']),
            response=AuthenticatorAssertionResponse(
                client_data_json=_b64url_to_bytes(resp['clientDataJSON']),
                authenticator_data=_b64url_to_bytes(resp['authenticatorData']),
                signature=_b64url_to_bytes(resp['signature']),
                user_handle=_b64url_to_bytes(resp['userHandle']) if resp.get('userHandle') else None,
            ),
        )
    except Exception as exc:
        app_logger.warning('Passkey login parse error: %s', exc)
        return jsonify({'error': 'Invalid credential format'}), 400
    try:
        verification = _webauthn.verify_authentication_response(
            credential=cred,
            expected_challenge=c['challenge'],
            expected_rp_id=RP_ID,
            expected_origin=_passkey_origin(),
            credential_public_key=_b64url_to_bytes(passkey['public_key']),
            credential_current_sign_count=passkey['sign_count'],
            require_user_verification=False,
        )
    except Exception as exc:
        auth_manager.record_login_failure(ip)
        app_logger.warning('Passkey login verify error: %s', exc)
        return jsonify({'error': 'Passkey authentication failed'}), 401
    user_manager.update_passkey_sign_count(passkey['cred_id'], verification.new_sign_count)
    row = user_manager.get_user_by_id(passkey['user_id'])
    if not row:
        return jsonify({'error': 'User not found'}), 404
    user = user_manager._public(row)
    if user['status'] != 'active':
        return jsonify({'error': 'Account is not active'}), 403
    auth_manager.reset_login_attempts(ip)
    token, _exp = auth_manager.create_access_token(
        user['user_id'], user['role'], user['username'])
    app_logger.info("AUTH: passkey login '%s'", user['username'])
    analytics.incr('logins')
    return jsonify({'user': user, 'token': token})
def translate_text():
    data = request.get_json()
    if not data or not data.get('text'):
        return jsonify({'error': 'Text is required'}), 400

    text = data['text']
    source_lang = data.get('source_language', 'auto')
    target_lang = data.get('target_language', 'en')
    engine = data.get('engine', 'libretranslate')
    provider = data.get('provider')
    model = data.get('model')

    engine, provider, model, policy_warning, _ = apply_offline_translation_policy(engine, provider, model)

    api_key = None
    custom_config = None
    if engine == 'llm' and provider:
        api_key, _ = get_api_key(provider, request.headers)
        if provider in ('ollama', 'lmstudio'):
            custom_config = data.get('custom_config')

    glossary = None
    if config.get('glossary', {}).get('enabled', True):
        glossary = glossary_manager.get_entries_for_pair(source_lang, target_lang)

    app_logger.info(f"📝 REST API translation: {source_lang} → {target_lang} via {engine}{f' ({provider})' if provider else ''} | Text: {text[:50]}...")
    analytics.incr('translations')
    result = TranslationManager.translate(
        text=text, source_lang=source_lang, target_lang=target_lang,
        engine=engine, provider=provider, model=model,
        api_key=api_key, custom_config=custom_config,
        glossary=glossary if glossary else None,
        ai_auto_correct=data.get('ai_auto_correct', True),
    )

    if policy_warning:
        result['policy_warning'] = policy_warning

    if result.get('success'):
        session_id = data.get('session_id')
        if session_id:
            session_manager.add_message(session_id, {
                'source_text': text,
                'translated_text': result.get('translated_text', ''),
                'source_language': source_lang,
                'target_language': target_lang,
                'engine': result.get('engine', engine),
            })
            app_logger.info(f"💾 Message saved to session {session_id}")
        app_logger.info(f"✓ REST translation successful")
    else:
        app_logger.warning(f"✗ REST translation failed: {result.get('error', 'Unknown error')}")

    return jsonify(result)

@app.route('/api/translate/multi', methods=['POST'])
def translate_multi():
    """Translate text to multiple target languages simultaneously."""
    data = request.get_json()
    if not data or not data.get('text'):
        return jsonify({'error': 'Text is required'}), 400

    text = data['text']
    source_lang = data.get('source_language', 'auto')
    target_langs = data.get('target_languages', ['en'])
    engine = data.get('engine', 'libretranslate')
    provider = data.get('provider')
    model = data.get('model')

    engine, provider, model, policy_warning, _ = apply_offline_translation_policy(engine, provider, model)

    limit = config.get('translation', {}).get('simultaneous_targets_limit', 5)
    target_langs = target_langs[:limit]

    api_key = None
    custom_config = None
    if engine == 'llm' and provider:
        api_key, _ = get_api_key(provider, request.headers)
        if provider in ('ollama', 'lmstudio'):
            custom_config = data.get('custom_config')

    results = {}
    for lang in target_langs:
        glossary = None
        if config.get('glossary', {}).get('enabled', True):
            glossary = glossary_manager.get_entries_for_pair(source_lang, lang)
        results[lang] = TranslationManager.translate(
            text=text, source_lang=source_lang, target_lang=lang,
            engine=engine, provider=provider, model=model,
            api_key=api_key, custom_config=custom_config,
            glossary=glossary if glossary else None,
            ai_auto_correct=data.get('ai_auto_correct', True),
        )
        if policy_warning:
            results[lang]['policy_warning'] = policy_warning

    return jsonify({'results': results})

@app.route('/api/detect', methods=['POST'])
def detect_language():
    data = request.get_json()
    if not data or not data.get('text'):
        return jsonify({'error': 'Text is required'}), 400
    result = TranslationManager.detect_language(data['text'])
    return jsonify(result)

@app.route('/api/languages')
def get_languages():
    result = TranslationManager.get_languages()
    if result.get('success'):
        return jsonify(result)
    return jsonify({
        'success': True,
        'languages': config.get('translation', {}).get('available_languages', []),
        'source': 'config',
    })

@app.route('/api/libretranslate/status')
def libre_status():
    return jsonify(TranslationManager.check_libre_status())

@app.route('/api/llm/test', methods=['POST'])
def llm_test_connection():
    data = request.get_json() or {}
    provider = data.get('provider', 'ollama')
    
    mode_state = get_runtime_offline_state()
    client_force_offline = data.get('force_offline', False)
    effective_offline = mode_state['offline'] or client_force_offline
    
    if effective_offline and is_cloud_provider(provider):
        return jsonify({
            'connected': False,
            'status_code': None,
            'url': '',
            'error': 'Cloud providers are disabled in offline mode. Use local providers (Ollama, LMStudio) instead.'
        }), 403
    
    api_key, _ = get_api_key(provider, request.headers)
    custom_config = data.get('custom_config')
    result = LLMManager.test_connection(provider, api_key, custom_config)
    return jsonify(result)

@app.route('/api/llm/models', methods=['POST'])
def llm_list_models():
    data = request.get_json() or {}
    provider = data.get('provider', 'ollama')
    
    mode_state = get_runtime_offline_state()
    client_force_offline = data.get('force_offline', False)
    effective_offline = mode_state['offline'] or client_force_offline
    
    if effective_offline and is_cloud_provider(provider):
        return jsonify({
            'error': 'Cloud providers are disabled in offline mode. Use local providers (Ollama, LMStudio) instead.',
            'models': []
        }), 403
    
    api_key, _ = get_api_key(provider, request.headers)
    custom_config = data.get('custom_config')
    result = LLMManager.list_models(provider, api_key, custom_config)
    return jsonify(result)

@app.route('/api/whisper/transcribe', methods=['POST'])
def whisper_transcribe():
    if not whisper_manager.WHISPER_ENABLED:
        return jsonify({'error': 'Whisper not enabled'}), 503

    if 'audio' not in request.files:
        return jsonify({'error': 'Audio file required'}), 400

    audio_file = request.files['audio']
    language = request.form.get('language', None)
    selected_model = (request.form.get('whisper_model') or '').strip()
    if not selected_model:
        selected_model = whisper_manager.WHISPER_MODEL
    audio_data = audio_file.read()

    result = whisper_manager.transcribe(audio_data, language, selected_model)
    analytics.incr('transcriptions')
    return jsonify(result)

@app.route('/api/whisper/status')
def whisper_status():
    return jsonify(whisper_manager.get_status())

@app.route('/api/stt/models', methods=['POST'])
def stt_list_models():
    data = request.get_json() or {}
    provider = data.get('provider', '')
    if not provider:
        return jsonify({'models': [], 'error': 'Provider is required'}), 400

    api_key, _ = get_api_key(provider, request.headers)
    custom_config = data.get('custom_config')
    result = LLMManager.list_stt_models(provider, api_key, custom_config)
    return jsonify(result)

@app.route('/api/stt/transcribe', methods=['POST'])
def stt_transcribe_provider():
    if 'audio' not in request.files:
        return jsonify({'error': 'Audio file required'}), 400

    provider = (request.form.get('provider') or '').strip()
    model = (request.form.get('model') or '').strip()
    if not provider or not model:
        return jsonify({'error': 'Provider and model are required'}), 400

    audio_file = request.files['audio']
    audio_data = audio_file.read()
    language = request.form.get('language', None)
    custom_config_raw = request.form.get('custom_config', '')
    custom_config = None
    if custom_config_raw:
        try:
            custom_config = json.loads(custom_config_raw)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid custom_config'}), 400

    api_key, _ = get_api_key(provider, request.headers)
    result = LLMManager.transcribe_audio(
        provider=provider,
        model=model,
        audio_data=audio_data,
        filename=audio_file.filename or 'recording.webm',
        api_key=api_key,
        language=language,
        custom_config=custom_config,
    )
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/api/offline-status')
def offline_status():
    """Check if application is running in offline mode."""
    mode_state = get_runtime_offline_state()
    whisper_enabled = whisper_manager.WHISPER_ENABLED
    
    return jsonify({
        'offline': mode_state['offline'],
        'force_offline': mode_state['force_offline'],
        'detected_offline': mode_state['detected_offline'],
        'whisper_available': whisper_enabled,
        'libretranslate_available': True,
        'recommended_stt': 'whisper' if mode_state['offline'] else 'web_speech_api',
        'edge_fallback_allowed': mode_state['edge_fallback_allowed'],
        'cloud_llm_available': mode_state['cloud_llm_available'],
        'local_llm_required': mode_state['local_llm_required'],
    })

def _share_code_from_request():
    return (request.args.get('share') or request.headers.get('X-Share-Code') or '').strip()

def _session_access_error(session_data, action, session_id):
    """Return None when access is allowed, else a Flask (response, status) tuple.
    No-op (always allowed) when auth is disabled, preserving anonymous behavior."""
    if not ALLOW_AUTH:
        return None
    user = auth_manager.get_current_user()
    uid = (user or {}).get('sub')
    role = (user or {}).get('role')
    share_ok = False
    code = _share_code_from_request()
    if code:
        payload = crypto_manager.verify(code, max_age=SHARE_CODE_TTL)
        share_ok = bool(payload and payload.get('sid') == session_id)

    if (action == 'read'
            and session_data.get('visibility') == 'public'
            and session_data.get('join_password_hash')
            and not (uid and uid == session_data.get('owner_id'))
            and role != 'admin'):
        provided = (request.headers.get('X-Join-Password', '')
                    or request.args.get('join_password', ''))
        if not _verify_session_password(provided, session_data.get('join_password_hash')):
            return jsonify({'error': 'Password required', 'requires_password': True}), 403

    if session_manager.can_access(session_data, user, action, share_ok=share_ok):
        return None
    if user:
        return jsonify({'error': 'You do not have access to this session'}), 403
    return jsonify({'error': 'Authentication required'}), 401

@app.route('/api/sessions')
def list_sessions():
    sessions = session_manager.list_sessions()
    if ALLOW_AUTH:
        user = auth_manager.get_current_user()
        uid = (user or {}).get('sub')
        is_admin = (user or {}).get('role') == 'admin'
        if not is_admin:
            sessions = [
                s for s in sessions
                if s.get('owner_id') is None
                or s.get('visibility', 'public') in ('public', 'shared')
                or (uid and s.get('owner_id') == uid)
            ]
    return jsonify({
        'sessions': [
            {
                **session,
                'icon_url': _build_session_icon_url(session.get('id', ''), session),
            }
            for session in sessions
        ]
    })

@app.route('/api/sessions', methods=['POST'])
def create_session():
    data = request.get_json() or {}
    title = data.get('title', f"Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}")
    session_type = data.get('type', 'translate')
    languages = data.get('languages', [])
    owner_id = None
    if ALLOW_AUTH:
        owner_id = (auth_manager.get_current_user() or {}).get('sub')
        if owner_id:
            max_s = admin_settings_manager.get_settings().get('max_sessions_per_user', 0)
            if max_s and session_manager.count_user_sessions(owner_id) >= max_s:
                return jsonify({'error': 'Session limit reached for your account'}), 403
    visibility = data.get('visibility')
    app_logger.info(f"➕ Creating session: '{title}' | Type: {session_type} | Languages: {languages}")
    result = session_manager.create_session(
        title, session_type, languages, owner_id=owner_id, visibility=visibility,
    )
    session_id = result.get('id')
    analytics.incr('sessions_created')
    app_logger.info(f"✓ Session created: {session_id}")
    return jsonify(_serialize_session(session_id, result)), 201

@app.route('/api/sessions/public')
def list_public_sessions_route():
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        return jsonify({'error': 'Invalid pagination parameters'}), 400
    if ALLOW_AUTH and not admin_settings_manager.get_settings().get('allow_public_sessions', True):
        return jsonify({'sessions': []})
    sessions = session_manager.list_public_sessions(limit=limit, offset=offset)
    public = [{
        'id': s.get('id'),
        'title': s.get('title'),
        'type': s.get('type'),
        'languages': s.get('languages', []),
        'message_count': s.get('message_count', 0),
        'created_at': s.get('created_at'),
        'updated_at': s.get('updated_at'),
        'icon_url': _build_session_icon_url(s.get('id', ''), s),
    } for s in sessions]
    return jsonify({'sessions': public})

@app.route('/api/sessions/<session_id>')
def get_session(session_id):
    app_logger.info(f"📖 Loading session: {session_id}")
    result = session_manager.get_session(session_id)
    if result is None:
        app_logger.warning(f"✗ Session not found: {session_id}")
        return jsonify({'error': 'Session not found'}), 404
    denied = _session_access_error(result, 'read', session_id)
    if denied:
        return denied
    message_count = len(result.get('messages', []))
    app_logger.info(f"✓ Session loaded: {session_id} | Messages: {message_count}")
    return jsonify(_serialize_session(session_id, result))

@app.route('/api/sessions/<session_id>', methods=['PUT'])
def update_session(session_id):
    data = request.get_json() or {}
    existing = session_manager.get_session(session_id)
    if existing is None:
        return jsonify({'error': 'Session not found'}), 404
    denied = _session_access_error(existing, 'write', session_id)
    if denied:
        return denied
    new_title = data.get('title')
    kwargs = {'title': new_title}
    if 'visibility' in data:
        kwargs['visibility'] = data['visibility']
    if 'join_password' in data:
        pw = data['join_password']
        kwargs['join_password_hash'] = _hash_session_password(pw) if pw else None
    app_logger.info(f"✏️ Updating session: {session_id} | New title: '{new_title}'")
    result = session_manager.update_session(session_id, **kwargs)
    if result is None:
        app_logger.warning(f"✗ Session not found: {session_id}")
        return jsonify({'error': 'Session not found'}), 404
    app_logger.info(f"✓ Session updated: {session_id}")
    return jsonify(_serialize_session(session_id, result))

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    existing = session_manager.get_session(session_id)
    if existing is None:
        return jsonify({'error': 'Session not found'}), 404
    denied = _session_access_error(existing, 'write', session_id)
    if denied:
        return denied
    delete_icon = request.args.get('delete_icon', 'true').lower() != 'false'
    app_logger.info(f"🗑️ Deleting session: {session_id} | Delete icon: {delete_icon}")
    if session_manager.delete_session(session_id, delete_icon=delete_icon):
        app_logger.info(f"✓ Session deleted: {session_id}")
        return jsonify({'success': True})
    app_logger.warning(f"✗ Session not found: {session_id}")
    return jsonify({'error': 'Session not found'}), 404

@app.route('/api/sessions/<session_id>/icon')
def get_session_icon(session_id):
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return jsonify({'error': 'Session not found'}), 404

    icon_filename = session_data.get('icon_filename')
    if not icon_filename:
        return jsonify({'error': 'Session icon not set'}), 404

    return send_from_directory(session_manager.SESSION_ICON_DIR, icon_filename)

@app.route('/api/sessions/<session_id>/icon', methods=['POST'])
def upload_session_icon(session_id):
    app_logger.info(f"🖼️ Uploading icon for session: {session_id}")
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return jsonify({'error': 'Session not found'}), 404

    denied = _session_access_error(session_data, 'write', session_id)
    if denied:
        return denied

    if 'file' not in request.files:
        return jsonify({'error': 'Image file is required'}), 400

    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'Invalid image file'}), 400

    _, ext = os.path.splitext(upload.filename)
    ext = ext.lower()
    if ext not in ALLOWED_SESSION_ICON_EXTENSIONS:
        return jsonify({'error': 'Unsupported image format. Use PNG, JPG, or GIF.'}), 400

    content_type = (upload.mimetype or '').lower()
    if content_type and content_type not in ALLOWED_SESSION_ICON_MIME_TYPES:
        return jsonify({'error': 'Unsupported image MIME type.'}), 400

    session_manager._ensure_icon_dir()
    safe_base = secure_filename(os.path.splitext(upload.filename)[0]) or 'icon'
    new_filename = f"{session_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_base}{ext}"
    target_path = os.path.join(session_manager.SESSION_ICON_DIR, new_filename)
    upload.save(target_path)

    old_filename = session_data.get('icon_filename')
    updated = session_manager.update_session(session_id, icon_filename=new_filename)
    if updated is None:
        try:
            os.remove(target_path)
        except Exception:
            pass
        return jsonify({'error': 'Session not found'}), 404

    if old_filename and old_filename != new_filename:
        try:
            session_manager.delete_icon_file(old_filename)
        except Exception:
            pass

    return jsonify({'success': True, 'session': _serialize_session(session_id, updated)})

@app.route('/api/sessions/<session_id>/messages', methods=['POST'])
def add_session_message(session_id):
    data = request.get_json() or {}
    existing = session_manager.get_session(session_id)
    if existing is None:
        return jsonify({'error': 'Session not found'}), 404
    denied = _session_access_error(existing, 'write', session_id)
    if denied:
        return denied
    result = session_manager.add_message(session_id, data)
    if result is None:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({'success': True, 'message_count': len(result.get('messages', []))})

@app.route('/api/sessions/<session_id>/share', methods=['POST'])
def share_session(session_id):
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return jsonify({'error': 'Session not found'}), 404
    denied = _session_access_error(session_data, 'write', session_id)
    if denied:
        return denied
    if ALLOW_AUTH and not admin_settings_manager.get_settings().get('allow_session_sharing', True):
        return jsonify({'error': 'Session sharing is disabled'}), 403
    data = request.get_json(silent=True) or {}
    access = data.get('access', 'view')
    if access not in ('view', 'edit'):
        access = 'view'
    if session_data.get('visibility') == 'private':
        session_manager.update_session(session_id, visibility='shared')
    code = crypto_manager.sign({'sid': session_id, 'access': access})
    app_logger.info(f"🔗 Session shared: {session_id} (access={access})")
    return jsonify({
        'share_code': code,
        'share_url': f"/api/sessions/join/{code}",
        'access': access,
        'expires_in': SHARE_CODE_TTL,
    })

@app.route('/api/sessions/join/<code>')
def join_session(code):
    payload = crypto_manager.verify(code, max_age=SHARE_CODE_TTL)
    if not payload or not payload.get('sid'):
        return jsonify({'error': 'Invalid or expired share code'}), 404
    session_id = payload['sid']
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({
        'session': _serialize_session(session_id, session_data),
        'access': payload.get('access', 'view'),
        'share_code': code,
    })

def admin_api(view):
    """Require auth enabled + a valid admin JWT; else 404 / 401 / 403."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not ALLOW_AUTH:
            return jsonify({'error': 'Not found'}), 404
        user = auth_manager.get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': 'Admin privileges required'}), 403
        g.current_user = user
        return view(*args, **kwargs)
    return wrapper

@app.route('/admin')
def admin_dashboard_page():
    return render_template('admin-dashboard.html')

@app.route('/api/admin/stats')
@admin_api
def admin_stats():
    sessions = session_manager.list_sessions()
    return jsonify({
        'users': user_manager.count_users(),
        'sessions': len(sessions),
        'public_sessions': sum(1 for s in sessions if s.get('visibility') == 'public'),
        'whisper_enabled': whisper_manager.WHISPER_ENABLED,
    })

@app.route('/api/admin/users')
@admin_api
def admin_list_users():
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        return jsonify({'error': 'Invalid pagination parameters'}), 400
    return jsonify({
        'users': user_manager.list_users(limit=limit, offset=offset),
        'total': user_manager.count_users(),
    })

@app.route('/api/admin/users/<user_id>/role', methods=['POST'])
@admin_api
def admin_set_user_role(user_id):
    data = request.get_json() or {}
    try:
        ok = user_manager.set_role(user_id, data.get('role'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not ok:
        return jsonify({'error': 'User not found'}), 404
    app_logger.info(f"ADMIN: {g.current_user.get('username')} set role={data.get('role')} for {user_id}")
    return jsonify({'success': True})

@app.route('/api/admin/users/<user_id>/status', methods=['POST'])
@admin_api
def admin_set_user_status(user_id):
    data = request.get_json() or {}
    try:
        ok = user_manager.set_status(user_id, data.get('status'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not ok:
        return jsonify({'error': 'User not found'}), 404
    app_logger.info(f"ADMIN: {g.current_user.get('username')} set status={data.get('status')} for {user_id}")
    return jsonify({'success': True})

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@admin_api
def admin_delete_user(user_id):
    if user_id == g.current_user.get('sub'):
        return jsonify({'error': 'You cannot delete your own account'}), 400
    if not user_manager.delete_user(user_id):
        return jsonify({'error': 'User not found'}), 404
    app_logger.info(f"ADMIN: {g.current_user.get('username')} deleted user {user_id}")
    return jsonify({'success': True})

@app.route('/api/admin/sessions')
@admin_api
def admin_list_all_sessions():
    sessions = session_manager.list_sessions()
    uid_to_name = {}
    for s in sessions:
        oid = s.get('owner_id')
        if oid and oid not in uid_to_name:
            row = user_manager.get_user_by_id(oid)
            uid_to_name[oid] = row['username'] if row else oid
    for s in sessions:
        oid = s.get('owner_id')
        s['owner_username'] = uid_to_name.get(oid) if oid else None
    return jsonify({'sessions': sessions})

@app.route('/api/admin/sessions/<session_id>', methods=['GET'])
@admin_api
def admin_get_session(session_id):
    data = session_manager.get_session(session_id)
    if data is None:
        return jsonify({'error': 'Session not found'}), 404
    oid = data.get('owner_id')
    if oid:
        row = user_manager.get_user_by_id(oid)
        data['owner_username'] = row['username'] if row else oid
    else:
        data['owner_username'] = None
    return jsonify(_serialize_session(session_id, data))

@app.route('/api/admin/sessions/<session_id>', methods=['PATCH'])
@admin_api
def admin_update_session(session_id):
    """Update a session's title, visibility, or owner (admin only)."""
    data = request.get_json() or {}
    kwargs = {}
    if 'title' in data:
        title = str(data['title']).strip()
        if not title:
            return jsonify({'error': 'Title cannot be empty'}), 400
        kwargs['title'] = title
    if 'visibility' in data:
        if data['visibility'] not in ('private', 'shared', 'public'):
            return jsonify({'error': 'Invalid visibility'}), 400
        kwargs['visibility'] = data['visibility']
    if 'owner_id' in data:
        new_owner = data['owner_id']
        if new_owner:
            if not user_manager.get_user_by_id(new_owner):
                return jsonify({'error': 'Owner user not found'}), 400
        kwargs['owner_id'] = new_owner or None
    if not kwargs:
        return jsonify({'error': 'No valid fields to update'}), 400
    result = session_manager.update_session(session_id, **kwargs)
    if result is None:
        return jsonify({'error': 'Session not found'}), 404
    app_logger.info(
        f"ADMIN: {g.current_user.get('username')} updated session {session_id} → {list(kwargs.keys())}"
    )
    return jsonify(_serialize_session(session_id, result))

@app.route('/api/admin/sessions/<session_id>/icon', methods=['POST'])
@admin_api
def admin_upload_session_icon(session_id):
    """Upload or replace the icon for any session (admin only)."""
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return jsonify({'error': 'Session not found'}), 404
    if 'file' not in request.files:
        return jsonify({'error': 'Image file is required'}), 400
    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'Invalid image file'}), 400
    _, ext = os.path.splitext(upload.filename)
    ext = ext.lower()
    if ext not in ALLOWED_SESSION_ICON_EXTENSIONS:
        return jsonify({'error': 'Unsupported image format. Use PNG, JPG, or GIF.'}), 400
    content_type = (upload.mimetype or '').lower()
    if content_type and content_type not in ALLOWED_SESSION_ICON_MIME_TYPES:
        return jsonify({'error': 'Unsupported image MIME type.'}), 400
    session_manager._ensure_icon_dir()
    safe_base = secure_filename(os.path.splitext(upload.filename)[0]) or 'icon'
    new_filename = f"{session_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_base}{ext}"
    target_path = os.path.join(session_manager.SESSION_ICON_DIR, new_filename)
    upload.save(target_path)
    old_filename = session_data.get('icon_filename')
    updated = session_manager.update_session(session_id, icon_filename=new_filename)
    if updated is None:
        try:
            os.remove(target_path)
        except Exception:
            pass
        return jsonify({'error': 'Session not found'}), 404
    if old_filename and old_filename != new_filename:
        try:
            session_manager.delete_icon_file(old_filename)
        except Exception:
            pass
    app_logger.info(f"ADMIN: {g.current_user.get('username')} updated icon for session {session_id}")
    return jsonify({'success': True, 'session': _serialize_session(session_id, updated)})

@app.route('/api/admin/sessions/<session_id>/icon', methods=['DELETE'])
@admin_api
def admin_delete_session_icon(session_id):
    """Remove the icon from a session."""
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return jsonify({'error': 'Session not found'}), 404
    old_filename = session_data.get('icon_filename')
    updated = session_manager.update_session(session_id, icon_filename=None)
    if updated is None:
        return jsonify({'error': 'Session not found'}), 404
    if old_filename:
        try:
            session_manager.delete_icon_file(old_filename)
        except Exception:
            pass
    return jsonify({'success': True})

@app.route('/api/admin/sessions/<session_id>', methods=['DELETE'])
@admin_api
def admin_delete_session(session_id):
    if session_manager.delete_session(session_id):
        app_logger.info(f"ADMIN: {g.current_user.get('username')} deleted session {session_id}")
        return jsonify({'success': True})
    return jsonify({'error': 'Session not found'}), 404

@app.route('/api/admin/settings')
@admin_api
def admin_get_settings():
    return jsonify(admin_settings_manager.get_settings())

@app.route('/api/admin/settings', methods=['POST'])
@admin_api
def admin_update_settings():
    result = admin_settings_manager.save_settings(request.get_json() or {})
    if not result.get('success'):
        return jsonify(result), 400
    app_logger.info(f"ADMIN: {g.current_user.get('username')} updated server settings")
    return jsonify({'success': True, 'settings': admin_settings_manager.get_settings()})

@app.route('/api/admin/analytics')
@admin_api
def admin_analytics():
    return jsonify(analytics.snapshot())

def _current_settings_user():
    """Return the authenticated user's id when auth is enabled, else None."""
    if not ALLOW_AUTH:
        return None
    user = auth_manager.get_current_user()
    return user.get('sub') if user else None

def _hash_session_password(password):
    """Hash a session join password for storage (non-credential; sha256 with SECRETS salt)."""
    if not password:
        return None
    salt = (os.environ.get('SECRETS', '') or 'lt-session-salt')[:32]
    return hashlib.sha256((salt + str(password)).encode('utf-8')).hexdigest()

def _verify_session_password(provided, stored_hash):
    """Return True if the provided password matches the stored hash."""
    if not stored_hash:
        return True
    if not provided:
        return False
    return hmac.compare_digest(_hash_session_password(str(provided)), stored_hash)

@app.route('/api/settings', methods=['GET'])
def get_user_settings():
    """Get settings. Logged-in users read from the encrypted per-user DB store;
    anonymous users receive defaults and keep their own settings in the browser."""
    uid = _current_settings_user()
    if uid:
        stored = user_manager.get_user_settings(uid) or {}
        merged = settings_manager.merge_with_defaults(stored)
        merged = settings_manager.decrypt_api_keys(merged)
        merged['storage'] = 'server'
        return jsonify(merged)
    defaults = settings_manager.get_default_settings()
    defaults['storage'] = 'browser'
    return jsonify(defaults)

@app.route('/api/settings', methods=['POST'])
def save_user_settings():
    """Save settings. Persisted per-user (API keys encrypted) when logged in;
    NOT stored on the server for anonymous users — the browser keeps them."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No settings provided'}), 400
    data.pop('storage', None)
    merged = settings_manager.merge_with_defaults(data)
    uid = _current_settings_user()
    if uid:
        user_manager.save_user_settings(uid, settings_manager.encrypt_api_keys(merged))
        merged['storage'] = 'server'
        return jsonify({'success': True, 'settings': merged})
    merged['storage'] = 'browser'
    return jsonify({'success': True, 'settings': merged})

@app.route('/api/settings/reset', methods=['POST'])
def reset_user_settings():
    """Reset settings to defaults (clears the user's DB record when logged in)."""
    uid = _current_settings_user()
    defaults = settings_manager.get_default_settings()
    if uid:
        user_manager.save_user_settings(uid, defaults.copy())
        defaults['storage'] = 'server'
    else:
        defaults['storage'] = 'browser'
    return jsonify({'success': True, 'settings': defaults})

@app.route('/api/settings/defaults', methods=['GET'])
def get_defaults():
    """Get default settings."""
    return jsonify(settings_manager.get_default_settings())

@app.route('/api/glossaries')
def list_glossaries():
    return jsonify({'glossaries': glossary_manager.list_glossaries()})

@app.route('/api/glossaries', methods=['POST'])
def create_glossary():
    data = request.get_json() or {}
    if not data.get('name'):
        return jsonify({'error': 'Name is required'}), 400
    name = data['name']
    app_logger.info(f"➕ Creating glossary: '{name}' | Source: {data.get('source_language', 'N/A')} | Target: {data.get('target_language', 'N/A')} | Entries: {len(data.get('entries', {}))}")
    result = glossary_manager.create_glossary(
        name=name,
        source_language=data.get('source_language', ''),
        target_language=data.get('target_language', ''),
        entries=data.get('entries', {}),
    )
    app_logger.info(f"✓ Glossary created: {name}")
    return jsonify(result), 201

@app.route('/api/glossaries/import', methods=['POST'])
def import_glossary():
    if 'file' not in request.files:
        return jsonify({'error': 'Glossary file is required'}), 400

    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'Invalid glossary file'}), 400

    source_language = (request.form.get('source_language') or '').strip()
    target_language = (request.form.get('target_language') or '').strip()

    app_logger.info(f"📊 Importing glossary from file: '{upload.filename}' | Source: {source_language or 'N/A'} | Target: {target_language or 'N/A'}")

    raw = upload.read()
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        app_logger.warning(f"✗ Failed to import glossary: Unable to decode file {upload.filename}")
        return jsonify({'error': 'Unable to decode glossary file'}), 400

    try:
        result = glossary_manager.replace_single_glossary_from_text(
            source_language=source_language,
            target_language=target_language,
            text=text,
            filename=upload.filename,
        )
        entry_count = len(result.get('entries', {}))
        app_logger.info(f"✓ Glossary imported successfully: {entry_count} entries from {upload.filename}")
        return jsonify(result), 201
    except ValueError as e:
        app_logger.warning(f"✗ Glossary import validation error: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        app_logger.exception(f'Failed to import glossary: {str(e)}')
        return jsonify({'error': 'Failed to import glossary'}), 500

@app.route('/api/glossaries/template')
def glossary_template():
    fmt = (request.args.get('format', 'csv') or 'csv').lower()

    templates = {
        'csv': {
            'content': 'source,target\nhello,bonjour\nthank you,merci\n',
            'mimetype': 'text/csv',
            'ext': 'csv',
        },
        'tsv': {
            'content': 'source\ttarget\nhello\tbonjour\nthank you\tmerci\n',
            'mimetype': 'text/tab-separated-values',
            'ext': 'tsv',
        },
        'txt': {
            'content': 'hello => bonjour\nthank you => merci\n',
            'mimetype': 'text/plain',
            'ext': 'txt',
        },
        'json': {
            'content': '{\n  "hello": "bonjour",\n  "thank you": "merci"\n}\n',
            'mimetype': 'application/json',
            'ext': 'json',
        },
    }

    if fmt not in templates:
        return jsonify({'error': 'Unsupported format. Use csv, json, tsv, or txt.'}), 400

    t = templates[fmt]
    headers = {
        'Content-Disposition': f'attachment; filename=glossary-template.{t["ext"]}'
    }
    return Response(t['content'], mimetype=t['mimetype'], headers=headers)

@app.route('/api/glossaries/<glossary_id>')
def get_glossary(glossary_id):
    result = glossary_manager.get_glossary(glossary_id)
    if result is None:
        return jsonify({'error': 'Glossary not found'}), 404
    return jsonify(result)

@app.route('/api/glossaries/<glossary_id>', methods=['PUT'])
def update_glossary(glossary_id):
    data = request.get_json() or {}
    result = glossary_manager.update_glossary(
        glossary_id, name=data.get('name'), entries=data.get('entries'),
    )
    if result is None:
        return jsonify({'error': 'Glossary not found'}), 404
    return jsonify(result)

@app.route('/api/glossaries/<glossary_id>', methods=['DELETE'])
def delete_glossary(glossary_id):
    if glossary_manager.delete_glossary(glossary_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Glossary not found'}), 404

@app.route('/api/logs')
def get_logs():
    if not LOGS_ACCESS_TOKEN:
        return jsonify({'error': 'Not found'}), 404
    provided = (request.headers.get('Authorization', '') or '')
    if provided.startswith('Bearer '):
        provided = provided[len('Bearer '):]
    provided = provided.strip() or (request.headers.get('X-Logs-Token', '') or '').strip()
    if not provided or not hmac.compare_digest(provided, LOGS_ACCESS_TOKEN):
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        lines = int(request.args.get('lines', 100))
        lines = max(1, min(lines, 1000))
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
            return jsonify({'logs': all_lines[-lines:]})
        return jsonify({'logs': []})
    except ValueError:
        return jsonify({'error': 'Invalid lines parameter'}), 400
    except Exception:
        app_logger.exception('Failed to read logs')
        return jsonify({'error': 'Failed to read logs'}), 500

@socketio.on('connect')
def handle_connect():
    app_logger.info(f"Client connected: {request.sid}")
    emit('connected', {'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    app_logger.info(f"Client disconnected: {request.sid}")

@socketio.on('join_session_room')
def handle_join_session_room(data):
    """Join a SocketIO room so other clients in the same session can push updates."""
    session_id = ((data or {}).get('session_id') or '').strip()
    if session_id and session_manager._is_safe_id(session_id):
        join_room(f'session:{session_id}')

@socketio.on('leave_session_room')
def handle_leave_session_room(data):
    """Leave the SocketIO room for a session."""
    session_id = ((data or {}).get('session_id') or '').strip()
    if session_id:
        leave_room(f'session:{session_id}')

@socketio.on('translate')
def handle_translate(data):
    """Real-time translation via WebSocket with intelligent fallback."""
    text = data.get('text', '')
    source_lang = data.get('source_language', 'auto')
    target_lang = data.get('target_language', 'en')
    engine = data.get('engine', 'libretranslate')
    provider = data.get('provider')
    model = data.get('model')
    panel = data.get('panel', 'left')
    live_mode = data.get('live_mode', False)
    interim = data.get('interim', False)
    request_id = data.get('request_id')

    if request_id:
        g.request_id = str(request_id)

    engine, provider, model, policy_warning, mode_state = apply_offline_translation_policy(engine, provider, model)

    api_key = data.get('api_key')
    api_key_source = data.get('api_key_source', 'client')

    if engine == 'llm' and provider:
        pseudo_headers = {
            'X-API-Key-Source': api_key_source,
            'X-API-Key': api_key or '',
        }
        api_key, _ = get_api_key(provider, pseudo_headers)

    custom_config = data.get('custom_config')

    glossary = None
    if config.get('glossary', {}).get('enabled', True):
        glossary = glossary_manager.get_entries_for_pair(source_lang, target_lang)

    app_logger.info(f"🔄 Translation request: {source_lang} → {target_lang} via {engine}{f' ({provider})' if provider else ''} | Text length: {len(text)} chars")
    analytics.incr('translations')

    result = TranslationManager.translate(
        text=text, source_lang=source_lang, target_lang=target_lang,
        engine=engine, provider=provider, model=model,
        api_key=api_key, custom_config=custom_config,
        glossary=glossary if glossary else None,
        ai_auto_correct=data.get('ai_auto_correct', True),
    )

    if policy_warning:
        result['policy_warning'] = policy_warning

    if not result.get('success') and engine == 'libretranslate' and not mode_state['offline'] and (provider or SERVER_API_KEYS.get('anthropic')):
        app_logger.info(f"⚠ LibreTranslate failed, falling back to LLM provider")
        fallback_provider = provider or 'anthropic'
        fallback_model = model or 'claude-3-5-sonnet-20241022'
        fallback_api_key = api_key or SERVER_API_KEYS.get(fallback_provider, '')
        
        result = TranslationManager.translate(
            text=text, source_lang=source_lang, target_lang=target_lang,
            engine='llm', provider=fallback_provider, model=fallback_model,
            api_key=fallback_api_key, custom_config=custom_config,
            glossary=glossary if glossary else None,
            ai_auto_correct=data.get('ai_auto_correct', True),
        )
        if result.get('success'):
            result['engine'] = f'llm:{fallback_provider} (fallback)'

    if result.get('success'):
        app_logger.info(f"✓ Translation successful: {source_lang} → {target_lang} | Result length: {len(result.get('translated_text', ''))} chars")
    else:
        app_logger.warning(f"✗ Translation failed: {source_lang} → {target_lang} | Error: {result.get('error', 'Unknown error')}")

    result['panel'] = panel
    result['original_text'] = text
    result['live_mode'] = live_mode
    result['interim'] = interim
    result['request_id'] = request_id

    ws_session_id = (data.get('session_id') or '').strip()
    if ws_session_id and session_manager._is_safe_id(ws_session_id) and result.get('success') and not interim:
        saved_msg = {
            'source_text': text,
            'translated_text': result.get('translated_text', ''),
            'source_language': source_lang,
            'target_language': target_lang,
            'engine': result.get('engine', engine),
            'panel': panel,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }
        session_manager.add_message(ws_session_id, saved_msg)
        socketio.emit(
            'session_new_message', saved_msg,
            to=f'session:{ws_session_id}',
            skip_sid=request.sid,
            namespace='/',
        )

    emit('translation_result', result)

def _guest_archive_loop():
    import time as _time
    while True:
        _time.sleep(3600)
        try:
            n = user_manager.archive_and_purge_guests()
            if n:
                app_logger.info("Guest archive job: purged %d expired guest accounts", n)
        except Exception:
            app_logger.exception("Guest archive job failed")

def _start_guest_archive_thread():
    import threading
    t = threading.Thread(target=_guest_archive_loop, daemon=True, name='guest-archive')
    t.start()

def validate_security_config():
    """Log the security posture at startup and fail hard when a production
    deployment is missing required secrets. Local/dev use is never blocked."""
    app_logger.info("Validating security configuration...")
    blocking = []

    if CORS_ALLOW_ALL:
        app_logger.warning(
            "⚠ SECURITY: CORS_ALLOWED_ORIGINS='*' lets ANY website call this API/"
            "WebSocket. Pin it to your explicit origin(s) for production."
        )
    elif CORS_SAME_ORIGIN_ONLY:
        app_logger.info(
            "✓ CORS: same-origin only (works on any host the app is served from; "
            "cross-origin denied). Set TRUST_PROXY=true behind an HTTPS proxy."
        )
    else:
        app_logger.info(f"✓ CORS: same-origin plus {', '.join(CORS_ALLOWED_ORIGINS)}")

    if not os.environ.get('SECRET_KEY'):
        app_logger.warning(
            "⚠ SECURITY: SECRET_KEY not set — using an ephemeral key that changes on "
            "restart. Set a stable SECRET_KEY for production."
        )

    if crypto_manager.is_ephemeral():
        msg = ("SECRETS not set — signed share/session tokens use an ephemeral key "
               "that changes on restart.")
        if REQUIRE_SECRETS or IS_PRODUCTION:
            blocking.append("SECRETS is required (REQUIRE_SECRETS/production) but was not provided")
            app_logger.error(f"✗ SECURITY: {msg}")
        else:
            app_logger.warning(f"⚠ SECURITY: {msg} Generate one with: openssl rand -hex 32")
    else:
        app_logger.info("✓ SECRETS configured")

    if ALLOW_CLIENT_API_KEYS and any(SERVER_API_KEYS.values()):
        app_logger.warning(
            "⚠ SECURITY: ALLOW_CLIENT_API_KEYS=true while server API keys are set — "
            "clients can override server keys. Disable if that is not intended."
        )

    _weak = {'', 'change-me', 'change-me-to-a-random-string', 'changeme', 'secret'}
    if os.environ.get('SECRET_KEY', '') in _weak or os.environ.get('SECRETS', '') in _weak:
        app_logger.warning(
            "⚠ SECURITY: SECRET_KEY/SECRETS is a placeholder value — replace it with a "
            "strong random value: openssl rand -hex 32"
        )

    if blocking and (REQUIRE_SECRETS or IS_PRODUCTION):
        raise SystemExit(
            "Refusing to start: unmet security requirements -> " + "; ".join(blocking)
            + ". Provide the required secrets or unset REQUIRE_SECRETS."
        )
    return not blocking

def run_preflight_checks():
    """Run pre-flight health checks for offline operation."""
    app_logger.info("=" * 60)
    app_logger.info("Running pre-flight checks...")
    app_logger.info("=" * 60)
    
    checks_passed = True
    
    mode_state = get_runtime_offline_state()
    offline = mode_state['offline']
    app_logger.info(
        "✓ Offline mode: %s%s",
        'ENABLED' if offline else 'DISABLED',
        ' (forced by settings)' if mode_state['force_offline'] else '',
    )
    
    if whisper_manager.WHISPER_ENABLED:
        try:
            whisper_status = whisper_manager.get_status()
            if not whisper_status.get('installed'):
                raise RuntimeError('faster-whisper not installed')

            if WHISPER_PRELOAD_ON_STARTUP:
                whisper_manager.get_whisper_model()
                app_logger.info(f"✓ Whisper STT: Available and preloaded (model: {whisper_manager.WHISPER_MODEL})")
            else:
                app_logger.info(
                    f"✓ Whisper STT: Available (lazy-load enabled, model: {whisper_manager.WHISPER_MODEL})"
                )
        except Exception as e:
            app_logger.warning(f"✗ Whisper STT: Failed to load - {e}")
            if offline:
                app_logger.error("  ⚠ CRITICAL: Offline mode requires Whisper for speech-to-text!")
                checks_passed = False
    else:
        app_logger.info(f"  Whisper STT: Disabled")
        if offline:
            app_logger.warning("  ⚠ WARNING: Offline mode without Whisper - speech input unavailable")
    
    libre_status = TranslationManager.check_libre_status(timeout=5)
    if libre_status.get('available'):
        app_logger.info(f"✓ LibreTranslate: Connected ({libre_status.get('url')})")
    else:
        is_local = os.environ.get('LIBRETRANSLATE_LOCAL_ENABLED', 'true').lower() in ('1', 'true', 'yes', 'on')
        status_error = libre_status.get('error')
        if not status_error:
            status_error = f"HTTP {libre_status.get('status_code', 'unknown')}"
        
        if is_local:
            app_logger.warning(
                f"⚠ LibreTranslate: Warming up (local mode) - {status_error}. "
                f"Language models are loading in background. "
                f"Check {libre_status.get('url')}/languages in 30-60 seconds."
            )
        else:
            app_logger.warning(f"✗ LibreTranslate: Not reachable - {status_error}")
            checks_passed = False
    
    if offline:
        ollama_available = False
        lmstudio_available = False
        
        try:
            ollama_url = os.environ.get('OLLAMA_HOST', 'http://host.docker.internal:11434')
            response = requests.get(f"{ollama_url}/api/tags", timeout=2)
            if response.ok:
                app_logger.info(f"✓ Ollama: Available ({ollama_url})")
                ollama_available = True
        except Exception:
            pass
        
        try:
            lmstudio_url = os.environ.get('LMSTUDIO_HOST', 'http://host.docker.internal:1234')
            response = requests.get(f"{lmstudio_url}/v1/models", timeout=2)
            if response.ok:
                app_logger.info(f"✓ LM Studio: Available ({lmstudio_url})")
                lmstudio_available = True
        except Exception:
            pass
        
        if not ollama_available and not lmstudio_available:
            app_logger.warning("  ⚠ WARNING: No local LLM detected - AI features will be unavailable")
            app_logger.warning("     Install Ollama (https://ollama.ai) or LM Studio for AI auto-correct")
    
    app_logger.info("=" * 60)
    if checks_passed:
        app_logger.info("✓ All critical checks passed - Ready to start")
    else:
        app_logger.warning("⚠ Some checks failed - Application may have limited functionality")
    app_logger.info("=" * 60)
    
    return checks_passed

if __name__ == '__main__':
    app_logger.info("Starting Live Translate server...")
    app_logger.info(f"Whisper enabled: {whisper_manager.WHISPER_ENABLED}")
    app_logger.info("Session persistence: always enabled")

    validate_security_config()

    if ALLOW_AUTH:
        user_manager.init_db()
        removed_tokens = user_manager.cleanup_expired_tokens()
        purged = user_manager.archive_and_purge_guests()
        app_logger.info(
            "Auth enabled (registration=%s, require=%s, guest=%s); "
            "cleaned %s expired tokens, purged %s expired guests",
            'on' if ALLOW_USER_REGISTRATION else 'off',
            'on' if REQUIRE_AUTH else 'off',
            'on' if ALLOW_GUEST_LOGIN else 'off',
            removed_tokens, purged,
        )
        _start_guest_archive_thread()
    else:
        app_logger.info("Auth disabled (anonymous mode)")

    checks_passed = run_preflight_checks()

    if STARTUP_FAIL_ON_CHECKS and not checks_passed:
        app_logger.error("Startup checks failed and STARTUP_FAIL_ON_CHECKS=true. Exiting.")
        raise SystemExit(1)

    removed = session_manager.cleanup_old_sessions()
    if removed:
        app_logger.info(f"Cleaned up {removed} old sessions")

    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
