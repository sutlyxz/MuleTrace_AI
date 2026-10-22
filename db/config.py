"""Environment-driven database configuration.

No credentials live in code. Values come from environment variables, optionally
loaded from a git-ignored ``.env`` file in the project root.
"""
from __future__ import annotations

from pathlib import Path
import os
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]

BACKEND_ENV = "MULETRACE_DATA_BACKEND"
DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
SUPPORTED_BACKENDS = ("csv", "postgres")
DEFAULT_BACKEND = "csv"

DATASET_ENV = "MULETRACE_DATASET"
DEFAULT_DATASET = "canonical"
SUPPORTED_DATASETS = ("canonical", "default", "demo")

DATA_DIR = PROJECT_ROOT / "data"
CANONICAL_TRANSACTIONS = DATA_DIR / "transactions.csv"
CANONICAL_ACCOUNTS = DATA_DIR / "accounts.csv"
CANONICAL_ALERTS = DATA_DIR / "alerts.json"

# Retained for backward-compatibility with callers/tools
DATASET_FILES: dict[str, dict[str, Path]] = {
    "default": {
        "transactions": CANONICAL_TRANSACTIONS,
        "accounts": CANONICAL_ACCOUNTS,
        "alerts": CANONICAL_ALERTS,
    },
    "demo": {
        "transactions": CANONICAL_TRANSACTIONS,
        "accounts": CANONICAL_ACCOUNTS,
        "alerts": CANONICAL_ALERTS,
    },
    "canonical": {
        "transactions": CANONICAL_TRANSACTIONS,
        "accounts": CANONICAL_ACCOUNTS,
        "alerts": CANONICAL_ALERTS,
    },
}


def _load_dotenv() -> None:
    """Load .env once, never overriding variables already set in the shell."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is optional
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


_load_dotenv()


def data_backend() -> str:
    """Return the active data backend ("csv" unless explicitly configured)."""
    value = (os.environ.get(BACKEND_ENV) or DEFAULT_BACKEND).strip().lower()
    if value not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"{BACKEND_ENV} must be one of {SUPPORTED_BACKENDS}, got {value!r}"
        )
    return value


def dataset_name() -> str:
    """Return active dataset name ('canonical').

    Retained for backward-compatible signatures; all application paths use the canonical dataset.
    """
    return DEFAULT_DATASET


def get_transactions_path() -> Path:
    """Return path to canonical transactions CSV file."""
    return CANONICAL_TRANSACTIONS


def get_accounts_path() -> Path:
    """Return path to canonical accounts CSV file."""
    return CANONICAL_ACCOUNTS


def get_alerts_path() -> Path:
    """Return path to canonical alerts JSON file."""
    return CANONICAL_ALERTS


def normalize_database_url(url: str) -> str:
    """Force the psycopg 3 driver for plain postgres:// / postgresql:// URLs."""
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_database_url(env_var: str = DATABASE_URL_ENV) -> str:
    """Read and normalize a database URL from the environment."""
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        raise RuntimeError(
            f"{env_var} is not set. Copy .env.example to .env and configure it."
        )
    url = normalize_database_url(raw)
    if not url.startswith("postgresql+"):
        raise RuntimeError(f"{env_var} must be a PostgreSQL URL")
    return url


def redact_url(url: str) -> str:
    """Hide the password part of a URL for logs and error messages."""
    return re.sub(r"(://[^:/@]+):[^@]*@", r"\1:***@", url)
