"""Unit tests for Cognito Admin Service and User Management Operations."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock
from botocore.exceptions import ClientError

from app.backend.auth.config import CognitoConfig
from app.backend.auth.session_store import InMemorySessionStore
from app.backend.auth.audit_repository import InMemoryAuditRepository
from app.backend.services.cognito_admin_service import CognitoAdminService
from app.backend.services.admin_service import (
    ValidationError,
    ConflictError,
    NotFoundError,
    ForbiddenError,
)


class TestCognitoAdminService(unittest.TestCase):
    def setUp(self):
        self.config = CognitoConfig(
            region="us-east-1",
            user_pool_id="us-east-1_dummyPool",
            app_client_id="dummyAppClient",
            group_admin="Admin",
            group_officer="BankOfficer",
        )
        self.mock_client = MagicMock()
        self.audit_repo = InMemoryAuditRepository()
        self.session_store = InMemorySessionStore()

        self.admin_service = CognitoAdminService(
            config=self.config,
            cognito_client=self.mock_client,
            audit_repo=self.audit_repo,
            session_store=self.session_store,
        )

    def test_list_users_with_group_mapping(self):
        now = datetime.now(timezone.utc)
        self.mock_client.list_users.return_value = {
            "Users": [
                {
                    "Username": "admin@agency.go.th",
                    "Enabled": True,
                    "UserCreateDate": now,
                    "UserLastModifiedDate": now,
                    "Attributes": [
                        {"Name": "email", "Value": "admin@agency.go.th"},
                        {"Name": "name", "Value": "Head Admin"},
                    ],
                },
                {
                    "Username": "officer@agency.go.th",
                    "Enabled": False,
                    "UserCreateDate": now,
                    "UserLastModifiedDate": now,
                    "Attributes": [
                        {"Name": "email", "Value": "officer@agency.go.th"},
                        {"Name": "name", "Value": "Officer Nattawut"},
                    ],
                },
            ],
            "PaginationToken": "next-token-abc",
        }

        # Mock group lookups
        def mock_groups(UserPoolId, Username):
            if "admin" in Username:
                return {"Groups": [{"GroupName": "Admin"}]}
            return {"Groups": [{"GroupName": "BankOfficer"}]}

        self.mock_client.admin_list_groups_for_user.side_effect = mock_groups

        result = self.admin_service.list_users(limit=25)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["pagination_token"], "next-token-abc")

        users = result["users"]
        self.assertEqual(users[0]["role"], "admin")
        self.assertTrue(users[0]["is_active"])
        self.assertEqual(users[1]["role"], "user")
        self.assertFalse(users[1]["is_active"])

    def test_create_bank_officer_success(self):
        self.mock_client.admin_create_user.return_value = {"User": {"Username": "new.officer@agency.go.th"}}
        self.mock_client.admin_add_user_to_group.return_value = {}

        created = self.admin_service.create_bank_officer(
            admin_user_id="admin-123",
            email="new.officer@agency.go.th",
            password="StrongPassword!123",
            display_name="Somchai Officer",
            client_ip="10.0.0.1",
        )

        self.assertEqual(created["email"], "new.officer@agency.go.th")
        self.assertEqual(created["display_name"], "Somchai Officer")
        self.assertEqual(created["role"], "user")
        self.assertTrue(created["is_active"])

        # Verify added to BankOfficer Cognito group
        self.mock_client.admin_add_user_to_group.assert_called_once_with(
            UserPoolId=self.config.user_pool_id,
            Username="new.officer@agency.go.th",
            GroupName=self.config.group_officer,
        )

        # Verify audit log
        logs, total = self.audit_repo.list_logs()
        self.assertEqual(total, 1)
        self.assertEqual(logs[0]["action"], "user_created")
        self.assertEqual(logs[0]["target_user_id"], "new.officer@agency.go.th")

    def test_create_bank_officer_duplicate_email_conflict(self):
        err = {"Error": {"Code": "UsernameExistsException", "Message": "An account with the given email already exists."}}
        self.mock_client.admin_create_user.side_effect = ClientError(err, "AdminCreateUser")

        with self.assertRaises(ConflictError):
            self.admin_service.create_bank_officer(
                admin_user_id="admin-123",
                email="existing@agency.go.th",
                password="StrongPassword!123",
                display_name="Existing User",
            )

    def test_create_bank_officer_weak_password_validation(self):
        with self.assertRaises(ValidationError):
            self.admin_service.create_bank_officer(
                admin_user_id="admin-123",
                email="valid@agency.go.th",
                password="weak",  # does not satisfy policy
                display_name="Valid Name",
            )

    def test_set_user_status_disable_and_enable(self):
        self.mock_client.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "BankOfficer"}]
        }
        self.mock_client.admin_disable_user.return_value = {}
        self.mock_client.admin_user_global_sign_out.return_value = {}
        self.mock_client.admin_enable_user.return_value = {}

        # 1. Disable user
        res_dis = self.admin_service.set_user_status(
            admin_user_id="admin-1",
            target_user_id="officer@agency.go.th",
            is_active=False,
        )
        self.assertFalse(res_dis["is_active"])
        self.mock_client.admin_disable_user.assert_called_once()
        self.mock_client.admin_user_global_sign_out.assert_called_once()

        # 2. Enable user
        res_en = self.admin_service.set_user_status(
            admin_user_id="admin-1",
            target_user_id="officer@agency.go.th",
            is_active=True,
        )
        self.assertTrue(res_en["is_active"])
        self.mock_client.admin_enable_user.assert_called_once()

    def test_set_user_status_cannot_disable_admin(self):
        self.mock_client.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "Admin"}]
        }

        with self.assertRaises(ForbiddenError):
            self.admin_service.set_user_status(
                admin_user_id="admin-1",
                target_user_id="other.admin@agency.go.th",
                is_active=False,
            )

    def test_reset_password_success(self):
        self.mock_client.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "BankOfficer"}]
        }
        self.mock_client.admin_set_user_password.return_value = {}
        self.mock_client.admin_user_global_sign_out.return_value = {}

        res = self.admin_service.reset_password(
            admin_user_id="admin-1",
            target_user_id="officer@agency.go.th",
            new_password="NewStrongPassword!456",
        )
        self.assertEqual(res["message"], "Password reset successfully")
        self.mock_client.admin_set_user_password.assert_called_once_with(
            UserPoolId=self.config.user_pool_id,
            Username="officer@agency.go.th",
            Password="NewStrongPassword!456",
            Permanent=True,
        )
        self.mock_client.admin_user_global_sign_out.assert_called_once()

    def test_reset_password_cannot_modify_admin(self):
        self.mock_client.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "Admin"}]
        }

        with self.assertRaises(ForbiddenError):
            self.admin_service.reset_password(
                admin_user_id="admin-1",
                target_user_id="admin.chief@agency.go.th",
                new_password="NewStrongPassword!456",
            )

    def test_list_audit_logs(self):
        self.audit_repo.record("admin-1", "user_created", "officer-1", {"role": "user"})
        self.audit_repo.record("admin-1", "user_deactivated", "officer-2")

        data = self.admin_service.list_audit_logs()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["audit_logs"][0]["action"], "user_deactivated")
        self.assertEqual(data["audit_logs"][1]["action"], "user_created")


if __name__ == "__main__":
    unittest.main()
