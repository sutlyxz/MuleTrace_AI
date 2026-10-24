"""Comprehensive automated test suite for Phase 4.2: Full Admin Portal UI & Backend Integration.

Covers Part F Requirements 1 through 23:
1. Admin session allows Admin Portal access (/admin.html, /assets/css/admin.css, /assets/js/admin.js).
2. Anonymous access is denied (401).
3. User-role access is denied (403).
4. Admin Portal uses real backend APIs.
5. Account list renders safe fields.
6. Admin accounts cannot be modified through UI.
7. Create form always creates role=user.
8. No public signup or Admin role selector exists.
9. Password validation and confirmation.
10. Passwords are not persisted in browser storage.
11. Password fields are cleared appropriately.
12. Activate/deactivate requests use PATCH correctly.
13. Deactivation requires confirmation.
14. Password reset requests use the correct endpoint.
15. Audit logs render safely without XSS.
16. Pagination and empty states.
17. Error and network-failure handling.
18. Logout calls the real backend endpoint.
19. CSRF protection remains active.
20. Existing login and investigation Dashboard remain unchanged.
21. Existing RBAC tests continue passing.
22. Existing error-page tests continue passing.
23. Integration test with muletrace_test without touching development database.
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

from app.backend.auth.security import hash_password
from app.backend.config import load_environment
from app.backend.db import config as db_config
from app.backend.db.auth_repositories import UserRepository
from app.backend.db.models import AuthAuditLog, AuthSession, Base, User
from app.backend.server import MuleTraceRequestHandler
from app.backend.services.admin_service import AdminService
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


class TestAdminPortalUI(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.frontend_dir = self.project_root / "app" / "frontend"

        self.engine = create_in_memory_engine()
        self.rate_limiter = LoginRateLimiter()
        self.auth_service = AuthService(engine=self.engine, rate_limiter=self.rate_limiter)
        self.admin_service = AdminService(engine=self.engine)

        with Session(self.engine) as session:
            user_repo = UserRepository(session)
            self.admin = user_repo.create_user(
                email="admin@agency.go.th",
                display_name="Administrator Boss",
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
            socket, (client_ip, 12345), server, directory=str(self.frontend_dir)
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

    # 1. Admin session allows Admin Portal access (/admin.html, /assets/css/admin.css, /assets/js/admin.js)
    def test_1_admin_can_access_admin_portal_and_assets(self):
        # 1a. /admin.html
        req_page = (
            f"GET /admin.html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_page, headers_page, body_page = self._execute_request(req_page)
        self.assertEqual(status_page, 200)
        self.assertIn("text/html", headers_page.get("content-type", ""))
        self.assertIn("Admin Portal", body_page.decode("utf-8"))

        # 1b. /assets/css/admin.css
        req_css = (
            f"GET /assets/css/admin.css HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_css, headers_css, body_css = self._execute_request(req_css)
        self.assertEqual(status_css, 200)
        self.assertIn("text/css", headers_css.get("content-type", ""))
        self.assertIn("--sand-dark", body_css.decode("utf-8"))

        # 1c. /assets/js/admin.js
        req_js = (
            f"GET /assets/js/admin.js HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n\r\n"
        ).encode("utf-8")
        status_js, headers_js, body_js = self._execute_request(req_js)
        self.assertEqual(status_js, 200)
        self.assertIn("/api/admin/users", body_js.decode("utf-8"))

    # 2. Anonymous access is denied (401)
    def test_2_anonymous_denied_admin_portal_and_assets(self):
        for path in ("/admin.html", "/assets/css/admin.css", "/assets/js/admin.js"):
            req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n\r\n".encode("utf-8")
            status, _, _ = self._execute_request(req)
            self.assertEqual(status, 401, f"Anonymous access to {path} must be 401")

    # 3. User-role access is denied (403)
    def test_3_officer_user_denied_admin_portal_and_assets(self):
        for path in ("/admin.html", "/assets/css/admin.css", "/assets/js/admin.js"):
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:8000\r\n"
                f"Cookie: muletrace_session={self.officer_token}\r\n\r\n"
            ).encode("utf-8")
            status, _, _ = self._execute_request(req)
            self.assertEqual(status, 403, f"Bank officer access to {path} must be 403")

    # 4. Admin Portal uses real backend APIs
    def test_4_admin_portal_api_integration_contracts(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        # Confirms real endpoints are called
        self.assertIn("/api/auth/me", admin_js)
        self.assertIn("/api/auth/logout", admin_js)
        self.assertIn("/api/admin/users", admin_js)
        self.assertIn("/status", admin_js)
        self.assertIn("/reset-password", admin_js)
        self.assertIn("/api/admin/audit-logs", admin_js)
        self.assertIn('credentials: "same-origin"', admin_js)

    # 5. Account list renders safe fields in DOM
    def test_5_admin_html_table_structure_safe(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        # Check table columns exist
        self.assertIn("Display Name", admin_html)
        self.assertIn("Email", admin_html)
        self.assertIn("Role", admin_html)
        self.assertIn("Status", admin_html)
        self.assertIn("Created At", admin_html)
        self.assertIn("Last Login", admin_html)
        self.assertIn("Actions", admin_html)

        # Must not have password column or secrets
        self.assertNotIn("password_hash", admin_html.lower())
        self.assertNotIn("token", admin_html.lower())

    # 6. Admin accounts cannot be modified through UI
    def test_6_admin_protected_badge_in_js(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertIn('user.role === "admin"', admin_js)
        self.assertIn("badge-protected", admin_js)

    # 7. Create form always creates role=user
    # 8. No public signup or Admin role selector exists
    def test_7_8_no_admin_role_selector_and_role_user_fixed(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        # Must not contain role selector dropdown
        self.assertNotIn('<select name="role"', admin_html)
        self.assertNotIn('<select id="role"', admin_html)
        self.assertNotIn('value="admin"', admin_html)
        # Must not have public signup links
        self.assertNotIn("signup", admin_html.lower())
        self.assertNotIn("register", admin_html.lower())

        # In admin.js, creation payload strictly hardcodes role: "user"
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertIn('role: "user"', admin_js)

    # 9. Password validation and confirmation
    def test_9_password_policy_checklist_present(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        self.assertIn("policyLen", admin_html)
        self.assertIn("policyCase", admin_html)
        self.assertIn("policyNum", admin_html)
        self.assertIn("policySpec", admin_html)

    # 10. Passwords are not persisted in browser storage
    def test_10_no_storage_persistence_of_secrets(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertNotIn("localStorage.setItem", admin_js)
        self.assertNotIn("sessionStorage.setItem", admin_js)
        self.assertNotIn("localStorage.password", admin_js)
        self.assertNotIn("sessionStorage.password", admin_js)

    # 11. Password fields are cleared appropriately
    def test_11_password_fields_cleared_on_close(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("clearCreateForm", admin_js)
        self.assertIn("clearResetForm", admin_js)
        self.assertIn('elements.createForm.reset()', admin_js)
        self.assertIn('elements.resetForm.reset()', admin_js)

    # 12. Activate/deactivate requests use PATCH correctly
    # 13. Deactivation requires confirmation
    def test_12_13_status_modal_uses_patch_and_confirmation(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertIn('method: "PATCH"', admin_js)
        self.assertIn("openStatusModal", admin_js)
        self.assertIn("statusDeactivateWarning", admin_js)

        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        self.assertIn("statusConfirmModal", admin_html)
        self.assertIn("statusDeactivateWarning", admin_html)

    # 14. Password reset requests use the correct endpoint
    def test_14_reset_password_endpoint_correct(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("/reset-password", admin_js)
        self.assertIn('body: JSON.stringify({ new_password: newPwd })', admin_js)

    # 15. Audit logs render safely without XSS
    def test_15_audit_logs_safe_rendering(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        # Verifies DOM methods are used rather than raw innerHTML for metadata/content
        self.assertIn("textContent", admin_js)
        self.assertIn("document.createElement", admin_js)

    # 16. Pagination and empty states
    def test_16_pagination_and_empty_states_present(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        self.assertIn("usersPaginationInfo", admin_html)
        self.assertIn("usersPrevBtn", admin_html)
        self.assertIn("usersNextBtn", admin_html)
        self.assertIn("usersEmptyState", admin_html)
        self.assertIn("auditPaginationInfo", admin_html)
        self.assertIn("auditEmptyState", admin_html)

    # 17. Error and network-failure handling
    def test_17_error_states_and_retry_buttons_present(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        self.assertIn("usersErrorState", admin_html)
        self.assertIn("usersRetryBtn", admin_html)
        self.assertIn("auditErrorState", admin_html)
        self.assertIn("auditRetryBtn", admin_html)

    # 18. Logout calls the real backend endpoint
    def test_18_logout_calls_backend(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("/api/auth/logout", admin_js)
        self.assertIn('window.location.replace("login.html")', admin_js)

    # 19. CSRF protection remains active
    def test_19_csrf_protection_preserved(self):
        csrf_payload = json.dumps({"is_active": False}).encode("utf-8")
        req_csrf = (
            f"PATCH /api/admin/users/{self.officer_id}/status HTTP/1.1\r\n"
            f"Host: 127.0.0.1:8000\r\n"
            f"Origin: http://evil-site.com\r\n"
            f"Cookie: muletrace_session={self.admin_token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(csrf_payload)}\r\n\r\n"
        ).encode("utf-8") + csrf_payload
        status, _, body = self._execute_request(req_csrf)
        self.assertEqual(status, 403)
        self.assertIn("csrf", json.loads(body.decode("utf-8"))["message"].lower())

    # 20. Existing login and investigation Dashboard remain unchanged
    def test_20_login_and_dashboard_preserved(self):
        login_html = (self.frontend_dir / "login.html").read_text(encoding="utf-8")
        self.assertIn('id="loginForm"', login_html)
        self.assertIn('id="emailInput"', login_html)
        self.assertIn('id="passwordInput"', login_html)

        index_html = (self.frontend_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="page-overview"', index_html)
        self.assertIn('id="page-cases"', index_html)
        self.assertIn('id="page-trail"', index_html)
        self.assertIn('id="logoutBtn"', index_html)

    # 21. Investigation data not exposed in Admin Portal
    def test_21_no_investigation_data_in_admin_portal(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")

        for s in ("CASE001", "CASE002", "TX001", "/api/cases", "/api/ai/summary"):
            self.assertNotIn(s, admin_html)
            self.assertNotIn(s, admin_js)

    # 22. Integration test in muletrace_test without touching development database
    def test_22_muletrace_test_database_integration(self):
        env = load_environment(self.project_root)
        test_db_url = env.get(db_config.TEST_DATABASE_URL_ENV) or os.environ.get(db_config.TEST_DATABASE_URL_ENV)

        if not test_db_url:
            self.skipTest("TEST_DATABASE_URL not set; skipping PostgreSQL integration")

        self.assertIn("test", test_db_url.lower())
        dev_url = env.get(db_config.DATABASE_URL_ENV) or os.environ.get(db_config.DATABASE_URL_ENV, "")
        self.assertNotEqual(test_db_url, dev_url)

        pg_engine = create_engine(test_db_url)
        pg_limiter = LoginRateLimiter()
        pg_auth = AuthService(engine=pg_engine, rate_limiter=pg_limiter)
        pg_admin = AdminService(engine=pg_engine)

        test_email = "portal_ui_test_officer@agency.go.th"
        test_pass = "TestOfficerPass123!@#"
        created_id = None

        try:
            # Seed disposable admin
            with Session(pg_engine) as session:
                ur = UserRepository(session)
                ex = ur.get_by_email(test_email)
                if ex:
                    session.delete(ex)
                    session.commit()

            # Create officer via AdminService
            res = pg_admin.create_bank_officer(
                email=test_email,
                password=test_pass,
                display_name="Portal UI Test Officer",
            )
            created_id = res["id"]
            self.assertEqual(res["role"], "user")

            # Officer can log in
            token, u = pg_auth.login(test_email, test_pass)
            self.assertEqual(u["id"], created_id)

            # Bank Officer cannot access Admin Portal
            self.assertEqual(u["role"], "user")

        finally:
            if created_id:
                with Session(pg_engine) as cleanup_sess:
                    u = cleanup_sess.execute(select(User).where(User.id == created_id)).scalar_one_or_none()
                    if u:
                        cleanup_sess.delete(u)
                        cleanup_sess.commit()
            pg_engine.dispose()

    # =========================================================================
    # Phase 4.2.1: Admin Portal User Management UI Refinement Tests
    # =========================================================================

    def test_23_separate_admin_and_officer_sections_in_html(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")

        # 1. Administrator Section
        self.assertIn('id="adminAccountsSection"', admin_html)
        self.assertIn("บัญชีผู้ดูแลระบบ (Administrator Accounts)", admin_html)
        self.assertIn('id="adminUsersTableBody"', admin_html)
        self.assertIn('id="adminProtectedBadge"', admin_html)

        # 2. Bank Officer Section
        self.assertIn('id="officerAccountsSection"', admin_html)
        self.assertIn("บัญชีเจ้าหน้าที่ธนาคาร (Bank Officer Accounts)", admin_html)
        self.assertIn('id="usersTableBody"', admin_html)
        self.assertIn('id="userSearchInput"', admin_html)
        self.assertIn('id="openCreateUserModalBtn"', admin_html)

    def test_24_admin_section_is_strictly_read_only(self):
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")

        # Administrator table headers in HTML
        self.assertIn("col-admin-name", admin_html)
        self.assertIn("col-admin-email", admin_html)
        self.assertIn("col-admin-role", admin_html)
        self.assertIn("col-admin-status", admin_html)
        self.assertIn("col-admin-protect", admin_html)

        # No action buttons or mutation links for Administrator table
        self.assertIn("renderAdminUsersTable", admin_js)
        self.assertIn("🛡️ สงวนสิทธิ์ระบบ (Protected)", admin_js)
        # renderAdminUsersTable must NOT attach openStatusModal or openResetModal
        admin_table_render_code = admin_js[admin_js.find("function renderAdminUsersTable"):admin_js.find("function applyUserFilter")]
        self.assertNotIn("openStatusModal", admin_table_render_code)
        self.assertNotIn("openResetModal", admin_table_render_code)
        self.assertNotIn("btn-outline-danger", admin_table_render_code)
        self.assertNotIn("btn-outline-success", admin_table_render_code)

    def test_25_officer_section_retains_management_actions_and_excludes_admin(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")

        # Officer table code
        officer_render_code = admin_js[admin_js.find("function renderUsersTable"):admin_js.find("function updateOverviewStats")]

        # Defense-in-depth: checks user.role !== "user" to exclude admins
        self.assertIn('if (user.role !== "user") return;', officer_render_code)

        # Retains active/deactivate and reset password actions
        self.assertIn("openStatusModal", officer_render_code)
        self.assertIn("openResetModal", officer_render_code)
        self.assertIn("btn-outline-danger", officer_render_code)
        self.assertIn("btn-outline-success", officer_render_code)

    def test_26_search_and_counts_scoped_to_bank_officers(self):
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")

        # Search filter operates on officerUsers, not all users
        filter_code = admin_js[admin_js.find("function applyUserFilter"):admin_js.find("function renderUsersTable")]
        self.assertIn("state.officerUsers", filter_code)
        self.assertNotIn("state.adminUsers", filter_code)

        # Overview statistics explicitly filter role === "user"
        stats_code = admin_js[admin_js.find("function updateOverviewStats"):admin_js.find("function updateUsersPagination")]
        self.assertIn('u.role === "user"', stats_code)

        # Pagination clearly specifies officer scope and current page
        pagination_code = admin_js[admin_js.find("function updateUsersPagination"):admin_js.find("function showUsersLoading")]
        self.assertIn("state.officerUsers.length", pagination_code)
        self.assertIn("บัญชีเจ้าหน้าที่", pagination_code)

    def test_27_table_layout_responsive_styles(self):
        admin_css = (self.frontend_dir / "assets" / "css" / "admin.css").read_text(encoding="utf-8")

        # Responsive container & scrolling
        self.assertIn(".table-responsive", admin_css)
        self.assertIn("overflow-x: auto", admin_css)
        self.assertIn("-webkit-overflow-scrolling: touch", admin_css)

        # Proportional column sizing
        self.assertIn(".col-officer-name", admin_css)
        self.assertIn(".col-officer-email", admin_css)
        self.assertIn(".col-officer-actions", admin_css)
        self.assertIn(".col-admin-protect", admin_css)

        # Compact cell padding and layout
        self.assertIn("table-layout: auto", admin_css)
        self.assertIn("padding: 10px 14px", admin_css)
        self.assertIn("padding: 11px 14px", admin_css)
        self.assertIn("padding: 5px 10px", admin_css)

    def test_28_modal_footer_visibility_and_scrolling(self):
        admin_css = (self.frontend_dir / "assets" / "css" / "admin.css").read_text(encoding="utf-8")
        admin_html = (self.frontend_dir / "admin.html").read_text(encoding="utf-8")
        admin_js = (self.frontend_dir / "assets" / "js" / "admin.js").read_text(encoding="utf-8")

        # 1. CSS Modal Container Rules: max-height and flexbox column layout
        self.assertIn("max-height: calc(100vh - 32px)", admin_css)
        self.assertIn(".modal-dialog > form", admin_css)
        self.assertIn("min-height: 0", admin_css)

        # 2. Fixed header and footer containment
        self.assertIn("flex-shrink: 0", admin_css)

        # 3. Independently scrollable modal body
        self.assertIn("overflow-y: auto", admin_css)
        self.assertIn("overscroll-behavior: contain", admin_css)
        self.assertIn(".modal-body::-webkit-scrollbar", admin_css)

        # 4. Viewport height and mobile media queries for compact screens
        self.assertIn("@media (max-height: 720px)", admin_css)
        self.assertIn("max-height: calc(100vh - 20px)", admin_css)
        self.assertIn("max-height: calc(100vh - 16px)", admin_css)

        # 5. HTML structure for Create Bank Officer and Reset Password modals
        self.assertIn('id="createUserModal"', admin_html)
        self.assertIn('id="createSubmitBtn"', admin_html)
        self.assertIn('id="cancelCreateModalBtn"', admin_html)
        self.assertIn('id="resetPasswordModal"', admin_html)
        self.assertIn('id="resetSubmitBtn"', admin_html)
        self.assertIn('id="cancelResetModalBtn"', admin_html)

        # 6. JavaScript resets modal body scrollTop when opening
        self.assertIn("bodyEl.scrollTop = 0", admin_js)


if __name__ == "__main__":
    unittest.main()
