"""
Live Translate - Real-time translation webapp with speech, text, and AI support.
Flask backend with SocketIO for real-time communication.
"""

import os
import json
import logging
import socket
import uuid
from logging.handlers import RotatingFileHandler
from datetime import datetime
import requests

from flask import Flask, request, jsonify, render_template, send_from_directory, Response, g, has_request_context
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

from llm_manager import LLMManager
from translation_manager import TranslationManager
import whisper_manager
import glossary_manager
import session_manager
import settings_manager

# ============================================================================
# App Configuration
# ============================================================================

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Config
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
LOG_DIR = os.environ.get('LOG_DIR', '/data/logs')

# Feature flags
ALLOW_CLIENT_API_KEYS = os.environ.get('ALLOW_CLIENT_API_KEYS', 'true').lower() == 'true'
WHISPER_PRELOAD_ON_STARTUP = os.environ.get('WHISPER_PRELOAD_ON_STARTUP', 'false').lower() == 'true'
STARTUP_FAIL_ON_CHECKS = os.environ.get('STARTUP_FAIL_ON_CHECKS', 'false').lower() == 'true'
ALLOWED_SESSION_ICON_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg'}
ALLOWED_SESSION_ICON_MIME_TYPES = {
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/svg+xml',
}

# Server-side API keys from environment variables
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

# ============================================================================
# Logging
# ============================================================================


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

# ============================================================================
# Load Config
# ============================================================================

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

config = load_config()

# ============================================================================
# Utility Functions
# ============================================================================

def mask_api_key(key):
    if not key or len(key) < 10:
        return None
    return f"●●●●●●{key[-6:]}"


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def _env_value(name, default=''):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip()

def is_offline_mode():
    """Detect if app should run in offline mode."""
    env_offline = _env_value('OFFLINE_MODE', 'auto').lower()
    if env_offline == 'true':
        return True
    elif env_offline == 'false':
        return False

    if _env_bool('OFFLINE_STRICT', False):
        return True
    
    # Auto-detect: try to reach a reliable endpoint
    try:
        # Try to connect to Google DNS (doesn't send data, just checks connectivity)
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return False
    except (socket.error, socket.timeout):
        return True


def build_offline_readiness_report():
    settings = settings_manager.get_settings()
    offline_mode = is_offline_mode()
    strict_mode = _env_bool('OFFLINE_STRICT', bool(settings.get('offline_strict', False)))
    configured_mode = settings.get('offline_mode', os.environ.get('OFFLINE_MODE', 'auto'))

    libre_status = TranslationManager.check_libre_status(timeout=3, retries=1)
    whisper_status = whisper_manager.get_status()

    local_translation_ready = bool(libre_status.get('available'))
    local_stt_ready = bool(whisper_status.get('enabled')) and bool(whisper_status.get('installed', True))
    offline_ready = local_translation_ready and (not whisper_status.get('enabled') or local_stt_ready)

    if offline_mode and not local_translation_ready:
        reason = 'Offline mode is enabled, but embedded LibreTranslate is not ready yet.'
    elif offline_mode and whisper_status.get('enabled') and not local_stt_ready:
        reason = 'Offline mode is enabled, but Whisper is not ready yet.'
    elif offline_mode and offline_ready:
        reason = 'Offline mode is enabled and local services are ready.'
    else:
        reason = 'Online mode is active. Local offline mode remains available after setup.'

    return {
        'offline': offline_mode,
        'enabled': offline_mode,
        'ready': offline_ready,
        'strict': strict_mode,
        'mode': configured_mode,
        'reason': reason,
        'local_translation_ready': local_translation_ready,
        'local_stt_ready': local_stt_ready,
        'libretranslate_available': bool(libre_status.get('available')),
        'libretranslate_warming_up': bool(libre_status.get('warming_up')),
        'whisper_available': bool(whisper_status.get('enabled')),
        'whisper_installed': bool(whisper_status.get('installed', True)),
        'recommended_stt': 'whisper' if offline_mode else 'web_speech_api',
        'cloud_llm_available': not offline_mode,
        'local_llm_required': offline_mode,
        'components': {
            'libretranslate': libre_status,
            'whisper': whisper_status,
        },
    }

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
    return payload

# ============================================================================
# Routes - Health & Config
# ============================================================================

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
    return response

@app.route('/')
def index():
    return render_template('index.html')

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
        },
        'server_api_keys': api_keys_info,
    })

# ============================================================================
# Routes - Translation
# ============================================================================

@app.route('/api/translate', methods=['POST'])
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

    # Get API key if LLM engine
    api_key = None
    custom_config = None
    if engine == 'llm' and provider:
        api_key, _ = get_api_key(provider, request.headers)
        if provider in ('ollama', 'lmstudio'):
            custom_config = data.get('custom_config')

    # Get glossary entries for the language pair
    glossary = None
    if config.get('glossary', {}).get('enabled', True):
        glossary = glossary_manager.get_entries_for_pair(source_lang, target_lang)

    app_logger.info(f"📝 REST API translation: {source_lang} → {target_lang} via {engine}{f' ({provider})' if provider else ''} | Text: {text[:50]}...")
    result = TranslationManager.translate(
        text=text, source_lang=source_lang, target_lang=target_lang,
        engine=engine, provider=provider, model=model,
        api_key=api_key, custom_config=custom_config,
        glossary=glossary if glossary else None,
        ai_auto_correct=data.get('ai_auto_correct', True),
    )

    # Persist successful translations whenever a session is active.
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
    # Fallback to config languages
    return jsonify({
        'success': True,
        'languages': config.get('translation', {}).get('available_languages', []),
        'source': 'config',
    })

# ============================================================================
# Routes - LibreTranslate
# ============================================================================

@app.route('/api/libretranslate/status')
def libre_status():
    return jsonify(TranslationManager.check_libre_status())

# ============================================================================
# Routes - LLM
# ============================================================================

@app.route('/api/llm/test', methods=['POST'])
def llm_test_connection():
    data = request.get_json() or {}
    provider = data.get('provider', 'ollama')
    api_key, _ = get_api_key(provider, request.headers)
    custom_config = data.get('custom_config')
    result = LLMManager.test_connection(provider, api_key, custom_config)
    return jsonify(result)


@app.route('/api/llm/models', methods=['POST'])
def llm_list_models():
    data = request.get_json() or {}
    provider = data.get('provider', 'ollama')
    api_key, _ = get_api_key(provider, request.headers)
    custom_config = data.get('custom_config')
    result = LLMManager.list_models(provider, api_key, custom_config)
    return jsonify(result)

# ============================================================================
# Routes - Whisper
# ============================================================================

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
        settings = settings_manager.get_settings()
        selected_model = settings.get('whisper_model', whisper_manager.WHISPER_MODEL)
    audio_data = audio_file.read()

    result = whisper_manager.transcribe(audio_data, language, selected_model)
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
    return jsonify(build_offline_readiness_report())


@app.route('/api/offline-readiness')
def offline_readiness():
    return jsonify(build_offline_readiness_report())


@app.route('/api/live-audio/providers')
def live_audio_providers():
    return jsonify({
        'enabled': True,
        'default_mode': 'standard',
        'modes': [
            {
                'id': 'standard',
                'name': 'Standard',
                'description': 'Current text/STT/TTS flow',
            },
        ],
        'providers': [
            {
                'id': 'gemini_live_translate',
                'name': 'Google Gemini 3.5 Live Translate',
                'type': 'cloud',
                'supports': ['speech_to_speech', 'speech_to_text'],
                'transport': ['webrtc'],
            },
            {
                'id': 'openai_realtime_translate',
                'name': 'OpenAI gpt-realtime-translate',
                'type': 'cloud',
                'supports': ['speech_to_speech', 'speech_to_text'],
                'transport': ['webrtc', 'websocket'],
            },
            {
                'id': 'azure_speech_translation',
                'name': 'Azure Speech Translation',
                'type': 'cloud',
                'supports': ['speech_to_text', 'text_to_speech'],
                'transport': ['websocket'],
            },
            {
                'id': 'seamlessm4t_local',
                'name': 'Meta SeamlessM4T / SeamlessStreaming',
                'type': 'local',
                'supports': ['speech_to_speech', 'speech_to_text'],
                'transport': ['websocket'],
            },
            {
                'id': 'modular_local_stack',
                'name': 'Whisper + Local MT + Piper/Coqui',
                'type': 'local',
                'supports': ['speech_to_text', 'text_to_speech'],
                'transport': ['websocket'],
            },
        ],
    })

# ============================================================================
# Routes - Sessions
# ============================================================================

@app.route('/api/sessions')
def list_sessions():
    sessions = session_manager.list_sessions()
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
    app_logger.info(f"➕ Creating session: '{title}' | Type: {session_type} | Languages: {languages}")
    result = session_manager.create_session(title, session_type, languages)
    session_id = result.get('id')
    app_logger.info(f"✓ Session created: {session_id}")
    return jsonify(_serialize_session(session_id, result)), 201


@app.route('/api/sessions/<session_id>')
def get_session(session_id):
    app_logger.info(f"📖 Loading session: {session_id}")
    result = session_manager.get_session(session_id)
    if result is None:
        app_logger.warning(f"✗ Session not found: {session_id}")
        return jsonify({'error': 'Session not found'}), 404
    message_count = len(result.get('messages', []))
    app_logger.info(f"✓ Session loaded: {session_id} | Messages: {message_count}")
    return jsonify(_serialize_session(session_id, result))


@app.route('/api/sessions/<session_id>', methods=['PUT'])
def update_session(session_id):
    data = request.get_json() or {}
    new_title = data.get('title')
    app_logger.info(f"✏️ Updating session: {session_id} | New title: '{new_title}'")
    result = session_manager.update_session(session_id, title=new_title)
    if result is None:
        app_logger.warning(f"✗ Session not found: {session_id}")
        return jsonify({'error': 'Session not found'}), 404
    app_logger.info(f"✓ Session updated: {session_id}")
    return jsonify(_serialize_session(session_id, result))


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
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

    if 'file' not in request.files:
        return jsonify({'error': 'Image file is required'}), 400

    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'Invalid image file'}), 400

    _, ext = os.path.splitext(upload.filename)
    ext = ext.lower()
    if ext not in ALLOWED_SESSION_ICON_EXTENSIONS:
        return jsonify({'error': 'Unsupported image format. Use PNG, SVG, JPG, or GIF.'}), 400

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
    result = session_manager.add_message(session_id, data)
    if result is None:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({'success': True, 'message_count': len(result.get('messages', []))})

# ============================================================================
# Routes - Settings
# ============================================================================

@app.route('/api/settings', methods=['GET'])
def get_user_settings():
    """Get all user settings."""
    settings = settings_manager.get_settings()
    return jsonify(settings)


@app.route('/api/settings', methods=['POST'])
def save_user_settings():
    """Save user settings."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No settings provided'}), 400
    
    result = settings_manager.save_settings(data)
    if result.get('success'):
        return jsonify({'success': True, 'settings': settings_manager.get_settings()})
    return jsonify(result), 500


@app.route('/api/settings/reset', methods=['POST'])
def reset_user_settings():
    """Reset all settings to defaults."""
    result = settings_manager.reset_settings()
    if result.get('success'):
        return jsonify(result)
    return jsonify(result), 500


@app.route('/api/settings/defaults', methods=['GET'])
def get_defaults():
    """Get default settings."""
    return jsonify(settings_manager.get_default_settings())

# ============================================================================
# Routes - Glossaries
# ============================================================================

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
        return jsonify({'error': f'Failed to import glossary: {e}'}), 500


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

# ============================================================================
# Routes - Logs
# ============================================================================

@app.route('/api/logs')
def get_logs():
    try:
        lines = int(request.args.get('lines', 100))
        lines = min(lines, 1000)
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
            return jsonify({'logs': all_lines[-lines:]})
        return jsonify({'logs': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# SocketIO - Real-time translation for conversation mode
# ============================================================================

@socketio.on('connect')
def handle_connect():
    app_logger.info(f"Client connected: {request.sid}")
    emit('connected', {'sid': request.sid})


@socketio.on('disconnect')
def handle_disconnect():
    app_logger.info(f"Client disconnected: {request.sid}")


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
    
    # Try requested engine first
    result = TranslationManager.translate(
        text=text, source_lang=source_lang, target_lang=target_lang,
        engine=engine, provider=provider, model=model,
        api_key=api_key, custom_config=custom_config,
        glossary=glossary if glossary else None,
        ai_auto_correct=data.get('ai_auto_correct', True),
    )

    # If LibreTranslate fails, automatically fallback to LLM
    if not result.get('success') and engine == 'libretranslate' and (provider or SERVER_API_KEYS.get('anthropic')):
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
    emit('translation_result', result)

# ============================================================================
# Main
# ============================================================================

def run_preflight_checks():
    """Run pre-flight health checks for offline operation."""
    app_logger.info("=" * 60)
    app_logger.info("Running pre-flight checks...")
    app_logger.info("=" * 60)
    
    checks_passed = True
    
    # Check offline mode status
    offline = is_offline_mode()
    app_logger.info(f"✓ Offline mode: {'ENABLED' if offline else 'DISABLED'}")
    
    # Check Whisper availability
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
    
    # Check LibreTranslate connectivity using active runtime endpoint selection
    libre_status = TranslationManager.check_libre_status(timeout=5)
    if libre_status.get('available'):
        app_logger.info(f"✓ LibreTranslate: Connected ({libre_status.get('url')})")
    else:
        # During local mode, warmup is normal - embedded process may still be loading models
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
    
    # Check local LLM availability in offline mode
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

    # Run pre-flight checks
    checks_passed = run_preflight_checks()

    if STARTUP_FAIL_ON_CHECKS and not checks_passed:
        app_logger.error("Startup checks failed and STARTUP_FAIL_ON_CHECKS=true. Exiting.")
        raise SystemExit(1)

    # Cleanup old sessions on startup
    removed = session_manager.cleanup_old_sessions()
    if removed:
        app_logger.info(f"Cleaned up {removed} old sessions")

    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
