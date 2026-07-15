# Security Policy

## Supported Versions

Security fixes are applied to the latest `main` branch and the most recent
published container image.

## Reporting a Vulnerability

Please report suspected vulnerabilities **privately** — do not open a public
issue for security problems.

1. Use GitHub's **"Report a vulnerability"** (Security → Advisories) on the
   repository, or contact the maintainer directly.
2. Include a description, reproduction steps, affected version/commit, and
   impact assessment.
3. Allow reasonable time for a fix before any public disclosure.

## Handling of Secrets

- Never commit real credentials. `.env` is git-ignored; use `.env.example` as a
  template and provide secrets via environment variables or a secrets manager.
- If a credential is ever committed or pushed, treat it as **compromised** and
  rotate it at the provider immediately — removing it from files does not undo
  prior exposure (git history and any pushed image retain it).

## Hardening Checklist (operators)

- Set a stable `SECRET_KEY` and a `SECRETS` value (`openssl rand -hex 32`).
- Pin `CORS_ALLOWED_ORIGINS` to your exact origin(s); avoid `*` in production.
- Keep `/api/logs` disabled or protect it with `LOGS_ACCESS_TOKEN`.
- Run behind HTTPS (terminate TLS at a reverse proxy).
- Enable authentication (`ALLOW_AUTH=true`) for multi-user deployments and set
  `REQUIRE_SECRETS=true`.
- Keep the container non-root (default) and the base image up to date.
