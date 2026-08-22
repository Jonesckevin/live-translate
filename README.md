# Live Translate

This project started because the online alternatives that were claimed to be very good and helpful, also cost a lot. This is an attempt at making a free version.

A self-hosted real-time translation web application with speech-to-text, virtual keyboards, and dual-panel conversation mode. Supports LibreTranslate (offline) and 10+ LLM providers as long as you bring your own Key (BYOK). The key can be set at the user or server level.

![Live Translate Screenshot](example.png)

## Features

- **Text Translation** – Default uses LibreTranslate Framework to Translate between 37+ languages with auto-detection
- **Dual Engine** – LibreTranslate (Argos, self-hosted, offline) + Optional LLM providers (OpenAI, Anthropic, Google Gemini, Meta AI, Ollama, LM Studio, DeepSeek, Cohere, Groq, Grok, Mistral, Perplexity)
- **Live Conversation Mode** – Dual-panel real-time translation with per-panel language and microphone selection
- **Speech-to-Text** – Web Speech API (browser-native) + optional Whisper (server-side via faster-whisper) + optional AI provider STT (for supported providers/models)
- **Custom Glossaries** – Create term glossaries for consistent translations
- **Session Management** – Auto-save conversation history with export
- **Docker Deployment** – Single `docker compose up`

## Quick Start

### Portainer

1. Link to Github repository: `github.com/4n6post/live-translate`
2. Load .env file into Portainer stack environment variables
3. Modify Any Variable you want to change (optional)
4. Deploy the stack and open **http://localhost:9015** in your browser.

### Local Build with Docker Compose

```bash
git clone https://github.com/4n6post/live-translate.git
cd live-translate

# Start the application with automatic image building
docker compose up -d --build
```

The default Whisper model (`tiny`) ships in `data/whisper-model` so it is usable
offline. Larger models (`base`, `small`, `medium`, `large-v3`) are downloaded at
runtime on first use and cached in `/data/whisper-model`, so they persist across
restarts but require internet to fetch the first time.

Embedded LibreTranslate downloads Argos language models into the container's
`/data/.local` cache (the app runs as non-root with `HOME=/data`), so they are
persisted under `./data` and reused across container rebuilds/restarts.

Open **http://localhost:9015** in your browser.

```bash
docker run --name live-translate --restart unless-stopped -p 9015:5000 -v ./data:/data \
	-e ALLOW_AUTH=true \
	-e REQUIRE_AUTH=true \
	-e SOCKETIO_CORS_CREDENTIALS=true \
	-e ALLOW_USER_REGISTRATION=true \
	-e ALLOW_GUEST_LOGIN=true \
	-e WHISPER_ENABLED=true \
	-e WHISPER_MODEL=tiny \
	-e ENABLE_SERVER_ANALYTICS=false \
	-e SECRET_KEY='$(openssl rand -hex 32)' \
	-e SECRETS='$(openssl rand -hex 32)' \
	-e REQUIRE_SECRETS=true \
	-e LOGS_ACCESS_TOKEN= \
	-e ALLOW_CLIENT_API_KEYS=true \
    jonesckevin/live-translate:latest
```

Open **http://localhost:9015** in your browser.

**Alternatively, build locally:**

```bash
git clone https://github.com/4n6post/live-translate.git
cd live-translate
docker build -t live-translate:latest .

# Then run with your local image
docker run -d \
  --name live-translate \
  -p 9015:5000 \
  -v $(pwd)/data:/data \
  -e REQUIRE_AUTH=false \
  -e OFFLINE_MODE=auto \
  live-translate:latest
```
