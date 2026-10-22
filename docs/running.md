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

```powershell
docker compose up --build
docker compose --profile analysis up --build
```

The first command serves the frontend. The second also starts the optional scanner profile. Stop with `Ctrl+C`; clean up this project's frontend and scanner containers with `docker compose --profile analysis down`.

The frontend remains served from `app/frontend`; its scripts and styles now live in `assets/js` and `assets/css`. Change optional remote API endpoints in `app/frontend/assets/js/config.js`.

## Troubleshooting

- If `python` is not available, install Python 3.11+ or use the full path to the Python executable.
- If Docker reports that the daemon is unavailable, start Docker Desktop; the Compose file itself does not start the daemon.
- If disk space is limited, avoid Docker, run frontend-only mode, and install dependencies with `--no-cache-dir` only when the scanner is required.
