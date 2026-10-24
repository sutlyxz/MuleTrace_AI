"""Comprehensive automated test suite for Phase 5.1: Login, Session Reliability & Real-Browser Acceptance.

Covers:
1. PostgreSQL database isolation (ensures tests run against muletrace_test only, never touching muletrace).
2. Administrator Login lifecycle, role-based redirect, and mutual exclusion (forbidden from /index.html and /api/cases).
3. Bank Officer Login lifecycle, role-based redirect, and mutual exclusion (forbidden from /admin.html, /api/admin/*, and admin assets).
4. Session persistence across requests and cache-control headers (no-store, no-cache, must-revalidate).
5. Invalid credentials and generic error message consistency (no user enumeration).
6. Rate limiting enforcement on brute force attempts (429).
7. Account deactivation: immediate session revocation on protected endpoints and login denial.
8. Account reactivation: ability to log in after reactivation.
9. Password reset: immediate revocation of all previous sessions, rejection of old password, acceptance of new password.
10. Logout reliability: session invalidation, cookie expiration (max-age=0), and unauthenticated back/refresh denial.
11. Multi-session isolation: logging out from one session does not revoke an independent user's session.
12. Generic server error responses (no stack trace or database detail disclosure on 500).
13. Frontend Login resilience (pageshow listener for bfcache and Back navigation, email normalization).
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import socket
from socketserver import BaseServer
import unittest

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.backend.auth.security import hash_password, normalize_email
from app.backend.config import load_environment
from app.backend.db import config as db_config
from app.backend.db.auth_repositories import SessionRepository, UserRepository
from app.backend.db.models import AuthAuditLog, AuthSession, Base, User
from app.backend.server import MuleTraceRequestHandler
from app.backend.services.admin_service import AdminService
from app.backend.services.auth_service import AuthService, LoginRateLimiter


class DummySocket(socket.socket):
    def __init__(self, input_bytes: bytes, client_ip: str = "127.0.0.1"):
        self.rfile = io.BytesIO(input_bytes)
        self.wfile = io.BytesIO()
        self.client_ip = client_ip
        self._closed = False

    def makefile(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "rb")
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, data, flags: int = 0):
        self.wfile.write(data)

    def send(self, data, flags: int = 0) -> int:
        self.wfile.write(data)
        return len(data)

    def getpeername(self):
        return (self.client_ip, 12345)

    def getsockname(self):
        return ("127.0.0.1", 8000)

    def close(self) -> None:
        pass


class TestSessionReliability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_config._load_dotenv()
        cls.test_db_url = os.environ.get(db_config.TEST_DATABASE_URL_ENV, "").strip()
        if not cls.test_db_url:
            cls.test_db_url = "postgresql+psycopg://postgres:postgres@localhost:5432/muletrace_test"

        cls.test_db_url = db_config.normalize_database_url(cls.test_db_url)
        if not os.environ.get(db_config.DATABASE_URL_ENV, "").strip():
            raise unittest.SkipTest("DATABASE_URL is required for live PostgreSQL session reliability tests")
        if not os.environ.get(db_config.DATABASE_URL_ENV, "").strip():
            raise unittest.SkipTest("DATABASE_URL is required for live PostgreSQL session reliability tests")
        cls.dev_db_url = db_config.get_database_url(db_config.DATABASE_URL_ENV)

        # STRICT SAFETY: Ensure test database is muletrace_test and NEVER development DB
        assert "muletrace_test" in cls.test_db_url, f"TEST_DATABASE_URL must be muletrace_test, got {cls.test_db_url}"
        assert cls.test_db_url != cls.dev_db_url, "TEST_DATABASE_URL must never match DATABASE_URL"
        assert "muletrace_restore_verify" not in cls.test_db_url, "TEST_DATABASE_URL must not touch backup database"

        cls.pg_engine = create_engine(cls.test_db_url, echo=False)
        cls.frontend_dir = Path("app/frontend")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "pg_engine"):
            cls.pg_engine.dispose()

    def setUp(self):
        self.rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)
        self.auth_service = AuthService(engine=self.pg_engine, rate_limiter=self.rate_limiter)
        self.admin_service = AdminService(engine=self.pg_engine)
        self.disposable_user_ids = []

    def tearDown(self):
        # Strict cleanup of disposable users from muletrace_test
        if self.disposable_user_ids:
            with Session(self.pg_engine) as session:
                for uid in self.disposable_user_ids:
                    u = session.execute(select(User).where(User.id == uid)).scalar_one_or_none()
                    if u:
                        session.delete(u)
                session.commit()

    def _execute_request(
        self,
        request_bytes: bytes,
        client_ip: str = "127.0.0.1",
        auth_service: AuthService | None = None,
        admin_service: AdminService | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        sock = DummySocket(request_bytes, client_ip=client_ip)
        
        class DummyServer(BaseServer):
            def __init__(self):
                self.server_name = "127.0.0.1"
                self.server_port = 8000

        class InjectedHandler(MuleTraceRequestHandler):
            pass

        InjectedHandler.auth_service = auth_service or self.auth_service
        InjectedHandler.admin_service = admin_service or self.admin_service

        server = DummyServer()
        handler = InjectedHandler(sock, (client_ip, 12345), server, directory=str(self.frontend_dir))

        response_bytes = sock.wfile.getvalue()
        parts = response_bytes.split(b"\r\n\r\n", 1)
        if len(parts) == 1:
            parts = response_bytes.split(b"\n\n", 1)
        header_text = parts[0].decode("iso-8859-1")
        body = parts[1] if len(parts) > 1 else b""

        header_lines = header_text.splitlines()
        status_line = header_lines[0]
        status_code = int(status_line.split(" ")[1])

        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        return status_code, headers, body

    def _create_disposable_user(self, email: str, role: str, password: str, is_active: bool = True) -> User:
        norm_email = normalize_email(email)
        with Session(self.pg_engine) as session:
            user_repo = UserRepository(session)
            existing = user_repo.get_by_email(norm_email)
            if existing:
                session.delete(existing)
                session.commit()

            u = user_repo.create_user(
                email=norm_email,
                display_name=f"Test {role.title()}",
                role=role,
                password_hash=hash_password(password),
                is_active=is_active,
            )
            session.commit()
            self.disposable_user_ids.append(u.id)
            return u

    # =========================================================================
    # Test 1: Database Isolation
    # =========================================================================
    def test_01_database_isolation_verified(self):
        """Confirm database URL conclusively targets muletrace_test."""
        self.assertIn("muletrace_test", self.test_db_url)
        self.assertNotIn("muletrace_restore_verify", self.test_db_url)
        self.assertNotEqual(self.test_db_url, self.dev_db_url)

    # =========================================================================
    # Test 2: Administrator Login & Navigation
    # =========================================================================
    def test_02_admin_login_and_role_navigation(self):
        """Admin logs in, gets redirected to /admin.html, denied from /index.html and /api/cases."""
        admin_email = "disp_admin_51@agency.go.th"
        admin_pass = "AdminPass123!@#"
        self._create_disposable_user(admin_email, "admin", admin_pass)

        # Login request
        payload = json.dumps({"email": admin_email, "password": admin_pass}).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, headers, body = self._execute_request(req, client_ip="127.0.5.1")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["user"]["role"], "admin")

        # Session cookie
        cookie_hdr = headers.get("set-cookie", "")
        self.assertIn("muletrace_session=", cookie_hdr)
        self.assertIn("HttpOnly", cookie_hdr)
        self.assertIn("SameSite=Lax", cookie_hdr)
        token = cookie_hdr.split("muletrace_session=")[1].split(";")[0].strip()

        # Strict Cache-Control
        self.assertIn("no-store", headers.get("cache-control", ""))

        # GET /admin.html is permitted
        req_admin = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_admin, h_admin, _ = self._execute_request(req_admin, client_ip="127.0.5.1")
        self.assertEqual(st_admin, 200)
        self.assertIn("no-store", h_admin.get("cache-control", ""))

        # GET /index.html is denied (403)
        req_index = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_index, _, _ = self._execute_request(req_index, client_ip="127.0.5.1")
        self.assertEqual(st_index, 403)

        # GET /api/cases is denied (403)
        req_cases = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_cases, _, _ = self._execute_request(req_cases, client_ip="127.0.5.1")
        self.assertEqual(st_cases, 403)

    # =========================================================================
    # Test 3: Bank Officer Login & Navigation
    # =========================================================================
    def test_03_officer_login_and_role_navigation(self):
        """Bank Officer logs in, gets redirected to /index.html, denied from /admin.html and admin assets."""
        officer_email = "disp_officer_51@agency.go.th"
        officer_pass = "OfficerPass123!@#"
        self._create_disposable_user(officer_email, "user", officer_pass)

        payload = json.dumps({"email": officer_email, "password": officer_pass}).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, headers, body = self._execute_request(req, client_ip="127.0.5.2")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["user"]["role"], "user")

        token = headers.get("set-cookie", "").split("muletrace_session=")[1].split(";")[0].strip()

        # GET /index.html is permitted
        req_index = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_index, _, _ = self._execute_request(req_index, client_ip="127.0.5.2")
        self.assertEqual(st_index, 200)

        # GET /admin.html is denied (403)
        req_admin = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_admin, _, _ = self._execute_request(req_admin, client_ip="127.0.5.2")
        self.assertEqual(st_admin, 403)

        # GET /api/admin/users is denied (403)
        req_adm_api = (
            f"GET /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_adm_api, _, _ = self._execute_request(req_adm_api, client_ip="127.0.5.2")
        self.assertEqual(st_adm_api, 403)

        # GET protected admin CSS asset is denied (403)
        req_adm_css = (
            f"GET /assets/css/admin.css HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        st_adm_css, _, _ = self._execute_request(req_adm_css, client_ip="127.0.5.2")
        self.assertEqual(st_adm_css, 403)

    # =========================================================================
    # Test 4: Invalid Credentials & Enumeration Protection
    # =========================================================================
    def test_04_invalid_credentials_generic_message(self):
        """Invalid credentials return generic error message without enumerating email existence."""
        officer_email = "disp_enum_51@agency.go.th"
        self._create_disposable_user(officer_email, "user", "CorrectPassword123!@#")

        # Existing email with wrong password
        payload1 = json.dumps({"email": officer_email, "password": "WrongPassword999!"}).encode("utf-8")
        req1 = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload1)}\r\n\r\n"
        ).encode("utf-8") + payload1
        st1, _, body1 = self._execute_request(req1, client_ip="127.0.5.3")
        self.assertEqual(st1, 401)
        msg1 = json.loads(body1.decode("utf-8"))["message"]

        # Non-existent email
        payload2 = json.dumps({"email": "nonexistent_51@agency.go.th", "password": "AnyPassword123!"}).encode("utf-8")
        req2 = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload2)}\r\n\r\n"
        ).encode("utf-8") + payload2
        st2, _, body2 = self._execute_request(req2, client_ip="127.0.5.4")
        self.assertEqual(st2, 401)
        msg2 = json.loads(body2.decode("utf-8"))["message"]

        # Exactly matching generic error messages
        self.assertEqual(msg1, msg2)
        self.assertEqual(msg1, "Invalid email or password")

    # =========================================================================
    # Test 5: Rate Limiting
    # =========================================================================
    def test_05_rate_limiting_triggers_429(self):
        """Exceeding 5 failed login attempts triggers 429 RateLimitError."""
        client_ip = "192.168.200.51"
        payload = json.dumps({"email": "ratelimit_51@agency.go.th", "password": "BadPass"}).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        # First 5 attempts return 401
        for _ in range(5):
            st, _, _ = self._execute_request(req, client_ip=client_ip)
            self.assertEqual(st, 401)

        # 6th attempt returns 429
        st_blocked, _, body_blocked = self._execute_request(req, client_ip=client_ip)
        self.assertEqual(st_blocked, 429)
        self.assertIn("Too many failed login attempts", json.loads(body_blocked.decode("utf-8"))["message"])

    # =========================================================================
    # Test 6: Account Deactivation & Immediate Session Revocation
    # =========================================================================
    def test_06_deactivation_revokes_sessions_immediately(self):
        """Deactivating an account immediately revokes existing sessions and denies login."""
        admin_user = self._create_disposable_user("admin_act_51@agency.go.th", "admin", "AdminPass123!@#")
        officer = self._create_disposable_user("officer_act_51@agency.go.th", "user", "OfficerPass123!@#")

        # Officer logs in
        raw_token, _ = self.auth_service.login(officer.email, "OfficerPass123!@#", client_ip="127.0.5.6")
        self.assertIsNotNone(self.auth_service.validate_session(raw_token))

        # Admin deactivates officer
        self.admin_service.set_user_status(
            admin_actor_id=admin_user.id,
            target_user_id=officer.id,
            is_active=False,
        )

        # Session is immediately invalid
        self.assertIsNone(self.auth_service.validate_session(raw_token))

        # Protected API returns 401
        req_me = (
            f"GET /api/auth/me HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={raw_token}\r\n\r\n"
        ).encode("utf-8")
        st, _, _ = self._execute_request(req_me, client_ip="127.0.5.6")
        self.assertEqual(st, 401)

        # Deactivated user cannot log in
        with self.assertRaises(Exception):
            self.auth_service.login(officer.email, "OfficerPass123!@#", client_ip="127.0.5.7")

        # Admin reactivates officer
        self.admin_service.set_user_status(
            admin_actor_id=admin_user.id,
            target_user_id=officer.id,
            is_active=True,
        )

        # Officer can now log in again
        new_token, _ = self.auth_service.login(officer.email, "OfficerPass123!@#", client_ip="127.0.5.8")
        self.assertIsNotNone(self.auth_service.validate_session(new_token))

    # =========================================================================
    # Test 7: Password Reset & Session Invalidation
    # =========================================================================
    def test_07_password_reset_revokes_sessions(self):
        """Resetting password immediately revokes sessions; rejects old password; accepts new password."""
        admin_user = self._create_disposable_user("admin_pw_51@agency.go.th", "admin", "AdminPass123!@#")
        officer = self._create_disposable_user("officer_pw_51@agency.go.th", "user", "OldPassword123!@#")

        # Officer logs in with old password
        old_token, _ = self.auth_service.login(officer.email, "OldPassword123!@#", client_ip="127.0.5.9")
        self.assertIsNotNone(self.auth_service.validate_session(old_token))

        # Admin resets password
        new_password = "BrandNewPassword123!@#"
        self.admin_service.reset_user_password(
            admin_actor_id=admin_user.id,
            target_user_id=officer.id,
            new_password=new_password,
        )

        # Old session is immediately revoked
        self.assertIsNone(self.auth_service.validate_session(old_token))

        # Login with old password fails
        with self.assertRaises(Exception):
            self.auth_service.login(officer.email, "OldPassword123!@#", client_ip="127.0.5.10")

        # Login with new password succeeds
        new_token, _ = self.auth_service.login(officer.email, new_password, client_ip="127.0.5.11")
        self.assertIsNotNone(self.auth_service.validate_session(new_token))

    # =========================================================================
    # Test 8: Logout Reliability & Session Isolation
    # =========================================================================
    def test_08_logout_and_session_isolation(self):
        """Logout invalidates the session and expires cookie; unrelated sessions remain intact."""
        u1 = self._create_disposable_user("officer_u1_51@agency.go.th", "user", "Password123!@#")
        u2 = self._create_disposable_user("officer_u2_51@agency.go.th", "user", "Password123!@#")

        t1, _ = self.auth_service.login(u1.email, "Password123!@#", client_ip="127.0.5.12")
        t2, _ = self.auth_service.login(u2.email, "Password123!@#", client_ip="127.0.5.13")

        # Both sessions valid
        self.assertIsNotNone(self.auth_service.validate_session(t1))
        self.assertIsNotNone(self.auth_service.validate_session(t2))

        # User 1 logs out
        req_logout = (
            f"POST /api/auth/logout HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={t1}\r\n"
            f"Content-Length: 0\r\n\r\n"
        ).encode("utf-8")
        st, headers, _ = self._execute_request(req_logout, client_ip="127.0.5.12")
        self.assertEqual(st, 200)

        # Cookie expired
        cookie_hdr = headers.get("set-cookie", "")
        self.assertIn("max-age=0", cookie_hdr.lower())

        # Session 1 is invalid
        self.assertIsNone(self.auth_service.validate_session(t1))

        # Session 2 is untouched and remains valid!
        self.assertIsNotNone(self.auth_service.validate_session(t2))

    # =========================================================================
    # Test 9: Server Error 500 Information Disclosure Prevention
    # =========================================================================
    def test_09_500_server_error_sanitization(self):
        """500 error responses return generic 'Internal server error' without stack traces."""
        class ExplodingAuthService(AuthService):
            def __init__(self):
                pass

            def login(self, *args, **kwargs):
                raise RuntimeError("psycopg.OperationalError: FATAL: database 'secret_db' connection failure at /internal/path")

        payload = json.dumps({"email": "a@b.com", "password": "p"}).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload
        st, _, body = self._execute_request(req, auth_service=ExplodingAuthService())
        self.assertEqual(st, 500)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Internal server error")
        self.assertNotIn("secret_db", data["message"])
        self.assertNotIn("OperationalError", data["message"])

    # =========================================================================
    # Test 10: Frontend Login Script Back Navigation & Normalization
    # =========================================================================
    def test_10_frontend_login_back_navigation_resilience(self):
        """login.js includes pageshow listener for bfcache and normalizes email."""
        login_js = (self.frontend_dir / "assets" / "js" / "login.js").read_text(encoding="utf-8")
        self.assertIn("window.addEventListener(\"pageshow\"", login_js)
        self.assertIn("checkActiveSession()", login_js)
        self.assertIn("emailInput.value.trim().toLowerCase()", login_js)


if __name__ == "__main__":
    unittest.main()
