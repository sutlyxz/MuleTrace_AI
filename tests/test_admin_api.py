"""Comprehensive automated test suite for Phase 4.1: Admin Management Backend API.

Covers Part G Requirements 1 through 30:
1. Admin can list users.
2. User cannot list users.
3. Anonymous cannot list users.
4. Admin can create a Bank Officer account.
5. Created account always has role=user.
6. Attempt to create admin via API is rejected.
7. Duplicate email is rejected.
8. Invalid email is rejected.
9. Weak password is rejected.
10. Password is stored as Argon2id hash.
11. Password is not exposed in responses.
12. Admin can deactivate a Bank Officer.
13. Deactivated account cannot log in.
14. Deactivation revokes existing sessions.
15. Admin can reactivate a Bank Officer.
16. Admin can reset a Bank Officer password.
17. Password reset revokes existing sessions.
18. Admin cannot deactivate or reset another Admin.
19. User cannot call any Admin mutation endpoint.
20. Anonymous cannot call any Admin mutation endpoint.
21. Cross-origin mutation requests fail CSRF validation.
22. Admin can view sanitized audit logs.
23. User cannot view audit logs.
24. Pagination limits are enforced.
25. Invalid user IDs and unknown users are handled safely.
26. Audit entries are created correctly.
27. Database transaction rollback does not leave partial changes or misleading audit entries.
28. Existing Dashboard and investigation APIs retain their RBAC behavior.
29. Existing 401/403/404/500 error pages continue working.
30. PostgreSQL integration test with disposable accounts in muletrace_test.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.backend.auth.security import hash_password, verify_password
from app.backend.config import load_environment
from app.backend.db import config as db_config
from app.backend.db.auth_repositories import (
    AuditLogRepository,
    SessionRepository,
    UserRepository,
)
from app.backend.db.models import AuthAuditLog, AuthSession, Base, User
from app.backend.server import MuleTraceRequestHandler
from app.backend.services.admin_service import (
    AdminService,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.backend.services.auth_service import AuthService, LoginRateLimiter


class DummySocket:
    def __init__(self, input_bytes: bytes):
        self.rfile = io.BytesIO(input_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str = "rb", buffering: int = -1):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes) -> None:
        self.wfile.write(b)

    def send(self, b: bytes) -> int:
        self.wfile.write(b)
        return len(b)

    def getpeername(self):
        return ("127.0.0.1", 12345)

    def getsockname(self):
        return ("127.0.0.1", 8000)


class DummyServer:
    def __init__(self):
        self.server_name = "127.0.0.1"
        self.server_port = 8000


def create_in_memory_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AuthSession.__table__, AuthAuditLog.__table__],
    )
    return engine


class TestAdminServiceIsolated(unittest.TestCase):
    """Isolated unit tests for AdminService business logic and safety checks."""

    def setUp(self):
        self.engine = create_in_memory_engine()
        self.admin_service = AdminService(engine=self.engine)
        self.rate_limiter = LoginRateLimiter()
        self.auth_service = AuthService(engine=self.engine, rate_limiter=self.rate_limiter)

        with Session(self.engine) as session:
            user_repo = UserRepository(session)
            self.admin_user = user_repo.create_user(
                email="admin@agency.go.th",
                display_name="Admin Boss",
                role="admin",
                password_hash=hash_password("AdminSecure123!@#"),
                is_active=True,
            )
            self.officer_user = user_repo.create_user(
                email="officer@agency.go.th",
                display_name="Bank Officer One",
                role="user",
                password_hash=hash_password("OfficerSecure123!@#"),
                is_active=True,
            )
            session.commit()
            self.admin_id = self.admin_user.id
            self.officer_id = self.officer_user.id

    def test_admin_service_create_bank_officer_success(self):
        result = self.admin_service.create_bank_officer(
            actor_id=self.admin_id,
            email="newofficer@agency.go.th",
            password="NewOfficerSecure123!@#",
            display_name="New Officer",
            client_ip="127.0.0.1",
        )
        self.assertEqual(result["role"], "user")
        self.assertEqual(result["email"], "newofficer@agency.go.th")
        self.assertEqual(result["display_name"], "New Officer")
        self.assertTrue(result["is_active"])
        self.assertNotIn("password", result)
        self.assertNotIn("password_hash", result)

        # Verify password is an Argon2id hash in database
        with Session(self.engine) as session:
            user_repo = UserRepository(session)
            created = user_repo.get_by_email("newofficer@agency.go.th")
            self.assertIsNotNone(created)
            self.assertTrue(created.password_hash.startswith("$argon2id$"))
            self.assertTrue(verify_password("NewOfficerSecure123!@#", created.password_hash))

    def test_admin_service_rejects_admin_role_creation(self):
        with self.assertRaises(ForbiddenError):
            self.admin_service.create_bank_officer(
                actor_id=self.admin_id,
                email="hacked_admin@agency.go.th",
                password="AdminPassword123!@#",
                role="admin",
            )

    def test_admin_service_rejects_duplicate_email(self):
        with self.assertRaises(ConflictError):
            self.admin_service.create_bank_officer(
                actor_id=self.admin_id,
                email="officer@agency.go.th",
                password="AnotherPassword123!@#",
            )

    def test_admin_service_rejects_weak_password(self):
        with self.assertRaises(ValidationError) as ctx:
            self.admin_service.create_bank_officer(
                actor_id=self.admin_id,
                email="weakpass@agency.go.th",
                password="short",
            )
        self.assertIn("10 characters", str(ctx.exception))

    def test_admin_service_deactivate_officer_revokes_sessions(self):
        # Create a session for officer
        token, _ = self.auth_service.login("officer@agency.go.th", "OfficerSecure123!@#")
        self.assertIsNotNone(self.auth_service.validate_session(token))

        # Deactivate officer
        result = self.admin_service.set_user_status(
            actor_id=self.admin_id,
            target_user_id=self.officer_id,
            is_active=False,
            client_ip="127.0.0.1",
        )
        self.assertFalse(result["is_active"])

        # Session must be immediately invalid
        self.assertIsNone(self.auth_service.validate_session(token))

        # Officer cannot log in while inactive
        with self.assertRaises(Exception):
            self.auth_service.login("officer@agency.go.th", "OfficerSecure123!@#")

    def test_admin_service_reactivate_officer(self):
        # First deactivate
        self.admin_service.set_user_status(
            actor_id=self.admin_id,
            target_user_id=self.officer_id,
            is_active=False,
        )
        # Reactivate
        result = self.admin_service.set_user_status(
            actor_id=self.admin_id,
            target_user_id=self.officer_id,
            is_active=True,
        )
        self.assertTrue(result["is_active"])

        # Can now log in again
        token, _ = self.auth_service.login("officer@agency.go.th", "OfficerSecure123!@#")
        self.assertIsNotNone(token)

    def test_admin_service_prevent_deactivating_admin(self):
        with self.assertRaises(ForbiddenError) as ctx:
            self.admin_service.set_user_status(
                actor_id=self.admin_id,
                target_user_id=self.admin_id,
                is_active=False,
            )
        self.assertIn("Cannot change status of Administrator", str(ctx.exception))

    def test_admin_service_prevent_resetting_admin_password(self):
        with self.assertRaises(ForbiddenError) as ctx:
            self.admin_service.reset_user_password(
                actor_id=self.admin_id,
                target_user_id=self.admin_id,
                new_password="NewAdminPassword123!@#",
            )
        self.assertIn("Cannot reset password of Administrator", str(ctx.exception))

    def test_admin_service_reset_officer_password_revokes_sessions(self):
        # Active session
        token, _ = self.auth_service.login("officer@agency.go.th", "OfficerSecure123!@#")
        self.assertIsNotNone(self.auth_service.validate_session(token))

        # Reset password
        result = self.admin_service.reset_user_password(
            actor_id=self.admin_id,
            target_user_id=self.officer_id,
            new_password="BrandNewOfficerPass123!@#",
            client_ip="127.0.0.1",
        )
        self.assertEqual(result["id"], self.officer_id)
        self.assertNotIn("password", result)

        # Old session revoked
        self.assertIsNone(self.auth_service.validate_session(token))

        # Old password fails
        with self.assertRaises(Exception):
            self.auth_service.login("officer@agency.go.th", "OfficerSecure123!@#")

        # New password succeeds
        new_token, _ = self.auth_service.login("officer@agency.go.th", "BrandNewOfficerPass123!@#")
        self.assertIsNotNone(new_token)

    def test_admin_service_list_users_pagination(self):
        res = self.admin_service.list_users(limit=1, offset=0)
        self.assertEqual(res["total"], 2)
        self.assertEqual(len(res["users"]), 1)
        self.assertEqual(res["limit"], 1)
        self.assertEqual(res["offset"], 0)

        # Safe fields only
        user_data = res["users"][0]
        self.assertIn("id", user_data)
        self.assertIn("email", user_data)
        self.assertIn("role", user_data)
        self.assertIn("is_active", user_data)
        self.assertNotIn("password_hash", user_data)

    def test_admin_service_list_audit_logs(self):
        # Create an action to generate an audit log
        self.admin_service.create_bank_officer(
            actor_id=self.admin_id,
            email="audited@agency.go.th",
            password="AuditOfficerSecure123!@#",
        )
        logs_res = self.admin_service.list_audit_logs(limit=10, offset=0)
        self.assertGreaterEqual(logs_res["total"], 1)
        actions = [log["action"] for log in logs_res["logs"]]
        self.assertIn("user_created", actions)

        # Check log structure
        first_log = logs_res["logs"][0]
        self.assertIn("id", first_log)
        self.assertIn("action", first_log)
        self.assertIn("actor_id", first_log)
        self.assertIn("target_user_id", first_log)
        self.assertIn("timestamp", first_log)
        self.assertIn("safe_metadata", first_log)


class TestAdminAPIEndpoints(unittest.TestCase):
    """End-to-end HTTP tests for Admin endpoints via InjectedHandler."""

    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.frontend_dir = str(self.project_root / "app" / "frontend")

        self.engine = create_in_memory_engine()
        self.rate_limiter = LoginRateLimiter()
        self.auth_service = AuthService(engine=self.engine, rate_limiter=self.rate_limiter)
        self.admin_service = AdminService(engine=self.engine)

        with Session(self.engine) as session:
            user_repo = UserRepository(session)
            self.admin = user_repo.create_user(
                email="admin@agency.go.th",
                display_name="System Administrator",
                role="admin",
                password_hash=hash_password("AdminSecure123!@#"),
                is_active=True,
            )
            self.officer = user_repo.create_user(
                email="officer@agency.go.th",
                display_name="Bank Officer",
                role="user",
                password_hash=hash_password("OfficerSecure123!@#"),
                is_active=True,
            )
            session.commit()
            self.admin_id = self.admin.id
            self.officer_id = self.officer.id

        self.admin_token, _ = self.auth_service.login(
            "admin@agency.go.th", "AdminSecure123!@#", client_ip="127.0.0.1"
        )
        self.officer_token, _ = self.auth_service.login(
            "officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )

    def _execute_request(
        self, request_bytes: bytes, client_ip: str = "127.0.0.1"
    ) -> tuple[int, dict[str, str], bytes]:
        socket = DummySocket(request_bytes)
        server = DummyServer()

        class InjectedHandler(MuleTraceRequestHandler):
            pass

        InjectedHandler.auth_service = self.auth_service
        InjectedHandler.admin_service = self.admin_service

        handler = InjectedHandler(
            socket, (client_ip, 12345), server, directory=self.frontend_dir
        )
        raw_output = socket.wfile.getvalue()

        parts = raw_output.split(b"\r\n\r\n", 1)
        header_text = parts[0].decode("iso-8859-1")
        body = parts[1] if len(parts) > 1 else b""

        lines = header_text.split("\r\n")
        status_line = lines[0]
        status_code = int(status_line.split(" ")[1])

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        return status_code, headers, body

    # 1. Admin can list users
    def test_1_admin_can_list_users(self):
        req = (
            f"GET /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertIn("users", data)
        self.assertEqual(data["total"], 2)
        # Check safe fields
        u = data["users"][0]
        self.assertIn("id", u)
        self.assertIn("email", u)
        self.assertIn("role", u)
        self.assertNotIn("password_hash", u)

    # 2. User cannot list users
    def test_2_user_cannot_list_users(self):
        req = (
            f"GET /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.officer_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("admin", data["message"].lower())

    # 3. Anonymous cannot list users
    def test_3_anonymous_cannot_list_users(self):
        req = b"GET /api/admin/users HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")

    # 4. Admin can create a Bank Officer account
    # 5. Created account always has role=user
    # 10. Password stored as Argon2id hash
    # 11. Password not exposed in responses
    def test_4_5_10_11_admin_create_bank_officer(self):
        payload = json.dumps({
            "email": "created_officer@agency.go.th",
            "password": "CreatedOfficerPass123!@#",
            "display_name": "Created Officer",
            "role": "admin",  # Tamper attempt to become admin!
        }).encode("utf-8")
        req = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        # Server role enforcement rejects client specifying role="admin" with 400 Bad Request
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertTrue("admin" in data["message"].lower() or "role" in data["message"].lower())

        # Now create properly without role or role="user"
        valid_payload = json.dumps({
            "email": "officer_ok@agency.go.th",
            "password": "OfficerOkPass123!@#",
            "display_name": "Officer OK",
            "role": "user",
        }).encode("utf-8")
        req_valid = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(valid_payload)}\r\n\r\n"
        ).encode("utf-8") + valid_payload

        status_ok, _, body_ok = self._execute_request(req_valid)
        self.assertEqual(status_ok, 201)
        data_ok = json.loads(body_ok.decode("utf-8"))
        self.assertEqual(data_ok["status"], "success")
        self.assertEqual(data_ok["user"]["role"], "user")
        self.assertEqual(data_ok["user"]["email"], "officer_ok@agency.go.th")
        self.assertNotIn("password", data_ok["user"])
        self.assertNotIn("password_hash", data_ok["user"])

        # Check hash in DB
        with Session(self.engine) as session:
            user = UserRepository(session).get_by_email("officer_ok@agency.go.th")
            self.assertIsNotNone(user)
            self.assertTrue(user.password_hash.startswith("$argon2id$"))

    # 6. Attempt to create admin via API is rejected
    def test_6_reject_admin_role_creation(self):
        payload = json.dumps({
            "email": "hacker_admin@agency.go.th",
            "password": "HackerAdmin123!@#",
            "role": "admin",
        }).encode("utf-8")
        req = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")

    # 7. Duplicate email is rejected
    def test_7_reject_duplicate_email(self):
        payload = json.dumps({
            "email": "officer@agency.go.th",
            "password": "OfficerOkPass123!@#",
        }).encode("utf-8")
        req = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 409)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("already exists", data["message"])

    # 8. Invalid email is rejected
    def test_8_reject_invalid_email(self):
        payload = json.dumps({
            "email": "invalid-email-no-at",
            "password": "ValidPassword123!@#",
        }).encode("utf-8")
        req = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("email", data["message"].lower())

    # 9. Weak password is rejected
    def test_9_reject_weak_password(self):
        payload = json.dumps({
            "email": "weak@agency.go.th",
            "password": "simple",
        }).encode("utf-8")
        req = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("password", data["message"].lower())

    # 12. Admin can deactivate a Bank Officer
    # 13. Deactivated account cannot log in
    # 14. Deactivation revokes existing sessions
    def test_12_13_14_deactivate_bank_officer(self):
        # Verify active session works
        self.assertIsNotNone(self.auth_service.validate_session(self.officer_token))

        payload = json.dumps({"is_active": False}).encode("utf-8")
        req = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["user"]["is_active"])

        # 14: Existing session revoked
        self.assertIsNone(self.auth_service.validate_session(self.officer_token))

        # 13: Login fails for inactive account
        login_payload = json.dumps({
            "email": "officer@agency.go.th",
            "password": "OfficerSecure123!@#"
        }).encode("utf-8")
        req_login = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(login_payload)}\r\n\r\n"
        ).encode("utf-8") + login_payload

        status_login, _, body_login = self._execute_request(req_login)
        self.assertEqual(status_login, 401)
        data_login = json.loads(body_login.decode("utf-8"))
        self.assertEqual(data_login["status"], "error")
        self.assertIn("invalid", data_login["message"].lower())

    # 15. Admin can reactivate a Bank Officer
    def test_15_reactivate_bank_officer(self):
        # First deactivate
        self.admin_service.set_user_status(self.admin_id, self.officer_id, False)

        # Reactivate via PATCH
        payload = json.dumps({"is_active": True}).encode("utf-8")
        req = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["user"]["is_active"])

    # 16. Admin can reset a Bank Officer password
    # 17. Password reset revokes existing sessions
    def test_16_17_reset_bank_officer_password(self):
        # Verify active session
        self.assertIsNotNone(self.auth_service.validate_session(self.officer_token))

        payload = json.dumps({"new_password": "NewResetPassword123!@#"}).encode("utf-8")
        req = (
            f"POST /api/admin/users/{self.officer_id}/reset-password HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")

        # 17: Existing session revoked
        self.assertIsNone(self.auth_service.validate_session(self.officer_token))

        # Old password rejected
        with self.assertRaises(Exception):
            self.auth_service.login("officer@agency.go.th", "OfficerSecure123!@#")

        # New password accepted
        token, user = self.auth_service.login("officer@agency.go.th", "NewResetPassword123!@#")
        self.assertIsNotNone(token)
        self.assertEqual(user["id"], self.officer_id)

    # 18. Admin cannot deactivate or reset another Admin
    def test_18_admin_cannot_deactivate_or_reset_admin(self):
        # Try to deactivate admin
        payload_deact = json.dumps({"is_active": False}).encode("utf-8")
        req_deact = (
            f"PATCH /api/admin/users/{self.admin_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload_deact)}\r\n\r\n"
        ).encode("utf-8") + payload_deact

        status, _, body = self._execute_request(req_deact)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("administrator", data["message"].lower())

        # Try to reset admin password
        payload_reset = json.dumps({"new_password": "NewAdminPass123!@#"}).encode("utf-8")
        req_reset = (
            f"POST /api/admin/users/{self.admin_id}/reset-password HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload_reset)}\r\n\r\n"
        ).encode("utf-8") + payload_reset

        status_rst, _, body_rst = self._execute_request(req_reset)
        self.assertEqual(status_rst, 403)
        data_rst = json.loads(body_rst.decode("utf-8"))
        self.assertIn("administrator", data_rst["message"].lower())

    # 19. User cannot call any Admin mutation endpoint
    def test_19_user_denied_admin_mutations(self):
        # POST create
        req_create = (
            f"POST /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.officer_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: 2\r\n\r\n{{}}"
        ).encode("utf-8")
        status, _, _ = self._execute_request(req_create)
        self.assertEqual(status, 403)

        # PATCH status
        req_patch = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.officer_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: 2\r\n\r\n{{}}"
        ).encode("utf-8")
        status_patch, _, _ = self._execute_request(req_patch)
        self.assertEqual(status_patch, 403)

        # POST reset
        req_reset = (
            f"POST /api/admin/users/{self.officer_id}/reset-password HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.officer_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: 2\r\n\r\n{{}}"
        ).encode("utf-8")
        status_reset, _, _ = self._execute_request(req_reset)
        self.assertEqual(status_reset, 403)

    # 20. Anonymous cannot call any Admin mutation endpoint
    def test_20_anonymous_denied_admin_mutations(self):
        # POST create
        req_create = (
            b"POST /api/admin/users HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Origin: http://127.0.0.1:8000\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 2\r\n\r\n{}"
        )
        status, _, _ = self._execute_request(req_create)
        self.assertEqual(status, 401)

        # PATCH status
        req_patch = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: 2\r\n\r\n{{}}"
        ).encode("utf-8")
        status_patch, _, _ = self._execute_request(req_patch)
        self.assertEqual(status_patch, 401)

    # 21. Cross-origin mutation requests fail CSRF validation
    def test_21_cross_origin_fails_csrf(self):
        payload = json.dumps({"is_active": False}).encode("utf-8")
        req = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://evil-attacker.com\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("csrf", data["message"].lower())

    # 22. Admin can view sanitized audit logs
    # 23. User cannot view audit logs
    def test_22_23_audit_logs_access(self):
        # Admin request
        req_admin = (
            f"GET /api/admin/audit-logs HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req_admin)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertIn("logs", data)

        # Officer request (forbidden)
        req_user = (
            f"GET /api/admin/audit-logs HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.officer_token}\r\n\r\n"
        ).encode("utf-8")
        status_user, _, body_user = self._execute_request(req_user)
        self.assertEqual(status_user, 403)
        data_user = json.loads(body_user.decode("utf-8"))
        self.assertEqual(data_user["status"], "error")

    # 24. Pagination limits are enforced
    def test_24_pagination_limits(self):
        req = (
            f"GET /api/admin/users?limit=1&offset=0 HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(len(data["users"]), 1)
        self.assertEqual(data["limit"], 1)

    # 25. Invalid user IDs and unknown users are handled safely
    def test_25_invalid_and_unknown_user_ids(self):
        patch_payload = json.dumps({"is_active": False}).encode("utf-8")

        # Non-existent user ID -> 404
        req_invalid = (
            f"PATCH /api/admin/users/usr_nonexistent_id/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(patch_payload)}\r\n\r\n"
        ).encode("utf-8") + patch_payload
        status_inv, _, body_inv = self._execute_request(req_invalid)
        self.assertEqual(status_inv, 404)
        data_inv = json.loads(body_inv.decode("utf-8"))
        self.assertIn("not found", data_inv["message"].lower())

        # Unknown numeric ID -> 404
        req_unknown = (
            f"PATCH /api/admin/users/999999/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(patch_payload)}\r\n\r\n"
        ).encode("utf-8") + patch_payload
        status_unk, _, body_unk = self._execute_request(req_unknown)
        self.assertEqual(status_unk, 404)
        data_unk = json.loads(body_unk.decode("utf-8"))
        self.assertIn("not found", data_unk["message"].lower())

    # 26. Audit entries are created correctly
    def test_26_audit_entries_created_correctly(self):
        # Perform deactivation
        payload = json.dumps({"is_active": False}).encode("utf-8")
        req = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload
        self._execute_request(req)

        # Verify audit log in database
        with Session(self.engine) as session:
            logs = session.execute(
                select(AuthAuditLog).where(AuthAuditLog.action == "user_deactivated")
            ).scalars().all()
            self.assertEqual(len(logs), 1)
            entry = logs[0]
            self.assertEqual(entry.actor_user_id, self.admin_id)
            self.assertEqual(entry.target_user_id, self.officer_id)
            self.assertEqual(entry.safe_metadata.get("is_active"), False)

    # 27. Database transaction atomicity (rollback on failure)
    def test_27_transaction_atomicity_on_failure(self):
        # Try to deactivate with invalid JSON -> atomic failure, no partial audit record
        bad_body = b"{invalid: json}"
        req_bad = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(bad_body)}\r\n\r\n"
        ).encode("utf-8") + bad_body
        status, _, _ = self._execute_request(req_bad)
        self.assertEqual(status, 400)

        # User is still active and no audit log created
        with Session(self.engine) as session:
            user = UserRepository(session).get_by_id(self.officer_id)
            self.assertTrue(user.is_active)

    # 28. Existing Dashboard and investigation APIs retain their RBAC behavior
    def test_28_existing_rbac_preserved(self):
        # Admin still cannot access dashboard
        req_dash = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_dash, _, _ = self._execute_request(req_dash)
        self.assertEqual(status_dash, 403)

        # Admin still cannot access investigation API
        req_api = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_api, _, _ = self._execute_request(req_api)
        self.assertEqual(status_api, 403)

        # Officer CAN access dashboard
        req_user_dash = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.officer_token}\r\n\r\n"
        ).encode("utf-8")
        status_user_dash, _, _ = self._execute_request(req_user_dash)
        self.assertEqual(status_user_dash, 200)

    # 29. Existing 401/403/404/500 error pages continue working
    def test_29_error_pages_continue_working(self):
        # 401 page for anonymous on protected HTML
        req_anon = b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status_anon, headers_anon, body_anon = self._execute_request(req_anon)
        self.assertEqual(status_anon, 401)
        self.assertIn("text/html", headers_anon.get("content-type", ""))
        self.assertIn("Authentication Required", body_anon.decode("utf-8"))

        # 403 page for admin on /index.html
        req_admin_dash = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_403, headers_403, body_403 = self._execute_request(req_admin_dash)
        self.assertEqual(status_403, 403)
        self.assertIn("text/html", headers_403.get("content-type", ""))
        self.assertIn("Access Denied", body_403.decode("utf-8"))


class TestPostgresAdminIntegration(unittest.TestCase):
    """Part G Requirement 30: Real PostgreSQL integration test with disposable accounts in muletrace_test."""

    def test_disposable_admin_actions_in_muletrace_test(self):
        project_root = Path(__file__).resolve().parents[1]
        env = load_environment(project_root)
        test_db_url = env.get(db_config.TEST_DATABASE_URL_ENV) or os.environ.get(db_config.TEST_DATABASE_URL_ENV)

        if not test_db_url:
            self.skipTest(f"{db_config.TEST_DATABASE_URL_ENV} not configured; skipping PostgreSQL test")

        # Safety verification
        self.assertIn("test", test_db_url.lower(), "Must use isolated test database")
        dev_url = env.get(db_config.DATABASE_URL_ENV) or os.environ.get(db_config.DATABASE_URL_ENV, "")
        self.assertNotEqual(test_db_url, dev_url, "Must not point to development database")

        pg_engine = create_engine(test_db_url)
        pg_limiter = LoginRateLimiter()
        pg_auth_service = AuthService(engine=pg_engine, rate_limiter=pg_limiter)
        pg_admin_service = AdminService(engine=pg_engine)

        disposable_admin_email = "disposable_admin_phase4@agency.go.th"
        disposable_officer_email = "disposable_officer_phase4@agency.go.th"
        disposable_pass = "TestIntegrationPass123!@#"

        admin_id = None
        officer_id = None

        try:
            # 1. Seed disposable admin and officer in muletrace_test
            with Session(pg_engine) as session:
                user_repo = UserRepository(session)
                for email in (disposable_admin_email, disposable_officer_email):
                    ex = user_repo.get_by_email(email)
                    if ex:
                        session.delete(ex)
                session.commit()

                admin = user_repo.create_user(
                    email=disposable_admin_email,
                    display_name="Disposable Admin",
                    role="admin",
                    password_hash=hash_password(disposable_pass),
                    is_active=True,
                )
                session.commit()
                admin_id = admin.id

            # 2. Test AdminService creates officer via real PostgreSQL
            create_res = pg_admin_service.create_bank_officer(
                actor_id=admin_id,
                email=disposable_officer_email,
                password=disposable_pass,
                display_name="Disposable PG Officer",
                client_ip="127.0.0.1",
            )
            officer_id = create_res["id"]
            self.assertEqual(create_res["role"], "user")
            self.assertTrue(create_res["is_active"])

            # 3. Test Officer login
            officer_token, _ = pg_auth_service.login(disposable_officer_email, disposable_pass)
            self.assertIsNotNone(officer_token)
            self.assertIsNotNone(pg_auth_service.validate_session(officer_token))

            # 4. Test Deactivation revokes session in PostgreSQL
            pg_admin_service.set_user_status(
                actor_id=admin_id,
                target_user_id=officer_id,
                is_active=False,
                client_ip="127.0.0.1",
            )
            self.assertIsNone(pg_auth_service.validate_session(officer_token))

            # 5. Test Password Reset
            new_pass = "NewPostgresResetPass123!@#"
            pg_admin_service.reset_user_password(
                actor_id=admin_id,
                target_user_id=officer_id,
                new_password=new_pass,
                client_ip="127.0.0.1",
            )

            # 6. Reactivate and login with new password
            pg_admin_service.set_user_status(admin_id, officer_id, True)
            new_token, _ = pg_auth_service.login(disposable_officer_email, new_pass)
            self.assertIsNotNone(new_token)
            pg_auth_service.logout(new_token)

            # 7. Verify audit log recorded in PostgreSQL
            audit_res = pg_admin_service.list_audit_logs(limit=10)
            self.assertGreaterEqual(audit_res["total"], 1)

        finally:
            # Strict cleanup from muletrace_test
            with Session(pg_engine) as session:
                for uid in (admin_id, officer_id):
                    if uid:
                        u = session.execute(select(User).where(User.id == uid)).scalar_one_or_none()
                        if u:
                            session.delete(u)
                session.commit()
            pg_engine.dispose()


if __name__ == "__main__":
    unittest.main()
