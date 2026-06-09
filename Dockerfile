ARG PYTHON_BASE=python:3.11-slim
FROM ${PYTHON_BASE}

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY App/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install LibreTranslate in an isolated venv to avoid Flask version conflicts
RUN python -m venv /opt/libretranslate-venv \
    && /opt/libretranslate-venv/bin/pip install --no-cache-dir libretranslate==1.9.6

# Patch LibreTranslate's IndexError bug where languages list is empty  
RUN LIBRE_SITE_PACKAGES=$(/opt/libretranslate-venv/bin/python -c "import site; print(site.getsitepackages()[0])") \
    && sed -i "s/language_target_fallback = languages\[1\] if len(languages) >= 2 else languages\[0\]/language_target_fallback = languages[1] if len(languages) >= 2 else (languages[0] if len(languages) >= 1 else 'en')/g" \
    "$LIBRE_SITE_PACKAGES/libretranslate/app.py"

# Pre-download all Whisper models into an image seed directory.
# On first container start, entrypoint copies these into /data/whisper-model.
ENV WHISPER_MODEL_SEED_DIR=/opt/whisper-model-seed
ENV WHISPER_MODEL_DIR=/data/whisper-model
RUN python -c "\
from faster_whisper import WhisperModel; \
import os; \
os.makedirs('${WHISPER_MODEL_SEED_DIR}', exist_ok=True); \
models = ['tiny', 'base', 'small', 'medium', 'large-v3']; \
[print(f'Downloading whisper model: {m}') or WhisperModel(m, device='cpu', compute_type='int8', download_root='${WHISPER_MODEL_SEED_DIR}') for m in models]; \
print('All Whisper models downloaded successfully')"

# Copy application code
COPY App/ .

# Create data directories
RUN mkdir -p /data/sessions /data/glossaries /data/logs /data/output /data/uploaded /data/whisper-model

EXPOSE 5000

ENV PYTHONUNBUFFERED=1
ENV LIBRETRANSLATE_LOCAL_ENABLED=true
ENV LIBRETRANSLATE_LOCAL_URL=http://127.0.0.1:5001
ENV LIBRETRANSLATE_SERVER_URL=http://libretranslate:5000
ENV SESSION_ICON_DIR=/data/session-icons

RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
