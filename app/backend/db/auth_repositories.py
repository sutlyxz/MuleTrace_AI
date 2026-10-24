"""Repository layer for Users, Sessions, and Security Audit Logs."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.backend.auth.security import normalize_email
from app.backend.db.models import AuthAuditLog, AuthSession, User


def _gen_id(prefix: str = "") -> str:
    """Generate a clean unique identifier."""
    raw = uuid.uuid4().hex
    return f"{prefix}{raw}" if prefix else raw


class UserRepository:
    """PostgreSQL user management operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_email(self, email: str) -> User | None:
        norm_email = normalize_email(email)
        stmt = select(User).where(User.email == norm_email)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def count_admins(self) -> int:
        stmt = select(func.count()).select_from(User).where(User.role == "admin", User.is_active == True)
        count_val = self.session.execute(stmt).scalar_one()
        return count_val if count_val else 0

    def create_user(
        self,
        email: str,
        display_name: str,
        role: str,
        password_hash: str,
        is_active: bool = True,
        must_change_password: bool = False,
    ) -> User:
        if role not in ("admin", "user"):
            raise ValueError(f"Invalid role '{role}'. Role must be 'admin' or 'user'.")
        norm_email = normalize_email(email)
        user = User(
            id=_gen_id("usr_"),
            email=norm_email,
            display_name=display_name.strip(),
            role=role,
            password_hash=password_hash,
            is_active=is_active,
            must_change_password=must_change_password,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.session.add(user)
        self.session.flush()
        return user

    def update_last_login(self, user_id: str, timestamp: datetime | None = None) -> None:
        ts = timestamp or datetime.now(timezone.utc)
        stmt = update(User).where(User.id == user_id).values(last_login_at=ts, updated_at=ts)
        self.session.execute(stmt)

    def list_users(self, limit: int = 50, offset: int = 0) -> Tuple[list[User], int]:
        count_stmt = select(func.count()).select_from(User)
        count_val = self.session.execute(count_stmt).scalar_one()
        total = count_val if count_val else 0

        stmt = (
            select(User)
            .order_by(User.created_at.desc(), User.id.asc())
            .limit(limit)
            .offset(offset)
        )
        users = list(self.session.execute(stmt).scalars().all())
        return users, total


class SessionRepository:
    """Server-side session management operations."""

    def __init__(self, session: Session):
        self.session = session

    def create_session(self, user_id: str, token_hash: str, expires_at: datetime) -> AuthSession:
        sess = AuthSession(
            id=_gen_id("ses_"),
            user_id=user_id,
            token_hash=token_hash,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            revoked_at=None,
        )
        self.session.add(sess)
        self.session.flush()
        return sess

    def get_active_session(self, token_hash: str) -> Tuple[AuthSession, User] | None:
        now = datetime.now(timezone.utc)
        stmt = (
            select(AuthSession, User)
            .join(User, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                User.is_active == True,
            )
        )
        row = self.session.execute(stmt).first()
        if row is None:
            return None
        return row[0], row[1]

    def revoke_session(self, token_hash: str) -> bool:
        now = datetime.now(timezone.utc)
        stmt = (
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        result = self.session.execute(stmt)
        if isinstance(result, CursorResult):
            return result.rowcount > 0
        return False

    def revoke_all_user_sessions(self, user_id: str) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        result = self.session.execute(stmt)
        if isinstance(result, CursorResult):
            return result.rowcount
        return 0


class AuditLogRepository:
    """Immutable security audit logging."""

    def __init__(self, session: Session):
        self.session = session

    def log(
        self,
        action: str,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> AuthAuditLog:
        # Sanitize metadata to never include sensitive keywords
        sanitized = None
        if safe_metadata:
            sanitized = {}
            for k, v in safe_metadata.items():
                if any(bad in k.lower() for bad in ("password", "token", "secret", "cookie")):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = v

        entry = AuthAuditLog(
            id=_gen_id("log_"),
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action,
            created_at=datetime.now(timezone.utc),
            safe_metadata=sanitized,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def list_logs(self, limit: int = 50, offset: int = 0) -> Tuple[list[AuthAuditLog], int]:
        count_stmt = select(func.count()).select_from(AuthAuditLog)
        count_val = self.session.execute(count_stmt).scalar_one()
        total = count_val if count_val else 0

        stmt = (
            select(AuthAuditLog)
            .order_by(AuthAuditLog.created_at.desc(), AuthAuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        logs = list(self.session.execute(stmt).scalars().all())
        return logs, total
