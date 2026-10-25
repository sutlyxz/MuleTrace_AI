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

    @property
    def auth_service(self) -> Any:
        override = getattr(self, "_custom_auth_service", None)
        if override is not None:
            return override
        class_override = getattr(self.__class__, "_custom_auth_service", None)
        if class_override is not None:
            return class_override
        from app.backend.services.auth_factory import get_active_auth_service
        return get_active_auth_service()

    @auth_service.setter
    def auth_service(self, val: Any) -> None:
        self._custom_auth_service = val

    @property
    def admin_service(self) -> Any:
        override = getattr(self, "_custom_admin_service", None)
        if override is not None:
            return override
        class_override = getattr(self.__class__, "_custom_admin_service", None)
        if class_override is not None:
            return class_override
        from app.backend.services.auth_factory import get_active_admin_service
        return get_active_admin_service()

    @admin_service.setter
    def admin_service(self, val: Any) -> None:
        self._custom_admin_service = val

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
        "/assets/js/simulation.js",
    }

    PROTECTED_ADMIN_ASSETS = {
        "/assets/css/admin.css",
        "/assets/js/admin.js",
    }

    SENSITIVE_EXTENSIONS = (
        ".py", ".env", ".csv", ".bat", ".sh", ".yml", ".yaml", ".ini", ".md", ".git"
    )


    def _get_aws_credentials_status(self) -> dict[str, Any]:
        key_id = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        sess = os.environ.get("AWS_SESSION_TOKEN", "").strip()
        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-east-1"
        ).strip()
        configured = bool(key_id and secret)
        masked = f"{key_id[:4]}...{key_id[-4:]}" if len(key_id) >= 8 else ("Configured" if configured else "Not Set")
        return {
            "status": "success",
            "configured": configured,
            "masked_key_id": masked,
            "region": region,
            "has_session": bool(sess),
        }

    def _update_aws_credentials(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        raw_text = str(payload.get("raw_text") or "").strip()
        access_key = str(payload.get("access_key_id") or "").strip()
        secret_key = str(payload.get("secret_access_key") or "").strip()
        session_val = str(payload.get("session_value") or "").strip()
        region_val = str(payload.get("region") or "").strip()

        if raw_text:
            for line in raw_text.splitlines():
                cleaned = line.strip()
                if not cleaned or cleaned.startswith("#") or cleaned.startswith("["):
                    continue
                for prefix in ("export ", "set ", "$env:"):
                    if cleaned.lower().startswith(prefix):
                        cleaned = cleaned[len(prefix):].strip()
                if "=" not in cleaned:
                    continue
                k, v = cleaned.split("=", 1)
                k_low = k.strip().lower()
                v_clean = v.strip().strip('"').strip("'")
                if k_low in ("aws_access_key_id", "access_key_id"):
                    access_key = v_clean
                elif k_low in ("aws_secret_access_key", "secret_access_key"):
                    secret_key = v_clean
                elif k_low in ("aws_session_token", "session_token", "session_value"):
                    session_val = v_clean
                elif k_low in ("aws_region", "aws_default_region", "region"):
                    region_val = v_clean

        if not access_key or not secret_key:
            return {
                "status": "error",
                "message": "AWS Access Key ID and Secret Access Key are required.",
            }, 400

        effective_region = region_val or os.environ.get("AWS_REGION") or "us-east-1"
        os.environ["AWS_ACCESS_KEY_ID"] = access_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key
        os.environ["AWS_REGION"] = effective_region
        os.environ["AWS_DEFAULT_REGION"] = effective_region
        if session_val:
            os.environ["AWS_SESSION_TOKEN"] = session_val
        elif access_key.startswith("AKIA"):
            os.environ.pop("AWS_SESSION_TOKEN", None)

        os.environ["MULETRACE_SIMULATION_TRANSPORT"] = "eventbridge"

        try:
            import tempfile
            runtime_file = Path(tempfile.gettempdir()) / "muletrace_aws_runtime.json"
            runtime_file.write_text(
                json.dumps(
                    {
                        "AWS_ACCESS_KEY_ID": access_key,
                        "AWS_SECRET_ACCESS_KEY": secret_key,
                        "AWS_SESSION_TOKEN": session_val,
                        "AWS_REGION": effective_region,
                        "AWS_DEFAULT_REGION": effective_region,
                    }
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        status_info = self._get_aws_credentials_status()
        status_info["message"] = f"AWS Credentials updated ({status_info['masked_key_id']})"
        return status_info, 200

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
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._send_cors_headers()
            if headers:
                for k, v in headers.items():
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

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
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._send_cors_headers()
            if headers:
                for k, v in headers.items():
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def copyfile(self, source: Any, outputfile: Any) -> None:
        """Suppress client socket abort tracebacks when browser cancels static asset downloads."""
        try:
            super().copyfile(source, outputfile)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def handle_one_request(self) -> None:
        """Suppress benign client socket disconnects on Windows."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def end_headers(self) -> None:
        """Add strict cache control headers to prevent browser caching of sensitive pages."""
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        try:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True
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

            if clean_lower == "/api/admin/aws-credentials":
                self._send_json_response(self._get_aws_credentials_status(), 200)
                return

            self._send_json_response({"status": "error", "message": "Admin endpoint not found"}, 404)
            return

        if clean_lower == "/api/aws/credentials":
            user = self._require_auth()
            if user is None:
                return
            self._send_json_response(self._get_aws_credentials_status(), 200)
            return

        # 3b. Simulation Run Status API (Requires authenticated role)
        if clean_lower.startswith("/api/simulation/status/"):
            user = self._require_auth()
            if user is None:
                return
            sim_run_id = clean_path.split("/")[-1]
            from app.backend.simulation.engine import SimulationEngine
            status_data = SimulationEngine.get_run_status(sim_run_id)
            if status_data:
                self._send_json_response({"status": "success", "data": status_data}, 200)
            else:
                self._send_json_response({"status": "error", "message": f"Run ID '{sim_run_id}' not found"}, 404)
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
                records = [
                    {
                        "caseId": "MT-1042",
                        "source": "A001",
                        "target": "B782",
                        "amount": 180000.0,
                        "time": "2026-09-16T02:13:00",
                        "status": "new",
                        "risk": "HIGH",
                        "priorityScore": 96,
                        "transactionId": "T001",
                        "description": "บัญชีเปิดใหม่ B782 รับโอนยอดสูง ฿180,000 จากหลายบัญชีและโอนออกต่อไปยัง C991 และ D201 ภายใน 90 นาที",
                    },
                    {
                        "caseId": "MT-1043",
                        "source": "A024",
                        "target": "B782",
                        "amount": 95000.0,
                        "time": "2026-09-16T02:14:00",
                        "status": "new",
                        "risk": "HIGH",
                        "priorityScore": 88,
                        "transactionId": "T002",
                        "description": "โอนเงินสมทบเข้าบัญชีเป้าหมาย B782 ต่อเนื่องในช่วงเวลาเดียวกัน เชื่อมโยงกับเครือข่ายเคสก่อนหน้า MT-0931",
                    },
                ]
                for idx, cid in enumerate(unique_cases):
                    accounts = cases_df[cases_df["case_id"] == cid]["account_id"].tolist()
                    target = accounts[0] if accounts else None
                    tx_match = tx_df[tx_df["target_account"] == target] if target else None
                    has_tx = tx_match is not None and not tx_match.empty
                    amount = float(tx_match.iloc[0]["amount"]) if has_tx else 0.0
                    source = str(tx_match.iloc[0]["source_account"]) if has_tx else "-"
                    tx_time = (
                        str(tx_match.iloc[0]["timestamp"]).replace(" ", "T")[:19]
                        if has_tx and "timestamp" in tx_match.columns
                        else "2026-09-16T02:13:00"
                    )
                    tx_id = (
                        str(tx_match.iloc[0]["transaction_id"])
                        if has_tx and "transaction_id" in tx_match.columns
                        else "T001"
                    )
                    records.append({
                        "caseId": cid,
                        "source": source,
                        "target": target,
                        "amount": amount,
                        "time": tx_time,
                        "status": "new",
                        "risk": "HIGH" if idx == 0 else "MEDIUM",
                        "priorityScore": 82 if idx == 0 else 74,
                        "transactionId": tx_id,
                        "description": f"ตรวจพบธุรกรรมต้องสงสัยเชื่อมโยงบัญชี {source} → {target} ในชุดข้อมูลเฝ้าระวัง",
                    })
                try:
                    from app.backend.simulation.transport import get_simulated_cases
                    for sim_case in get_simulated_cases():
                        if not any(r.get("caseId") == sim_case.get("caseId") for r in records):
                            records.insert(0, sim_case)
                except Exception:
                    pass
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

                if not isinstance(email, str) or not email.strip():
                    self._send_json_response({"status": "error", "message": "Email is required."}, 400)
                    return
                if not isinstance(password, str) or not password:
                    self._send_json_response({"status": "error", "message": "Password is required."}, 400)
                    return

                dname = str(display_name) if display_name is not None else None
                role_val = str(role_override) if role_override is not None else None

                try:
                    user_data = self.admin_service.create_bank_officer(
                        admin_actor_id=admin_user["id"],
                        email=email,
                        password=password,
                        display_name=dname,
                        client_supplied_role=role_val,
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
                if not isinstance(new_password, str) or not new_password:
                    self._send_json_response({"status": "error", "message": "New password is required."}, 400)
                    return

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

            if clean_path == "/api/admin/aws-credentials":
                res_data, code = self._update_aws_credentials(payload)
                self._send_json_response(res_data, code)
                return

            self._send_json_response({"status": "error", "message": "Admin endpoint not found"}, 404)
            return

        if clean_path == "/api/aws/credentials":
            user = self._require_auth()
            if user is None:
                return
            if not self._is_safe_origin():
                self._send_json_response({"status": "error", "message": "CSRF verification failed"}, 403)
                return
            res_data, code = self._update_aws_credentials(payload)
            self._send_json_response(res_data, code)
            return

        # 3b. Officer-initiated Bedrock Converse tool-use agent (never automatic)
        if clean_path in ("/api/ai/investigate", "/ai/investigate"):
            user = self._require_user()
            if user is None:
                return

            case_id = str(payload.get("case_id") or "").strip()
            if not case_id or len(case_id) > 100:
                self._send_json_response({"error": "Valid case_id required"}, 400)
                return

            investigation = payload.get("investigation") if isinstance(payload.get("investigation"), dict) else {}
            try:
                from app.backend.aws.dynamodb_service import get_investigation_alert
                stored = get_investigation_alert(case_id) or {}
            except Exception:
                stored = {}
            stored_data = stored.get("data") if isinstance(stored.get("data"), dict) else {}

            if case_id.startswith("SIM-"):
                simulation_context = {
                    key: stored_data[key]
                    for key in (
                        "caseId", "case_id", "source_account", "target_account",
                        "transaction_id", "amount", "score", "priority", "risk", "scenario",
                    )
                    if stored_data.get(key) is not None
                }
                if not simulation_context:
                    try:
                        from app.backend.simulation.transport import get_simulated_cases
                        sim_match = next((sc for sc in get_simulated_cases() if sc.get("caseId") == case_id), None)
                        if sim_match:
                            simulation_context = {
                                "caseId": sim_match.get("caseId"),
                                "source_account": sim_match.get("source"),
                                "target_account": sim_match.get("target"),
                                "amount": sim_match.get("amount"),
                                "score": sim_match.get("priorityScore"),
                                "risk": sim_match.get("risk"),
                            }
                    except Exception:
                        pass
                objective = (
                    f"Review synthetic test case {case_id}. "
                    "Use available tools to check related account or transaction records when possible. "
                    "Simulation metadata below is sourced from DynamoDB, not the canonical CSV dataset. "
                    "Do not treat CSV tool results as proof of simulation events. "
                    "If a tool cannot verify a simulation record, explicitly say it is unverified. "
                    "Do not invent evidence or infer wrongdoing. Simulation metadata: "
                    + json.dumps(simulation_context, ensure_ascii=False, default=str)
                )
            else:
                context_data = {
                    "case_id": case_id,
                    "frontend_investigation": investigation,
                    "simulation_case": None,
                }
                objective = (
                    "Investigate the synthetic AML case " + case_id + ". "
                    "IMPORTANT: If the case_id starts with SIM-, you MUST first call "
                    "get_simulation_case using the case_id to retrieve the actual "
                    "simulation record from DynamoDB. "
                    "A case ID is NOT an account ID. Never pass a SIM- case ID "
                    "to account-based tools. "
                    "Use only real source and target account identifiers found "
                    "in the retrieved simulation record for account-based tools. "
                    "Canonical CSV tools may not contain simulated transactions. "
                    "Do not interpret missing CSV records as missing DynamoDB evidence. "
                    "Clearly distinguish DynamoDB simulation evidence from CSV evidence. "
                    "For non-SIM cases, investigate using the normal engine tools. "
                    "Do not fabricate tool findings or claim guilt. Context: "
                    + json.dumps(context_data, ensure_ascii=False, default=str)[:12000]
                )

            try:
                from app.backend.aws.bedrock_service import run_investigation_agent
                result = run_investigation_agent(
                    objective=objective,
                    max_turns=6,
                    model_id="amazon.nova-micro-v1:0",
                )
                result_status = result.get("status", "error")
                code = 502 if result_status in ("content_filtered", "error") else 200
                self._send_json_response({
                    "status": result_status,
                    "case_id": case_id,
                    "summary": result.get("final_answer", ""),
                    "executed_tools": result.get("executed_tools", []),
                    "turns_taken": result.get("turns_taken", 0),
                    "model_id": result.get("model_id"),
                }, code)
                return
            except Exception as exc:
                self._send_json_response({"status": "error", "message": str(exc)}, 502)
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

                # Fetch engine investigation metrics or build per-case simulated dataset
                try:
                    if str(case_id).upper().startswith("SIM-"):
                        from app.backend.simulation.transport import get_simulated_cases
                        sim_match = next(
                            (sc for sc in get_simulated_cases() if sc.get("caseId") == str(case_id)),
                            None,
                        )
                        tx_records = (
                            investigation_input.get("transactions")
                            or (sim_match or {}).get("transactions")
                            or []
                        )
                        ev_chain = investigation_input.get("evidence_chain") or []
                        src_acc = (
                            investigation_input.get("source_account")
                            or (sim_match or {}).get("source")
                            or "-"
                        )
                        tgt_acc = (
                            investigation_input.get("target_account")
                            or (sim_match or {}).get("target")
                            or "-"
                        )
                        scope_accounts = investigation_input.get("linked_accounts") or list(
                            dict.fromkeys(
                                [src_acc, tgt_acc]
                                + [str(t.get("from") or t.get("source_account", "")) for t in tx_records]
                                + [str(t.get("to") or t.get("target_account", "")) for t in tx_records]
                            )
                        )
                        investigation_data = {
                            "case_id": str(case_id),
                            "source_account": src_acc,
                            "target_account": tgt_acc,
                            "alert_amount": investigation_input.get("alert_amount")
                            or (sim_match or {}).get("amount", 0.0),
                            "accounts_in_scope": [a for a in scope_accounts if a and a != "-"],
                            "score": investigation_input.get("priority_score")
                            or (sim_match or {}).get("priorityScore", 90),
                            "priority": investigation_input.get("risk_level")
                            or (sim_match or {}).get("risk", "HIGH"),
                            "rule_types_matched": [
                                item.get("title", "pattern_match") for item in ev_chain
                            ]
                            or ["multiple_incoming", "rapid_outgoing", "high_value_transfer"],
                            "reasons": [
                                f"{item.get('title', '')}: {item.get('detail', '')}"
                                for item in ev_chain
                            ]
                            or [
                                f"Target node {tgt_acc} received high-frequency transfers from {src_acc} and routed funds across connected nodes"
                            ],
                            "finding_count": max(len(ev_chain), 1),
                            "evidence_transaction_ids": [
                                str(t.get("transaction_id") or t.get("id", ""))
                                for t in tx_records[:15]
                                if t.get("transaction_id") or t.get("id")
                            ],
                            "evidence": tx_records[:20],
                        }
                    else:
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
                            f"- สัญญาณความเสี่ยงที่พบ: {', '.join(investigation_data.get('rule_types_matched', ['multiple_incoming', 'rapid_outgoing']))}\n"
                            f"- สถานะ: สรุปผลเบื้องต้นจากระบบกฎภายในเรียบร้อยแล้ว\n"
                            f"(แจ้งเตือนการเชื่อมต่อ AWS Bedrock: {ai_err})"
                        )

                self._send_json_response({"status": "success", "summary": summary})
                return

            except Exception:
                self._send_json_response({"status": "error", "message": "Internal server error"}, 500)
                return

        # 5. Simulation Execution API (Requires 'user' role; Bank Officer action)
        if clean_path in ("/api/simulation/run", "/api/simulate", "/simulation/run"):
            user = self._require_user()
            if user is None:
                return

            if not self._is_safe_origin():
                self._send_json_response({"status": "error", "message": "CSRF verification failed"}, 403)
                return

            try:
                from datetime import datetime
                from app.backend.simulation.engine import SimulationEngine

                seed_val = payload.get("seed")
                if seed_val is not None:
                    try:
                        seed_val = int(seed_val)
                    except (ValueError, TypeError):
                        seed_val = None

                base_time_raw = payload.get("base_timestamp") or payload.get("base_time")
                base_time_dt = None
                if base_time_raw and isinstance(base_time_raw, str):
                    try:
                        base_time_dt = datetime.fromisoformat(base_time_raw.replace("Z", "+00:00"))
                    except Exception:
                        base_time_dt = None

                import concurrent.futures
                from app.backend.simulation.transport import LocalSimulationTransport

                engine_inst = SimulationEngine()
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(engine_inst.run_simulation, seed=seed_val, base_time=base_time_dt)
                        sim_res = fut.result(timeout=2.5)
                except Exception:
                    fallback_engine = SimulationEngine(transport=LocalSimulationTransport())
                    sim_res = fallback_engine.run_simulation(seed=seed_val, base_time=base_time_dt)
                self._send_json_response({"status": "success", "data": sim_res}, 200)
                return
            except Exception as sim_err:
                self._send_json_response({"status": "error", "message": f"Simulation failed: {sim_err}"}, 500)
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
                if not isinstance(is_active, bool):
                    self._send_json_response({"status": "error", "message": "is_active must be a boolean."}, 400)
                    return

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


def _setup_local_demo_auth_if_needed() -> None:
    """Configure Amazon Cognito when AWS credentials are available, or fallback to SQLite."""
    os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_isiF7v59f")
    os.environ.setdefault("COGNITO_APP_CLIENT_ID", "7e9d5usrro4b6jnd7pk741m3vi")
    os.environ.setdefault("COGNITO_GROUP_ADMIN", "Admin")
    os.environ.setdefault("COGNITO_GROUP_OFFICER", "BankOfficer")

    if os.environ.get("MULETRACE_AUTH_PROVIDER", "").strip().lower() == "cognito":
        MuleTraceRequestHandler._custom_auth_service = None
        MuleTraceRequestHandler._custom_admin_service = None
        pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
        client_id = os.environ.get("COGNITO_APP_CLIENT_ID", "")
        print(f"[*] Auth Provider: Amazon Cognito (UserPool: {pool_id}, ClientId: {client_id})", flush=True)
        return

    if os.environ.get("DATABASE_URL", "").strip():
        return

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from app.backend.auth.security import hash_password
        from app.backend.db.auth_repositories import UserRepository
        from app.backend.db.models import Base

        import tempfile
        db_file = Path(tempfile.gettempdir()) / "muletrace_demo_auth.sqlite"
        demo_engine = create_engine(
            f"sqlite:///{db_file.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(
            demo_engine,
            tables=[Base.metadata.tables[t] for t in ("users", "auth_sessions", "auth_audit_logs")],
        )
        with Session(demo_engine) as session:
            user_repo = UserRepository(session)
            if not user_repo.get_by_email("officer@agency.go.th"):
                user_repo.create_user(
                    email="officer@agency.go.th",
                    display_name="Bank Officer",
                    role="user",
                    password_hash=hash_password("OfficerPass123!@#"),
                    is_active=True,
                )
            if not user_repo.get_by_email("admin@agency.go.th"):
                user_repo.create_user(
                    email="admin@agency.go.th",
                    display_name="System Admin",
                    role="admin",
                    password_hash=hash_password("AdminPass123!@#"),
                    is_active=True,
                )
            session.commit()

        MuleTraceRequestHandler._custom_auth_service = AuthService(engine=demo_engine)
        MuleTraceRequestHandler._custom_admin_service = AdminService(engine=demo_engine)
        print("[*] Auth Service active (Argon2id + 5-attempt rate limit):", flush=True)
        print("    - Bank Officer (Dashboard): officer@agency.go.th  /  OfficerPass123!@#", flush=True)
        print("    - Administrator (Admin):    admin@agency.go.th    /  AdminPass123!@#", flush=True)
    except Exception as exc:
        print(f"[!] Auth setup warning: {exc}", flush=True)


def run_server(port: int = 8000, bind: str = "127.0.0.1", directory: Path | str | None = None) -> None:
    # Load private environment (.env)
    env = load_environment(PROJECT_ROOT)
    os.environ.update(env)
    try:
        import tempfile
        runtime_file = Path(tempfile.gettempdir()) / "muletrace_aws_runtime.json"
        if runtime_file.is_file():
            saved_creds = json.loads(runtime_file.read_text(encoding="utf-8"))
            for k, v in saved_creds.items():
                if v:
                    os.environ[k] = str(v)
    except Exception:
        pass
    if not os.environ.get("MULETRACE_SIMULATION_TRANSPORT", "").strip():
        if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"):
            os.environ["MULETRACE_SIMULATION_TRANSPORT"] = "eventbridge"
    _setup_local_demo_auth_if_needed()
    active_transport = os.environ.get("MULETRACE_SIMULATION_TRANSPORT", "local").strip().lower()
    if active_transport == "eventbridge":
        bus_name = os.environ.get("EVENTBRIDGE_BUS_NAME", "muletrace-transactions")
        print(f"[*] Simulation Transport: Amazon EventBridge (bus: {bus_name})", flush=True)

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
