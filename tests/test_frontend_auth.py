"""Unit and integration tests for Phase 3 Frontend Authentication Integration.

Covers:
- DOM structure preservation for login.html and index.html
- Elimination of fake sessionStorage bypass
- Real PostgreSQL / SQLite test engine authentication via POST /api/auth/login
- Role-based redirect contract (admin -> admin.html, user -> index.html)
- Disposable user test in muletrace_test database (when TEST_DATABASE_URL is set)
- Rejection of invalid credentials and disabled accounts
- Session cookie attributes (HttpOnly, SameSite=Lax, Path=/)
- GET /api/auth/me session inspection
- POST /api/auth/logout behavior and CSRF verification
- Rate limiting protection (429)
- Mutually exclusive RBAC enforcement on /admin.html vs /index.html and investigation APIs
- Temporary Admin landing page safety constraints
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import socket
from socketserver import BaseServer
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.backend.auth.security import hash_password
from app.backend.config import load_environment
from app.backend.db import config as db_config
from app.backend.db.auth_repositories import UserRepository
from app.backend.db.models import AuthAuditLog, AuthSession, Base, User
from app.backend.server import MuleTraceRequestHandler
from app.backend.services.auth_service import AuthService, LoginRateLimiter


def create_inmemory_auth_service() -> AuthService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[t] for t in ("users", "auth_sessions", "auth_audit_logs")],
    )
    # Fresh isolated rate limiter per service instance
    rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)
    service = AuthService(engine=engine, rate_limiter=rate_limiter)

    with Session(engine) as session:
        user_repo = UserRepository(session)
        user_repo.create_user(
            email="test_officer@agency.go.th",
            display_name="Bank Officer",
            role="user",
            password_hash=hash_password("OfficerSecure123!@#"),
            is_active=True,
        )
        user_repo.create_user(
            email="test_admin@agency.go.th",
            display_name="System Admin",
            role="admin",
            password_hash=hash_password("AdminSecure123!@#"),
            is_active=True,
        )
        user_repo.create_user(
            email="disabled_officer@agency.go.th",
            display_name="Disabled Officer",
            role="user",
            password_hash=hash_password("DisabledPass123!@#"),
            is_active=False,
        )
        session.commit()

    return service


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


class DummyServer(BaseServer):
    def __init__(self):
        self.server_name = "127.0.0.1"
        self.server_port = 8000


class TestFrontendAuthIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.frontend_dir = str(cls.project_root / "app" / "frontend")

    def setUp(self):
        self.auth_service = create_inmemory_auth_service()

    def _execute_request(
        self,
        request_bytes: bytes,
        auth_service: AuthService | None = None,
        client_ip: str = "127.0.0.1",
    ) -> tuple[int, dict[str, str], bytes]:
        service = auth_service or self.auth_service
        socket = DummySocket(request_bytes, client_ip=client_ip)
        server = DummyServer()

        class InjectedHandler(MuleTraceRequestHandler):
            pass

        InjectedHandler.auth_service = service
        handler = InjectedHandler(socket, (client_ip, 12345), server, directory=self.frontend_dir)
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

    # 1. Login page DOM structure and preservation
    def test_login_page_dom_structure_preserved(self):
        login_html_path = Path(self.frontend_dir) / "login.html"
        self.assertTrue(login_html_path.exists())
        content = login_html_path.read_text(encoding="utf-8")

        # Essential forms and elements
        self.assertIn('id="loginForm"', content)
        self.assertIn('id="emailInput"', content)
        self.assertIn('id="passwordInput"', content)
        self.assertIn('id="submitBtn"', content)
        self.assertIn('id="feedbackAlert"', content)
        self.assertIn('id="togglePasswordBtn"', content)

        # Branding & layout structure
        self.assertIn('class="branding-column"', content)
        self.assertIn('class="form-column"', content)
        self.assertIn('class="language-switch"', content)

        # Confirm no public signup or registration forms
        self.assertNotIn("signup", content.lower())
        self.assertNotIn("register", content.lower())
        self.assertNotIn("create account", content.lower())

    # 2. Login JavaScript: no fake sessionStorage login bypass
    def test_login_js_no_fake_session_storage(self):
        login_js_path = Path(self.frontend_dir) / "assets" / "js" / "login.js"
        self.assertTrue(login_js_path.exists())
        content = login_js_path.read_text(encoding="utf-8")

        # Must not store auth tokens or set fake active session
        self.assertNotIn('sessionStorage.setItem("muletrace_auth_session"', content)
        self.assertNotIn('localStorage.setItem("muletrace_auth_session"', content)

        # Must call real backend endpoints
        self.assertIn("/api/auth/login", content)
        self.assertIn("/api/auth/me", content)
        self.assertIn("/api/auth/logout", content)
        self.assertIn('credentials: "same-origin"', content)

    # 3. Successful admin login sets cookie and returns admin role
    def test_admin_login_success_and_cookie(self):
        payload = json.dumps({
            "email": "test_admin@agency.go.th",
            "password": "AdminSecure123!@#"
        }).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["user"]["role"], "admin")
        self.assertEqual(data["user"]["email"], "test_admin@agency.go.th")

        # Cookie check
        set_cookie = headers.get("set-cookie", "")
        self.assertIn("muletrace_session=", set_cookie)
        self.assertIn("httponly", set_cookie.lower())
        self.assertIn("samesite=lax", set_cookie.lower())
        self.assertIn("path=/", set_cookie.lower())

    # 4. Successful user login sets cookie and returns user role
    def test_user_login_success_and_cookie(self):
        payload = json.dumps({
            "email": "test_officer@agency.go.th",
            "password": "OfficerSecure123!@#"
        }).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["user"]["role"], "user")
        self.assertEqual(data["user"]["email"], "test_officer@agency.go.th")

        set_cookie = headers.get("set-cookie", "")
        self.assertIn("muletrace_session=", set_cookie)
        self.assertIn("httponly", set_cookie.lower())

    # 5. Invalid credentials return 401 with generic message
    def test_invalid_credentials_returns_401(self):
        payload = json.dumps({
            "email": "test_officer@agency.go.th",
            "password": "WrongPassword!@#"
        }).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("Invalid email or password", data["message"])

    # 6. Disabled account returns 401 with generic message
    def test_disabled_account_returns_401(self):
        payload = json.dumps({
            "email": "disabled_officer@agency.go.th",
            "password": "DisabledPass123!@#"
        }).encode("utf-8")
        req = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("Invalid email or password", data["message"])

    # 7. GET /api/auth/me behavior (authenticated vs anonymous)
    def test_get_auth_me_authenticated_and_anonymous(self):
        # Anonymous -> 401
        req_anon = b"GET /api/auth/me HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status_anon, _, _ = self._execute_request(req_anon)
        self.assertEqual(status_anon, 401)

        # Authenticated -> 200 with user summary
        token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )
        req_auth = (
            f"GET /api/auth/me HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={token}\r\n\r\n"
        ).encode("utf-8")
        status_auth, _, body = self._execute_request(req_auth)
        self.assertEqual(status_auth, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["user"]["email"], "test_officer@agency.go.th")
        self.assertEqual(data["user"]["role"], "user")

    # 8. Logout invalidates session and clears cookie
    def test_logout_invalidates_session_and_clears_cookie(self):
        token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )
        self.assertIsNotNone(self.auth_service.validate_session(token))

        req = (
            f"POST /api/auth/logout HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Referer: http://127.0.0.1:8000/index.html\r\n"
            f"Cookie: muletrace_session={token}\r\n"
            f"Content-Length: 0\r\n\r\n"
        ).encode("utf-8")

        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")

        # Cookie cleared
        set_cookie = headers.get("set-cookie", "")
        self.assertIn("max-age=0", set_cookie.lower())

        # Session invalidated
        self.assertIsNone(self.auth_service.validate_session(token))

    # 9. CSRF rejection on logout
    def test_csrf_rejection_on_logout(self):
        token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )
        req = (
            f"POST /api/auth/logout HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://evil-attacker.com\r\n"
            f"Cookie: muletrace_session={token}\r\n"
            f"Content-Length: 0\r\n\r\n"
        ).encode("utf-8")

        status, _, body = self._execute_request(req)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("CSRF verification failed", data["message"])

        # Session must remain valid after rejected CSRF attempt
        self.assertIsNotNone(self.auth_service.validate_session(token))

    # 10. Rate limiting behavior (429)
    def test_rate_limiting_triggers_429(self):
        limiter_ip = "192.168.100.99"
        for _ in range(5):
            payload = json.dumps({
                "email": "test_officer@agency.go.th",
                "password": "WrongPassword"
            }).encode("utf-8")
            req = (
                f"POST /api/auth/login HTTP/1.1\r\n"
                f"Host: 127.0.0.1:8000\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n"
            ).encode("utf-8") + payload
            self._execute_request(req, client_ip=limiter_ip)

        # 6th attempt must trigger 429
        payload = json.dumps({
            "email": "test_officer@agency.go.th",
            "password": "OfficerSecure123!@#"
        }).encode("utf-8")
        req_blocked = (
            f"POST /api/auth/login HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8") + payload

        status, _, body = self._execute_request(req_blocked, client_ip=limiter_ip)
        self.assertEqual(status, 429)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("Too many failed login attempts", data["message"])

    # 11. Role-based route access: /admin.html vs /index.html
    def test_role_based_access_to_landing_pages(self):
        admin_token, _ = self.auth_service.login(
            "test_admin@agency.go.th", "AdminSecure123!@#", client_ip="127.0.0.1"
        )
        user_token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )

        # Anonymous to admin.html -> 401
        req_anon_admin = b"GET /admin.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req_anon_admin)
        self.assertEqual(status, 401)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("Authentication Required", body.decode("utf-8"))

        # User to admin.html -> 403 Forbidden
        req_user_admin = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={user_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req_user_admin)
        self.assertEqual(status, 403)
        self.assertIn("text/html", headers.get("content-type", ""))
        body_str = body.decode("utf-8")
        self.assertIn("Access Denied", body_str)
        self.assertIn("/index.html", body_str)

        # Admin to admin.html -> 200 OK
        req_admin_admin = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req_admin_admin)
        self.assertEqual(status, 200)
        self.assertIn(b"Admin Portal", body)

        # Admin to index.html -> 403 Forbidden (Admin cannot access investigation dashboard)
        req_admin_index = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req_admin_index)
        self.assertEqual(status, 403)
        self.assertIn("text/html", headers.get("content-type", ""))
        body_str = body.decode("utf-8")
        self.assertIn("Access Denied", body_str)
        self.assertIn("/admin.html", body_str)

        # User to index.html -> 200 OK
        req_user_index = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req_user_index)
        self.assertEqual(status, 200)

    # 11b. Root '/' RBAC redirection and dashboard protection
    def test_root_path_rbac_redirection(self):
        admin_token, _ = self.auth_service.login(
            "test_admin@agency.go.th", "AdminSecure123!@#", client_ip="127.0.0.1"
        )
        user_token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )

        # Anonymous visiting '/' -> 302 to /login.html
        req_anon = b"GET / HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, _ = self._execute_request(req_anon)
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("location"), "/login.html")

        # Admin visiting '/' -> 302 to /admin.html (Never exposes Dashboard)
        req_admin = (
            f"GET / HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, _ = self._execute_request(req_admin)
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("location"), "/admin.html")

        # User visiting '/' -> 200 OK (serves index.html)
        req_user = (
            f"GET / HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req_user)
        self.assertEqual(status, 200)
        self.assertTrue(b"<!doctype html>" in body.lower())

    # 11c. Strict no-store cache control headers on protected HTML and responses
    def test_strict_cache_control_headers(self):
        admin_token, _ = self.auth_service.login(
            "test_admin@agency.go.th", "AdminSecure123!@#", client_ip="127.0.0.1"
        )
        user_token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )

        requests_to_check = [
            (f"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={admin_token}\r\n\r\n".encode(), 403),
            (f"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={user_token}\r\n\r\n".encode(), 200),
            (f"GET /admin.html HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={admin_token}\r\n\r\n".encode(), 200),
            (f"GET /admin.html HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={user_token}\r\n\r\n".encode(), 403),
            (f"GET /api/cases HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={admin_token}\r\n\r\n".encode(), 403),
            (b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", 401),
        ]

        for req, expected_status in requests_to_check:
            status, headers, _ = self._execute_request(req)
            self.assertEqual(status, expected_status)
            cc = headers.get("cache-control", "").lower()
            self.assertIn("no-store", cc)
            self.assertIn("no-cache", cc)
            self.assertEqual(headers.get("pragma", "").lower(), "no-cache")

    # 11d. Case-insensitive and alternate URL path normalization bypass protection
    def test_alternate_path_normalization_bypasses(self):
        admin_token, _ = self.auth_service.login(
            "test_admin@agency.go.th", "AdminSecure123!@#", client_ip="127.0.0.1"
        )
        user_token, _ = self.auth_service.login(
            "test_officer@agency.go.th", "OfficerSecure123!@#", client_ip="127.0.0.1"
        )

        # Admin denied uppercase and query variants of /index.html
        for path in ["/INDEX.HTML", "/Index.html", "/index.html?bypass=1", "/INDEX.HTML?foo=bar"]:
            req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={admin_token}\r\n\r\n".encode()
            status, _, _ = self._execute_request(req)
            self.assertEqual(status, 403, f"Admin was not denied on alternate path: {path}")

        # User denied uppercase variants of /admin.html
        for path in ["/ADMIN.HTML", "/Admin.html", "/admin.html?bypass=1"]:
            req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={user_token}\r\n\r\n".encode()
            status, _, _ = self._execute_request(req)
            self.assertEqual(status, 403, f"User was not denied on admin path: {path}")

        # Admin allowed uppercase /ADMIN.HTML
        req_admin_upper = f"GET /ADMIN.HTML HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={admin_token}\r\n\r\n".encode()
        status, _, _ = self._execute_request(req_admin_upper)
        self.assertEqual(status, 200)

        # User allowed uppercase /INDEX.HTML
        req_user_upper = f"GET /INDEX.HTML HTTP/1.1\r\nHost: 127.0.0.1\r\nCookie: muletrace_session={user_token}\r\n\r\n".encode()
        status, _, _ = self._execute_request(req_user_upper)
        self.assertEqual(status, 200)

    # 11e. Server launcher entrypoint verification (scripts/run.py and run.bat)
    def test_run_launcher_entrypoint_matches_server(self):
        scripts_run_path = self.project_root / "scripts" / "run.py"
        self.assertTrue(scripts_run_path.exists())
        content = scripts_run_path.read_text(encoding="utf-8")
        # Confirms scripts/run.py executes app.backend.server
        self.assertIn("'app.backend.server'", content)

        # Confirms server.py has Windows socket reuse hardening
        server_py_path = self.project_root / "app" / "backend" / "server.py"
        server_content = server_py_path.read_text(encoding="utf-8")
        self.assertIn("allow_reuse_address", server_content)

    # 12. Admin Portal safety constraints (Phase 4.2)
    def test_admin_landing_page_safety_constraints(self):
        admin_html_path = Path(self.frontend_dir) / "admin.html"
        self.assertTrue(admin_html_path.exists())
        content = admin_html_path.read_text(encoding="utf-8")

        # Must link to admin css and admin js
        self.assertIn("assets/css/admin.css", content)
        self.assertIn("assets/js/admin.js", content)

        # Must NOT contain public signup
        self.assertNotIn("signup", content.lower())
        self.assertNotIn("register", content.lower())

        # Must NOT contain investigation data or case IDs
        self.assertNotIn("CASE001", content)
        self.assertNotIn("CASE002", content)
        self.assertNotIn("TX00", content)

        # Must contain logout and session verification
        self.assertIn("adminLogoutBtn", content)
        admin_js_path = Path(self.frontend_dir) / "assets" / "js" / "admin.js"
        self.assertTrue(admin_js_path.exists())
        js_content = admin_js_path.read_text(encoding="utf-8")
        self.assertIn("/api/auth/logout", js_content)
        self.assertIn("/api/auth/me", js_content)

    # 13. Investigation dashboard preservation (Part E)
    def test_investigation_dashboard_preserved(self):
        index_html_path = Path(self.frontend_dir) / "index.html"
        self.assertTrue(index_html_path.exists())
        content = index_html_path.read_text(encoding="utf-8")

        # Critical elements intact
        self.assertIn('id="page-overview"', content)
        self.assertIn('id="page-cases"', content)
        self.assertIn('id="page-trail"', content)
        self.assertIn('id="runAi"', content)
        self.assertIn('id="logoutBtn"', content)

        # Logout calls backend API
        self.assertIn("/api/auth/logout", content)
        self.assertIn('credentials: "same-origin"', content)

        # Fail-closed client-side session guard exists and redirects admin
        self.assertIn("/api/auth/me", content)
        self.assertIn('"admin.html"', content)

        # No-cache meta tags present to prevent browser disk caching
        self.assertIn('http-equiv="Cache-Control"', content)

        # No fake sessionStorage auth check
        self.assertNotIn('sessionStorage.getItem("muletrace_auth_session")', content)

    # 14. Real PostgreSQL integration test with disposable user in muletrace_test
    def test_disposable_user_in_muletrace_test(self):
        env = load_environment(self.project_root)
        test_db_url = env.get(db_config.TEST_DATABASE_URL_ENV) or os.environ.get(db_config.TEST_DATABASE_URL_ENV)

        if not test_db_url:
            self.skipTest(f"{db_config.TEST_DATABASE_URL_ENV} not configured in .env; skipping PostgreSQL integration test")

        # Safety check: URL must contain 'test' and differ from development database
        self.assertIn("test", test_db_url.lower(), "TEST_DATABASE_URL must be isolated test DB")
        dev_url = env.get(db_config.DATABASE_URL_ENV) or os.environ.get(db_config.DATABASE_URL_ENV, "")
        self.assertNotEqual(test_db_url, dev_url, "TEST_DATABASE_URL must differ from production/development DB")

        pg_engine = create_engine(test_db_url)
        pg_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)
        pg_service = AuthService(engine=pg_engine, rate_limiter=pg_limiter)

        disposable_email = "disposable_officer_phase3@agency.go.th"
        disposable_password = "DisposableOfficerPass123!@#"

        created_user_id = None
        try:
            # 1. Seed disposable bank officer into muletrace_test only
            with Session(pg_engine) as session:
                user_repo = UserRepository(session)
                existing = user_repo.get_by_email(disposable_email)
                if existing:
                    session.delete(existing)
                    session.commit()

                user = user_repo.create_user(
                    email=disposable_email,
                    display_name="Disposable Test Officer",
                    role="user",
                    password_hash=hash_password(disposable_password),
                    is_active=True,
                )
                session.commit()
                created_user_id = user.id

            # 2. Test login via HTTP request
            payload = json.dumps({
                "email": disposable_email,
                "password": disposable_password
            }).encode("utf-8")
            req_login = (
                f"POST /api/auth/login HTTP/1.1\r\n"
                f"Host: 127.0.0.1:8000\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n"
            ).encode("utf-8") + payload

            status, headers, body = self._execute_request(req_login, auth_service=pg_service, client_ip="127.0.0.2")
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data["user"]["role"], "user")
            self.assertEqual(data["user"]["email"], disposable_email)

            # Extract token from Set-Cookie header
            cookie_hdr = headers.get("set-cookie", "")
            self.assertIn("muletrace_session=", cookie_hdr)
            token = cookie_hdr.split("muletrace_session=")[1].split(";")[0].strip()

            # 3. Test GET /api/auth/me
            req_me = (
                f"GET /api/auth/me HTTP/1.1\r\n"
                f"Host: 127.0.0.1:8000\r\n"
                f"Cookie: muletrace_session={token}\r\n\r\n"
            ).encode("utf-8")
            status_me, _, body_me = self._execute_request(req_me, auth_service=pg_service, client_ip="127.0.0.2")
            self.assertEqual(status_me, 200)
            data_me = json.loads(body_me.decode("utf-8"))
            self.assertEqual(data_me["user"]["id"], created_user_id)

            # 4. Test GET /admin.html is forbidden (403) for bank officer
            req_admin = (
                f"GET /admin.html HTTP/1.1\r\n"
                f"Host: 127.0.0.1:8000\r\n"
                f"Cookie: muletrace_session={token}\r\n\r\n"
            ).encode("utf-8")
            status_admin, _, _ = self._execute_request(req_admin, auth_service=pg_service, client_ip="127.0.0.2")
            self.assertEqual(status_admin, 403)

            # 5. Test logout
            req_logout = (
                f"POST /api/auth/logout HTTP/1.1\r\n"
                f"Host: 127.0.0.1:8000\r\n"
                f"Origin: http://127.0.0.1:8000\r\n"
                f"Cookie: muletrace_session={token}\r\n"
                f"Content-Length: 0\r\n\r\n"
            ).encode("utf-8")
            status_logout, _, _ = self._execute_request(req_logout, auth_service=pg_service, client_ip="127.0.0.2")
            self.assertEqual(status_logout, 200)

            # Token now invalid
            self.assertIsNone(pg_service.validate_session(token))

        finally:
            # 6. Strict cleanup: delete disposable user from muletrace_test
            if created_user_id:
                with Session(pg_engine) as cleanup_session:
                    existing = cleanup_session.execute(select(User).where(User.id == created_user_id)).scalar_one_or_none()
                    if existing:
                        cleanup_session.delete(existing)
                        cleanup_session.commit()
            pg_engine.dispose()


if __name__ == "__main__":
    unittest.main()
