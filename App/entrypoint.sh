#!/bin/sh
set -eu

APP_UID=1000
APP_GID=1000
SECRETS_FILE="/data/.secrets"

mkdir -p /data/logs /data/sessions /data/glossaries /data/output /data/uploaded \
  /data/session-icons /data/cache/huggingface /data/.local 2>/dev/null || true

if [ "$(id -u)" = "0" ]; then
  chown -R "${APP_UID}:${APP_GID}" /data /app 2>/dev/null || true
fi

# Initialize the persistent secrets file on first run. Keeping secrets in /data
# means encrypted user API keys, JWTs, and share codes survive container restarts.
if [ ! -f "$SECRETS_FILE" ]; then
  : > "$SECRETS_FILE"
  chmod 600 "$SECRETS_FILE"
  if [ "$(id -u)" = "0" ]; then
    chown "${APP_UID}:${APP_GID}" "$SECRETS_FILE"
  fi
fi

load_or_create_secret() {
  VAR_NAME="$1"
  CURRENT="$(eval "printf '%s' \"\${$VAR_NAME:-}\"")"
  if [ -n "$CURRENT" ]; then
    return
  fi
  SAVED="$(awk -F= -v v="$VAR_NAME" '$1==v {sub(/^[^=]*=/,""); print}' "$SECRETS_FILE" 2>/dev/null | head -n1)"
  if [ -n "$SAVED" ]; then
    export "$VAR_NAME=$SAVED"
    echo "Reusing persisted $VAR_NAME from $SECRETS_FILE"
    return
  fi
  GENERATED="$(openssl rand -hex 32)"
  export "$VAR_NAME=$GENERATED"
  echo "$VAR_NAME=$GENERATED" >> "$SECRETS_FILE"
  if [ "${REQUIRE_SECRETS:-true}" = "true" ]; then
    echo "WARNING: $VAR_NAME was not configured; generated and persisted to $SECRETS_FILE. For production, set it explicitly in your environment."
  fi
}

load_or_create_secret SECRET_KEY
load_or_create_secret SECRETS

# Helper to run a command as the non-root app user (no-op when already non-root).
run_as_app() {
  if [ "$(id -u)" = "0" ]; then
    setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$@"
  else
    exec "$@"
  fi
}

if [ "${LIBRETRANSLATE_LOCAL_ENABLED:-true}" = "true" ]; then
  echo "Starting embedded LibreTranslate at 127.0.0.1:5001"
  export HF_HOME=/data/cache/huggingface
  # Tee LibreTranslate's output to a persisted log AND the container stdout so
  # first-run Argos model downloads are visible in `docker compose logs`.
  run_as_app /opt/libretranslate-venv/bin/libretranslate \
    --host 127.0.0.1 \
    --port 5001 \
    --disable-web-ui \
    2>&1 | tee /data/logs/libretranslate.log &
  LIBRE_PID=$!
  echo "LibreTranslate started (PID: $LIBRE_PID); logs: /data/logs/libretranslate.log"
  sleep 5
  if ! kill -0 "$LIBRE_PID" 2>/dev/null; then
    echo "WARNING: LibreTranslate failed to start. Last log lines:"
    tail -n 20 /data/logs/libretranslate.log 2>/dev/null || true
    echo "Note: Using LLM providers as translation backend via automatic fallback"
  fi
fi

if [ "$(id -u)" = "0" ]; then
  exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups python app.py
else
  exec python app.py
fi

