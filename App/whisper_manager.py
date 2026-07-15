"""
Whisper Manager - Optional server-side speech-to-text using faster-whisper.
Only loaded when WHISPER_ENABLED=true environment variable is set.
"""

import os
import logging
import tempfile

logger = logging.getLogger(__name__)

WHISPER_ENABLED = os.environ.get('WHISPER_ENABLED', 'false').lower() == 'true'
WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'base')
WHISPER_USE_GPU = os.environ.get('WHISPER_USE_GPU', 'false').lower() == 'true'
WHISPER_MODEL_DIR = os.environ.get('WHISPER_MODEL_DIR', '/data/whisper-model')

_whisper_model = None
_whisper_model_name = None
_whisper_runtime_device = None
_whisper_runtime_compute_type = None
_whisper_gpu_fallback_used = False

def _is_cuda_runtime_error(error):
    message = str(error).lower()
    cuda_tokens = ('cuda', 'cublas', 'cudnn', 'ctranslate2')
    failure_tokens = ('driver', 'runtime version', 'insufficient', 'initialization', 'failed')
    return any(token in message for token in cuda_tokens) and any(token in message for token in failure_tokens)

def _load_model_instance(WhisperModel, model_name, device, compute_type):
    logger.info(f"Loading Whisper model: {model_name} ({device} mode, {compute_type}) from {WHISPER_MODEL_DIR}")
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=WHISPER_MODEL_DIR,
    )
    logger.info(f"Whisper model loaded successfully ({device}, {compute_type})")
    return model

def get_whisper_model(force_cpu=False, force_reload=False, model_name=None):
    """Lazy-load the Whisper model."""
    global _whisper_model, _whisper_model_name, _whisper_runtime_device, _whisper_runtime_compute_type, _whisper_gpu_fallback_used

    selected_model = (model_name or WHISPER_MODEL or 'base').strip() or 'base'

    if force_reload:
        _whisper_model = None

    if _whisper_model is not None and _whisper_model_name != selected_model:
        logger.info(
            "Whisper model selection changed (%s -> %s). Reloading model.",
            _whisper_model_name,
            selected_model,
        )
        _whisper_model = None

    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel

            prefer_gpu = WHISPER_USE_GPU and not force_cpu
            device = "cuda" if prefer_gpu else "cpu"
            compute_type = "float16" if prefer_gpu else "int8"

            try:
                _whisper_model = _load_model_instance(WhisperModel, selected_model, device, compute_type)
                _whisper_model_name = selected_model
                _whisper_runtime_device = device
                _whisper_runtime_compute_type = compute_type
            except Exception as e:
                if prefer_gpu and _is_cuda_runtime_error(e):
                    logger.warning(
                        "Whisper GPU initialization failed (%s). Falling back to CPU int8.",
                        e,
                    )
                    _whisper_model = _load_model_instance(WhisperModel, selected_model, "cpu", "int8")
                    _whisper_model_name = selected_model
                    _whisper_runtime_device = "cpu"
                    _whisper_runtime_compute_type = "int8"
                    _whisper_gpu_fallback_used = True
                else:
                    raise
        except ImportError:
            logger.error("faster-whisper not installed. Install with: pip install faster-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    return _whisper_model

def transcribe(audio_data, language=None, model_name=None):
    """
    Transcribe audio data to text.
    audio_data: bytes of audio file (wav, mp3, webm, etc.)
    language: optional language code hint (e.g. 'en', 'fr')
    Returns: dict with success, text, language, segments
    """
    if not WHISPER_ENABLED:
        return {'success': False, 'error': 'Whisper is not enabled. Set WHISPER_ENABLED=true.'}

    global _whisper_gpu_fallback_used

    try:
        model = get_whisper_model(model_name=model_name)

        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            kwargs = {}
            if language and language != 'auto':
                kwargs['language'] = language

            try:
                segments, info = model.transcribe(tmp_path, beam_size=5, **kwargs)
            except RuntimeError as e:
                if WHISPER_USE_GPU and _is_cuda_runtime_error(e):
                    logger.warning(
                        "Whisper CUDA runtime error during transcription (%s). Retrying once on CPU int8.",
                        e,
                    )
                    _whisper_gpu_fallback_used = True
                    model = get_whisper_model(force_cpu=True, force_reload=True, model_name=model_name)
                    segments, info = model.transcribe(tmp_path, beam_size=5, **kwargs)
                else:
                    raise

            text_parts = []
            segment_list = []
            for segment in segments:
                text_parts.append(segment.text)
                segment_list.append({
                    'start': round(segment.start, 2),
                    'end': round(segment.end, 2),
                    'text': segment.text.strip(),
                })

            full_text = ' '.join(text_parts).strip()

            return {
                'success': True,
                'text': full_text,
                'language': info.language,
                'language_probability': round(info.language_probability, 2),
                'segments': segment_list,
            }
        finally:
            os.unlink(tmp_path)

    except ImportError:
        return {'success': False, 'error': 'faster-whisper not installed'}
    except Exception as e:
        logger.exception(f"Whisper transcription failed: {e}")
        return {'success': False, 'error': str(e)}

def get_status():
    """Get Whisper availability status."""
    status = {
        'enabled': WHISPER_ENABLED,
        'model': _whisper_model_name or WHISPER_MODEL,
        'use_gpu': WHISPER_USE_GPU,
        'model_dir': WHISPER_MODEL_DIR,
        'loaded': _whisper_model is not None,
        'runtime_device': _whisper_runtime_device,
        'runtime_compute_type': _whisper_runtime_compute_type,
        'gpu_fallback_used': _whisper_gpu_fallback_used,
    }
    if WHISPER_ENABLED:
        try:
            from faster_whisper import WhisperModel
            status['installed'] = True
        except ImportError:
            status['installed'] = False
    return status
