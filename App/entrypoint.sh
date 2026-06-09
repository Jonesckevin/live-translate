#!/bin/sh
set -eu

WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/data/whisper-model}"
WHISPER_MODEL_SEED_DIR="${WHISPER_MODEL_SEED_DIR:-/opt/whisper-model-seed}"

if [ -d "$WHISPER_MODEL_SEED_DIR" ]; then
  mkdir -p "$WHISPER_MODEL_DIR"
  if [ -z "$(ls -A "$WHISPER_MODEL_DIR" 2>/dev/null)" ]; then
    echo "Seeding Whisper models into $WHISPER_MODEL_DIR"
    cp -R "$WHISPER_MODEL_SEED_DIR"/* "$WHISPER_MODEL_DIR"/ 2>/dev/null || true
  fi
fi

if [ "${LIBRETRANSLATE_LOCAL_ENABLED:-true}" = "true" ]; then
  echo "Starting embedded LibreTranslate at 127.0.0.1:5001"
  export HF_HOME=/data/cache/huggingface
  
  /opt/libretranslate-venv/bin/libretranslate \
    --host 127.0.0.1 \
    --port 5001 \
    --disable-web-ui \
    2>&1 | tee /tmp/libretranslate.log &
  LIBRE_PID=$!
  echo "LibreTranslate started (PID: $LIBRE_PID)"
  sleep 5
  
  # Check if it's still running
  if ! kill -0 $LIBRE_PID 2>/dev/null; then
    echo "WARNING: LibreTranslate failed to start"
    echo "Note: Using LLM providers as translation backend via automatic fallback"
  fi
fi

exec python app.py
