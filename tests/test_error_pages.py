"""Unit and regression tests for Phase 3.2: Professional Error Pages & Authentication UX.

Covers:
1. Admin GET /index.html returns HTTP 403 and HTML with role-safe action to /admin.html.
2. User GET /admin.html returns HTTP 403 and HTML with role-safe action to /index.html.
3. Anonymous GET /index.html returns HTTP 401 and HTML with action to /login.html.
4. Authenticated user GET /index.html remains HTTP 200 HTML.
5. Authenticated admin GET /admin.html remains HTTP 200 HTML.
6. Admin GET /api/cases remains HTTP 403 and JSON schema.
7. Anonymous GET /api/auth/me remains HTTP 401 and JSON schema.
8. Unknown HTML page returns HTTP 404 and HTML.
9. Unknown API route returns HTTP 404 and JSON.
10. Server internal exception handling returns HTTP 500 and generic HTML/JSON without leaking stack traces.
11. HTML error responses include Cache-Control: no-store.
12. Error pages are accessible, responsive, and contain required Thai/English copy.
13. URL normalization and case bypass protections remain intact.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import socket
from socketserver import BaseServer
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.backend.auth.security import hash_password
from app.backend.db.auth_repositories import UserRepository
from app.backend.db.models import AuthAuditLog, AuthSession, Base, User
from app.backend.error_pages import render_error_page
from app.backend.server import MuleTraceRequestHandler
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


class DummyServer(BaseServer):
    def __init__(self):
        self.server_name = "127.0.0.1"
        self.server_port = 8000


class TestErrorPagesAndAuthUX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.frontend_dir = str(cls.project_root / "app" / "frontend")

        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            cls.engine,
            tables=[Base.metadata.tables[t] for t in ("users", "auth_sessions", "auth_audit_logs")],
        )
        rate_limiter = LoginRateLimiter(max_attempts=10, window_seconds=900)
        cls.auth_service = AuthService(engine=cls.engine, rate_limiter=rate_limiter)

        with Session(cls.engine) as session:
            repo = UserRepository(session)
            cls.user_record = repo.create_user(
                email="officer_ep@agency.go.th",
                display_name="Officer ErrorPage",
                role="user",
                password_hash=hash_password("OfficerPass123!@#"),
                is_active=True,
            )
            cls.admin_record = repo.create_user(
                email="admin_ep@agency.go.th",
                display_name="Admin ErrorPage",
                role="admin",
                password_hash=hash_password("AdminPass123!@#"),
                is_active=True,
            )
            session.commit()

        # Login both
        cls.user_token, _ = cls.auth_service.login(
            "officer_ep@agency.go.th", "OfficerPass123!@#", "127.0.0.1"
        )
        cls.admin_token, _ = cls.auth_service.login(
            "admin_ep@agency.go.th", "AdminPass123!@#", "127.0.0.1"
        )

    def _execute_request(self, raw_http: bytes, client_ip: str = "127.0.0.1"):
        sock = DummySocket(raw_http, client_ip=client_ip)
        server = DummyServer()

        class InjectedHandler(MuleTraceRequestHandler):
            pass

        InjectedHandler.auth_service = self.auth_service
        try:
            InjectedHandler(sock, (client_ip, 12345), server, directory=self.frontend_dir)
        except Exception:
            pass

        output = sock.wfile.getvalue()
        parts = output.split(b"\r\n\r\n", 1)
        header_part = parts[0].decode("utf-8", errors="replace")
        body = parts[1] if len(parts) > 1 else b""

        header_lines = header_part.split("\r\n")
        status_line = header_lines[0]
        status_code = int(status_line.split(" ")[1]) if " " in status_line else 0

        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        return status_code, headers, body

    # 1. Admin GET /index.html returns HTTP 403 and HTML
    def test_admin_get_index_html_returns_403_html(self):
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
        self.assertIn("<!doctype html>", body_str.lower())
        self.assertIn("403", body_str)
        self.assertIn("ไม่มีสิทธิ์เข้าถึงหน้านี้", body_str)
        self.assertIn("Access Denied", body_str)
        # Role-safe primary action for admin: only admin.html
        self.assertIn("/admin.html", body_str)
        self.assertIn("กลับไปหน้าผู้ดูแลระบบ", body_str)
        # Must NOT show secondary login button on authenticated 403
        self.assertNotIn("/login.html", body_str)
        self.assertNotIn("ไปหน้าเข้าสู่ระบบ", body_str)
        # Must NOT expose email address or personal account identifiers
        self.assertNotIn("admin_ep@agency.go.th", body_str)
        self.assertNotIn("@agency.go.th", body_str)
        # Displays only the verified role
        self.assertIn("บทบาทปัจจุบัน:", body_str)
        self.assertIn("admin", body_str)
        self.assertIn("ผู้ดูแลระบบ", body_str)
        self.assertNotIn("/api/cases", body_str)

    # 2. User GET /admin.html returns HTTP 403 and HTML
    def test_user_get_admin_html_returns_403_html(self):
        req = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 403)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        body_str = body.decode("utf-8")
        self.assertIn("<!doctype html>", body_str.lower())
        self.assertIn("403", body_str)
        self.assertIn("ไม่มีสิทธิ์เข้าถึงหน้านี้", body_str)
        # Role-safe primary action for user: only index.html
        self.assertIn("/index.html", body_str)
        self.assertIn("กลับไปหน้า Dashboard", body_str)
        # Must NOT show secondary login button on authenticated 403
        self.assertNotIn("/login.html", body_str)
        self.assertNotIn("ไปหน้าเข้าสู่ระบบ", body_str)
        # Must NOT expose email address or personal account identifiers
        self.assertNotIn("officer_ep@agency.go.th", body_str)
        self.assertNotIn("@agency.go.th", body_str)
        # Displays only the verified role
        self.assertIn("บทบาทปัจจุบัน:", body_str)
        self.assertIn("user", body_str)
        self.assertIn("เจ้าหน้าที่ธนาคาร", body_str)

    # 3. Anonymous GET /index.html returns HTTP 401 and HTML
    def test_anonymous_get_index_html_returns_401_html(self):
        req = b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        body_str = body.decode("utf-8")
        self.assertIn("<!doctype html>", body_str.lower())
        self.assertIn("401", body_str)
        self.assertIn("กรุณาเข้าสู่ระบบ", body_str)
        self.assertIn("Authentication Required", body_str)
        self.assertIn("/login.html", body_str)
        self.assertIn("ไปหน้าเข้าสู่ระบบ", body_str)

    # 4. Authenticated user GET /index.html remains HTTP 200
    def test_user_get_index_html_returns_200(self):
        req = (
            f"GET /index.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.user_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        self.assertTrue(b"MuleTrace" in body or b"Dashboard" in body)

    # 5. Authenticated admin GET /admin.html remains HTTP 200
    def test_admin_get_admin_html_returns_200(self):
        req = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        self.assertIn(b"Admin Portal", body)

    # 6. Admin GET /api/cases remains HTTP 403 and JSON
    def test_admin_get_api_cases_returns_403_json(self):
        req = (
            f"GET /api/cases HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 403)
        self.assertIn("application/json", headers.get("content-type", ""))
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("user", data["message"].lower())

    # 7. Anonymous GET /api/auth/me remains HTTP 401 and JSON
    def test_anonymous_get_api_auth_me_returns_401_json(self):
        req = b"GET /api/auth/me HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)
        self.assertIn("application/json", headers.get("content-type", ""))
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")

    # 8. Unknown HTML page returns HTTP 404 and HTML
    def test_unknown_html_page_returns_404_html(self):
        req = b"GET /nonexistent-page.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 404)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("no-store", headers.get("cache-control", ""))
        body_str = body.decode("utf-8")
        self.assertIn("<!doctype html>", body_str.lower())
        self.assertIn("404", body_str)
        self.assertIn("ไม่พบหน้าที่คุณต้องการ", body_str)
        self.assertIn("Page Not Found", body_str)

    # 9. Unknown API route returns HTTP 404 and JSON
    def test_unknown_api_route_returns_404_json(self):
        req = b"GET /api/unknown/endpoint HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers.get("content-type", ""))
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("not found", data["message"].lower())

    # 10. Internal error handling returns generic HTTP 500 response without stack traces
    def test_internal_error_returns_500_generic_html(self):
        # We simulate an internal exception during do_GET on an HTML page
        with patch.object(MuleTraceRequestHandler, "_get_current_user", side_effect=RuntimeError("Database crashed! Secret: dbpass123")):
            req = b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
            status, headers, body = self._execute_request(req)
            self.assertEqual(status, 500)
            self.assertIn("text/html", headers.get("content-type", ""))
            body_str = body.decode("utf-8")
            self.assertIn("500", body_str)
            self.assertIn("ระบบขัดข้องชั่วคราว", body_str)
            self.assertIn("Something Went Wrong", body_str)
            # Must NOT leak stack trace or internal exception details
            self.assertNotIn("dbpass123", body_str)
            self.assertNotIn("RuntimeError", body_str)
            self.assertNotIn("Traceback", body_str)

    def test_internal_error_on_api_returns_500_generic_json(self):
        with patch.object(MuleTraceRequestHandler, "_get_current_user", side_effect=RuntimeError("API crashed! Secret: apisecret")):
            req = b"GET /api/cases HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
            status, headers, body = self._execute_request(req)
            self.assertEqual(status, 500)
            self.assertIn("application/json", headers.get("content-type", ""))
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data["status"], "error")
            self.assertIn("internal server error", data["message"].lower())
            self.assertNotIn("apisecret", data["message"])

    # 11. Direct test of render_error_page module
    def test_render_error_page_attributes(self):
        # 401 anonymous: retains login action
        html_401 = render_error_page(401, user=None)
        self.assertIn("401", html_401)
        self.assertIn("Authentication Required", html_401)
        self.assertIn('href="/login.html"', html_401)
        self.assertIn("ไปหน้าเข้าสู่ระบบ", html_401)

        # 403 admin: shows only admin navigation, displays role, hides email and secondary login button
        html_403_admin = render_error_page(403, user={"role": "admin", "email": "admin@example.com"})
        self.assertIn("403", html_403_admin)
        self.assertIn("Access Denied", html_403_admin)
        self.assertIn('href="/admin.html"', html_403_admin)
        self.assertIn("กลับไปหน้าผู้ดูแลระบบ", html_403_admin)
        self.assertIn("admin", html_403_admin)
        self.assertIn("ผู้ดูแลระบบ", html_403_admin)
        self.assertNotIn("admin@example.com", html_403_admin)
        self.assertNotIn("@example.com", html_403_admin)
        self.assertNotIn('href="/login.html"', html_403_admin)
        self.assertNotIn("ไปหน้าเข้าสู่ระบบ", html_403_admin)

        # 403 user: shows only dashboard navigation, displays role, hides email and secondary login button
        html_403_user = render_error_page(403, user={"role": "user", "email": "user@example.com"})
        self.assertIn("403", html_403_user)
        self.assertIn("Access Denied", html_403_user)
        self.assertIn('href="/index.html"', html_403_user)
        self.assertIn("กลับไปหน้า Dashboard", html_403_user)
        self.assertIn("user", html_403_user)
        self.assertIn("เจ้าหน้าที่ธนาคาร", html_403_user)
        self.assertNotIn("user@example.com", html_403_user)
        self.assertNotIn("@example.com", html_403_user)
        self.assertNotIn('href="/login.html"', html_403_user)
        self.assertNotIn("ไปหน้าเข้าสู่ระบบ", html_403_user)

        # 403 unverified / invalid role: safe fallback to login, no privileged destination
        html_403_unknown = render_error_page(403, user={"role": "guest", "email": "intruder@bad.com"})
        self.assertNotIn("/admin.html", html_403_unknown)
        self.assertNotIn("/index.html", html_403_unknown)
        self.assertIn('href="/login.html"', html_403_unknown)
        self.assertNotIn("intruder@bad.com", html_403_unknown)
        self.assertNotIn('<div class="user-session-card"', html_403_unknown)

        # 404
        html_404 = render_error_page(404, user=None)
        self.assertIn("404", html_404)
        self.assertIn("Page Not Found", html_404)

        # 500
        html_500 = render_error_page(500, user=None)
        self.assertIn("500", html_500)
        self.assertIn("Something Went Wrong", html_500)

    # 12. Normalization bypass tests with error pages
    def test_normalization_bypass_returns_html_error(self):
        req = (
            f"GET /INDEX.HTML HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 403)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("403", body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
