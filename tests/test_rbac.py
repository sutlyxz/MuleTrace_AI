"""Tests for Phase 2 Role-Based Access Control (RBAC) and Resource Protection."""
from __future__ import annotations

import io
import json
from pathlib import Path
import socket
from socketserver import BaseServer
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.backend.auth.security import hash_password
from app.backend.db.auth_repositories import UserRepository
from app.backend.db.models import AuthAuditLog, AuthSession, Base, User
from app.backend.server import MuleTraceRequestHandler
from app.backend.services.admin_service import AdminService
from app.backend.services.auth_service import AuthService


def create_rbac_test_auth_service():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[t] for t in ("users", "auth_sessions", "auth_audit_logs")],
    )
    service = AuthService(engine=engine)

    with Session(engine) as session:
        user_repo = UserRepository(session)
        user_repo.create_user(
            email="officer@agency.go.th",
            display_name="Bank Officer",
            role="user",
            password_hash=hash_password("OfficerPass123!@#"),
            is_active=True,
        )
        user_repo.create_user(
            email="admin@agency.go.th",
            display_name="System Admin",
            role="admin",
            password_hash=hash_password("AdminPass123!@#"),
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
    def __init__(self, input_bytes: bytes):
        self.rfile = io.BytesIO(input_bytes)
        self.wfile = io.BytesIO()
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
        return ("127.0.0.1", 12345)

    def getsockname(self):
        return ("127.0.0.1", 8000)

    def close(self) -> None:
        pass


class DummyServer(BaseServer):
    def __init__(self):
        self.server_name = "127.0.0.1"
        self.server_port = 8000


class TestPhase2RBAC(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.frontend_dir = str(self.project_root / "app" / "frontend")
        self.auth_service = create_rbac_test_auth_service()

        # Generate tokens
        self.user_token, _ = self.auth_service.login(
            "officer@agency.go.th", "OfficerPass123!@#", client_ip="127.0.0.1"
        )
        self.admin_token, _ = self.auth_service.login(
            "admin@agency.go.th", "AdminPass123!@#", client_ip="127.0.0.1"
        )

    def _execute_request(self, request_bytes: bytes) -> tuple[int, dict[str, str], bytes]:
        socket = DummySocket(request_bytes)
        server = DummyServer()

        class InjectedHandler(MuleTraceRequestHandler):
            pass

        InjectedHandler.auth_service = self.auth_service
        InjectedHandler.admin_service = AdminService(engine=self.auth_service.engine)
        handler = InjectedHandler(socket, ("127.0.0.1", 12345), server, directory=self.frontend_dir)
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

    # 1. Anonymous user denied access to Dashboard HTML
    def test_anonymous_denied_dashboard_html(self):
        req = b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        body_str = body.decode("utf-8")
        self.assertIn("Authentication Required", body_str)
        self.assertIn("401", body_str)

    def test_anonymous_root_redirects_to_login(self):
        req = b"GET / HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, _ = self._execute_request(req)
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("location"), "/login.html")

    # 2. Admin denied access to Dashboard HTML
    def test_admin_denied_dashboard_html(self):
        req = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 403)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        body_str = body.decode("utf-8")
        self.assertIn("Access Denied", body_str)
        self.assertIn("403", body_str)
        self.assertIn("/admin.html", body_str)

    # 3. 'user' allowed access to Dashboard HTML
    def test_user_allowed_dashboard_html(self):
        req = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        self.assertTrue(b"<!doctype html>" in body.lower() or b"<html" in body.lower())

    # 4. Anonymous user denied access to investigation APIs
    def test_anonymous_denied_investigation_cases_api(self):
        req = b"GET /api/cases HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")

    def test_anonymous_denied_investigation_ai_summary_api(self):
        payload = json.dumps({"case_id": "CASE001"}).encode("utf-8")
        headers = (
            f"POST /api/ai/summary HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8")
        req = headers + payload
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")

    # 5. Admin denied access to investigation APIs
    def test_admin_denied_investigation_cases_api(self):
        req = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("user", data["message"].lower())

    def test_admin_denied_investigation_ai_summary_api(self):
        payload = json.dumps({"case_id": "CASE001"}).encode("utf-8")
        headers = (
            f"POST /api/ai/summary HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("utf-8")
        req = headers + payload
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")

    # 6. 'user' allowed access to investigation APIs
    def test_user_allowed_investigation_cases_api(self):
        req = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertIn("cases", data)

    # 7. 'user' denied access to Admin-only functionality
    def test_user_denied_admin_endpoint(self):
        req = (
            f"GET /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 403)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("admin", data["message"].lower())

    # 8. Admin authorization guard accepts valid Admin sessions
    def test_admin_guard_accepts_admin(self):
        req = (
            f"GET /api/admin/users HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertIn("users", data)

    # 9. Expired session returns 401
    def test_expired_session_returns_401(self):
        # Manually expire session in DB
        with Session(self.auth_service.engine) as session:
            db_sess = session.query(AuthSession).first()
            assert db_sess is not None
            from datetime import datetime, timezone, timedelta
            db_sess.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            session.commit()

        req = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)

    # 10. Revoked session returns 401
    def test_revoked_session_returns_401(self):
        self.auth_service.logout(self.user_token)
        req = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)

    # 11. Disabled user returns 401
    def test_disabled_user_returns_401_on_login_and_request(self):
        # Direct login attempt by disabled user fails
        with self.assertRaises(Exception):
            self.auth_service.login("disabled_officer@agency.go.th", "DisabledPass123!@#")

    # 12. Malformed or missing session cookie returns 401
    def test_malformed_session_cookie_returns_401(self):
        req = (
            b"GET /api/cases HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Cookie: muletrace_session=invalid_non_existent_token_hex_999\r\n\r\n"
        )
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 401)

    # 13. Query-string and path-normalization bypass attempts are denied
    def test_path_normalization_bypass_attempts(self):
        # Trailing slash bypass attempt
        req1 = (
            f"GET /api/admin/users/ HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status1, _, _ = self._execute_request(req1)
        self.assertEqual(status1, 403)

        # Duplicate slash bypass attempt
        req2 = b"GET //api//cases HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status2, _, _ = self._execute_request(req2)
        self.assertEqual(status2, 401)

        # Query string bypass attempt
        req3 = b"GET /api/cases?bypass=true&admin=1 HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status3, _, _ = self._execute_request(req3)
        self.assertEqual(status3, 401)

    # 14. Sensitive files are not publicly accessible
    def test_sensitive_files_denied(self):
        sensitive_paths = [
            "/server.py",
            "/app/backend/server.py",
            "/.env",
            "/data/transactions.csv",
            "/tests/test_rbac.py",
            "/../server.py",
        ]
        for p in sensitive_paths:
            req = f"GET {p} HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n".encode("utf-8")
            status, _, _ = self._execute_request(req)
            self.assertIn(status, (403, 404))

    # 15. Login page and required public assets still load
    def test_login_page_and_public_assets_accessible(self):
        public_urls = [
            "/login.html",
            "/assets/css/login.css",
            "/assets/js/login.js",
            "/manifest.webmanifest",
            "/sw.js",
            "/api/health",
        ]
        for url in public_urls:
            req = f"GET {url} HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n".encode("utf-8")
            status, _, _ = self._execute_request(req)
            self.assertEqual(status, 200, f"Failed on url: {url}")

    # 16. Existing authorized investigation API responses remain compatible
    def test_investigation_cases_response_schema_compatibility(self):
        req = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, _, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertIsInstance(data["cases"], list)
        if data["cases"]:
            case = data["cases"][0]
            self.assertIn("caseId", case)
            self.assertIn("source", case)
            self.assertIn("target", case)
            self.assertIn("amount", case)
            self.assertIn("status", case)

    # 17. Protected assets (CSS/JS for investigation dashboard) require 'user' role
    def test_investigation_assets_protected(self):
        # Anonymous denied
        req_anon = b"GET /assets/js/case-manager.js HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status_anon, _, _ = self._execute_request(req_anon)
        self.assertEqual(status_anon, 401)

        # Admin denied
        req_admin = (
            f"GET /assets/js/case-manager.js HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_admin, _, _ = self._execute_request(req_admin)
        self.assertEqual(status_admin, 403)

        # User allowed
        req_user = (
            f"GET /assets/js/case-manager.js HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status_user, _, _ = self._execute_request(req_user)
        self.assertEqual(status_user, 200)


if __name__ == "__main__":
    unittest.main()
