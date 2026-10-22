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

Windows users can run `run.bat` to start the frontend together with the local scanner.

## One-command startup

Run `run.bat` from any folder or double-click it from Explorer. It resolves the project root,
creates `.env` from `.env.example` only when `.env` is missing, refreshes the project `.venv`
when `requirements.txt` changes, and starts the frontend plus the CSV scanner. Changing source
files or `.env` is picked up on the next `run.bat` invocation; the scanner continues watching
CSV data while it is running.

Use `run.bat --no-browser` to leave the browser closed, or `run.bat --help` for usage.
Press Ctrl+C to stop both local services before starting them again. The first run needs
internet access and enough space for `.venv`; later runs reuse installed dependencies.

Use `run.bat docker` for Docker mode. It creates `.env` when needed, rebuilds with `--build`,
and recreates the frontend and scanner containers so added or changed files are included.

## Run with Docker

Optional: copy `.env.example` to `.env` (do not overwrite an existing file) to customize
`FRONTEND_PORT` and `SCAN_INTERVAL`. See `docs/running.md` for details.

```powershell
docker compose up --build
```

Open `http://localhost:8000`. To run the rule scanner as well:

```powershell
docker compose --profile analysis up --build
```

The scanner writes generated alerts to `app/data/alerts.json` through the mounted data directory.

## Private keys and AWS

Keep local/private values in the root `.env`, which is ignored by Git and excluded from Docker
build context. The current demo does not require any key. If a future feature uses AWS, add its
backend-only variables there (for example `AWS_REGION`, `AWS_ACCESS_KEY_ID`, and
`AWS_SECRET_ACCESS_KEY`, plus `AWS_SESSION_TOKEN` for temporary credentials); never put them
in `app/frontend/assets/js/config.js`, HTML, CSS, or the browser environment. `run.bat` passes
private variables only to the backend scanner. Adding keys does not enable an AWS integration:
the current application still runs locally, without calling AWS.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

See `docs/architecture.md` for module responsibilities and `docs/running.md` for startup options.

## Low-storage recommendation

Use the non-Docker demo mode first. It avoids Docker images and Python dependencies. Install the backend environment only when analysis is needed, and keep `--no-cache-dir` in the install command to avoid retaining package caches.

Risk scores and alerts are investigation aids, not proof of wrongdoing. Use synthetic data for development and demonstrations.
