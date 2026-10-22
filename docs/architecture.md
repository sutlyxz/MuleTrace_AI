# Architecture

```text
Browser
  │
  ▼
app/frontend/index.html
  ├── assets/css/ ── shared styles and case-manager styles
  ├── assets/js/  ── application, cases, API, config, i18n, demo data
  └── sw.js      ── caches local assets; stays at root for scope

app/data/*.csv
  │
  ▼
app/backend/engine.py
  │
  ├── app/backend/core/risk_rules.py
  ├── app/backend/core/tracing.py
  └── app/backend/services/alert_service.py
          │
          ▼
      app/data/alerts.json
```

The frontend is intentionally static and can run without the backend. The backend reads synthetic CSV files from `app/data` using paths derived from the package location, so commands work from the repository root or from Docker. There is no API server in this basic layout; the frontend's remote API fields remain optional configuration for future integration.

## Responsibilities

- `engine.py` is the public backend entry point for investigation functions.
- `core/` contains risk rules and tracing algorithms.
- `services/` stores and deduplicates alerts using the engine's findings.
- `workers/auto_scanner.py` watches CSV changes and invokes the alert service.
- `aws/` remains an empty integration placeholder, not a required runtime service.

Run Python entry points as modules from the project root, for example `python -m app.backend.workers.auto_scanner --once`.
