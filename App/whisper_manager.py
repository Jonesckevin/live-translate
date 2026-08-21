"""
Whisper Manager - Optional server-side speech-to-text using faster-whisper.

The heavy model + inference run in a dedicated worker OS process
(whisper_worker.py) so CPU-bound transcription never blocks the main server's
gevent event loop. This module is a thin client that spawns the worker and
exchanges JSON-line jobs over stdin/stdout.
"""

import os
import sys
import json
import logging
import tempfile
import threading
import subprocess

logger = logging.getLogger(__name__)

WHISPER_ENABLED = os.environ.get('WHISPER_ENABLED', 'true').lower() == 'true'
WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'tiny')
WHISPER_USE_GPU = os.environ.get('WHISPER_USE_GPU', 'false').lower() == 'true'
WHISPER_MODEL_DIR = os.environ.get('WHISPER_MODEL_DIR', '/data/whisper-model')

# 3 minutes per transcription; generous upper bound for long audio on CPU.
_TRANSCRIBE_TIMEOUT = 180

_bridge = None
_bridge_lock = threading.Lock()


class _WhisperWorkerBridge:
    """Spawns and supervises the worker subprocess and dispatches results."""

    def __init__(self):
        self._proc = None
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._next_id = 0

    def _spawn(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'whisper_worker.py')
        logger.info("Starting Whisper worker process: %s", script)
        self._proc = subprocess.Popen(
            [sys.executable, script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        # Real OS thread (not a greenlet) that blocks on the worker's stdout
        # without ever blocking the gevent event loop.
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        try:
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                job_id = msg.get('id')
                with self._pending_lock:
                    entry = self._pending.get(job_id)
                    if entry is not None:
                        entry['result'] = msg.get('result')
                        entry['event'].set()
        finally:
            # Worker exited: fail any still-pending jobs (waiters will pop them).
            with self._pending_lock:
                pending = list(self._pending.values())
            for entry in pending:
                entry['result'] = {'success': False, 'error': 'Whisper worker stopped'}
                entry['event'].set()

    def transcribe(self, audio_path, language, model_name):
        self._spawn()
        with self._pending_lock:
            job_id = self._next_id
            self._next_id += 1
            event = threading.Event()
            self._pending[job_id] = {'event': event, 'result': None}
        job = json.dumps({
            'id': job_id,
            'audio_path': audio_path,
            'language': language,
            'model_name': model_name,
        })
        self._proc.stdin.write(job + '\n')
        self._proc.stdin.flush()
        # threading.Event.wait() is greenlet-aware under gevent, so this yields
        # to the event loop instead of blocking it.
        event.wait(timeout=_TRANSCRIBE_TIMEOUT)
        with self._pending_lock:
            entry = self._pending.pop(job_id, None)
        if entry is None or entry['result'] is None:
            return {'success': False, 'error': 'Whisper transcription timed out'}
        return entry['result']

    def ensure_started(self):
        self._spawn()


def _get_bridge():
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = _WhisperWorkerBridge()
        return _bridge


def get_whisper_model(force_cpu=False, force_reload=False, model_name=None):
    """Ensure the Whisper worker (which owns the model) is running.

    The model itself lives in the worker process; this just verifies the worker
    is up so background preloading does not block the main process.
    """
    if WHISPER_ENABLED:
        _get_bridge().ensure_started()
    return True


def transcribe(audio_data, language=None, model_name=None):
    """Transcribe audio bytes in the isolated worker process.

    audio_data: bytes of an audio file (wav, mp3, webm, etc.)
    language: optional language code hint.
    Returns: dict with success, text, language, segments.
    """
    if not WHISPER_ENABLED:
        return {'success': False, 'error': 'Whisper is not enabled. Set WHISPER_ENABLED=true.'}
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
        return _get_bridge().transcribe(tmp_path, language, model_name)
    except Exception as e:
        logger.exception("Whisper transcription failed: %s", e)
        return {'success': False, 'error': str(e)}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def get_status():
    """Return Whisper availability/status (model is loaded in the worker)."""
    status = {
        'enabled': WHISPER_ENABLED,
        'model': WHISPER_MODEL,
        'use_gpu': WHISPER_USE_GPU,
        'model_dir': WHISPER_MODEL_DIR,
        'loaded': WHISPER_ENABLED,  # model loads in the worker process
        'runtime_device': 'cuda' if WHISPER_USE_GPU else 'cpu',
        'runtime_compute_type': 'float16' if WHISPER_USE_GPU else 'int8',
        'gpu_fallback_used': False,
        'process_isolated': True,
    }
    if WHISPER_ENABLED:
        try:
            from faster_whisper import WhisperModel
            status['installed'] = True
        except ImportError:
            status['installed'] = False
    return status
