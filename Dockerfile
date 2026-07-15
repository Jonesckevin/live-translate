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
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status==200 else 1)" || exit 1
CMD ["/app/entrypoint.sh"]
