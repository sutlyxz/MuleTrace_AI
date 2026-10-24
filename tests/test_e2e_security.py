"""Phase 4.3: End-to-End Security & Browser Acceptance Test Suite.

Executes comprehensive E2E tests against the isolated PostgreSQL database (muletrace_test).
Validates:
- Part A: Test environment isolation and preflight verification
- Part B: Full account lifecycle (Admin bootstrap/login, officer creation, officer login,
          role isolation, deactivation, reactivation, password reset, logout)
- Part C: Full authorization matrix (Anonymous, Admin, Officer, Deactivated, Revoked)
- Part D: CSRF, cookie security, session revocation, error handling, SQL/trace protection
- Part E: Frontend integration, safe DOM rendering (XSS protection), responsive table rules
- Part I: Strict development database (muletrace) immutability verification
"""
from __future__ import annotations

import http.client
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import threading
import time
import unittest
from urllib.parse import urlparse

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.backend.auth.security import hash_password, verify_password
from app.backend.config import load_environment
from app.backend.db import config as db_config
from app.backend.db.auth_repositories import (
    AuditLogRepository,
    SessionRepository,
    UserRepository,
)
from app.backend.db.models import (
    Account,
    Alert,
    AlertTransaction,
    AuthAuditLog,
    AuthSession,
    Base,
    Case,
    CaseAccount,
    Transaction,
    User,
)
from app.backend.server import MuleTraceRequestHandler
from app.backend.services.admin_service import AdminService
from app.backend.services.auth_service import AuthService, LoginRateLimiter

PROJECT_ROOT = Path(r"C:\MuleTrace_AI")
FRONTEND_DIR = PROJECT_ROOT / "app" / "frontend"
TEST_PORT = 8001
TEST_HOST = "127.0.0.1"


class IsolatedTestServerHandler(MuleTraceRequestHandler):
    """Handler bound exclusively to the PostgreSQL muletrace_test engine."""
    pass


class TestPhase43E2ESecurity(unittest.TestCase):
    test_engine = None
    server = None
    server_thread = None
    dev_baseline = {}

    @classmethod
    def setUpClass(cls):
        # 1. Environment & Database Isolation Verification
        env = load_environment(PROJECT_ROOT)
        dev_url = env.get(db_config.DATABASE_URL_ENV) or ""
        test_url = env.get(db_config.TEST_DATABASE_URL_ENV) or ""

        if not dev_url or not test_url:
            raise unittest.SkipTest("DATABASE_URL and TEST_DATABASE_URL are required for live PostgreSQL E2E tests")

        dev_db = urlparse(dev_url).path.lstrip("/")
        test_db = urlparse(test_url).path.lstrip("/")

        assert dev_db == "muletrace", f"Development DB must be muletrace, got {dev_db}"
        assert test_db == "muletrace_test", f"Test DB must be muletrace_test, got {test_db}"
        assert dev_db != test_db, "TEST DB cannot be the same as DEV DB"
        assert test_db != "muletrace_restore_verify", "TEST DB cannot be backup verification DB"

        # Record DEV DB initial baseline
        dev_engine = create_engine(dev_url)
        with Session(dev_engine) as sess:
            cls.dev_baseline = {
                "users": sess.scalar(select(func.count(User.id))),
                "accounts": sess.scalar(select(func.count(Account.account_id))),
                "transactions": sess.scalar(select(func.count(Transaction.transaction_id))),
                "cases": sess.scalar(select(func.count(Case.case_id))),
                "case_accounts": sess.scalar(select(func.count(CaseAccount.case_id))),
                "alerts": sess.scalar(select(func.count(Alert.alert_id))),
                "alert_transactions": sess.scalar(select(func.count(AlertTransaction.alert_id))),
                "alembic_rev": sess.execute(text("SELECT version_num FROM alembic_version")).scalar(),
            }
        dev_engine.dispose()

        # Connect to test database
        cls.test_engine = create_engine(test_url)
        cls.rate_limiter = LoginRateLimiter()
        cls.auth_service = AuthService(engine=cls.test_engine, rate_limiter=cls.rate_limiter)
        cls.admin_service = AdminService(engine=cls.test_engine)

        # Inject services into IsolatedTestServerHandler
        IsolatedTestServerHandler.auth_service = cls.auth_service
        IsolatedTestServerHandler.admin_service = cls.admin_service

        # Start isolated HTTP server on port 8001
        def make_handler(*args, **kwargs):
            return IsolatedTestServerHandler(*args, directory=str(FRONTEND_DIR), **kwargs)

        ThreadingHTTPServer.allow_reuse_address = True
        cls.server = ThreadingHTTPServer((TEST_HOST, TEST_PORT), make_handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)  # Allow server to bind

    @classmethod
    def tearDownClass(cls):
        # Clean up any disposable test users from muletrace_test
        if cls.test_engine:
            with Session(cls.test_engine) as sess:
                test_users = sess.execute(select(User).where(User.email.like("e2e_4_3_%"))).scalars().all()
                for u in test_users:
                    sess.delete(u)
                sess.commit()
            cls.test_engine.dispose()

        # Shutdown port 8001 test server
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()

        # Verify DEV DB was NOT mutated
        env = load_environment(PROJECT_ROOT)
        dev_url = env.get(db_config.DATABASE_URL_ENV) or ""
        dev_engine = create_engine(dev_url)
        with Session(dev_engine) as sess:
            current = {
                "users": sess.scalar(select(func.count(User.id))),
                "accounts": sess.scalar(select(func.count(Account.account_id))),
                "transactions": sess.scalar(select(func.count(Transaction.transaction_id))),
                "cases": sess.scalar(select(func.count(Case.case_id))),
                "case_accounts": sess.scalar(select(func.count(CaseAccount.case_id))),
                "alerts": sess.scalar(select(func.count(Alert.alert_id))),
                "alert_transactions": sess.scalar(select(func.count(AlertTransaction.alert_id))),
                "alembic_rev": sess.execute(text("SELECT version_num FROM alembic_version")).scalar(),
            }
        dev_engine.dispose()

        assert current == cls.dev_baseline, f"DEV DB was altered! Expected {cls.dev_baseline}, got {current}"

    def _http_request(
        self,
        method: str,
        path: str,
        body: dict | str | bytes | None = None,
        headers: dict | None = None,
        cookie: str | None = None,
        origin: str | None = f"http://{TEST_HOST}:{TEST_PORT}",
    ) -> tuple[int, dict[str, str], bytes]:
        """Performs a real HTTP request against the isolated port 8001 server."""
        conn = http.client.HTTPConnection(TEST_HOST, TEST_PORT, timeout=10)
        req_headers = {"Host": f"{TEST_HOST}:{TEST_PORT}", "Accept": "application/json, text/html, */*"}

        if origin is not None:
            req_headers["Origin"] = origin
        if cookie:
            req_headers["Cookie"] = f"muletrace_session={cookie}"

        if headers:
            req_headers.update(headers)

        payload = None
        if body is not None:
            if isinstance(body, dict):
                payload = json.dumps(body).encode("utf-8")
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/json"
            elif isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = body
            req_headers["Content-Length"] = str(len(payload))

        conn.request(method, path, body=payload, headers=req_headers)
        res = conn.getresponse()
        res_body = res.read()
        res_headers = {k.lower(): v for k, v in res.getheaders()}
        conn.close()
        return res.status, res_headers, res_body

    def _extract_cookie(self, headers: dict[str, str]) -> str | None:
        set_cookie = headers.get("set-cookie")
        if not set_cookie:
            return None
        c = SimpleCookie()
        c.load(set_cookie)
        if "muletrace_session" in c:
            return c["muletrace_session"].value
        return None

    def _create_disposable_user(self, email: str, role: str, password: str = "SecurePass123!@#") -> str:
        with Session(self.test_engine) as session:
            repo = UserRepository(session)
            existing = repo.get_by_email(email)
            if existing:
                session.delete(existing)
                session.commit()
            user = repo.create_user(
                email=email,
                display_name=f"Disposable {role.capitalize()}",
                role=role,
                password_hash=hash_password(password),
                is_active=True,
            )
            session.commit()
            return user.id

    # =========================================================================
    # Part B — End-to-End Account Lifecycle
    # =========================================================================

    def test_b_full_account_lifecycle(self):
        """Tests the complete 8-step account lifecycle in muletrace_test."""
        ts = int(time.time() * 1000)
        admin_email = f"e2e_4_3_admin_{ts}@agency.go.th"
        officer_email = f"e2e_4_3_officer_{ts}@agency.go.th"
        admin_pwd = "AdminSecurePass123!@#"
        officer_initial_pwd = "OfficerInitial123!@#"
        officer_new_pwd = "OfficerNewPass456!@#"

        # --- STEP 1: Admin Authentication ---
        admin_id = self._create_disposable_user(admin_email, role="admin", password=admin_pwd)
        status, headers, body = self._http_request(
            "POST",
            "/api/auth/login",
            body={"email": admin_email, "password": admin_pwd},
        )
        self.assertEqual(status, 200)
        admin_cookie = self._extract_cookie(headers)
        self.assertIsNotNone(admin_cookie)
        self.assertIn("httponly", headers.get("set-cookie", "").lower())
        self.assertIn("samesite=lax", headers.get("set-cookie", "").lower())

        # Confirm GET /api/auth/me identifies role=admin
        status, _, body = self._http_request("GET", "/api/auth/me", cookie=admin_cookie)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["user"]["role"], "admin")
        self.assertEqual(data["user"]["email"], admin_email)

        # Confirm Admin can access /admin.html
        status, headers, body = self._http_request("GET", "/admin.html", cookie=admin_cookie)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("Admin Portal", body.decode("utf-8"))

        # --- STEP 2: Admin Creates Bank Officer ---
        status, _, body = self._http_request(
            "POST",
            "/api/admin/users",
            body={
                "email": officer_email,
                "display_name": "E2E Bank Officer",
                "password": officer_initial_pwd,
                "role": "user",
            },
            cookie=admin_cookie,
        )
        self.assertEqual(status, 201)
        create_res = json.loads(body.decode("utf-8"))
        self.assertEqual(create_res["status"], "success")
        officer_id = create_res["user"]["id"]
        self.assertEqual(create_res["user"]["role"], "user")
        self.assertEqual(create_res["user"]["email"], officer_email)
        # Confirm password and password_hash are NEVER exposed in response
        self.assertNotIn("password", create_res["user"])
        self.assertNotIn("password_hash", create_res["user"])

        # Confirm password in DB is Argon2id hash
        with Session(self.test_engine) as sess:
            u = sess.execute(select(User).where(User.id == officer_id)).scalar_one()
            self.assertTrue(u.password_hash.startswith("$argon2id$"))
            self.assertTrue(verify_password(officer_initial_pwd, u.password_hash))

            # Confirm user_created audit event exists
            audit = sess.execute(
                select(AuthAuditLog).where(
                    AuthAuditLog.action == "user_created",
                    AuthAuditLog.target_user_id == officer_id,
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.actor_user_id, admin_id)

        # --- STEP 3: Bank Officer Login & Role Boundaries ---
        status, headers, _ = self._http_request(
            "POST",
            "/api/auth/login",
            body={"email": officer_email, "password": officer_initial_pwd},
        )
        self.assertEqual(status, 200)
        officer_cookie = self._extract_cookie(headers)
        self.assertIsNotNone(officer_cookie)

        # Confirm GET /api/auth/me identifies role=user
        status, _, body = self._http_request("GET", "/api/auth/me", cookie=officer_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["user"]["role"], "user")

        # Confirm Bank Officer can access /index.html and investigation APIs
        status, _, body = self._http_request("GET", "/index.html", cookie=officer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("MuleTrace", body.decode("utf-8"))

        status, _, _ = self._http_request("GET", "/api/cases", cookie=officer_cookie)
        self.assertEqual(status, 200)

        # Confirm Bank Officer CANNOT access /admin.html or Admin APIs
        status, _, _ = self._http_request("GET", "/admin.html", cookie=officer_cookie)
        self.assertEqual(status, 403)

        status, _, _ = self._http_request("GET", "/api/admin/users", cookie=officer_cookie)
        self.assertEqual(status, 403)

        status, _, _ = self._http_request("GET", "/api/admin/audit-logs", cookie=officer_cookie)
        self.assertEqual(status, 403)

        # Confirm Bank Officer CANNOT access Admin-specific assets
        for asset in ("/assets/css/admin.css", "/assets/js/admin.js"):
            status, _, _ = self._http_request("GET", asset, cookie=officer_cookie)
            self.assertEqual(status, 403)

        # --- STEP 4: Admin Role Isolation ---
        # Confirm Admin CANNOT access Dashboard or investigation APIs
        status, _, _ = self._http_request("GET", "/index.html", cookie=admin_cookie)
        self.assertEqual(status, 403)

        status, _, _ = self._http_request("GET", "/api/cases", cookie=admin_cookie)
        self.assertEqual(status, 403)

        # Confirm Admin can access Admin APIs
        status, _, _ = self._http_request("GET", "/api/admin/users", cookie=admin_cookie)
        self.assertEqual(status, 200)

        # --- STEP 5: Account Deactivation & Session Revocation ---
        status, _, body = self._http_request(
            "PATCH",
            f"/api/admin/users/{officer_id}/status",
            body={"is_active": False},
            cookie=admin_cookie,
        )
        self.assertEqual(status, 200)

        with Session(self.test_engine) as sess:
            u = sess.execute(select(User).where(User.id == officer_id)).scalar_one()
            self.assertFalse(u.is_active)

            # Confirm user_deactivated audit event
            audit = sess.execute(
                select(AuthAuditLog).where(
                    AuthAuditLog.action == "user_deactivated",
                    AuthAuditLog.target_user_id == officer_id,
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(audit)

        # Confirm revoked officer session returns HTTP 401 on protected APIs
        status, _, _ = self._http_request("GET", "/api/auth/me", cookie=officer_cookie)
        self.assertEqual(status, 401)

        status, _, _ = self._http_request("GET", "/api/cases", cookie=officer_cookie)
        self.assertEqual(status, 401)

        # Confirm deactivated account cannot log in
        status, _, _ = self._http_request(
            "POST",
            "/api/auth/login",
            body={"email": officer_email, "password": officer_initial_pwd},
        )
        self.assertEqual(status, 401)

        # --- STEP 6: Account Reactivation ---
        status, _, _ = self._http_request(
            "PATCH",
            f"/api/admin/users/{officer_id}/status",
            body={"is_active": True},
            cookie=admin_cookie,
        )
        self.assertEqual(status, 200)

        with Session(self.test_engine) as sess:
            u = sess.execute(select(User).where(User.id == officer_id)).scalar_one()
            self.assertTrue(u.is_active)

            # Confirm user_activated audit event
            audit = sess.execute(
                select(AuthAuditLog).where(
                    AuthAuditLog.action == "user_activated",
                    AuthAuditLog.target_user_id == officer_id,
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(audit)

        # Confirm reactivated account can log in again
        status, headers, _ = self._http_request(
            "POST",
            "/api/auth/login",
            body={"email": officer_email, "password": officer_initial_pwd},
        )
        self.assertEqual(status, 200)
        officer_cookie_2 = self._extract_cookie(headers)
        self.assertIsNotNone(officer_cookie_2)

        # --- STEP 7: Password Reset & Session Revocation ---
        status, _, body = self._http_request(
            "POST",
            f"/api/admin/users/{officer_id}/reset-password",
            body={"new_password": officer_new_pwd},
            cookie=admin_cookie,
        )
        self.assertEqual(status, 200)
        reset_res = json.loads(body.decode("utf-8"))
        self.assertEqual(reset_res["status"], "success")
        self.assertNotIn("password", reset_res)

        # Confirm old password no longer works
        status, _, _ = self._http_request(
            "POST",
            "/api/auth/login",
            body={"email": officer_email, "password": officer_initial_pwd},
        )
        self.assertEqual(status, 401)

        # Confirm active session before reset was revoked
        status, _, _ = self._http_request("GET", "/api/auth/me", cookie=officer_cookie_2)
        self.assertEqual(status, 401)

        # Confirm new password works
        status, headers, _ = self._http_request(
            "POST",
            "/api/auth/login",
            body={"email": officer_email, "password": officer_new_pwd},
        )
        self.assertEqual(status, 200)
        officer_cookie_3 = self._extract_cookie(headers)
        self.assertIsNotNone(officer_cookie_3)

        # Confirm password_reset audit event exists and does not contain plain password
        with Session(self.test_engine) as sess:
            audit = sess.execute(
                select(AuthAuditLog).where(
                    AuthAuditLog.action == "password_reset",
                    AuthAuditLog.target_user_id == officer_id,
                )
            ).scalar_one_or_none()
            self.assertIsNotNone(audit)
            self.assertNotIn(officer_new_pwd, json.dumps(audit.safe_metadata or {}))

        # --- STEP 8: Logout ---
        # Logout as Officer
        status, _, _ = self._http_request("POST", "/api/auth/logout", cookie=officer_cookie_3)
        self.assertEqual(status, 200)
        status, _, _ = self._http_request("GET", "/api/auth/me", cookie=officer_cookie_3)
        self.assertEqual(status, 401)

        # Logout as Admin
        status, _, _ = self._http_request("POST", "/api/auth/logout", cookie=admin_cookie)
        self.assertEqual(status, 200)
        status, _, _ = self._http_request("GET", "/api/auth/me", cookie=admin_cookie)
        self.assertEqual(status, 401)

    # =========================================================================
    # Part C — Comprehensive Authorization Matrix
    # =========================================================================

    def test_c_authorization_matrix(self):
        """Verifies access to all protected HTML, API, and static endpoints across all 5 caller states."""
        ts = int(time.time() * 1000)
        admin_email = f"e2e_4_3_matrix_admin_{ts}@agency.go.th"
        officer_email = f"e2e_4_3_matrix_officer_{ts}@agency.go.th"
        deactivated_email = f"e2e_4_3_matrix_deact_{ts}@agency.go.th"
        pwd = "MatrixSecurePass123!@#"

        admin_id = self._create_disposable_user(admin_email, "admin", pwd)
        officer_id = self._create_disposable_user(officer_email, "user", pwd)
        deact_id = self._create_disposable_user(deactivated_email, "user", pwd)

        # Obtain cookies
        _, h_adm, _ = self._http_request("POST", "/api/auth/login", body={"email": admin_email, "password": pwd})
        admin_cookie = self._extract_cookie(h_adm)

        _, h_off, _ = self._http_request("POST", "/api/auth/login", body={"email": officer_email, "password": pwd})
        officer_cookie = self._extract_cookie(h_off)

        _, h_dea, _ = self._http_request("POST", "/api/auth/login", body={"email": deactivated_email, "password": pwd})
        deact_cookie = self._extract_cookie(h_dea)

        # Deactivate the deactivated account (revokes session)
        self._http_request("PATCH", f"/api/admin/users/{deact_id}/status", body={"is_active": False}, cookie=admin_cookie)

        # Revoked session cookie
        revoked_cookie = "nonexistent_or_revoked_session_token_12345"

        # Define matrix test cases: (resource, method, anon_exp, admin_exp, officer_exp, deact_exp, revoked_exp)
        test_matrix = [
            # HTML Pages
            ("/login.html", "GET", 200, 200, 200, 200, 200),
            ("/admin.html", "GET", 401, 200, 403, 401, 401),
            ("/index.html", "GET", 401, 403, 200, 401, 401),
            # APIs
            ("/api/auth/me", "GET", 401, 200, 200, 401, 401),
            ("/api/admin/users", "GET", 401, 200, 403, 401, 401),
            ("/api/admin/audit-logs", "GET", 401, 200, 403, 401, 401),
            ("/api/cases", "GET", 401, 403, 200, 401, 401),
            # Static Assets
            ("/assets/css/admin.css", "GET", 401, 200, 403, 401, 401),
            ("/assets/js/admin.js", "GET", 401, 200, 403, 401, 401),
            ("/assets/css/style.css", "GET", 401, 403, 200, 401, 401),
            ("/assets/js/app.js", "GET", 401, 403, 200, 401, 401),
        ]

        for path, method, anon_exp, admin_exp, officer_exp, deact_exp, revoked_exp in test_matrix:
            with self.subTest(resource=path, role="Anonymous"):
                s, _, _ = self._http_request(method, path)
                self.assertEqual(s, anon_exp, f"Anonymous {method} {path} expected {anon_exp}, got {s}")

            with self.subTest(resource=path, role="Admin"):
                s, _, _ = self._http_request(method, path, cookie=admin_cookie)
                self.assertEqual(s, admin_exp, f"Admin {method} {path} expected {admin_exp}, got {s}")

            with self.subTest(resource=path, role="Officer"):
                s, _, _ = self._http_request(method, path, cookie=officer_cookie)
                self.assertEqual(s, officer_exp, f"Officer {method} {path} expected {officer_exp}, got {s}")

            with self.subTest(resource=path, role="Deactivated"):
                s, _, _ = self._http_request(method, path, cookie=deact_cookie)
                self.assertEqual(s, deact_exp, f"Deactivated {method} {path} expected {deact_exp}, got {s}")

            with self.subTest(resource=path, role="Revoked"):
                s, _, _ = self._http_request(method, path, cookie=revoked_cookie)
                self.assertEqual(s, revoked_exp, f"Revoked {method} {path} expected {revoked_exp}, got {s}")

    # =========================================================================
    # Part D — CSRF and HTTP Security Tests
    # =========================================================================

    def test_d_csrf_cross_origin_rejected(self):
        """Cross-origin mutation requests must be rejected with 403 CSRF error."""
        ts = int(time.time() * 1000)
        admin_email = f"e2e_4_3_csrf_admin_{ts}@agency.go.th"
        officer_email = f"e2e_4_3_csrf_officer_{ts}@agency.go.th"
        pwd = "CsrfSecurePass123!@#"

        self._create_disposable_user(admin_email, "admin", pwd)
        officer_id = self._create_disposable_user(officer_email, "user", pwd)

        _, h_adm, _ = self._http_request("POST", "/api/auth/login", body={"email": admin_email, "password": pwd})
        admin_cookie = self._extract_cookie(h_adm)

        evil_origin = "http://attacker-site.com"

        # 1. Cross-origin POST /api/admin/users rejected
        s, _, body = self._http_request(
            "POST",
            "/api/admin/users",
            body={"email": f"hacked_{ts}@agency.go.th", "password": pwd, "role": "user"},
            cookie=admin_cookie,
            origin=evil_origin,
        )
        self.assertEqual(s, 403)
        self.assertIn("csrf", json.loads(body.decode("utf-8"))["message"].lower())

        # 2. Cross-origin PATCH /api/admin/users/{id}/status rejected
        s, _, body = self._http_request(
            "PATCH",
            f"/api/admin/users/{officer_id}/status",
            body={"is_active": False},
            cookie=admin_cookie,
            origin=evil_origin,
        )
        self.assertEqual(s, 403)

        # Verify officer was NOT deactivated by the cross-origin attack
        with Session(self.test_engine) as sess:
            u = sess.execute(select(User).where(User.id == officer_id)).scalar_one()
            self.assertTrue(u.is_active, "Cross-origin request mutated officer status!")

        # 3. Cross-origin POST /api/admin/users/{id}/reset-password rejected
        s, _, body = self._http_request(
            "POST",
            f"/api/admin/users/{officer_id}/reset-password",
            body={"new_password": "HackedPass123!@#"},
            cookie=admin_cookie,
            origin=evil_origin,
        )
        self.assertEqual(s, 403)

    def test_d_security_headers_and_malformed_inputs(self):
        """Verifies Cache-Control, malformed JSON, and unknown user handling."""
        ts = int(time.time() * 1000)
        admin_email = f"e2e_4_3_sec_admin_{ts}@agency.go.th"
        pwd = "SecSecurePass123!@#"

        self._create_disposable_user(admin_email, "admin", pwd)
        _, h_adm, _ = self._http_request("POST", "/api/auth/login", body={"email": admin_email, "password": pwd})
        admin_cookie = self._extract_cookie(h_adm)

        # Cache-Control headers on protected pages
        status, headers, _ = self._http_request("GET", "/admin.html", cookie=admin_cookie)
        self.assertEqual(status, 200)
        cache_ctrl = headers.get("cache-control", "").lower()
        self.assertIn("no-store", cache_ctrl)
        self.assertIn("no-cache", cache_ctrl)

        # Malformed JSON handling
        status, _, body = self._http_request(
            "POST",
            "/api/admin/users",
            body="{invalid_json: true,",
            headers={"Content-Type": "application/json"},
            cookie=admin_cookie,
        )
        self.assertEqual(status, 400)
        # Confirm no internal stack trace leaked
        self.assertNotIn("Traceback", body.decode("utf-8"))
        self.assertNotIn("psycopg", body.decode("utf-8").lower())

        # Unknown user ID handling
        status, _, body = self._http_request(
            "PATCH",
            "/api/admin/users/usr_nonexistent_id_9999/status",
            body={"is_active": False},
            cookie=admin_cookie,
        )
        self.assertEqual(status, 404)
        self.assertNotIn("syntax error", body.decode("utf-8").lower())

    # =========================================================================
    # Part E — Frontend Security & Static Checks
    # =========================================================================

    def test_e_frontend_security_and_layout(self):
        """Verifies frontend HTML/JS/CSS security properties."""
        admin_html = (FRONTEND_DIR / "admin.html").read_text(encoding="utf-8")
        admin_js = (FRONTEND_DIR / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        admin_css = (FRONTEND_DIR / "assets" / "css" / "admin.css").read_text(encoding="utf-8")

        # 1. No fake browser storage authentication
        self.assertNotIn("localStorage.setItem", admin_js)
        self.assertNotIn("sessionStorage.setItem", admin_js)

        # 2. Strict read-only admin accounts section
        self.assertIn('id="adminAccountsSection"', admin_html)
        self.assertIn('id="officerAccountsSection"', admin_html)
        self.assertIn("🛡️ สงวนสิทธิ์ระบบ (Protected)", admin_js)

        # 3. Safe DOM manipulation via textContent (Zero innerHTML on user-controlled inputs)
        self.assertIn("nameStrong.textContent =", admin_js)
        self.assertIn("tdEmail.textContent =", admin_js)
        self.assertNotIn("tdName.innerHTML", admin_js)
        self.assertNotIn("tdEmail.innerHTML", admin_js)

        # 4. Password inputs cleared on modal close
        self.assertIn("clearCreateForm", admin_js)
        self.assertIn("clearResetForm", admin_js)

        # 5. Proportional column widths & compact cell padding
        self.assertIn(".col-officer-name", admin_css)
        self.assertIn(".col-officer-email", admin_css)
        self.assertIn(".col-officer-actions", admin_css)
        self.assertIn(".col-admin-protect", admin_css)
        self.assertIn("table-layout: auto", admin_css)
        self.assertIn("padding: 10px 14px", admin_css)
        self.assertIn("padding: 5px 10px", admin_css)


if __name__ == "__main__":
    unittest.main()
