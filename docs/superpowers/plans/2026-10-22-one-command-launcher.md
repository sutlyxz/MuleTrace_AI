# One-command Launcher Implementation Plan

> **For agentic workers:** Use executing-plans inline, with regression tests before implementation.

**Goal:** Make run.bat start the current frontend and scanner using fresh private configuration on every invocation.

**Architecture:** A thin batch wrapper locates a working Python and delegates local startup to scripts/run.py. The Python launcher manages a project virtual environment, synchronizes changed requirements, creates a missing .env without overwriting an existing file, and passes private configuration only to the scanner process. Docker startup remains available without requiring Python.

**Tech Stack:** Python standard library, python-dotenv, existing pandas scanner, Windows batch, Docker Compose.

## Constraints

- Default to local demo analysis; do not add real AWS requests or a fake AWS implementation.
- Never print private configuration or copy .env into frontend assets/images.
- Re-read .env and synchronize dependency changes on each new run; preserve existing .env contents.
- Source changes are picked up on restart; CSV changes remain watched by the existing scanner.
- Existing direct frontend and scanner commands remain available.

## Tasks

1. Add tests for configuration defaults/precedence, literal private values, changed/removed keys, missing-file creation, settings validation, and child-process cleanup.
2. Add app/backend/config.py: load_environment(root, base_environment), RuntimeSettings.from_environment(environment), and frontend_environment(environment).
3. Add scripts/run.py: ensure_environment_file(root), prepare_runtime(root), local_commands(root, settings), run_local(root, settings, environment, open_browser), and CLI main(). Bootstrap only the project's .venv and install with no package cache when requirements change or dependencies are missing.
4. Replace run.bat: root-relative invocation, validate Python 3.11+, local default, explicit docker mode with build and force-recreate, and visible errors/nonzero exit status.
5. Add optional scanner-only env_file in Compose, safe empty AWS placeholders in .env.example, and instructions for adding future backend-only private keys.
6. Verify unit tests, actual static serving and scanner startup using temporary fixtures, Compose parsing with fake credentials, and batch entry points without invoking a browser or loading real credentials.

## Review Focus

- Reloading a changed .env must not retain removed values from an earlier load.
- Requirements stamps are updated only after successful installation.
- Frontend process receives an allowlisted environment, not backend credentials.
- Failure to start either child terminates the other child; Ctrl+C cleans up both.
- Batch invocation from a different current directory must resolve the same project root.
