# Deployment Guide

Production checklist for self-hosting Live Translate. See
[CONFIGURATION.md](CONFIGURATION.md) for every environment variable.

## 1. Prerequisites

- Docker + Docker Compose
- A reverse proxy terminating **HTTPS** (Caddy, Nginx, Traefik, …)

## 2. Secrets

```bash
cp .env.example .env
# Generate stable secrets:
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "SECRETS=$(openssl rand -hex 32)" >> .env
```

If you leave `SECRET_KEY`/`SECRETS` unset, the container entrypoint generates
them and persists them to `/data/.secrets` (reused on restart) — so a restart no
longer invalidates encrypted user API keys or login sessions. For production you
should still set them explicitly, and ensure `/data/.secrets` is included in your
backups.

Provide LLM provider keys via the environment or a secrets manager. **Never**
commit `.env`. If a secret is ever committed/pushed, rotate it at the provider.

## 3. Recommended production settings

```env
REQUIRE_SECRETS=true
CORS_ALLOWED_ORIGINS=https://translate.example.com
# Auth (multi-user):
ALLOW_AUTH=true
REQUIRE_AUTH=true                 # force login; anonymous API access rejected (401)
ALLOW_GUEST_LOGIN=false           # enable for anonymous guest access
ALLOW_USER_REGISTRATION=true      # first account becomes admin; disable after bootstrap
# Logs are disabled by default; to enable, set a token:
# LOGS_ACCESS_TOKEN=<random>
```

## 4. Build & run

```bash
docker compose up -d --build
docker compose ps          # expect: healthy
docker compose logs -f     # verify security validation + no tracebacks
```

## 5. Bootstrap the admin

1. Browse to your domain, click **Register** in the top-right widget (or `POST
   /auth/register`). The **first** account is granted admin.
2. Consider setting `ALLOW_USER_REGISTRATION=false` afterwards if you don't want
   open sign-ups, then recreate: `docker compose up -d`.
3. Manage users, sessions, and server settings at `/admin`.

## 6. Reverse proxy (example: forward to container port 9015)

Terminate TLS at the proxy and forward WebSocket upgrades for `/socket.io/`.
Set `CORS_ALLOWED_ORIGINS` to the public origin.

## 7. Backups

Persisted state lives in `./data` (sessions, glossaries, `users.db`,
`admin_settings.json`, Whisper/LibreTranslate model caches). Back up `./data`.

## 8. Verify

```bash
pip install -r App/requirements-dev.txt
BASE_URL=https://translate.example.com python -m pytest tests -v
```

## Operational notes

- The container starts as root so the entrypoint can repair ownership of the
  bind-mounted `/data` volume, then drops to the non-root `appuser` (uid 1000)
  before launching the app. For a fresh clone on Linux, ensure the host `./data`
  directory is writable or owned by uid 1000.
- `SECRET_KEY`/`SECRETS` (and the Fernet-encrypted user API keys they protect)
  are tied to `/data/.secrets` — back it up together with `./data`.
- A `HEALTHCHECK` hits `/health`; orchestrators can auto-restart on failure.
- Offline/air-gapped: keep cloud LLM keys and `GOOGLE_ANALYTICS_KEY` unset;
  translation uses LibreTranslate and STT uses local Whisper.
