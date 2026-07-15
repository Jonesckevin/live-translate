# Privacy Policy

_Last updated: 2026-07-13_

Live Translate is self-hosted software. The operator who deploys it is the data controller. This template describes typical data handling; operators should adapt it to their deployment and jurisdiction.

## Data the application processes

- **Translation input/output**: text and (optionally) audio you submit fortranslation or transcription. This is processed to provide the service and maybe persisted in session transcripts if you save a session.
- **Account data** (only when authentication is enabled): username, an optional email, and a bcrypt password hash. Passwords are never stored in plaintext.
- **Operational logs**: request metadata (timestamps, IP address, request IDs) used for debugging and security. Logs may contain translated text.

## Third-party processors

- **LLM / STT providers** (optional, opt-in): if you choose a cloud provider,your input text/audio is sent to that provider under their terms. Offline mode(LibreTranslate + local Whisper) keeps processing on your server.
- **Google Analytics** (optional, off by default): enabled only if the operator sets `GOOGLE_ANALYTICS_KEY`. When enabled, aggregate page-view analytics arecollected with IP anonymization enabled; user content is never sent to analytics.

## Data storage

- **No HTTP cookies**: This application does not use HTTP cookies.
- **Browser local storage** (persistent): User preferences and settings (language choice, speech engine, API key priority) are stored locally on your device and never sent to the server.
- **Session storage** (temporary): Settings and session data are stored during your browsing session and cleared when the browser closes.
- **Authentication tokens**: JWT tokens are stored in your browser for login state and are cleared on logout.

## Data retention

- Session transcripts persist until deleted or until the configured retention window elapses (`SESSION_RETENTION_DAYS`).
- Accounts persist until deleted by the user or an administrator.

## Your rights

Depending on your jurisdiction you may have rights to access, correct, export, or delete your data. Contact the operator of the instance you use to exercise them.

## Offline / air-gapped deployments

With cloud providers and analytics disabled, Live Translate processes data entirely on the operator's infrastructure and makes no external calls.
