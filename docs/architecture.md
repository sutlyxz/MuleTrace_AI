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
app/backend/engine.py ◄───► app/backend/aws/bedrock_service.py (AWS Bedrock AI)
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

- `engine.py` is the public backend entry point for investigation functions and AI summary facades.
- `core/` contains risk rules and tracing algorithms.
- `services/` stores and deduplicates alerts using the engine's findings.
- `workers/auto_scanner.py` watches CSV changes and invokes the alert service.
- `aws/` provides AWS Bedrock integration (`bedrock_service.py`), supporting:
  - Converse API for multi-model LLM generation (Anthropic Claude, Amazon Nova, etc.)
  - Bedrock Tool Use mapping `engine.py` functions directly into LLM agent tools
  - AI Narrative generation for AML case and account triage
  - Autonomous multi-step investigation agent loop
  - Graceful fallback when running in local demo mode without AWS credentials

Private configuration belongs to the repository-root `.env`. The launcher gives public settings
to the frontend server and private settings only to backend workers. The browser never receives
AWS keys or other private variables.

Run Python entry points as modules from the project root, for example:
- `python -m app.backend.workers.auto_scanner --once`
- `python -m unittest discover -s tests -p "test_*.py"`
