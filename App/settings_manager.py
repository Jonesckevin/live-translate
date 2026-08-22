"""
Settings Manager - User settings storage and management.
Stored as JSON file in /data/settings.json.
"""

import os
import json
import logging

import crypto_manager
from storage_utils import atomic_write_json

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.environ.get('SETTINGS_FILE', '/data/settings.json')

DEFAULT_SETTINGS = {
    'ai_auto_correct': True,
    'force_offline': False,
    'api_key_priority': 'client',
    'header_title': 'Live Translate',
    'header_logo_data_url': '',
    'api_keys': {},
    'provider_models': {},
    'translation_engine': 'libretranslate',
    'translation_provider': 'anthropic',
    'translation_model': '',
    'live_translation': 'stream',
    'interim_debounce_left': 120,
    'interim_debounce_right': 120,
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
        atomic_write_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())

def get_settings():
    """Get all user settings."""
    _ensure_file()
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        merged = DEFAULT_SETTINGS.copy()
        merged.update(settings)
        return merged
    except Exception as e:
        logger.error(f"Error reading settings: {e}")
        return DEFAULT_SETTINGS.copy()

def get_default_settings():
    """Get default settings (for comparison or reset preview)."""
    return DEFAULT_SETTINGS.copy()

def merge_with_defaults(partial):
    """Return DEFAULT_SETTINGS overlaid with the recognized keys from `partial`."""
    merged = DEFAULT_SETTINGS.copy()
    if isinstance(partial, dict):
        for key, value in partial.items():
            if key in DEFAULT_SETTINGS:
                merged[key] = value
    return merged

def encrypt_api_keys(settings):
    """Return a copy of settings with api_keys values encrypted for storage."""
    settings = dict(settings)
    keys = settings.get('api_keys') or {}
    encrypted = {}
    for provider, value in keys.items():
        if value:
            encrypted[provider] = crypto_manager.encrypt(value)
    settings['api_keys'] = encrypted
    return settings

def decrypt_api_keys(settings):
    """Return a copy of settings with api_keys values decrypted for client use."""
    settings = dict(settings)
    keys = settings.get('api_keys') or {}
    decrypted = {}
    for provider, value in keys.items():
        if not value:
            continue
        plain = crypto_manager.decrypt(value)
        if plain:
            decrypted[provider] = plain
    settings['api_keys'] = decrypted
    return settings
