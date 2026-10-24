"""Unit and integration tests for Authentication HTTP endpoints."""
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
from app.backend.services.auth_service import AuthService


def create_test_auth_service():
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

    # Seed test users
    with Session(engine) as session:
        user_repo = UserRepository(session)
        user_repo.create_user(
            email="officer@agency.go.th",
            display_name="Bank Officer",
            role="user",
            password_hash=hash_password("OfficerSecure10!@#"),
            is_active=True,
        )
        user_repo.create_user(
            email="admin@agency.go.th",
            display_name="System Administrator",
            role="admin",
            password_hash=hash_password("AdminSecure10!@#"),
            is_active=True,
        )
        user_repo.create_user(
            email="disabled@agency.go.th",
            display_name="Suspended Officer",
            role="user",
            password_hash=hash_password("DisabledSecure10!@#"),
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


class TestAuthApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.frontend_dir = str(self.project_root / "app" / "frontend")
        self.auth_service = create_test_auth_service()

    def _execute_request(self, request_bytes: bytes) -> tuple[int, dict[str, str], bytes]:
        socket = DummySocket(request_bytes)
        server = DummyServer()

        # Custom handler subclass with injected isolated auth service
        class InjectedHandler(MuleTraceRequestHandler):
            pass

        InjectedHandler.auth_service = self.auth_service

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

    def test_post_login_success(self):
        payload = json.dumps({"email": "officer@agency.go.th", "password": "OfficerSecure10!@#"}).encode("utf-8")
        req = (
            b"POST /api/auth/login HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n"
            + payload
        )
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        self.assertIn("set-cookie", headers)
        cookie = headers["set-cookie"]
        self.assertIn("muletrace_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/", cookie)

        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("user", {}).get("email"), "officer@agency.go.th")
        self.assertEqual(data.get("user", {}).get("role"), "user")

    def test_post_login_invalid_password(self):
        payload = json.dumps({"email": "officer@agency.go.th", "password": "WrongPassword123!"}).encode("utf-8")
        req = (
            b"POST /api/auth/login HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n"
            + payload
        )
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)
        self.assertNotIn("set-cookie", headers)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("message"), "Invalid email or password")

    def test_post_login_unknown_email(self):
        payload = json.dumps({"email": "nonexistent@agency.go.th", "password": "AnyPassword10!@#"}).encode("utf-8")
        req = (
            b"POST /api/auth/login HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n"
            + payload
        )
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("message"), "Invalid email or password")

    def test_post_login_disabled_account(self):
        payload = json.dumps({"email": "disabled@agency.go.th", "password": "DisabledSecure10!@#"}).encode("utf-8")
        req = (
            b"POST /api/auth/login HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n"
            + payload
        )
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("message"), "Invalid email or password")

    def test_get_me_unauthenticated_returns_401(self):
        req = b"GET /api/auth/me HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 401)

    def test_get_me_authenticated_user_and_admin(self):
        # 1. Login user
        token_user, _ = self.auth_service.login("officer@agency.go.th", "OfficerSecure10!@#")
        req_user = (
            b"GET /api/auth/me HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Cookie: muletrace_session=" + token_user.encode("ascii") + b"\r\n\r\n"
        )
        status, _, body = self._execute_request(req_user)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("user", {}).get("role"), "user")

        # 2. Login admin
        token_admin, _ = self.auth_service.login("admin@agency.go.th", "AdminSecure10!@#")
        req_admin = (
            b"GET /api/auth/me HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Cookie: muletrace_session=" + token_admin.encode("ascii") + b"\r\n\r\n"
        )
        status, _, body = self._execute_request(req_admin)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("user", {}).get("role"), "admin")

    def test_post_logout_revokes_session_and_clears_cookie(self):
        token, _ = self.auth_service.login("officer@agency.go.th", "OfficerSecure10!@#")
        req_logout = (
            b"POST /api/auth/logout HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Origin: http://127.0.0.1:8000\r\n"
            b"Cookie: muletrace_session=" + token.encode("ascii") + b"\r\n\r\n"
        )
        status, headers, body = self._execute_request(req_logout)
        self.assertEqual(status, 200)
        self.assertIn("set-cookie", headers)
        cookie = headers["set-cookie"]
        self.assertIn("Max-Age=0", cookie)

        # Subsequent check must be 401
        req_me = (
            b"GET /api/auth/me HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Cookie: muletrace_session=" + token.encode("ascii") + b"\r\n\r\n"
        )
        status_me, _, _ = self._execute_request(req_me)
        self.assertEqual(status_me, 401)

    def test_post_logout_csrf_verification(self):
        req_logout = (
            b"POST /api/auth/logout HTTP/1.1\r\n"
            b"Host: 127.0.0.1:8000\r\n"
            b"Origin: http://attacker.malicious.com\r\n\r\n"
        )
        status, _, body = self._execute_request(req_logout)
        self.assertEqual(status, 403)

    def test_no_public_signup_endpoint(self):
        for path in (b"/api/auth/signup", b"/api/auth/register", b"/signup", b"/register"):
            req = b"POST " + path + b" HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n"
            status, _, _ = self._execute_request(req)
            self.assertEqual(status, 404, f"Public registration endpoint '{path.decode()}' must not exist.")


if __name__ == "__main__":
    unittest.main()
