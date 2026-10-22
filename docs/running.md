# Running the application

## Frontend only

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory app/frontend
```

This is the smallest-footprint option. It uses the dashboard's built-in demo data and does not require pandas.

## Backend scan

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe -m app.backend.workers.auto_scanner --once
```

Use the command without `--once` to watch the CSV files for changes.

## Docker

Optional: copy the example configuration from the project root before starting Compose:

```powershell
Copy-Item .env.example .env
```

Only copy when `.env` does not already exist; otherwise edit your existing local file.
Compose reads `.env` automatically. `FRONTEND_PORT` sets the host port (default `8000`),
and `SCAN_INTERVAL` sets the scanner polling interval in seconds (default `3`, must be positive).
For example, setting `FRONTEND_PORT=8080` makes the dashboard available at `http://localhost:8080`.
Both defaults also work without creating `.env`.

```powershell
docker compose up --build
docker compose --profile analysis up --build
```

The first command serves the frontend. The second also starts the optional scanner profile. Stop with `Ctrl+C`; clean up this project's frontend and scanner containers with `docker compose --profile analysis down`.

The frontend remains served from `app/frontend`; its scripts and styles now live in `assets/js` and `assets/css`. Change optional remote API endpoints in `app/frontend/assets/js/config.js`.

Non-Docker commands do not load `.env` automatically. Set the HTTP port directly in the server
command and pass `--interval 3` (or another positive value) to the scanner. No AWS credentials
are required for the current demo; never put credentials or secrets in frontend configuration.

## Troubleshooting

- If `python` is not available, install Python 3.11+ or use the full path to the Python executable.
- If Docker reports that the daemon is unavailable, start Docker Desktop; the Compose file itself does not start the daemon.
- If disk space is limited, avoid Docker, run frontend-only mode, and install dependencies with `--no-cache-dir` only when the scanner is required.
