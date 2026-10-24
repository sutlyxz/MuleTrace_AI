"""Core security, password hashing, and token handling using Argon2id and SHA-256."""
from __future__ import annotations

import hashlib
import re
import secrets
from typing import Tuple

import argon2
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Standard RFC 9106 recommended parameters for Argon2id
_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MiB
    parallelism=1,
    hash_len=32,
    type=argon2.Type.ID,
)

# Pre-computed dummy hash to mitigate side-channel timing attacks when user does not exist
_DUMMY_HASH = _HASHER.hash("muletrace_constant_dummy_timing_mitigation_hash_2026!")

# Regex for email format validation
_EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def normalize_email(email: str) -> str:
    """Normalize email address to lowercase and trimmed string."""
    if not email:
        return ""
    return str(email).strip().lower()


def validate_email_format(email: str) -> bool:
    """Validate email address format."""
    normalized = normalize_email(email)
    return bool(_EMAIL_REGEX.match(normalized))


def validate_password_policy(password: str) -> Tuple[bool, str]:
    """Enforce strong password policy:

    - Minimum 10 characters
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one digit (0-9)
    - At least one special/symbol character
    """
    if not password or len(password) < 10:
        return False, "Password must be at least 10 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one digit."
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Password must contain at least one special character."
    return True, ""


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    if not password:
        raise ValueError("Password cannot be empty.")
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against Argon2id hash in constant time."""
    if not password or not password_hash:
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False


def dummy_verify_password() -> None:
    """Execute dummy password verification to equalize timing for non-existent users."""
    try:
        _HASHER.verify(_DUMMY_HASH, "dummy_constant_mismatch_attempt_string")
    except Exception:
        pass


def generate_session_token() -> str:
    """Generate high-entropy cryptographically secure random session token (32 bytes urlsafe)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Compute SHA-256 hash of opaque session token to store in PostgreSQL."""
    if not token:
        raise ValueError("Token cannot be empty.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
