# App Structure Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Organize the project under a standard `app/` directory containing `frontend`, `backend`, and `data`, while preserving current behavior and providing Docker and non-Docker launch commands.

**Architecture:** The static UI moves to `app/frontend`. Python engine, investigation rules, scanner, and AWS placeholders move to `app/backend`. Runtime data moves to `app/data`; tests remain at the repository root and import the backend package through stable package paths.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, Python 3, pandas, Docker Compose, unittest.

## Global Constraints

- Preserve existing rule-engine behavior and JSON/CSV formats.
- Do not add a database, frontend framework, or API server in this migration.
- Keep frontend demo mode working without Python dependencies.
- Do not include secrets or generated caches in the image or repository.

## Review Focus

- Backend modules must resolve `app/data` from any current working directory.
- Existing tests must import the moved backend modules without path hacks.
- Windows launcher must choose demo mode without requiring Docker.
- Docker image must serve the frontend and keep the scanner optional.
- Generated `alerts.json` must remain writable through a mounted data directory.

### Task 1: Establish package and path contracts

**Files:**
- Create: `app/__init__.py`
- Create: `app/backend/__init__.py`
- Create: `app/backend/investigation/__init__.py`
- Modify: tests imports and path assertions as needed

**Check:** Tests import `app.backend.engine` and `app.backend.investigation.*` from the repository root.

### Task 2: Move runtime code and data

**Files:**
- Move: `ui/` to `app/frontend/`
- Move: `engine.py` to `app/backend/engine.py`
- Move: `investigation/` to `app/backend/investigation/`
- Move: `aws/` to `app/backend/aws/`
- Move: `data/` to `app/data/`
- Modify: backend data paths and internal imports

**Check:** Existing unit tests pass without changing their behavioral assertions.

### Task 3: Add standard launch files

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Modify: `run.bat`

**Check:** Static demo command and scanner command are documented and configuration parses without requiring a Docker daemon.

### Task 4: Document structure and commands

**Files:**
- Modify: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/running.md`

**Check:** Documentation names only the new paths and includes low-storage guidance.

### Task 5: Verify migration

**Check:** Run targeted unit tests, import checks, and repository reference search; report any environment-only limitations separately.
