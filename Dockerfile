ARG PYTHON_BASE=python:3.12-slim

FROM ${PYTHON_BASE} AS builder
WORKDIR /tmp/build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY App/requirements.txt .
COPY App/requirements-auth.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefix /install -r requirements.txt && \
    pip install --no-cache-dir --prefix /install -r requirements-auth.txt
RUN python -m venv /opt/libretranslate-venv \
    && /opt/libretranslate-venv/bin/pip install --no-cache-dir libretranslate==1.9.6
RUN LIBRE_SITE_PACKAGES=$(/opt/libretranslate-venv/bin/python -c "import site; print(site.getsitepackages()[0])") \
    && sed -i "s/language_target_fallback = languages\[1\] if len(languages) >= 2 else languages\[0\]/language_target_fallback = languages[1] if len(languages) >= 2 else (languages[0] if len(languages) >= 1 else 'en')/g" \
    "$LIBRE_SITE_PACKAGES/libretranslate/app.py"
FROM ${PYTHON_BASE}
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY --from=builder /opt/libretranslate-venv /opt/libretranslate-venv
COPY App/ .
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/appuser appuser \
    && mkdir -p /data/sessions /data/glossaries /data/logs /data/output /data/uploaded \
        /data/whisper-model /data/session-icons /data/cache/huggingface \
    && chmod +x /app/entrypoint.sh \
    && chown -R appuser:appuser /app /data /home/appuser
EXPOSE 5000
ENV PYTHONUNBUFFERED=1
ENV HOME=/data
ENV HF_HOME=/data/cache/huggingface
ENV LIBRETRANSLATE_LOCAL_ENABLED=true
ENV LIBRETRANSLATE_LOCAL_URL=http://127.0.0.1:5001
ENV LIBRETRANSLATE_SERVER_URL=http://libretranslate:5000
ENV SESSION_ICON_DIR=/data/session-icons
ENV DATA_DIR=./data
ENV LOG_DIR=/data/logs
ENV MAX_UPLOAD_MB=25
ENV OFFLINE_MODE=auto
ENV ALLOW_USER_REGISTRATION=true
ENV ALLOW_GUEST_LOGIN=true
ENV WHISPER_ENABLED=true
ENV WHISPER_MODEL=tiny
ENV WHISPER_USE_GPU=false
ENV WHISPER_MODEL_DIR=/data/whisper-model
ENV WHISPER_PRELOAD_ON_STARTUP=true
ENV JWT_TTL_SECONDS=86400
ENV GUEST_TTL_HOURS=24
ENV LOGIN_RATE_MAX=5
ENV LOGIN_RATE_WINDOW=900
ENV REGISTER_RATE_MAX=3
ENV REGISTER_RATE_WINDOW=3600
ENV SHARE_CODE_TTL=86400
ENV LOG_SESSIONS=false
ENV LOG_TRANSLATIONS=false
ENV ENABLE_SERVER_ANALYTICS=false
ENV REQUIRE_SECRETS=true
ENV ALLOW_CLIENT_API_KEYS=true
ENV STARTUP_FAIL_ON_CHECKS=false
ENV TRUST_PROXY=false
ENV SOCKETIO_ASYNC_HANDLERS=true
ENV SOCKETIO_PING_TIMEOUT=60
ENV SOCKETIO_PING_INTERVAL=25
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status==200 else 1)" || exit 1
CMD ["/app/entrypoint.sh"]
