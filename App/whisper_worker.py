"""Whisper worker process.

Runs as a standalone OS process (NOT under gevent) so CPU-bound Whisper
inference never blocks the main server's gevent event loop. The main process
spawns this worker, sends transcription jobs as JSON lines on stdin, and reads
results as JSON lines on stdout.

Job line:   {"id": <int>, "audio_path": <str>, "language": <str|None>, "model_name": <str|None>}
Result line:{"id": <int>, "result": { ... }}
"""

import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('whisper-worker')

WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'tiny')
WHISPER_USE_GPU = os.environ.get('WHISPER_USE_GPU', 'false').lower() == 'true'
WHISPER_MODEL_DIR = os.environ.get('WHISPER_MODEL_DIR', '/data/whisper-model')

_model = None
_model_name = None


def _is_cuda_runtime_error(error):
    message = str(error).lower()
    cuda_tokens = ('cuda', 'cublas', 'cudnn', 'ctranslate2')
    failure_tokens = ('driver', 'runtime version', 'insufficient', 'initialization', 'failed')
    return any(token in message for token in cuda_tokens) and any(token in message for token in failure_tokens)


def _load(model_name):
    """Load (and cache) the requested model in this worker process."""
    global _model, _model_name
    selected = (model_name or WHISPER_MODEL or 'base').strip() or 'base'
    if _model is not None and _model_name == selected:
        return _model
    from faster_whisper import WhisperModel

    _model = None
    prefer_gpu = WHISPER_USE_GPU
    device = "cuda" if prefer_gpu else "cpu"
    compute_type = "float16" if prefer_gpu else "int8"
    logger.info("Loading Whisper model: %s (%s, %s) from %s", selected, device, compute_type, WHISPER_MODEL_DIR)
    try:
        m = WhisperModel(selected, device=device, compute_type=compute_type, download_root=WHISPER_MODEL_DIR)
    except Exception as e:
        if prefer_gpu and _is_cuda_runtime_error(e):
            logger.warning("GPU init failed (%s); falling back to CPU int8", e)
            m = WhisperModel(selected, device="cpu", compute_type="int8", download_root=WHISPER_MODEL_DIR)
        else:
            raise
    _model = m
    _model_name = selected
    return m


def _transcribe(audio_path, language, model_name):
    """Transcribe a single audio file. Returns a result dict."""
    try:
        model = _load(model_name)
        kwargs = {}
        if language and language != 'auto':
            kwargs['language'] = language
        segments, info = model.transcribe(audio_path, beam_size=5, **kwargs)
        text_parts = []
        segs = []
        for seg in segments:
            text_parts.append(seg.text)
            segs.append({'start': round(seg.start, 2), 'end': round(seg.end, 2), 'text': seg.text.strip()})
        return {
            'success': True,
            'text': ' '.join(text_parts).strip(),
            'language': info.language,
            'language_probability': round(info.language_probability, 2),
            'segments': segs,
        }
    except ImportError:
        return {'success': False, 'error': 'faster-whisper not installed'}
    except Exception as e:
        logger.exception("transcription failed")
        return {'success': False, 'error': str(e)}


def main():
    # Eagerly preload the default model so the first request is fast. Failures
    # are non-fatal (the worker retries per job).
    try:
        _load(WHISPER_MODEL)
        logger.info("worker preloaded model: %s", WHISPER_MODEL)
    except Exception as e:
        logger.warning("worker preload failed: %s", e)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except Exception:
            continue
        job_id = job.get('id')
        try:
            result = _transcribe(job.get('audio_path'), job.get('language'), job.get('model_name'))
        except Exception as e:
            result = {'success': False, 'error': str(e)}
        try:
            sys.stdout.write(json.dumps({'id': job_id, 'result': result}) + '\n')
            sys.stdout.flush()
        except BrokenPipeError:
            break


if __name__ == '__main__':
    main()
