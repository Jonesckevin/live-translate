#!/bin/sh
set -eu

# Generate SECRET_KEY and SECRETS if not provided
if [ -z "${SECRET_KEY:-}" ]; then
  export SECRET_KEY=$(openssl rand -hex 32)
  echo "Generated random SECRET_KEY"
fi

if [ -z "${SECRETS:-}" ]; then
  export SECRETS=$(openssl rand -hex 32)
  echo "Generated random SECRETS"
fi

mkdir -p /data/logs /data/sessions /data/glossaries /data/output /data/uploaded \
  /data/session-icons /data/cache/huggingface /data/.local 2>/dev/null || true

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

  if ! kill -0 $LIBRE_PID 2>/dev/null; then
    echo "WARNING: LibreTranslate failed to start"
    echo "Note: Using LLM providers as translation backend via automatic fallback"
  fi
fi

exec python app.py
