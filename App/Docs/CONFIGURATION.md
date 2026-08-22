# Configuration Reference

All configuration is via environment variables (see `.env.example`). Values
shown are defaults. Booleans accept `true`/`false`.

## Core / translation

| Variable | Default | Description |
|----------|---------|-------------|
| `LIBRETRANSLATE_LOCAL_ENABLED` | `true` | Run embedded LibreTranslate in-container. |
| `LIBRETRANSLATE_LOCAL_URL` | `http://127.0.0.1:5001` | Embedded LibreTranslate URL. |
| `LIBRETRANSLATE_SERVER_URL` | `http://libretranslate:5000` | External LibreTranslate URL (when local disabled). |
| `OFFLINE_MODE` | `auto` | `auto` / `true` / `false`. |
| `OLLAMA_HOST` / `LMSTUDIO_HOST` | host.docker.internal | Local LLM servers. |
| `SESSION_RETENTION_DAYS` | `30` | Auto-purge session files older than this many days. |

## Speech-to-text

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_ENABLED` | `true` | Enable server-side Whisper STT. |
| `WHISPER_MODEL` | `tiny` | `tiny` / `base` / `small` / `medium` / `large-v3`. |
| `WHISPER_USE_GPU` | `false` | Use GPU if available. |
| `WHISPER_PRELOAD_ON_STARTUP` | `true` | Pre-load the model at startup (faster first use; delays readiness). |
| `WHISPER_MODEL_DIR` | `/data/whisper-model` | Cache directory for downloaded Whisper models. |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(persisted)* | Flask signing key. Set a stable random value in production. If unset, the container entrypoint generates one, persists it to `/data/.secrets`, and reuses it on restart. |
| `SECRETS` | *(persisted)* | Key for signing share/session tokens **and encrypting stored API keys** (Fernet). `openssl rand -hex 32`. Keep it stable — if it changes, previously-encrypted keys become unreadable. If unset, the entrypoint persists it to `/data/.secrets` and reuses it on restart, so restarts no longer invalidate stored keys. |
| `REQUIRE_SECRETS` | `true` | When `true`, the entrypoint logs a warning if `SECRET_KEY`/`SECRETS` were auto-generated; set them explicitly for production. |
| `CORS_ALLOWED_ORIGINS` | *(empty = same-origin)* | Empty allows any host the app is served from (localhost, LAN IP, your domain) and denies cross-origin. Provide a comma-separated list to allow extra cross-origins, or `*` (insecure). |
| `TRUST_PROXY` | `false` | Set `true` behind a trusted HTTPS reverse proxy to honor `X-Forwarded-Proto/Host` (needed for same-origin over HTTPS on a domain). |
| `MAX_UPLOAD_MB` | `25` | Max request/upload size in MB (returns 413 beyond). |
| `LOGS_ACCESS_TOKEN` | *(unset)* | If unset, `/api/logs` is disabled (404). If set, requires a matching bearer token. |
| `CONTENT_SECURITY_POLICY` | *(built-in)* | Override the CSP header. |

## WebSocket (Socket.IO)

| Variable | Default | Description |
|----------|---------|-------------|
| `SOCKETIO_CORS_CREDENTIALS` | `true` | Allow cookies with Socket.IO CORS requests. Keep disabled with a wildcard origin. |
| `SOCKETIO_PING_TIMEOUT` | `60` | Socket.IO ping timeout (seconds). |
| `SOCKETIO_PING_INTERVAL` | `25` | Socket.IO ping interval (seconds). |

## Authentication (optional, Phase 2+)

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOW_AUTH` | `true` | Master switch for accounts. When off, the app is fully anonymous and `/auth/*` returns 404. |
| `REQUIRE_AUTH` | `true` | When `true` (and `ALLOW_AUTH`), anonymous access to functional API routes (translation, sessions, glossaries, settings) is rejected with 401. Public/info/auth endpoints (`/health`, `/docs`, `/static/`, `/join/`, `/auth/*`, `/api/config`, `/api/languages`, `/api/libretranslate/status`, `/api/offline-status`) remain reachable. Guest logins still work when `ALLOW_GUEST_LOGIN=true`. |
| `ALLOW_USER_REGISTRATION` | `true` | Enable `POST /auth/register`. First account becomes admin. |
| `ALLOW_GUEST_LOGIN` | `true` | Allow anonymous guest logins (issues a short-lived token). |
| `GUEST_TTL_HOURS` | `24` | Guest session lifetime (hours). |
| `JWT_TTL_SECONDS` | `86400` | Access-token lifetime. |
| `LOGIN_RATE_MAX` | `5` | Max failed logins per window per IP. |
| `LOGIN_RATE_WINDOW` | `900` | Rate-limit window (seconds). |
| `REGISTER_RATE_MAX` | `3` | Max registrations per window per IP. |
| `REGISTER_RATE_WINDOW` | `3600` | Registration rate-limit window (seconds). |
| `SHARE_CODE_TTL` | `86400` | Session share-code lifetime (seconds). |
| `USERS_DB` | `/data/users.db` | SQLite path for accounts. |
| `ALLOW_CLIENT_API_KEYS` | `true` | Allow clients to supply their own provider API keys via request headers. |

## Analytics (optional, Phase 5)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_ANALYTICS_KEY` | *(empty)* | GA measurement ID. Empty = disabled (offline-safe). |
| `ENABLE_SERVER_ANALYTICS` | `true` (Compose) / `false` (code default) | Track aggregate counters (no PII), viewable in the admin panel. When off, counter collection is a no-op. |

## Admin runtime settings

Managed from the admin panel (`/admin`) and stored in `ADMIN_SETTINGS_FILE`
(`/data/admin_settings.json`): `allow_public_sessions`, `allow_session_sharing`,
`enable_analytics`, `max_sessions_per_user`, `cache_retention_days`.

## LLM provider keys

Set any of: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` (Google Gemini),
`DEEPSEEK_API_KEY`, `COHERE_API_KEY`, `GROQ_API_KEY`, `GROK_API_KEY`,
`MISTRAL_API_KEY`, `PERPLEXITY_API_KEY`. Provide via environment or a secrets
manager — never commit them. (Note: the Google Gemini provider reads `GOOGLE_API_KEY`.)

## Paths

| Variable | Default |
|----------|---------|
| `LOG_DIR` | `/data/logs` |
| `SESSION_DIR` | `/data/sessions` |
| `SESSION_ICON_DIR` | `/data/session-icons` |
| `GLOSSARY_DIR` | `/data/glossaries` |
| `HF_HOME` | `/data/cache/huggingface` |
| `RECORDING_DIR` | `/data/output` |
| `SETTINGS_FILE` | `/data/settings.json` |
