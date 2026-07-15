#!/bin/sh
set -eu

APP_USER="${APP_USER:-appuser}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/logs /data/sessions /data/glossaries /data/output /data/uploaded \
    /data/session-icons /data/cache/huggingface /data/.local 2>/dev/null || true
  chown -R "$APP_USER":"$APP_USER" /data 2>/dev/null || true

  echo "Dropping privileges to '$APP_USER'"
  exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups "$0" "$@"
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

  if ! kill -0 $LIBRE_PID 2>/dev/null; then
    echo "WARNING: LibreTranslate failed to start"
    echo "Note: Using LLM providers as translation backend via automatic fallback"
  fi
fi

exec python app.py
