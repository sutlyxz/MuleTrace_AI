# Running the application

## Frontend only

```powershell
python -m http.server 8000 --bind 127.0.0.1 --directory app/frontend
```

This is the smallest-footprint option. It uses the dashboard's built-in demo data and does not require pandas.

## One command

```powershell
run.bat
```

`run.bat` works from Explorer or another current directory. It uses local mode by default,
creates `.env` from `.env.example` only if needed, refreshes `.venv` dependencies when
`requirements.txt` changes, and starts both the frontend and the CSV scanner. Restart it after
changing source files or `.env`; the current scanner watches CSV changes while running.

The first run may download dependencies into `.venv`. Later runs install again only when
`requirements.txt` changes or required imports are missing. Press Ctrl+C to stop both services.
Use `run.bat --no-browser` to start without automatically opening a browser.

This is restart-based refresh, not hot reload: stop and rerun after changing Python code,
dependencies, or `.env`. The frontend serves files directly, so refresh the browser for HTML,
CSS, and JavaScript edits. New file paths must still be referenced by the application.

For Docker mode:

```powershell
run.bat docker
```

This runs `docker compose --profile analysis up --build --force-recreate`, so changed files and
new environment values are included in new containers. It does not overwrite an existing `.env`.

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
The scanner `env_file` requires Docker Compose 2.24 or newer.
Compose reads `.env` automatically for public settings and the optional scanner service. `FRONTEND_PORT` sets the host port (default `8000`),
and `SCAN_INTERVAL` sets the scanner polling interval in seconds (default `3`, must be positive).
For example, setting `FRONTEND_PORT=8080` makes the dashboard available at `http://localhost:8080`.
Both defaults also work without creating `.env`.

```powershell
docker compose up --build
docker compose --profile analysis up --build
```

The first command serves the frontend. The second also starts the optional scanner profile. Stop with `Ctrl+C`; clean up this project's frontend and scanner containers with `docker compose --profile analysis down`.

The frontend remains served from `app/frontend`; its scripts and styles now live in `assets/js` and `assets/css`. Change optional remote API endpoints in `app/frontend/assets/js/config.js`.

Direct `python -m ...` commands do not load `.env` automatically; the local launcher does.
When running modules directly, set the HTTP port in the server
command and pass `--interval 3` (or another positive value) to the scanner. No AWS credentials
are required for the current demo. If AWS integration is added later, store AWS variables only
in `.env`; `run.bat` passes private values to backend processes, never to the static frontend.

## Private configuration

- Local operation needs no AWS or other private key. Leave optional AWS entries commented out.
- Existing `.env` is never overwritten or automatically merged with template changes. Add any
  future private variable directly to your own `.env`; only placeholder names belong in `.env.example`.
- For AWS, use `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and when needed
  `AWS_SESSION_TOKEN`. Keys are forwarded to backend workers only; no AWS client exists yet.
- The local launcher reads `.env` literally without variable expansion or shell evaluation;
  its values override same-named inherited environment values. Docker Compose uses its own
  precedence rules: an exported shell variable overrides `.env` for public port/interval interpolation.
- Single-quote private values containing `$` or `#` and never paste real keys in logs or frontend files.
- Do not serve the project root with a static server: only serve `app/frontend`, so `.env` stays private.
- Updating `.env` does not modify CSV files or connect scanner output to the frontend; those
  existing architectural boundaries are unchanged.

## Troubleshooting

- If `python` is not available, install Python 3.11+ or use the full path to the Python executable.
- If Docker reports that the daemon is unavailable, start Docker Desktop; the Compose file itself does not start the daemon.
- If disk space is limited, avoid Docker, run frontend-only mode, and install dependencies with `--no-cache-dir` only when the scanner is required.
