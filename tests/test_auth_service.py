"""Isolated tests for AuthService, repositories, rate limiting, and bootstrap."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.backend.auth.bootstrap import bootstrap_admin
from app.backend.auth.security import hash_password
from app.backend.db.auth_repositories import (
    AuditLogRepository,
    SessionRepository,
    UserRepository,
)
from app.backend.db.models import Base
from app.backend.services.auth_service import (
    AuthService,
    AuthenticationError,
    LoginRateLimiter,
    RateLimitError,
    ServiceUnavailableError,
)


def create_in_memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.backend.db.models import AuthAuditLog, AuthSession, User
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AuthSession.__table__, AuthAuditLog.__table__],
    )
    return engine


class TestAuthServiceIsolated(unittest.TestCase):
    def setUp(self):
        self.engine = create_in_memory_db()
        self.rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=60)
        self.auth_service = AuthService(engine=self.engine, rate_limiter=self.rate_limiter)

        # Seed sample officer (user)
        with Session(self.engine) as session:
            user_repo = UserRepository(session)
            user_repo.create_user(
                email="officer@agency.go.th",
                display_name="Officer Jane",
                role="user",
                password_hash=hash_password("OfficerSecure10!@#"),
                is_active=True,
            )
            # Disabled account
            user_repo.create_user(
                email="disabled@agency.go.th",
                display_name="Disabled User",
                role="user",
                password_hash=hash_password("DisabledSecure10!@#"),
                is_active=False,
            )
            session.commit()

    def test_first_admin_bootstrap_success(self):
        result = bootstrap_admin(
            engine=self.engine,
            interactive=False,
            email="admin@agency.go.th",
            display_name="Super Admin",
            password="AdminSecure10!@#",
        )
        self.assertTrue(result)

        # Verify admin in database
        with Session(self.engine) as session:
            repo = UserRepository(session)
            admin = repo.get_by_email("admin@agency.go.th")
            self.assertIsNotNone(admin)
            self.assertEqual(admin.role, "admin")
            self.assertTrue(admin.is_active)

    def test_bootstrap_rejects_duplicate_admin(self):
        # First bootstrap
        bootstrap_admin(
            engine=self.engine,
            interactive=False,
            email="admin@agency.go.th",
            display_name="Super Admin",
            password="AdminSecure10!@#",
        )
        # Second bootstrap attempt must be rejected
        result = bootstrap_admin(
            engine=self.engine,
            interactive=False,
            email="another_admin@agency.go.th",
            display_name="Second Admin",
            password="AnotherSecure10!@#",
        )
        self.assertFalse(result, "Duplicate bootstrap must be rejected.")

    def test_valid_login_and_session_lifecycle(self):
        token, user_info = self.auth_service.login(
            "officer@agency.go.th", "OfficerSecure10!@#", client_ip="10.0.0.1"
        )
        self.assertIsNotNone(token)
        self.assertEqual(user_info["email"], "officer@agency.go.th")
        self.assertEqual(user_info["role"], "user")

        # Validate session
        validated_user = self.auth_service.validate_session(token)
        self.assertIsNotNone(validated_user)
        self.assertEqual(validated_user["id"], user_info["id"])
        self.assertEqual(validated_user["role"], "user")

        # Logout
        logged_out = self.auth_service.logout(token)
        self.assertTrue(logged_out)

        # After logout, session is revoked
        after_logout = self.auth_service.validate_session(token)
        self.assertIsNone(after_logout, "Revoked session must not validate.")

    def test_incorrect_password_fails_with_generic_message(self):
        with self.assertRaises(AuthenticationError) as ctx:
            self.auth_service.login("officer@agency.go.th", "WrongPassword123!@#")
        self.assertEqual(str(ctx.exception), "Invalid email or password.")

    def test_unknown_email_fails_with_generic_message(self):
        with self.assertRaises(AuthenticationError) as ctx:
            self.auth_service.login("nonexistent@agency.go.th", "AnyPassword10!@#")
        self.assertEqual(str(ctx.exception), "Invalid email or password.")

    def test_disabled_account_fails_authentication(self):
        with self.assertRaises(AuthenticationError) as ctx:
            self.auth_service.login("disabled@agency.go.th", "DisabledSecure10!@#")
        self.assertEqual(str(ctx.exception), "Invalid email or password.")

    def test_rate_limiting_lockout_after_consecutive_failures(self):
        ip = "192.168.1.100"
        email = "officer@agency.go.th"
        for _ in range(5):
            try:
                self.auth_service.login(email, "WrongPassword!", client_ip=ip)
            except AuthenticationError:
                pass

        # 6th attempt must trigger RateLimitError
        with self.assertRaises(RateLimitError):
            self.auth_service.login(email, "OfficerSecure10!@#", client_ip=ip)

    def test_expired_session_fails_validation(self):
        token, _ = self.auth_service.login("officer@agency.go.th", "OfficerSecure10!@#")

        # Manually backdate session expiry
        with Session(self.engine) as session:
            from app.backend.auth.security import hash_token
            from app.backend.db.models import AuthSession
            tok_hash = hash_token(token)
            db_session = session.query(AuthSession).filter_by(token_hash=tok_hash).one()
            db_session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            session.commit()

        self.assertIsNone(self.auth_service.validate_session(token))

    def test_postgresql_unavailable_fails_closed(self):
        from unittest.mock import MagicMock
        from sqlalchemy.exc import OperationalError

        failing_engine = MagicMock()
        failing_engine.connect.side_effect = OperationalError("Connection refused", None, None)

        broken_service = AuthService(engine=failing_engine)

        with self.assertRaises(ServiceUnavailableError):
            broken_service.login("officer@agency.go.th", "OfficerSecure10!@#")


if __name__ == "__main__":
    unittest.main()
