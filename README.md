# Live Translate

This project started because the online alternatives that were claimed to be very good and helpful, also cost a lot. This is an attempt at making a free version.

A self-hosted real-time translation web application with speech-to-text, virtual keyboards, and dual-panel conversation mode. Supports LibreTranslate (offline) and 10+ LLM providers as long as you bring your own Key (BYOK). The key can be set at the user or server level.

![Live Translate Screenshot](example.png)

## Features

- **Text Translation** – Default uses LibreTranslate Framework to Translate between 37+ languages with auto-detection
- **Dual Engine** – LibreTranslate (Argos, self-hosted, offline) + Optional LLM providers (OpenAI, Anthropic, Gemini, Ollama, LM Studio, DeepSeek, Cohere, Groq, Grok, Mistral, Perplexity)
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

During image build, Whisper models `tiny`, `base`, `small`, `medium`, and `large-v3` are pre-downloaded into an internal seed cache, then copied into `/data/whisper-model` on first container start. This avoids runtime re-downloads and persists models across restarts/rebuilds.

Embedded LibreTranslate language package downloads are also persisted by mounting `./data/cache/libretranslate-local` to `/root/.local`, so Argos language models are reused across container rebuilds/restarts.

Open **http://localhost:9015** in your browser.
