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

## Speech-to-text

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_ENABLED` | `false` | Enable server-side Whisper STT. |
| `WHISPER_MODEL` | `base` | `tiny` / `base` / `small` / `medium` / `large-v3`. |
| `WHISPER_USE_GPU` | `false` | Use GPU if available. |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(ephemeral)* | Flask signing key. Set a stable random value in production. |
| `SECRETS` | *(ephemeral)* | Key for signing share/session tokens **and encrypting stored API keys** (Fernet). `openssl rand -hex 32`. Keep it stable — if it changes, previously-encrypted keys become unreadable. |
| `REQUIRE_SECRETS` | `false` | Refuse to start without `SECRETS` (also implied by `FLASK_ENV=production`). |
| `CORS_ALLOWED_ORIGINS` | *(empty = same-origin)* | Empty allows any host the app is served from (localhost, LAN IP, your domain) and denies cross-origin. Provide a comma-separated list to allow extra cross-origins, or `*` (insecure). |
| `TRUST_PROXY` | `false` | Set `true` behind a trusted HTTPS reverse proxy to honor `X-Forwarded-Proto/Host` (needed for same-origin over HTTPS on a domain). |
| `MAX_UPLOAD_MB` | `25` | Max request/upload size in MB (returns 413 beyond). |
| `LOGS_ACCESS_TOKEN` | *(unset)* | If unset, `/api/logs` is disabled (404). If set, requires a matching bearer token. |
| `CONTENT_SECURITY_POLICY` | *(built-in)* | Override the CSP header. |

## Authentication (optional, Phase 2+)

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOW_AUTH` | `false` | Master switch for accounts. When off, the app is fully anonymous and `/auth/*` returns 404. |
| `ALLOW_USER_REGISTRATION` | `false` | Enable `POST /auth/register`. First account becomes admin. |
| `JWT_TTL_SECONDS` | `86400` | Access-token lifetime. |
| `LOGIN_RATE_MAX` | `5` | Max failed logins per window per IP. |
| `LOGIN_RATE_WINDOW` | `900` | Rate-limit window (seconds). |
| `SHARE_CODE_TTL` | `86400` | Session share-code lifetime (seconds). |
| `USERS_DB` | `/data/users.db` | SQLite path for accounts. |

## Analytics (optional, Phase 5)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_ANALYTICS_KEY` | *(empty)* | GA measurement ID. Empty = disabled (offline-safe). |
| `ENABLE_SERVER_ANALYTICS` | `false` | Track aggregate counters (no PII), viewable in the admin panel. |

## Admin runtime settings

Managed from the admin panel (`/admin`) and stored in `ADMIN_SETTINGS_FILE`
(`/data/admin_settings.json`): `allow_public_sessions`, `allow_session_sharing`,
`enable_analytics`, `max_sessions_per_user`, `cache_retention_days`.

## LLM provider keys

Set any of: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`DEEPSEEK_API_KEY`, `COHERE_API_KEY`, `GROQ_API_KEY`, `GROK_API_KEY`,
`MISTRAL_API_KEY`, `PERPLEXITY_API_KEY`. Provide via environment or a secrets
manager — never commit them.

## Paths

| Variable | Default |
|----------|---------|
| `LOG_DIR` | `/data/logs` |
| `SESSION_DIR` | `/data/sessions` |
| `SESSION_ICON_DIR` | `/data/session-icons` |
| `GLOSSARY_DIR` | `/data/glossaries` |
| `HF_HOME` | `/data/cache/huggingface` |
