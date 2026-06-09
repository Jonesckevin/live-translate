"""
Translation Manager - Unified interface for LibreTranslate and LLM-based translation.
Routes translation requests to the appropriate engine and handles glossary processing.
"""

import os
import logging
import socket
import time

import requests

from llm_manager import LLMManager

logger = logging.getLogger(__name__)


def _env_true(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


LIBRETRANSLATE_LOCAL_ENABLED = _env_true('LIBRETRANSLATE_LOCAL_ENABLED', True)
LIBRETRANSLATE_LOCAL_URL = os.environ.get('LIBRETRANSLATE_LOCAL_URL', 'http://127.0.0.1:5001')
LIBRETRANSLATE_SERVER_URL = os.environ.get(
    'LIBRETRANSLATE_SERVER_URL',
    os.environ.get('LIBRETRANSLATE_URL', 'http://libretranslate:5000'),
)
LIBRETRANSLATE_HOST = LIBRETRANSLATE_LOCAL_URL if LIBRETRANSLATE_LOCAL_ENABLED else LIBRETRANSLATE_SERVER_URL

logger.info(
    "LibreTranslate endpoint selected: %s (local_enabled=%s)",
    LIBRETRANSLATE_HOST,
    LIBRETRANSLATE_LOCAL_ENABLED,
)


class TranslationManager:
    """Unified translation interface supporting LibreTranslate and LLM providers."""

    @staticmethod
    def translate_libre(text, source_lang, target_lang, timeout=30):
        """Translate using LibreTranslate API."""
        try:
            endpoint = f"{LIBRETRANSLATE_HOST}/translate"
            payload = {
                'q': text,
                'source': source_lang if source_lang != 'auto' else 'auto',
                'target': target_lang,
                'format': 'text',
            }
            response = requests.post(endpoint, json=payload, timeout=timeout)
            if response.ok:
                data = response.json()
                return {
                    'success': True,
                    'translated_text': data.get('translatedText', ''),
                    'detected_language': data.get('detectedLanguage', {}).get('language'),
                    'engine': 'libretranslate',
                }
            else:
                error_msg = 'Translation failed'
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except Exception:
                    error_msg = f"HTTP {response.status_code}"
                logger.warning(f"LibreTranslate API error: {error_msg}")
                return {'success': False, 'error': error_msg, 'engine': 'libretranslate'}
        except requests.exceptions.Timeout:
            logger.warning(f"LibreTranslate timeout (endpoint: {LIBRETRANSLATE_HOST})")
            return {'success': False, 'error': 'LibreTranslate timeout (models still loading?)', 'engine': 'libretranslate'}
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"LibreTranslate connection error (endpoint: {LIBRETRANSLATE_HOST}): {e}")
            return {'success': False, 'error': 'LibreTranslate not reachable (models still loading?)', 'engine': 'libretranslate'}
        except Exception as e:
            logger.error(f"LibreTranslate unexpected error: {str(e)}")
            return {'success': False, 'error': str(e), 'engine': 'libretranslate'}

    @staticmethod
    def translate_llm(text, source_lang, target_lang, provider, model, api_key=None, custom_config=None, ai_auto_correct=True):
        """Translate using an LLM provider."""
        lang_label = target_lang
        result = LLMManager.translate(text, lang_label, provider, model, api_key, custom_config, ai_auto_correct)
        if result.get('success'):
            return {
                'success': True,
                'translated_text': result['content'],
                'engine': f'llm:{provider}',
            }
        return {'success': False, 'error': result.get('error', 'LLM translation failed'), 'engine': f'llm:{provider}'}

    @staticmethod
    def translate(text, source_lang, target_lang, engine='libretranslate',
                  provider=None, model=None, api_key=None, custom_config=None,
                  glossary=None, timeout=30, ai_auto_correct=True):
        """
        Unified translation entry point.
        engine: 'libretranslate' or 'llm'
        glossary: dict of {source_term: target_term} for pre/post processing
        ai_auto_correct: whether to enable AI spelling/typo correction (LLM only)
        """
        # Pre-process: apply glossary substitutions
        processed_text = text
        placeholders = {}
        if glossary:
            for i, (src_term, tgt_term) in enumerate(glossary.items()):
                placeholder = f"__GLOSS_{i}__"
                if src_term in processed_text:
                    processed_text = processed_text.replace(src_term, placeholder)
                    placeholders[placeholder] = tgt_term

        # Route to engine
        if engine == 'libretranslate':
            logger.debug(f"Using LibreTranslate engine: {LIBRETRANSLATE_HOST}")
            result = TranslationManager.translate_libre(processed_text, source_lang, target_lang, timeout)
        elif engine == 'llm':
            if not provider or not model:
                logger.warning(f"LLM engine selected but missing: provider={provider}, model={model}")
                return {'success': False, 'error': 'LLM provider and model required'}
            logger.debug(f"Using LLM engine: provider={provider}, model={model}")
            result = TranslationManager.translate_llm(
                processed_text, source_lang, target_lang, provider, model, api_key, custom_config, ai_auto_correct
            )
        else:
            logger.error(f"Unknown engine: {engine}")
            return {'success': False, 'error': f'Unknown engine: {engine}'}

        # Post-process: restore glossary terms
        if result.get('success') and placeholders:
            translated = result['translated_text']
            for placeholder, tgt_term in placeholders.items():
                translated = translated.replace(placeholder, tgt_term)
            result['translated_text'] = translated

        return result

    @staticmethod
    def detect_language(text, timeout=10):
        """Detect language using LibreTranslate."""
        try:
            endpoint = f"{LIBRETRANSLATE_HOST}/detect"
            payload = {'q': text}
            response = requests.post(endpoint, json=payload, timeout=timeout)
            if response.ok:
                data = response.json()
                return {'success': True, 'detections': data}
            return {'success': False, 'error': f"HTTP {response.status_code}"}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'LibreTranslate not reachable'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def get_languages(timeout=10):
        """Get supported languages from LibreTranslate."""
        try:
            endpoint = f"{LIBRETRANSLATE_HOST}/languages"
            response = requests.get(endpoint, timeout=timeout)
            if response.ok:
                return {'success': True, 'languages': response.json()}
            return {'success': False, 'error': f"HTTP {response.status_code}"}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'LibreTranslate not reachable'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def check_libre_status(timeout=5, retries=1, retry_delay=0.5):
        """Check LibreTranslate health with minimal retries for preflight.
        
        During startup in local mode, service may still be warming up.
        For live health checks, retries can be increased by caller.
        """
        endpoint = f"{LIBRETRANSLATE_HOST}/languages"
        last_error = None
        
        for attempt in range(retries):
            try:
                response = requests.get(endpoint, timeout=timeout)
                if response.ok:
                    return {
                        'available': True,
                        'status_code': response.status_code,
                        'url': LIBRETRANSLATE_HOST,
                    }
                last_error = f"HTTP {response.status_code}"
            except requests.exceptions.ConnectionError:
                last_error = 'Not reachable'
            except Exception as e:
                last_error = str(e)
            
            # Quick retry backoff only if not last attempt
            if attempt < retries - 1:
                time.sleep(retry_delay)
        
        # In local mode, report as "available" even if warming up
        # Translations will work via LLM fallback while models load
        is_local = LIBRETRANSLATE_LOCAL_ENABLED
        if is_local and last_error != 'Not reachable':
            # Service responded with an error (e.g., 500) but is listening
            return {
                'available': True,
                'warming_up': True,
                'url': LIBRETRANSLATE_HOST,
            }
        
        # Try to ping the port directly in local mode
        if is_local:
            try:
                host, port = LIBRETRANSLATE_LOCAL_URL.split('://')[-1].split(':')
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((host, int(port)))
                sock.close()
                if result == 0:
                    # Port is open - service is running even if not responding to /languages
                    return {
                        'available': True,
                        'warming_up': True,
                        'url': LIBRETRANSLATE_HOST,
                    }
            except:
                pass
        
        return {'available': False, 'error': last_error or 'Unknown error', 'url': LIBRETRANSLATE_HOST}
