"""Admin Management Service for Phase 4.1.

Implements secure account management operations for Administrators:
- Listing users (with stable ordering and pagination)
- Provisioning Bank Officer accounts (role enforced as 'user')
- Activating and deactivating Bank Officer accounts (with immediate session revocation)
- Resetting Bank Officer passwords (with password policy and session revocation)
- Viewing security audit logs (with stable ordering and pagination)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.backend.auth.security import (
    hash_password,
    normalize_email,
    validate_email_format,
    validate_password_policy,
)
from app.backend.db.auth_repositories import (
    AuditLogRepository,
    SessionRepository,
    UserRepository,
)
from app.backend.db.session import get_engine, session_scope


class AdminServiceError(Exception):
    """Base exception for Admin Service."""


class ValidationError(AdminServiceError):
    """Raised when input validation fails (e.g. invalid email, weak password, invalid type)."""


class ConflictError(AdminServiceError):
    """Raised on conflicting state (e.g. duplicate email)."""


class NotFoundError(AdminServiceError):
    """Raised when the target resource is not found."""


class ForbiddenError(AdminServiceError):
    """Raised when an operation is forbidden by business rules (e.g. modifying an Admin)."""


class ServiceUnavailableError(AdminServiceError):
    """Raised when the database or dependent service is unreachable."""


class AdminService:
    """Administrator account management and security audit service."""

    def __init__(self, engine: Engine | None = None):
        self.engine = engine

    def _get_engine(self) -> Engine:
        if self.engine is not None:
            return self.engine
        return get_engine()

    def list_users(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List user accounts with pagination. Excludes secrets and password hashes."""
        bounded_limit = max(1, min(int(limit), 100))
        bounded_offset = max(0, int(offset))

        try:
            with session_scope(self._get_engine()) as session:
                user_repo = UserRepository(session)
                users, total = user_repo.list_users(limit=bounded_limit, offset=bounded_offset)
                return {
                    "users": [
                        {
                            "id": u.id,
                            "email": u.email,
                            "display_name": u.display_name,
                            "role": u.role,
                            "is_active": u.is_active,
                            "created_at": u.created_at.isoformat() if u.created_at else None,
                            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                        }
                        for u in users
                    ],
                    "total": total,
                    "limit": bounded_limit,
                    "offset": bounded_offset,
                }
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Database service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error while listing users.") from err

    def create_bank_officer(
        self,
        admin_actor_id: str | None = None,
        email: str = "",
        password: str = "",
        display_name: str | None = None,
        client_supplied_role: str | None = None,
        actor_id: str | None = None,
        client_ip: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Provision a new Bank Officer account with role='user'.

        Server strictly enforces role='user'. Rejects attempts to create another admin.
        """
        effective_actor_id = admin_actor_id or actor_id or ""

        # Reject attempts to create admin
        role_to_check = client_supplied_role or kwargs.get("role")
        if role_to_check and str(role_to_check).strip().lower() == "admin":
            raise ForbiddenError("Cannot create an administrator account through this endpoint.")

        if not email or not str(email).strip():
            raise ValidationError("Email is required.")

        norm_email = normalize_email(str(email))
        if not validate_email_format(norm_email):
            raise ValidationError("Invalid email address format.")

        if not password or not str(password):
            raise ValidationError("Password is required.")

        is_valid, msg = validate_password_policy(str(password))
        if not is_valid:
            raise ValidationError(msg)

        dname = str(display_name).strip() if display_name and str(display_name).strip() else norm_email.split("@")[0]
        p_hash = hash_password(str(password))

        try:
            with session_scope(self._get_engine()) as session:
                user_repo = UserRepository(session)
                audit_repo = AuditLogRepository(session)

                existing = user_repo.get_by_email(norm_email)
                if existing is not None:
                    raise ConflictError(f"A user with email '{norm_email}' already exists.")

                new_user = user_repo.create_user(
                    email=norm_email,
                    display_name=dname,
                    role="user",
                    password_hash=p_hash,
                    is_active=True,
                )

                safe_meta: dict[str, Any] = {
                    "email": new_user.email,
                    "role": new_user.role,
                    "display_name": new_user.display_name,
                }
                if client_ip:
                    safe_meta["ip"] = client_ip

                audit_repo.log(
                    action="user_created",
                    actor_user_id=effective_actor_id,
                    target_user_id=new_user.id,
                    safe_metadata=safe_meta,
                )

                return {
                    "id": new_user.id,
                    "email": new_user.email,
                    "display_name": new_user.display_name,
                    "role": new_user.role,
                    "is_active": new_user.is_active,
                    "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
                }
        except (ValidationError, ConflictError, ForbiddenError):
            raise
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Database service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error during user creation.") from err

    def set_user_status(
        self,
        admin_actor_id: str | None = None,
        target_user_id: str = "",
        is_active: bool = True,
        actor_id: str | None = None,
        client_ip: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Activate or deactivate a Bank Officer account.

        Revokes all active sessions immediately when deactivating an account.
        Disallows modifying Administrator accounts.
        """
        effective_actor_id = admin_actor_id or actor_id or ""

        if not isinstance(is_active, bool):
            raise ValidationError("is_active must be a boolean.")

        try:
            with session_scope(self._get_engine()) as session:
                user_repo = UserRepository(session)
                session_repo = SessionRepository(session)
                audit_repo = AuditLogRepository(session)

                target_user = user_repo.get_by_id(target_user_id)
                if target_user is None:
                    raise NotFoundError(f"User '{target_user_id}' not found.")

                if target_user.role == "admin":
                    raise ForbiddenError("Cannot change status of Administrator accounts.")

                target_user.is_active = is_active
                target_user.updated_at = datetime.now(timezone.utc)

                revoked_sessions = 0
                if not is_active:
                    revoked_sessions = session_repo.revoke_all_user_sessions(target_user.id)

                action = "user_deactivated" if not is_active else "user_activated"
                safe_meta: dict[str, Any] = {
                    "is_active": is_active,
                    "role": target_user.role,
                    "revoked_sessions": revoked_sessions,
                }
                if client_ip:
                    safe_meta["ip"] = client_ip

                audit_repo.log(
                    action=action,
                    actor_user_id=effective_actor_id,
                    target_user_id=target_user.id,
                    safe_metadata=safe_meta,
                )

                return {
                    "id": target_user.id,
                    "email": target_user.email,
                    "display_name": target_user.display_name,
                    "role": target_user.role,
                    "is_active": target_user.is_active,
                    "updated_at": target_user.updated_at.isoformat() if target_user.updated_at else None,
                }
        except (ValidationError, NotFoundError, ForbiddenError):
            raise
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Database service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error during status update.") from err

    def reset_user_password(
        self,
        admin_actor_id: str | None = None,
        target_user_id: str = "",
        new_password: str = "",
        actor_id: str | None = None,
        client_ip: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Reset a Bank Officer's password and immediately revoke all existing sessions.

        Disallows resetting Administrator passwords through this endpoint.
        """
        effective_actor_id = admin_actor_id or actor_id or ""

        if not new_password or not str(new_password):
            raise ValidationError("New password is required.")

        is_valid, msg = validate_password_policy(str(new_password))
        if not is_valid:
            raise ValidationError(msg)

        p_hash = hash_password(str(new_password))

        try:
            with session_scope(self._get_engine()) as session:
                user_repo = UserRepository(session)
                session_repo = SessionRepository(session)
                audit_repo = AuditLogRepository(session)

                target_user = user_repo.get_by_id(target_user_id)
                if target_user is None:
                    raise NotFoundError(f"User '{target_user_id}' not found.")

                if target_user.role == "admin":
                    raise ForbiddenError("Cannot reset password of Administrator accounts.")

                target_user.password_hash = p_hash
                target_user.updated_at = datetime.now(timezone.utc)

                revoked_sessions = session_repo.revoke_all_user_sessions(target_user.id)

                safe_meta: dict[str, Any] = {
                    "role": target_user.role,
                    "revoked_sessions": revoked_sessions,
                }
                if client_ip:
                    safe_meta["ip"] = client_ip

                audit_repo.log(
                    action="password_reset",
                    actor_user_id=effective_actor_id,
                    target_user_id=target_user.id,
                    safe_metadata=safe_meta,
                )

                return {
                    "id": target_user.id,
                    "message": "Password reset successfully",
                }
        except (ValidationError, NotFoundError, ForbiddenError):
            raise
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Database service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error during password reset.") from err

    def list_audit_logs(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """View sanitized security audit logs with pagination in newest-first order."""
        bounded_limit = max(1, min(int(limit), 100))
        bounded_offset = max(0, int(offset))

        try:
            with session_scope(self._get_engine()) as session:
                audit_repo = AuditLogRepository(session)
                logs, total = audit_repo.list_logs(limit=bounded_limit, offset=bounded_offset)
                entries = [
                    {
                        "id": log.id,
                        "actor_user_id": log.actor_user_id,
                        "actor_id": log.actor_user_id,
                        "target_user_id": log.target_user_id,
                        "action": log.action,
                        "created_at": log.created_at.isoformat() if log.created_at else None,
                        "timestamp": log.created_at.isoformat() if log.created_at else None,
                        "safe_metadata": log.safe_metadata,
                    }
                    for log in logs
                ]
                return {
                    "audit_logs": entries,
                    "logs": entries,
                    "total": total,
                    "limit": bounded_limit,
                    "offset": bounded_offset,
                }
        except (OperationalError, RuntimeError) as err:
            raise ServiceUnavailableError("Database service unavailable.") from err
        except SQLAlchemyError as err:
            raise ServiceUnavailableError("Database error while listing audit logs.") from err


default_admin_service = AdminService()
