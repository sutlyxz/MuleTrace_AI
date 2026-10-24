"""Unit tests for Amazon Cognito Authentication Service and Session Lifecycle."""
from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from app.backend.auth.config import CognitoConfig
from app.backend.auth.cognito_service import (
    CognitoAuthService,
    ChallengeRequiredError,
    decode_jwt_payload_unverified,
)
from app.backend.auth.session_store import InMemorySessionStore
from app.backend.auth.audit_repository import InMemoryAuditRepository
from app.backend.services.auth_service import (
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)


def _make_dummy_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(b"dummysig").decode().rstrip("=")
    return f"{header}.{payload}.{sig}"


class TestCognitoAuthService(unittest.TestCase):
    def setUp(self):
        self.config = CognitoConfig(
            region="us-east-1",
            user_pool_id="us-east-1_dummyPool",
            app_client_id="dummyAppClient123",
            group_admin="Admin",
            group_officer="BankOfficer",
        )
        self.mock_client = MagicMock()
        self.session_store = InMemorySessionStore()
        self.audit_repo = InMemoryAuditRepository()
        self.auth_service = CognitoAuthService(
            config=self.config,
            cognito_client=self.mock_client,
            session_store=self.session_store,
            audit_repo=self.audit_repo,
        )

    def test_decode_jwt_payload_unverified(self):
        claims = {"sub": "user-123", "email": "test@example.com", "cognito:groups": ["BankOfficer"]}
        token = _make_dummy_jwt(claims)
        decoded = decode_jwt_payload_unverified(token)
        self.assertEqual(decoded.get("sub"), "user-123")
        self.assertEqual(decoded.get("email"), "test@example.com")
        self.assertIn("BankOfficer", decoded.get("cognito:groups", []))

    def test_login_success_bank_officer(self):
        id_token = _make_dummy_jwt({
            "sub": "officer-uuid-456",
            "email": "officer@agency.go.th",
            "name": "Nattawut K.",
            "cognito:groups": ["BankOfficer"],
        })
        self.mock_client.initiate_auth.return_value = {
            "AuthenticationResult": {
                "IdToken": id_token,
                "AccessToken": "dummy_access_token",
                "RefreshToken": "dummy_refresh_token",
                "ExpiresIn": 3600,
            }
        }

        raw_token, user_info = self.auth_service.login(
            email="officer@agency.go.th",
            password="StrongPassword!123",
            client_ip="192.168.1.50",
        )

        self.assertTrue(len(raw_token) > 20)
        self.assertEqual(user_info["role"], "user")
        self.assertEqual(user_info["email"], "officer@agency.go.th")
        self.assertEqual(user_info["display_name"], "Nattawut K.")

        # Verify session verification works with issued token
        verified = self.auth_service.verify_session(raw_token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["role"], "user")
        self.assertEqual(verified["email"], "officer@agency.go.th")

        # Verify audit log recorded
        logs, total = self.audit_repo.list_logs()
        self.assertEqual(total, 1)
        self.assertEqual(logs[0]["action"], "login_success")
        self.assertEqual(logs[0]["actor_user_id"], "officer-uuid-456")

    def test_login_success_admin(self):
        id_token = _make_dummy_jwt({
            "sub": "admin-uuid-999",
            "email": "admin@agency.go.th",
            "name": "System Administrator",
            "cognito:groups": ["Admin"],
        })
        self.mock_client.initiate_auth.return_value = {
            "AuthenticationResult": {
                "IdToken": id_token,
                "AccessToken": "dummy_access_token",
                "ExpiresIn": 3600,
            }
        }

        raw_token, user_info = self.auth_service.login("admin@agency.go.th", "AdminPass123!")
        self.assertEqual(user_info["role"], "admin")

    def test_login_unauthorized_group(self):
        id_token = _make_dummy_jwt({
            "sub": "random-user",
            "email": "random@example.com",
            "cognito:groups": ["Guests"],
        })
        self.mock_client.initiate_auth.return_value = {
            "AuthenticationResult": {"IdToken": id_token, "ExpiresIn": 3600}
        }

        with self.assertRaises(AuthenticationError) as ctx:
            self.auth_service.login("random@example.com", "Password123!")
        self.assertIn("Access denied", str(ctx.exception))

    def test_login_invalid_credentials_rejected(self):
        err_response = {"Error": {"Code": "NotAuthorizedException", "Message": "Incorrect username or password."}}
        self.mock_client.initiate_auth.side_effect = ClientError(err_response, "InitiateAuth")

        with self.assertRaises(AuthenticationError) as ctx:
            self.auth_service.login("officer@agency.go.th", "WrongPassword")
        self.assertEqual(str(ctx.exception), "Invalid email or password")

    def test_login_disabled_user_rejected(self):
        err_response = {"Error": {"Code": "NotAuthorizedException", "Message": "User is disabled."}}
        self.mock_client.initiate_auth.side_effect = ClientError(err_response, "InitiateAuth")

        with self.assertRaises(AuthenticationError) as ctx:
            self.auth_service.login("disabled@agency.go.th", "AnyPassword")
        self.assertEqual(str(ctx.exception), "Account has been disabled")

    def test_login_rate_limiting(self):
        err_response = {"Error": {"Code": "TooManyRequestsException", "Message": "Too many requests"}}
        self.mock_client.initiate_auth.side_effect = ClientError(err_response, "InitiateAuth")

        with self.assertRaises(RateLimitError):
            self.auth_service.login("officer@agency.go.th", "Password")

    def test_login_new_password_required_challenge(self):
        self.mock_client.initiate_auth.return_value = {
            "ChallengeName": "NEW_PASSWORD_REQUIRED",
            "Session": "session-string-12345",
            "ChallengeParameters": {"requiredAttributes": "[]"},
        }

        with self.assertRaises(ChallengeRequiredError) as ctx:
            self.auth_service.login("newuser@agency.go.th", "TempPassword123!")
        self.assertEqual(ctx.exception.challenge_name, "NEW_PASSWORD_REQUIRED")
        self.assertEqual(ctx.exception.session, "session-string-12345")

    def test_complete_new_password_challenge(self):
        id_token = _make_dummy_jwt({
            "sub": "user-uuid-1",
            "email": "newuser@agency.go.th",
            "cognito:groups": ["BankOfficer"],
        })
        self.mock_client.respond_to_auth_challenge.return_value = {
            "AuthenticationResult": {
                "IdToken": id_token,
                "AccessToken": "token",
                "ExpiresIn": 3600,
            }
        }

        raw_token, user_info = self.auth_service.complete_new_password_challenge(
            email="newuser@agency.go.th",
            new_password="NewPermanentPassword123!",
            session_string="session-string-12345",
        )
        self.assertEqual(user_info["role"], "user")
        self.assertIsNotNone(self.auth_service.verify_session(raw_token))

    def test_logout_revokes_session(self):
        id_token = _make_dummy_jwt({"sub": "u1", "email": "u1@test.com", "cognito:groups": ["Admin"]})
        self.mock_client.initiate_auth.return_value = {
            "AuthenticationResult": {"IdToken": id_token, "ExpiresIn": 3600}
        }
        raw_token, _ = self.auth_service.login("u1@test.com", "Pass123!")

        self.assertIsNotNone(self.auth_service.verify_session(raw_token))
        # Logout
        revoked = self.auth_service.logout(raw_token)
        self.assertTrue(revoked)
        # Session is now invalid
        self.assertIsNone(self.auth_service.verify_session(raw_token))

    def test_missing_config_fails_closed(self):
        with self.assertRaises(ValueError):
            CognitoConfig(region="", user_pool_id="pool", app_client_id="client")
        with self.assertRaises(ValueError):
            CognitoConfig(region="us-east-1", user_pool_id="", app_client_id="client")
        with self.assertRaises(ValueError):
            CognitoConfig(region="us-east-1", user_pool_id="pool", app_client_id="")

    def test_service_outage_fails_closed_no_fallback(self):
        self.mock_client.initiate_auth.side_effect = Exception("Cognito Service Down")
        with self.assertRaises(ServiceUnavailableError):
            self.auth_service.login("officer@agency.go.th", "Pass")


if __name__ == "__main__":
    unittest.main()
