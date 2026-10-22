# MuleTrace AI

MuleTrace AI is a synthetic-data investigation prototype. It combines a static dashboard with a Python rule engine for transaction tracing and transparent risk triage.

## Project structure

```text
MuleTrace_AI/
├── app/
│   ├── frontend/
│   │   ├── index.html
│   │   ├── assets/
│   │   │   ├── css/    # Dashboard styles
│   │   │   └── js/     # UI behavior, API adapter, config, and demo data
│   │   ├── manifest.webmanifest
│   │   └── sw.js       # Service Worker kept at the frontend root
│   ├── backend/
│   │   ├── engine.py   # Public investigation facade
│   │   ├── core/       # Risk rules and tracing algorithms
│   │   ├── services/   # Alert persistence and orchestration
│   │   ├── workers/    # Background scanner entry point
│   │   └── aws/        # Reserved AWS integration placeholder
│   └── data/           # CSV input and generated alerts
├── tests/              # Python unit tests
├── docs/               # Architecture and run instructions
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── run.bat
```

## Run without Docker

For the frontend demo, use a local Python installation:

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory app/frontend
```

Open `http://localhost:8000`. No Python package installation is needed for demo-only use.

For backend analysis, install the small Python environment and run a one-time scan:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe -m app.backend.workers.auto_scanner --once
```

Windows users can also run `run.bat` for the frontend demo.

## Run with Docker

```powershell
docker compose up --build
```

Open `http://localhost:8000`. To run the rule scanner as well:

```powershell
docker compose --profile analysis up --build
```

The scanner writes generated alerts to `app/data/alerts.json` through the mounted data directory.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

See `docs/architecture.md` for module responsibilities and `docs/running.md` for startup options.

## Low-storage recommendation

Use the non-Docker demo mode first. It avoids Docker images and Python dependencies. Install the backend environment only when analysis is needed, and keep `--no-cache-dir` in the install command to avoid retaining package caches.

Risk scores and alerts are investigation aids, not proof of wrongdoing. Use synthetic data for development and demonstrations.
