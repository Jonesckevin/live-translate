# Contributing to Live Translate

Thanks for your interest in improving Live Translate!

## Getting started

```bash
git clone https://github.com/jonesckevin/live-translate.git
cd live-translate
cp .env.example .env          # then edit as needed
docker compose up -d --build
```

The app is served at http://localhost:9015.

## Development workflow

- Keep changes focused and backward compatible. New behavior should be gated
  behind an environment variable with a safe default.
- Preserve the anonymous/offline experience: authentication and multi-tenant
  features are **opt-in** (`ALLOW_AUTH`), disabled by default.
- Follow the existing code style (standard library first, small focused modules).

## Testing

Integration tests live in `tests/` and run against a live instance:

```bash
pip install -r App/requirements-dev.txt
BASE_URL=http://localhost:9015 python -m pytest tests -v
```

For auth-dependent tests, start the server with a fresh database and
`ALLOW_AUTH=true ALLOW_USER_REGISTRATION=true`.

## Pull requests

1. Create a feature branch.
2. Add or update tests for your change.
3. Ensure `pytest` passes and the container builds and starts cleanly.
4. Describe the change and any new configuration in the PR.

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
