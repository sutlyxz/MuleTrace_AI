"""MuleTrace AI Unified Web & API Server.

Serves the frontend static dashboard while providing backend API endpoints
to connect the UI with AWS Bedrock AI and the investigation engine.
Zero external server dependencies (uses Python standard library http.server).
"""
from __future__ import annotations

import argparse
import functools
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.parse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend import engine
from app.backend.config import load_environment
from app.backend.error_pages import render_error_page
from app.backend.services.admin_service import (
    AdminService,
    ConflictError as AdminConflictError,
    ForbiddenError as AdminForbiddenError,
    NotFoundError as AdminNotFoundError,
    ServiceUnavailableError as AdminServiceUnavailableError,
    ValidationError as AdminValidationError,
    default_admin_service,
)
from app.backend.services.auth_service import (
    AuthService,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
    default_auth_service,
)


class MuleTraceRequestHandler(SimpleHTTPRequestHandler):
    """Handles static file requests and MuleTrace AI backend API endpoints."""

    MAX_BODY_SIZE = 1_048_576  # 1 MB maximum request body size
    auth_service: AuthService = default_auth_service
    admin_service: AdminService = default_admin_service

    PUBLIC_PATHS = {
        "/login.html",
        "/login",
        "/assets/css/login.css",
        "/assets/js/login.js",
        "/manifest.webmanifest",
        "/sw.js",
        "/assets/icon.svg",
        "/favicon.ico",
    }

    PROTECTED_INVESTIGATION_ASSETS = {
        "/assets/css/style.css",
        "/assets/css/case-manager.css",
        "/assets/js/app.js",
        "/assets/js/api.js",
        "/assets/js/case-manager.js",
        "/assets/js/config.js",
        "/assets/js/data.js",
        "/assets/js/i18n.js",
    }

    PROTECTED_ADMIN_ASSETS = {
        "/assets/css/admin.css",
        "/assets/js/admin.js",
    }

    SENSITIVE_EXTENSIONS = (
        ".py", ".env", ".csv", ".bat", ".sh", ".yml", ".yaml", ".ini", ".md", ".git"
    )

    def _normalize_path(self) -> str:
        """Strip query string, resolve duplicate slashes, and trim trailing slashes."""
        raw_path = urllib.parse.urlsplit(self.path).path
        clean = re.sub(r"/+", "/", raw_path)
        if len(clean) > 1 and clean.endswith("/"):
            clean = clean.rstrip("/")
        return clean

    def _is_safe_origin(self) -> bool:
        """Verify Origin or Referer header against Host to defend against CSRF attacks."""
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True
        host = self.headers.get("Host")
        if not host:
            return False
        try:
            origin_netloc = urllib.parse.urlsplit(origin).netloc.lower()
            return origin_netloc == host.lower()
        except Exception:
            return False

    def _get_session_token(self) -> str | None:
        """Extract opaque session token from HttpOnly cookie or Authorization Bearer header."""
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            cookie = SimpleCookie()
            try:
                cookie.load(cookie_header)
                if "muletrace_session" in cookie:
                    return cookie["muletrace_session"].value
            except Exception:
                pass

        auth_header = self.headers.get("Authorization", "").strip()
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()

        return None

    def _get_current_user(self) -> dict[str, Any] | None:
        """Validate session token against auth_service. Returns user summary or None."""
        raw_token = self._get_session_token()
        if not raw_token:
            return None
        return self.auth_service.validate_session(raw_token)

    def _require_auth(self) -> dict[str, Any] | None:
        """Enforce valid authentication. Sends 401 if missing or invalid."""
        try:
            user = self._get_current_user()
        except ServiceUnavailableError:
            self._send_error(503, "Authentication service unavailable")
            return None

        if user is None:
            self._send_error(401, "Authentication required")
            return None
        return user

    def _require_role(self, allowed_role: str) -> dict[str, Any] | None:
        """Enforce mutually exclusive role access (admin vs user).

        Returns user dict if authorized; sends 401 if unauthenticated, 403 if role mismatch.
        """
        user = self._require_auth()
        if user is None:
            return None

        user_role = user.get("role")
        if user_role != allowed_role:
            self._send_error(403, f"Forbidden: '{allowed_role}' role required", user=user)
            return None
        return user

    def _require_user(self) -> dict[str, Any] | None:
        """Convenience role guard for bank employee investigation endpoints."""
        return self._require_role("user")

    def _require_admin(self) -> dict[str, Any] | None:
        """Convenience role guard for future administrator portal endpoints."""
        return self._require_role("admin")

    def _make_session_cookie(self, token: str, max_age: int | None = 43200) -> str:
        cookie = SimpleCookie()
        cookie["muletrace_session"] = token
        cookie["muletrace_session"]["path"] = "/"
        cookie["muletrace_session"]["httponly"] = True
        cookie["muletrace_session"]["samesite"] = "Lax"
        if max_age is not None:
            cookie["muletrace_session"]["max-age"] = max_age
            if max_age == 0:
                cookie["muletrace_session"]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
        if forwarded_proto == "https":
            cookie["muletrace_session"]["secure"] = True
        return cookie["muletrace_session"].OutputString()

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Cookie")

    def _is_api_request(self) -> bool:
        """Return True if the request path targets backend API endpoints."""
        clean = self._normalize_path().lower()
        return clean.startswith("/api/")

    def _send_html_response(
        self, html_content: str, status_code: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        payload = html_content.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._send_cors_headers()
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(
        self,
        status_code: int,
        message: str,
        user: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Dispatch error response: JSON for /api/* requests; polished HTML for browser pages."""
        if self._is_api_request():
            self._send_json_response({"status": "error", "message": message}, status_code, headers=headers)
        else:
            if user is None:
                try:
                    user = self._get_current_user()
                except Exception:
                    user = None
            html_page = render_error_page(status_code, user=user)
            self._send_html_response(html_page, status_code, headers=headers)

    def _send_json_response(
        self, data: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def end_headers(self) -> None:
        """Add strict cache control headers to prevent browser caching of sensitive pages."""
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except Exception:
            self._send_error(500, "Internal server error")

    def _handle_get(self) -> None:
        clean_path = self._normalize_path()
        clean_lower = clean_path.lower()

        # Security check: Block path traversal and sensitive file access
        if ".." in clean_path or any(clean_lower.endswith(ext) for ext in self.SENSITIVE_EXTENSIONS):
            self._send_error(403, "Access denied")
            return

        # 1. Public Health Check
        if clean_lower in ("/api/health", "/health"):
            health = engine.health_check()
            self._send_json_response(health)
            return

        # 2. Authenticated Profile / Session Inspection (Any authenticated role: admin or user)
        if clean_lower in ("/api/auth/me", "/auth/me"):
            user = self._require_auth()
            if user is not None:
                self._send_json_response({"status": "success", "user": user}, 200)
            return

        # 3. Admin APIs (Requires 'admin' role; user is denied with 403)
        if clean_lower.startswith("/api/admin/") or clean_lower == "/api/admin":
            admin_user = self._require_admin()
            if admin_user is None:
                return

            parsed_url = urllib.parse.urlsplit(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)

            if clean_lower == "/api/admin/users":
                try:
                    limit = int(query_params.get("limit", [50])[0])
                except (ValueError, TypeError):
                    limit = 50
                try:
                    offset = int(query_params.get("offset", [0])[0])
                except (ValueError, TypeError):
                    offset = 0

                try:
                    data = self.admin_service.list_users(limit=limit, offset=offset)
                    self._send_json_response({"status": "success", **data})
                except AdminServiceUnavailableError as exc:
                    self._send_json_response({"status": "error", "message": str(exc)}, 503)
                except Exception:
                    self._send_json_response({"status": "error", "message": "Failed to list users"}, 500)
                return

            if clean_lower == "/api/admin/audit-logs":
                try:
                    limit = int(query_params.get("limit", [50])[0])
                except (ValueError, TypeError):
                    limit = 50
                try:
                    offset = int(query_params.get("offset", [0])[0])
                except (ValueError, TypeError):
                    offset = 0

                try:
                    data = self.admin_service.list_audit_logs(limit=limit, offset=offset)
                    self._send_json_response({"status": "success", **data})
                except AdminServiceUnavailableError as exc:
                    self._send_json_response({"status": "error", "message": str(exc)}, 503)
                except Exception:
                    self._send_json_response({"status": "error", "message": "Failed to list audit logs"}, 500)
                return

            self._send_json_response({"status": "error", "message": "Admin endpoint not found"}, 404)
            return

        # 4. Investigation APIs (Requires 'user' role; admin is denied)
        if clean_lower in ("/api/cases", "/cases"):
            user = self._require_user()
            if user is None:
                return
            try:
                cases_df = engine.load_case_accounts()
                tx_df = engine.load_transactions()
                unique_cases = cases_df["case_id"].dropna().unique().tolist()
                records = []
                for cid in unique_cases:
                    accounts = cases_df[cases_df["case_id"] == cid]["account_id"].tolist()
                    target = accounts[0] if accounts else None
                    tx_match = tx_df[tx_df["target_account"] == target] if target else None
                    amount = float(tx_match.iloc[0]["amount"]) if tx_match is not None and not tx_match.empty else 0
                    source = tx_match.iloc[0]["source_account"] if tx_match is not None and not tx_match.empty else "-"
                    records.append({
                        "caseId": cid,
                        "source": source,
                        "target": target,
                        "amount": amount,
                        "status": "new",
                    })
                self._send_json_response({"status": "success", "cases": records})
                return
            except Exception:
                self._send_json_response({"status": "error", "message": "Internal server error"}, 500)
                return

        # If any other /api/* path reaches here, default deny
        if clean_lower.startswith("/api/"):
            self._send_json_response({"status": "error", "message": "Endpoint not found"}, 404)
            return

        # 5. Public Static Assets (Login page, login css, login js, manifest, favicon)
        if clean_lower in self.PUBLIC_PATHS:
            super().do_GET()
            return

        # 6. Investigation Dashboard HTML (index.html or /)
        if clean_lower in ("/", "/index.html"):
            user = self._get_current_user()
            if user is None:
                if clean_lower == "/":
                    # Helpful browser UX: redirect anonymous visitor from root to login
                    self.send_response(302)
                    self.send_header("Location", "/login.html")
                    self.end_headers()
                else:
                    self._send_error(401, "Authentication required", user=None)
                return

            if user.get("role") == "admin":
                if clean_lower == "/":
                    # Admin visiting root: redirect to admin landing page
                    self.send_response(302)
                    self.send_header("Location", "/admin.html")
                    self.end_headers()
                else:
                    self._send_error(
                        403,
                        "Forbidden: Bank officer 'user' role required for Investigation Dashboard",
                        user=user,
                    )
                return

            if user.get("role") != "user":
                self._send_error(
                    403,
                    "Forbidden: Bank officer 'user' role required for Investigation Dashboard",
                    user=user,
                )
                return

            super().do_GET()
            return

        # 6a. Admin Portal Landing HTML (admin.html) - Phase 3 Minimal Landing
        if clean_lower == "/admin.html":
            user = self._get_current_user()
            if user is None:
                self._send_error(401, "Authentication required", user=None)
                return

            if user.get("role") != "admin":
                self._send_error(
                    403,
                    "Forbidden: Administrator 'admin' role required",
                    user=user,
                )
                return

            super().do_GET()
            return

        # 6b. Admin Portal Frontend Assets (JS/CSS for Admin Portal)
        if clean_lower in self.PROTECTED_ADMIN_ASSETS:
            user = self._get_current_user()
            if user is None:
                self._send_error(401, "Authentication required", user=None)
                return
            if user.get("role") != "admin":
                self._send_error(
                    403,
                    "Forbidden: Administrator 'admin' role required",
                    user=user,
                )
                return
            super().do_GET()
            return

        # 7. Investigation-Specific Frontend Assets (JS/CSS for dashboard)
        if clean_lower in self.PROTECTED_INVESTIGATION_ASSETS:
            user = self._get_current_user()
            if user is None:
                self._send_json_response({"status": "error", "message": "Authentication required"}, 401)
                return
            if user.get("role") != "user":
                self._send_json_response(
                    {"status": "error", "message": "Forbidden: Bank officer 'user' role required"}, 403
                )
                return
            super().do_GET()
            return

        # 8. Default Deny for unclassified files
        self._send_error(404, "File not found or access denied")

    def do_POST(self) -> None:
        clean_path = self._normalize_path()

        # Bounded body size check (max 1 MB)
        content_length_header = self.headers.get("Content-Length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
                if content_length > self.MAX_BODY_SIZE:
                    self._send_json_response(
                        {"status": "error", "message": "Request payload too large (max 1MB)"}, 413
                    )
                    return
            except ValueError:
                self._send_json_response({"status": "error", "message": "Invalid Content-Length header"}, 400)
                return
        else:
            content_length = 0

        # Read bounded payload
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body.strip() else {}
        except Exception:
            self._send_json_response({"status": "error", "message": "Malformed JSON payload"}, 400)
            return

        # 1. Public Authentication Login
        if clean_path in ("/api/auth/login", "/auth/login"):
            try:
                email = payload.get("email")
                password = payload.get("password")
                if not email or not password:
                    self._send_json_response(
                        {"status": "error", "message": "Email and password are required"}, 400
                    )
                    return

                # Rate limiting client IP: Use direct client address to prevent header spoofing
                client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

                raw_token, user_info = self.auth_service.login(
                    str(email), str(password), client_ip=client_ip
                )
                cookie_str = self._make_session_cookie(raw_token)
                self._send_json_response(
                    {"status": "success", "user": user_info},
                    status_code=200,
                    headers={"Set-Cookie": cookie_str},
                )
                return
            except AuthenticationError:
                self._send_json_response(
                    {"status": "error", "message": "Invalid email or password"}, 401
                )
                return
            except RateLimitError as rl_err:
                self._send_json_response(
                    {"status": "error", "message": str(rl_err)}, 429
                )
                return
            except ServiceUnavailableError:
                self._send_json_response(
                    {"status": "error", "message": "Authentication service unavailable"}, 503
                )
                return
            except Exception:
                self._send_json_response({"status": "error", "message": "Internal server error"}, 500)
                return

        # 2. Authentication Logout (Requires CSRF check; accessible to any role)
        if clean_path in ("/api/auth/logout", "/auth/logout"):
            if not self._is_safe_origin():
                self._send_json_response({"status": "error", "message": "CSRF verification failed"}, 403)
                return

            try:
                raw_token = self._get_session_token()
                if raw_token:
                    self.auth_service.logout(raw_token)
                expired_cookie = self._make_session_cookie("", max_age=0)
                self._send_json_response(
                    {"status": "success", "message": "Logged out successfully"},
                    status_code=200,
                    headers={"Set-Cookie": expired_cookie},
                )
                return
            except Exception:
                self._send_json_response({"status": "error", "message": "Internal server error"}, 500)
                return

        # 3. Admin APIs (Requires 'admin' role; user is denied with 403)
        if clean_path.startswith("/api/admin/") or clean_path == "/api/admin":
            admin_user = self._require_admin()
            if admin_user is None:
                return

            if not self._is_safe_origin():
                self._send_json_response({"status": "error", "message": "CSRF verification failed"}, 403)
                return

            # POST /api/admin/users - Provision Bank Officer account
            if clean_path == "/api/admin/users":
                email = payload.get("email")
                password = payload.get("password")
                display_name = payload.get("display_name")
                role_override = payload.get("role")

                try:
                    user_data = self.admin_service.create_bank_officer(
                        admin_actor_id=admin_user["id"],
                        email=email,
                        password=password,
                        display_name=display_name,
                        client_supplied_role=role_override,
                    )
                    self._send_json_response({"status": "success", "user": user_data}, 201)
                except AdminValidationError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 400)
                except AdminForbiddenError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 400)
                except AdminConflictError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 409)
                except AdminServiceUnavailableError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 503)
                except Exception:
                    self._send_json_response({"status": "error", "message": "Failed to create user"}, 500)
                return

            # POST /api/admin/users/{user_id}/reset-password
            reset_match = re.match(r"^/api/admin/users/([^/]+)/reset-password$", clean_path)
            if reset_match:
                target_user_id = reset_match.group(1)
                new_password = payload.get("new_password") or payload.get("password")

                try:
                    result = self.admin_service.reset_user_password(
                        admin_actor_id=admin_user["id"],
                        target_user_id=target_user_id,
                        new_password=new_password,
                    )
                    self._send_json_response({"status": "success", **result}, 200)
                except AdminValidationError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 400)
                except AdminNotFoundError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 404)
                except AdminForbiddenError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 403)
                except AdminServiceUnavailableError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 503)
                except Exception:
                    self._send_json_response({"status": "error", "message": "Failed to reset password"}, 500)
                return

            self._send_json_response({"status": "error", "message": "Admin endpoint not found"}, 404)
            return

        # 4. Investigation API: AI Summary Narrative (Requires 'user' role; admin is denied)
        if clean_path in ("/api/ai/summary", "/ai/summary"):
            user = self._require_user()
            if user is None:
                return

            try:
                case_id = payload.get("case_id") or "CASE001"
                target_lang = (payload.get("language") or "th").strip().lower()
                investigation_input = payload.get("investigation") or {}

                # Map external case IDs if needed (e.g. MT-1042 -> CASE001)
                normalized_case = "CASE001" if "1042" in str(case_id) else ("CASE002" if "1043" in str(case_id) else str(case_id))

                # Fetch engine investigation metrics
                try:
                    investigation_data = engine.score_investigation(case_id=normalized_case)
                except Exception:
                    investigation_data = {
                        "case_id": normalized_case,
                        "investigation": investigation_input,
                    }

                # Generate AI Narrative via Bedrock
                try:
                    from app.backend.aws.bedrock_service import generate_narrative_report
                    report = generate_narrative_report(investigation_data, language=target_lang)
                    summary = report.get("narrative", "")
                    if not summary.strip():
                        raise ValueError("Empty report generated")
                except Exception as ai_err:
                    # Fallback summary if AWS Bedrock is offline or unconfigured
                    if target_lang == "en":
                        summary = (
                            f"MuleTrace AML Rule Engine Report for {case_id}:\n"
                            f"- Priority Score: {investigation_data.get('score', 80)} ({investigation_data.get('priority', 'High')})\n"
                            f"- Key Signals: {', '.join(investigation_data.get('rule_types_matched', ['multiple_incoming', 'rapid_outgoing']))}\n"
                            f"- Status: Active investigation triage completed.\n"
                            f"(Note: AWS Bedrock connection notice: {ai_err})"
                        )
                    else:
                        summary = (
                            f"รายงานระบบกฎ MuleTrace AML สำหรับเคส {case_id}:\n"
                            f"- คะแนนความสำคัญ: {investigation_data.get('score', 80)} ({investigation_data.get('priority', 'High')})\n"
                            f"- สัญญาณความเสี่ยงหลัก: {', '.join(investigation_data.get('rule_types_matched', ['multiple_incoming', 'rapid_outgoing']))}\n"
                            f"- สถานะ: ดำเนินการคัดกรองเบื้องต้นเสร็จสิ้น\n"
                            f"(หมายเหตุการเชื่อมต่อ AWS Bedrock: {ai_err})"
                        )

                self._send_json_response({"status": "success", "summary": summary})
                return

            except Exception:
                self._send_json_response({"status": "error", "message": "Internal server error"}, 500)
                return

        self._send_json_response({"status": "error", "message": "Endpoint not found"}, 404)

    def do_PATCH(self) -> None:
        clean_path = self._normalize_path()

        # Bounded body size check (max 1 MB)
        content_length_header = self.headers.get("Content-Length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
                if content_length > self.MAX_BODY_SIZE:
                    self._send_json_response(
                        {"status": "error", "message": "Request payload too large (max 1MB)"}, 413
                    )
                    return
            except ValueError:
                self._send_json_response({"status": "error", "message": "Invalid Content-Length header"}, 400)
                return
        else:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body.strip() else {}
        except Exception:
            self._send_json_response({"status": "error", "message": "Malformed JSON payload"}, 400)
            return

        # Admin APIs (Requires 'admin' role; user is denied with 403)
        if clean_path.startswith("/api/admin/") or clean_path == "/api/admin":
            admin_user = self._require_admin()
            if admin_user is None:
                return

            if not self._is_safe_origin():
                self._send_json_response({"status": "error", "message": "CSRF verification failed"}, 403)
                return

            # PATCH /api/admin/users/{user_id}/status
            status_match = re.match(r"^/api/admin/users/([^/]+)/status$", clean_path)
            if status_match:
                target_user_id = status_match.group(1)
                is_active = payload.get("is_active")

                try:
                    user_data = self.admin_service.set_user_status(
                        admin_actor_id=admin_user["id"],
                        target_user_id=target_user_id,
                        is_active=is_active,
                    )
                    self._send_json_response({"status": "success", "user": user_data}, 200)
                except AdminValidationError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 400)
                except AdminNotFoundError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 404)
                except AdminForbiddenError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 403)
                except AdminServiceUnavailableError as err:
                    self._send_json_response({"status": "error", "message": str(err)}, 503)
                except Exception:
                    self._send_json_response({"status": "error", "message": "Failed to update user status"}, 500)
                return

            self._send_json_response({"status": "error", "message": "Admin endpoint not found"}, 404)
            return

        self._send_json_response({"status": "error", "message": "Endpoint not found"}, 404)


def run_server(port: int = 8000, bind: str = "127.0.0.1", directory: Path | str | None = None) -> None:
    # Load private environment (.env)
    env = load_environment(PROJECT_ROOT)
    os.environ.update(env)

    target_dir = Path(directory) if directory else PROJECT_ROOT / "app" / "frontend"
    handler = functools.partial(MuleTraceRequestHandler, directory=str(target_dir))

    # On Windows, prevent duplicate process binding to the same port
    ThreadingHTTPServer.allow_reuse_address = False if os.name == "nt" else True
    server = ThreadingHTTPServer((bind, port), handler)
    print(f"[*] MuleTrace AI Server running on http://{bind}:{port}/", flush=True)
    print(f"[*] Serving static files from: {target_dir}", flush=True)
    print(f"[*] AI Summary API Endpoint ready at: http://{bind}:{port}/api/ai/summary", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down MuleTrace AI Server...", flush=True)
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MuleTrace AI Unified Web & API Server")
    parser.add_argument("port", type=int, nargs="?", default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--bind", "-b", default="127.0.0.1", help="Address to bind to (default: 127.0.0.1)")
    parser.add_argument("--directory", "-d", default=None, help="Directory to serve static files from")
    args = parser.parse_args()

    run_server(port=args.port, bind=args.bind, directory=args.directory)


if __name__ == "__main__":
    main()
