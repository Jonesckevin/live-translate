"""
Settings Manager - User settings storage and management.
Stored as JSON file in /data/settings.json.
"""

import os
import json
import logging
import tempfile

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.environ.get('SETTINGS_FILE', '/data/settings.json')

DEFAULT_SETTINGS = {
    'ai_auto_correct': True,
    'api_key_priority': 'client',
    'header_title': 'Live Translate',
    'header_logo_data_url': '',
    'api_keys': {},
    'provider_models': {},
    'translation_engine': 'libretranslate',
    'translation_provider': 'anthropic',
    'translation_model': '',
    'stt_engine': 'web_speech_api',
    'stt_provider': 'groq',
    'stt_model': '',
    'whisper_model': os.environ.get('WHISPER_MODEL', 'base'),
    'voice_mode': 'single',
    'playback_voices': [],
    'push_to_talk_left': '',
    'push_to_talk_right': '',
    'speech_mode': 'standard',
    'offline_mode': 'auto',
    'offline_strict': False,
}


def _ensure_file():
    """Ensure settings file exists with defaults."""
    if not os.path.exists(SETTINGS_FILE):
        _atomic_write_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())


def _atomic_write_json(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=directory or None)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def get_settings():
    """Get all user settings."""
    _ensure_file()
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        # Merge with defaults to ensure all keys exist
        merged = DEFAULT_SETTINGS.copy()
        merged.update(settings)
        return merged
    except Exception as e:
        logger.error(f"Error reading settings: {e}")
        return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save user settings."""
    _ensure_file()
    try:
        # Validate and merge with defaults
        merged = DEFAULT_SETTINGS.copy()
        merged.update(settings)

        _atomic_write_json(SETTINGS_FILE, merged)
        return {'success': True}
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return {'success': False, 'error': str(e)}


def update_setting(key, value):
    """Update a single setting."""
    settings = get_settings()
    settings[key] = value
    return save_settings(settings)


def reset_settings():
    """Reset all settings to defaults."""
    try:
        _atomic_write_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())
        return {'success': True, 'settings': DEFAULT_SETTINGS.copy()}
    except Exception as e:
        logger.error(f"Error resetting settings: {e}")
        return {'success': False, 'error': str(e)}


def get_default_settings():
    """Get default settings (for comparison or reset preview)."""
    return DEFAULT_SETTINGS.copy()
