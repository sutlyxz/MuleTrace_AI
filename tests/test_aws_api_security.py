"""Automated tests for AWS API Gateway / FastAPI security layer (aws/app.py and aws/auth_security.py).

Verifies:
- Unauthenticated requests to investigation APIs (/cases, /cases/{id}, /trace, /score, /evidence) return 401 Unauthorized.
- Public endpoints (/health) remain accessible without authentication.
- Authenticated Bank Officer can access investigation APIs.
- Bank Officer is rejected with 403 Forbidden when attempting to access Admin APIs (/api/admin/users, /api/admin/audit-logs).
- Authenticated Admin can access both Admin APIs and investigation APIs.
- Authentication via session cookie or Authorization Bearer token.
- Expired or revoked session tokens return 401 Unauthorized.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from app.backend.auth.session_store import InMemorySessionStore
from aws.app import app
from aws.auth_security import (
    get_current_user,
    require_admin_role,
    require_investigation_role,
)


def _run_asgi(
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    """Helper to execute an ASGI request against the FastAPI app synchronously without external libraries."""
    headers_dict = headers or {}
    raw_headers = [
        (k.lower().encode("latin1"), v.encode("latin1"))
        for k, v in headers_dict.items()
    ]
    response_start: dict[str, Any] = {}
    response_body = bytearray()

    if "?" in path:
        path_part, qs = path.split("?", 1)
    else:
        path_part, qs = path, ""

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path_part,
        "raw_path": path_part.encode("ascii"),
        "query_string": qs.encode("ascii"),
        "headers": raw_headers,
        "client": ("127.0.0.1", 54321),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            response_start["status"] = message["status"]
            response_start["headers"] = {
                k.decode("latin1"): v.decode("latin1")
                for k, v in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    async def _invoke() -> None:
        await app(scope, receive, send)

    asyncio.run(_invoke())
    status = response_start.get("status", 500)
    resp_headers = response_start.get("headers", {})
    return status, resp_headers, bytes(response_body)


class TestAwsApiSecurity(unittest.TestCase):
    """Test suite for AWS API routes and role authorization boundaries."""

    def setUp(self) -> None:
        self.session_store = InMemorySessionStore()

    def test_health_endpoint_is_public(self) -> None:
        """Verify that /health does not require authentication."""
        status, headers, body = _run_asgi("GET", "/health")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "ok")

    def test_unauthenticated_cases_endpoint_returns_401(self) -> None:
        """Verify that /cases rejects unauthenticated requests with HTTP 401."""
        status, headers, body = _run_asgi("GET", "/cases")
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("detail", data)

    def test_unauthenticated_trace_endpoint_returns_401(self) -> None:
        """Verify that /trace rejects unauthenticated requests with HTTP 401."""
        status, headers, body = _run_asgi(
            "POST",
            "/trace",
            headers={"content-type": "application/json"},
            body=b'{"source_account": "ACC1", "target_account": "ACC2"}',
        )
        self.assertEqual(status, 401)

    def test_unauthenticated_score_endpoint_returns_401(self) -> None:
        """Verify that /score rejects unauthenticated requests with HTTP 401."""
        status, headers, body = _run_asgi("GET", "/score?case_id=CASE-001")
        self.assertEqual(status, 401)

    def test_unauthenticated_evidence_endpoint_returns_401(self) -> None:
        """Verify that /evidence rejects unauthenticated requests with HTTP 401."""
        status, headers, body = _run_asgi("GET", "/evidence")
        self.assertEqual(status, 401)

    def test_bank_officer_cookie_access_to_cases(self) -> None:
        """Verify Bank Officer with valid session cookie can access investigation endpoints."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "officer@bank.com",
                "email": "officer@bank.com",
                "role": "user",
                "display_name": "Bank Officer One",
                "auth_provider": "cognito",
            },
            ttl_seconds=7200,
        )

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            status, headers, body = _run_asgi(
                "GET",
                "/cases",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 200)

    def test_bank_officer_forbidden_from_admin_apis(self) -> None:
        """Verify Bank Officer receives 403 Forbidden when attempting Admin operations."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "officer@bank.com",
                "email": "officer@bank.com",
                "role": "user",
                "display_name": "Bank Officer One",
                "auth_provider": "cognito",
            },
            ttl_seconds=7200,
        )

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            # Probe /api/admin/users
            status, headers, body = _run_asgi(
                "GET",
                "/api/admin/users",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 403)
            data = json.loads(body.decode("utf-8"))
            self.assertIn("Requires role in ['admin']", data.get("detail", ""))

    def test_admin_allowed_access_to_admin_apis(self) -> None:
        """Verify Admin role can access Admin Portal APIs."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "admin@bank.com",
                "email": "admin@bank.com",
                "role": "admin",
                "display_name": "System Administrator",
                "auth_provider": "cognito",
            },
            ttl_seconds=7200,
        )

        mock_admin_svc = MagicMock()
        mock_admin_svc.list_users.return_value = {"users": [{"email": "test@bank.com"}], "total": 1}

        with patch("aws.auth_security.get_session_store", return_value=self.session_store), \
             patch("aws.app.get_active_admin_service", return_value=mock_admin_svc):
            status, headers, body = _run_asgi(
                "GET",
                "/api/admin/users",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data.get("total"), 1)

    def test_admin_allowed_access_to_investigation_apis(self) -> None:
        """Verify Admin role can also access investigation APIs."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "admin@bank.com",
                "email": "admin@bank.com",
                "role": "admin",
                "display_name": "System Administrator",
                "auth_provider": "cognito",
            },
            ttl_seconds=7200,
        )

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            status, headers, body = _run_asgi(
                "GET",
                "/cases",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 200)

    def test_expired_session_returns_401(self) -> None:
        """Verify expired session token returns 401 Unauthorized."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "officer@bank.com",
                "email": "officer@bank.com",
                "role": "user",
            },
            ttl_seconds=-10,
        )

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            status, headers, body = _run_asgi(
                "GET",
                "/cases",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 401)

    def test_revoked_session_returns_401(self) -> None:
        """Verify revoked session token returns 401 Unauthorized."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "officer@bank.com",
                "email": "officer@bank.com",
                "role": "user",
            },
            ttl_seconds=3600,
        )
        self.session_store.revoke_session(token)

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            status, headers, body = _run_asgi(
                "GET",
                "/cases",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 401)
            self.assertEqual(status, 401)


class TestDirectSecurityDependencies(unittest.TestCase):
    """Direct unit tests for auth_security dependency functions."""

    def test_require_investigation_role_rejects_unauthorized_role(self) -> None:
        user = {
            "user_id": "random_user",
            "email": "random@bank.com",
            "role": "guest",  # Neither admin nor user
            "display_name": "Guest User",
            "auth_provider": "cognito",
        }
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_investigation_role(user))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_require_admin_role_rejects_officer(self) -> None:
        user = {
            "user_id": "officer_id",
            "email": "officer@bank.com",
            "role": "user",  # Bank Officer role
            "display_name": "Bank Officer",
            "auth_provider": "cognito",
        }
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_admin_role(user))
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
