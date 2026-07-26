"""
LLM Manager - Unified LLM client supporting multiple providers.
Ported from OCR-WebApp with translation-focused modifications.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://host.docker.internal:11434')
LMSTUDIO_HOST = os.environ.get('LMSTUDIO_HOST', 'http://host.docker.internal:1234')

class LLMManager:
    """Unified LLM client supporting multiple providers."""

    NON_CHAT_PATTERNS = [
        'embed', 'text-embedding', 'dall-e', 'dalle', 'whisper',
        'tts', 'text-to-speech', 'moderation', 'rerank', 'classify',
        'summarize', 'detect', 'aya-expanse', 'c4ai-aya',
        'computer-use', 'realtime', 'audio-preview', 'search-preview',
    ]

    CHAT_PATTERNS = [
        'gpt-', 'o1', 'o3', 'chatgpt', 'claude', 'gemini',
        'command', 'deepseek', 'groq', 'grok', 'mistral', 'llama',
        'sonar', 'codestral', 'pixtral', 'ministral',
    ]

    PROVIDER_CONFIGS = {
        'ollama': {
            'type': 'local',
            'models_endpoint': '/api/tags',
            'chat_endpoint': '/api/chat',
        },
        'lmstudio': {
            'type': 'local',
            'models_endpoint': '/v1/models',
            'chat_endpoint': '/v1/chat/completions',
        },
        'openai': {
            'type': 'openai',
            'base_url': 'https://api.openai.com/v1',
            'models_endpoint': '/models',
            'chat_endpoint': '/chat/completions',
            'audio_transcription_endpoint': '/audio/transcriptions',
            'stt_models_fallback': [
                'gpt-4o-mini-transcribe',
                'gpt-4o-transcribe',
                'gpt-4o-transcribe-diarize',
                'whisper-1',
            ],
        },
        'anthropic': {
            'type': 'anthropic',
            'base_url': 'https://api.anthropic.com/v1',
            'chat_endpoint': '/messages',
        },
        'gemini': {
            'type': 'gemini',
            'base_url': 'https://generativelanguage.googleapis.com/v1beta',
        },
        'deepseek': {
            'type': 'openai',
            'base_url': 'https://api.deepseek.com/v1',
            'models_endpoint': '/models',
            'chat_endpoint': '/chat/completions',
        },
        'cohere': {
            'type': 'openai',
            'base_url': 'https://api.cohere.ai/compatibility/v1',
            'native_models_url': 'https://api.cohere.ai/v1/models',
            'chat_endpoint': '/chat/completions',
        },
        'groq': {
            'type': 'openai',
            'base_url': 'https://api.groq.com/openai/v1',
            'models_endpoint': '/models',
            'chat_endpoint': '/chat/completions',
            'audio_transcription_endpoint': '/audio/transcriptions',
            'stt_models_fallback': [
                'whisper-large-v3-turbo',
                'whisper-large-v3',
            ],
        },
        'grok': {
            'type': 'openai',
            'base_url': 'https://api.x.ai/v1',
            'models_endpoint': '/models',
            'chat_endpoint': '/chat/completions',
        },
        'mistral': {
            'type': 'openai',
            'base_url': 'https://api.mistral.ai/v1',
            'models_endpoint': '/models',
            'chat_endpoint': '/chat/completions',
        },
        'perplexity': {
            'type': 'openai',
            'base_url': 'https://api.perplexity.ai',
            'chat_endpoint': '/chat/completions',
        },
    }

    @staticmethod
    def filter_chat_models(models):
        if not models:
            return models
        filtered = []
        for model_id in models:
            model_lower = model_id.lower()
            is_non_chat = any(p in model_lower for p in LLMManager.NON_CHAT_PATTERNS)
            if is_non_chat:
                continue
            is_chat = any(p in model_lower for p in LLMManager.CHAT_PATTERNS)
            if is_chat or not is_non_chat:
                filtered.append(model_id)
        return filtered

    @staticmethod
    def get_base_url(provider, custom_config=None):
        if provider == 'ollama':
            if custom_config:
                protocol = custom_config.get('protocol', 'http')
                host = custom_config.get('host', 'localhost')
                port = custom_config.get('port', 11434)
                return f"{protocol}://{host}:{port}"
            return OLLAMA_HOST
        elif provider == 'lmstudio':
            if custom_config:
                protocol = custom_config.get('protocol', 'http')
                host = custom_config.get('host', 'localhost')
                port = custom_config.get('port', 1234)
                return f"{protocol}://{host}:{port}"
            return LMSTUDIO_HOST
        else:
            return LLMManager.PROVIDER_CONFIGS.get(provider, {}).get('base_url', '')

    @staticmethod
    def test_connection(provider, api_key=None, custom_config=None):
        try:
            base_url = LLMManager.get_base_url(provider, custom_config)
            prov_config = LLMManager.PROVIDER_CONFIGS.get(provider, {})
            headers = {'Content-Type': 'application/json', 'User-Agent': 'Live-Translate/1.0'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            if provider == 'ollama':
                endpoint = f"{base_url}/api/tags"
            elif provider == 'lmstudio':
                endpoint = f"{base_url}/v1/models"
            elif provider == 'anthropic':
                endpoint = f"{base_url}/models"
                headers['x-api-key'] = api_key or ''
                headers['anthropic-version'] = '2023-06-01'
                headers.pop('Authorization', None)
            elif 'models_endpoint' in prov_config:
                endpoint = f"{base_url}{prov_config['models_endpoint']}"
            else:
                endpoint = f"{base_url}{prov_config.get('chat_endpoint', '/chat/completions')}"
                test_payload = {
                    'model': 'test-model',
                    'messages': [{'role': 'user', 'content': 'test'}],
                    'max_tokens': 1
                }
                response = requests.post(endpoint, json=test_payload, headers=headers, timeout=5)
                return {
                    'connected': response.status_code < 500,
                    'status_code': response.status_code,
                    'url': endpoint,
                    'error': None if response.status_code < 500 else f"HTTP {response.status_code}"
                }

            response = requests.get(endpoint, headers=headers, timeout=5)
            return {
                'connected': response.ok,
                'status_code': response.status_code,
                'url': endpoint,
                'error': None if response.ok else f"HTTP {response.status_code}"
            }
        except requests.exceptions.Timeout:
            return {'connected': False, 'status_code': None, 'url': base_url, 'error': 'Connection timeout'}
        except requests.exceptions.ConnectionError as e:
            return {'connected': False, 'status_code': None, 'url': base_url, 'error': f'Connection refused: {str(e)}'}
        except Exception as e:
            return {'connected': False, 'status_code': None, 'url': '', 'error': str(e)}

    @staticmethod
    def list_models(provider, api_key=None, custom_config=None):
        try:
            base_url = LLMManager.get_base_url(provider, custom_config)
            prov_config = LLMManager.PROVIDER_CONFIGS.get(provider, {})
            headers = {'Content-Type': 'application/json', 'User-Agent': 'Live-Translate/1.0'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            if provider == 'ollama':
                endpoint = f"{base_url}/api/tags"
                response = requests.get(endpoint, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                return {'models': [m['name'] for m in data.get('models', [])], 'error': None}

            elif provider == 'lmstudio':
                endpoint = f"{base_url}/v1/models"
                response = requests.get(endpoint, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                return {'models': [m['id'] for m in data.get('data', [])], 'error': None}

            elif provider == 'anthropic':
                if not api_key:
                    return {'models': [], 'error': 'API key required'}
                endpoint = f"{base_url}/models"
                headers['x-api-key'] = api_key
                headers['anthropic-version'] = '2023-06-01'
                headers.pop('Authorization', None)
                response = requests.get(endpoint, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                models = []
                if isinstance(data.get('data'), list):
                    models = [m['id'] for m in data['data'] if m.get('id')]
                elif isinstance(data.get('models'), list):
                    models = [m.get('id') or m.get('name') for m in data['models'] if m.get('id') or m.get('name')]
                return {'models': models, 'error': None}

            elif provider == 'gemini':
                endpoint = f"{base_url}/models?key={api_key}"
                response = requests.get(endpoint, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                models = []
                for m in data.get('models', []):
                    name = m.get('name', '')
                    model_id = name.split('/')[-1] if '/' in name else name
                    if model_id:
                        models.append(model_id)
                return {'models': LLMManager.filter_chat_models(models), 'error': None}

            elif provider == 'cohere':
                if not api_key:
                    return {'models': [], 'error': 'API key required'}
                native_url = prov_config.get('native_models_url', 'https://api.cohere.ai/v1/models')
                response = requests.get(native_url, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                models = [m.get('name') or m.get('id') for m in data.get('models', []) if m.get('name') or m.get('id')]
                return {'models': LLMManager.filter_chat_models(models), 'error': None}

            elif provider == 'perplexity':
                if not api_key:
                    return {'models': [], 'error': 'API key required'}
                endpoint = f"{base_url}/models"
                try:
                    response = requests.get(endpoint, headers=headers, timeout=10)
                    if response.ok:
                        data = response.json()
                        models = [m.get('id') for m in data.get('data', []) if m.get('id')]
                        if models:
                            return {'models': models, 'error': None}
                    elif response.status_code == 401:
                        return {'models': [], 'error': 'Invalid API key'}
                except Exception:
                    pass
                return {'models': ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'], 'error': None}

            elif provider == 'deepseek':
                if not api_key:
                    return {'models': [], 'error': 'API key required'}
                endpoint = f"{base_url}/models"
                try:
                    response = requests.get(endpoint, headers=headers, timeout=10)
                    if response.ok:
                        data = response.json()
                        models = [m.get('id') or m.get('name') for m in data.get('data', []) if m.get('id') or m.get('name')]
                        return {'models': models, 'error': None}
                    elif response.status_code == 401:
                        return {'models': [], 'error': 'Invalid API key'}
                except Exception:
                    pass
                try:
                    alt_endpoint = 'https://api.deepseek.com/models'
                    response = requests.get(alt_endpoint, headers=headers, timeout=10)
                    if response.ok:
                        data = response.json()
                        models = [m.get('id') or m.get('name') for m in data.get('data', []) if m.get('id') or m.get('name')]
                        return {'models': models, 'error': None}
                except Exception:
                    pass
                return {'models': [], 'error': 'Could not connect to DeepSeek API'}

            else:
                models_endpoint = prov_config.get('models_endpoint', '/models')
                endpoint = f"{base_url}{models_endpoint}"
                response = requests.get(endpoint, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                models = []
                for m in data.get('data', []) or data.get('models', []):
                    model_id = m.get('id') or m.get('name')
                    if model_id:
                        models.append(model_id)
                return {'models': LLMManager.filter_chat_models(models), 'error': None}

        except requests.exceptions.Timeout:
            return {'models': [], 'error': 'Connection timeout'}
        except requests.exceptions.ConnectionError as e:
            return {'models': [], 'error': f'Connection refused: {str(e)}'}
        except requests.exceptions.HTTPError as e:
            return {'models': [], 'error': f'HTTP error: {e.response.status_code}'}
        except Exception as e:
            return {'models': [], 'error': str(e)}

    @staticmethod
    def chat(provider, messages, model, api_key=None, custom_config=None, temperature=0.7, max_tokens=2000):
        try:
            base_url = LLMManager.get_base_url(provider, custom_config)
            config_data = LLMManager.PROVIDER_CONFIGS.get(provider, {})
            headers = {'Content-Type': 'application/json', 'User-Agent': 'Live-Translate/1.0'}
            timeout = 120

            if provider == 'ollama':
                endpoint = f"{base_url}/api/chat"
                payload = {'model': model, 'messages': messages, 'stream': False}
                response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                if response.ok:
                    data = response.json()
                    return {'success': True, 'content': data.get('message', {}).get('content', '')}

            elif provider == 'anthropic':
                endpoint = f"{base_url}/messages"
                headers['x-api-key'] = api_key
                headers['anthropic-version'] = '2023-06-01'
                system_msg = next((m['content'] for m in messages if m['role'] == 'system'), '')
                user_messages = [m for m in messages if m['role'] != 'system']
                payload = {
                    'model': model, 'messages': user_messages,
                    'system': system_msg, 'max_tokens': max_tokens, 'temperature': temperature,
                }
                response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                if response.ok:
                    data = response.json()
                    content = data.get('content', [{}])[0].get('text', '')
                    return {'success': True, 'content': content}

            elif provider == 'gemini':
                endpoint = f"{base_url}/models/{model}:generateContent?key={api_key}"
                parts = [{'text': f"{m['role']}: {m['content']}"} for m in messages]
                payload = {
                    'contents': [{'parts': parts}],
                    'generationConfig': {'maxOutputTokens': max_tokens, 'temperature': temperature},
                }
                response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                if response.ok:
                    data = response.json()
                    content = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                    return {'success': True, 'content': content}

            else:
                if api_key:
                    headers['Authorization'] = f'Bearer {api_key}'
                chat_endpoint = config_data.get('chat_endpoint', '/chat/completions')
                endpoint = f"{base_url}{chat_endpoint}"
                payload = {
                    'model': model, 'messages': messages,
                    'max_tokens': max_tokens, 'temperature': temperature,
                }
                response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                if response.ok:
                    data = response.json()
                    content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    return {'success': True, 'content': content}

            error_msg = f"HTTP {response.status_code}"
            try:
                error_data = response.json()
                if 'error' in error_data:
                    if isinstance(error_data['error'], dict):
                        error_msg = error_data['error'].get('message', error_msg)
                    else:
                        error_msg = str(error_data['error'])
                elif 'message' in error_data:
                    error_msg = error_data['message']
            except Exception:
                status_code = response.status_code
                if status_code == 404:
                    error_msg = f"Model '{model}' not found."
                elif status_code == 401:
                    error_msg = "Authentication failed. Check your API key."
                elif status_code == 403:
                    error_msg = f"Access denied to model '{model}'."
                elif status_code == 429:
                    error_msg = "Rate limit exceeded. Please wait and try again."

            return {'success': False, 'error': error_msg}

        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Request timed out'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Connection failed - server unreachable'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def list_stt_models(provider, api_key=None, custom_config=None):
        try:
            config_data = LLMManager.PROVIDER_CONFIGS.get(provider, {})
            endpoint_suffix = config_data.get('audio_transcription_endpoint')
            fallback_models = config_data.get('stt_models_fallback', [])
            if not endpoint_suffix:
                return {'models': [], 'error': 'Provider does not support speech-to-text'}

            base_url = LLMManager.get_base_url(provider, custom_config)
            headers = {'Content-Type': 'application/json', 'User-Agent': 'Live-Translate/1.0'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            try:
                response = requests.get(f"{base_url}/models", headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                models = []
                for m in data.get('data', []) or data.get('models', []):
                    model_id = m.get('id') or m.get('name')
                    if model_id:
                        models.append(model_id)

                stt_models = [
                    model for model in models
                    if any(pattern in model.lower() for pattern in ('whisper', 'transcribe', 'diarize'))
                ]
                if stt_models:
                    return {'models': stt_models, 'error': None}
            except Exception:
                pass

            return {'models': fallback_models, 'error': None if fallback_models else 'No STT models found'}
        except requests.exceptions.Timeout:
            return {'models': [], 'error': 'Connection timeout'}
        except requests.exceptions.ConnectionError as e:
            return {'models': [], 'error': f'Connection refused: {str(e)}'}
        except Exception as e:
            return {'models': [], 'error': str(e)}

    @staticmethod
    def transcribe_audio(provider, model, audio_data, filename, api_key=None, language=None, custom_config=None):
        try:
            config_data = LLMManager.PROVIDER_CONFIGS.get(provider, {})
            endpoint_suffix = config_data.get('audio_transcription_endpoint')
            if not endpoint_suffix:
                return {'success': False, 'error': 'Provider does not support speech-to-text'}

            base_url = LLMManager.get_base_url(provider, custom_config)
            headers = {'User-Agent': 'Live-Translate/1.0'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            data = {
                'model': model,
                'response_format': 'json',
                'temperature': '0',
            }
            if language and language != 'auto':
                data['language'] = language

            files = {
                'file': (filename or 'recording.webm', audio_data, 'audio/webm'),
            }
            response = requests.post(
                f"{base_url}{endpoint_suffix}",
                headers=headers,
                data=data,
                files=files,
                timeout=120,
            )

            if response.ok:
                content_type = (response.headers.get('content-type') or '').lower()
                if 'application/json' in content_type:
                    payload = response.json()
                    return {
                        'success': True,
                        'text': payload.get('text', ''),
                        'raw': payload,
                    }
                return {'success': True, 'text': response.text.strip(), 'raw': None}

            error_msg = f"HTTP {response.status_code}"
            try:
                error_data = response.json()
                if 'error' in error_data:
                    if isinstance(error_data['error'], dict):
                        error_msg = error_data['error'].get('message', error_msg)
                    else:
                        error_msg = str(error_data['error'])
                elif 'message' in error_data:
                    error_msg = error_data['message']
            except Exception:
                pass
            return {'success': False, 'error': error_msg}
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Speech-to-text request timed out'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Speech-to-text provider unreachable'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def translate(text, target_language, provider, model, api_key=None, custom_config=None, ai_auto_correct=True):
        instructions = [
            "1. **Preserve Structure:** Maintain all original formatting, line breaks, paragraphs, and spacing",
        ]
        
        if ai_auto_correct:
            instructions.append(
                "2. **Auto-Correct Errors:** If you detect obvious spelling errors, mistyped letters, or unclear wording, intelligently correct them during translation to convey the intended meaning"
            )
        
        instructions.extend([
            f"{3 if ai_auto_correct else 2}. **Technical Terms:** Preserve technical terms, proper nouns, brand names, and specialized vocabulary appropriately",
            f"{4 if ai_auto_correct else 3}. **Tone Matching:** Match the tone and formality level of the original text",
            f"{5 if ai_auto_correct else 4}. **Cultural Context:** Adapt idioms and cultural references appropriately for the target language",
            f"{6 if ai_auto_correct else 5}. **Numbers & Dates:** Keep numbers, dates, measurements in their original format unless conversion is contextually necessary",
        ])
        
        system_prompt = f"""You are an expert translator.

**Your Task:** Translate the following text to {target_language} using accurate and professional setting style writing.

**Critical Instructions:**
{chr(10).join(instructions)}

**Output Requirements:**
- Output ONLY the translated text
- Do NOT add explanations, notes, or meta-commentary
- Do NOT prefix with phrases like "Here is the translation" or "Translation:"
- Do NOT include thinking tags or reasoning blocks

**Quality Standards:**
- Ensure the translation is complete and not truncated
- Maintain the same approximate length and structure as the original
- Ensure natural fluency in the target language while preserving original meaning"""

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': text},
        ]
        return LLMManager.chat(provider, messages, model, api_key, custom_config, temperature=0.3, max_tokens=4096)
