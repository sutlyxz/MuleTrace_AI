"""Authentication Service implementing login, session management, and rate limiting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any, Tuple

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.backend.auth.security import (
    dummy_verify_password,
    generate_session_token,
    hash_token,
    normalize_email,
    verify_password,
)
from app.backend.db.auth_repositories import (
    AuditLogRepository,
    SessionRepository,
    UserRepository,
)
from app.backend.db.session import get_engine, session_scope


class AuthServiceError(Exception):
    """Base exception for authentication service errors."""


class AuthenticationError(AuthServiceError):
    """Raised on invalid credentials, inactive accounts, or authentication failures."""


class RateLimitError(AuthServiceError):
    """Raised when request frequency exceeds allowed limits."""


class ServiceUnavailableError(AuthServiceError):
    """Raised when PostgreSQL database is unreachable."""


class LoginRateLimiter:
    """Thread-safe sliding window rate limiter to protect against brute-force attacks."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._records: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_rate_limited(self, key: str) -> bool:
        if not key:
            return False
        now = time.time()
        with self._lock:
            attempts = self._records.get(key, [])
            # Prune old attempts outside window
            attempts = [ts for ts in attempts if now - ts < self.window_seconds]
            self._records[key] = attempts
            return len(attempts) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        if not key:
            return
        now = time.time()
        with self._lock:
            attempts = self._records.get(key, [])
            attempts = [ts for ts in attempts if now - ts < self.window_seconds]
            attempts.append(now)
            self._records[key] = attempts

    def reset(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            self._records.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


# Default global rate limiter instance (5 failed attempts per 15 minutes)
_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)


class AuthService:
    """Authentication and session management service."""

    def __init__(
        self,
        engine: Engine | None = None,
        rate_limiter: LoginRateLimiter | None = None,
        session_duration_hours: int = 12,
    ):
        self.engine = engine
        self.rate_limiter = rate_limiter or _rate_limiter
        self.session_duration = timedelta(hours=session_duration_hours)

    def _get_engine(self) -> Engine:
        if self.engine is not None:
            return self.engine
        return get_engine()

    def login(
        self,
        email: str,
        password: str,
        client_ip: str = "127.0.0.1",
    ) -> Tuple[str, dict[str, Any]]:
        """Validate credentials, create a server-side session, and return the session token.

        Fails closed with ServiceUnavailableError if PostgreSQL is offline.
        Protects against timing attacks and user enumeration.
        """
        norm_email = normalize_email(email)
        rate_key = f"{client_ip}:{norm_email}"

        # 1. Rate limiting check
        if self.rate_limiter.is_rate_limited(rate_key) or self.rate_limiter.is_rate_limited(client_ip):
            raise RateLimitError("Too many failed login attempts. Please try again later.")

        # 2. Database validation
        try:
            with session_scope(self._get_engine()) as session:
                user_repo = UserRepository(session)
                session_repo = SessionRepository(session)
                audit_repo = AuditLogRepository(session)

                user = user_repo.get_by_email(norm_email)

                # If user not found: run dummy hash verification to prevent timing attack enumeration
                if user is None:
                    dummy_verify_password()
                    self.rate_limiter.record_failure(rate_key)
                    self.rate_limiter.record_failure(client_ip)
                    audit_repo.log(
                        action="login_failure",
                        safe_metadata={"reason": "invalid_credentials", "ip": client_ip},
                    )
                    raise AuthenticationError("Invalid email or password.")

                # If user exists: verify password
                if not verify_password(password, user.password_hash):
                    self.rate_limiter.record_failure(rate_key)
                    self.rate_limiter.record_failure(client_ip)
                    audit_repo.log(
                        action="login_failure",
                        target_user_id=user.id,
                        safe_metadata={"reason": "invalid_credentials", "ip": client_ip},
                    )
                    raise AuthenticationError("Invalid email or password.")

                # Check account active status
                if not user.is_active:
                    self.rate_limiter.record_failure(rate_key)
                    self.rate_limiter.record_failure(client_ip)
                    audit_repo.log(
                        action="login_failure_disabled",
                        target_user_id=user.id,
                        safe_metadata={"reason": "account_disabled", "ip": client_ip},
                    )
                    # Generic error to prevent enumeration of disabled status
                    raise AuthenticationError("Invalid email or password.")

                # Authentication successful: create session
                self.rate_limiter.reset(rate_key)
                raw_token = generate_session_token()
                tok_hash = hash_token(raw_token)
                expires_at = datetime.now(timezone.utc) + self.session_duration

                session_repo.create_session(user.id, tok_hash, expires_at)
                user_repo.update_last_login(user.id)
                audit_repo.log(
                    action="login_success",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    safe_metadata={"role": user.role, "ip": client_ip},
                )

                user_info = {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "role": user.role,
                }
                return raw_token, user_info

        except (AuthenticationError, RateLimitError):
            raise
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Authentication service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error during authentication.") from err

    def validate_session(self, raw_token: str) -> dict[str, Any] | None:
        """Validate opaque session token against PostgreSQL. Returns user dict or None."""
        if not raw_token or not raw_token.strip():
            return None

        tok_hash = hash_token(raw_token.strip())
        try:
            with session_scope(self._get_engine()) as session:
                session_repo = SessionRepository(session)
                active = session_repo.get_active_session(tok_hash)
                if active is None:
                    return None
                _, user = active
                return {
                    "id": user.id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "role": user.role,
                }
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Authentication service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error during session validation.") from err

    def logout(self, raw_token: str) -> bool:
        """Revoke session token and record audit trail."""
        if not raw_token or not raw_token.strip():
            return False

        tok_hash = hash_token(raw_token.strip())
        try:
            with session_scope(self._get_engine()) as session:
                session_repo = SessionRepository(session)
                audit_repo = AuditLogRepository(session)

                active = session_repo.get_active_session(tok_hash)
                user_id = active[1].id if active else None

                revoked = session_repo.revoke_session(tok_hash)
                if revoked:
                    audit_repo.log(
                        action="logout",
                        actor_user_id=user_id,
                        target_user_id=user_id,
                    )
                return revoked
        except Exception:
            return False


# Singleton default service instance
default_auth_service = AuthService()
