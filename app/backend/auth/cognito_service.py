"""Amazon Cognito Authentication Service for MuleTrace AI.

Implements backend-mediated authentication using AWS Cognito User Pools,
resolves Cognito groups to MuleTrace roles, and manages secure server-side sessions.
"""
from __future__ import annotations

import base64
import json
from typing import Any

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]

from .config import CognitoConfig
from .session_store import SessionStore, get_session_store
from .audit_repository import AuditRepository, default_memory_audit_repo
from ..services.auth_service import (
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)


class ChallengeRequiredError(AuthenticationError):
    """Raised when Cognito requires a password reset or MFA challenge."""

    def __init__(self, challenge_name: str, session: str, parameters: dict[str, Any] | None = None) -> None:
        super().__init__(f"Cognito challenge required: {challenge_name}")
        self.challenge_name = challenge_name
        self.session = session
        self.parameters = parameters or {}


def decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """Safely decode JWT claims without signature verification.

    Cognito tokens received directly from the TLS-secured initiate_auth response
    are authentic from the identity provider.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1]
        # Pad base64 string
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


class CognitoAuthService:
    """Backend-mediated Cognito Authentication provider."""

    def __init__(
        self,
        config: CognitoConfig | None = None,
        cognito_client: Any = None,
        session_store: SessionStore | None = None,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self.config = config or CognitoConfig.from_environment()
        self._cognito_client = cognito_client
        self.session_store = session_store or get_session_store()
        self.audit_repo = audit_repo or default_memory_audit_repo

    def _get_client(self) -> Any:
        if self._cognito_client is not None:
            return self._cognito_client
        if boto3 is None:
            raise ServiceUnavailableError("boto3 library is not available in the current environment")
        try:
            self._cognito_client = boto3.client("cognito-idp", region_name=self.config.region)
            return self._cognito_client
        except Exception as exc:
            raise ServiceUnavailableError(f"Failed to initialize Cognito client: {exc}")

    def login(
        self,
        email: str,
        password: str,
        client_ip: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Authenticate user against Amazon Cognito using USER_PASSWORD_AUTH flow."""
        normalized_email = (email or "").strip().lower()
        if not normalized_email or not password:
            raise AuthenticationError("Email and password are required")

        client = self._get_client()

        try:
            response = client.initiate_auth(
                ClientId=self.config.app_client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": normalized_email,
                    "PASSWORD": password,
                },
            )
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            msg = err.response.get("Error", {}).get("Message", "")

            if code == "NotAuthorizedException":
                if "disabled" in msg.lower():
                    raise AuthenticationError("Account has been disabled")
                raise AuthenticationError("Invalid email or password")
            elif code == "UserNotFoundException":
                raise AuthenticationError("Invalid email or password")
            elif code == "TooManyRequestsException":
                raise RateLimitError("Too many authentication attempts. Please try again later.")
            elif code == "ResourceNotFoundException":
                raise ServiceUnavailableError("Cognito User Pool or App Client not found")
            else:
                raise ServiceUnavailableError(f"Cognito authentication error: {msg}")
        except BotoCoreError as err:
            raise ServiceUnavailableError(f"Cognito service communication error: {err}")
        except Exception as err:
            raise ServiceUnavailableError(f"Cognito authentication unavailable: {err}")

        # Check for authentication challenge
        challenge = response.get("ChallengeName")
        if challenge:
            session = response.get("Session", "")
            params = response.get("ChallengeParameters", {})
            if challenge == "NEW_PASSWORD_REQUIRED":
                raise ChallengeRequiredError(challenge, session, params)
            raise AuthenticationError(f"Unsupported Cognito challenge: {challenge}")

        result = response.get("AuthenticationResult")
        if not result:
            raise AuthenticationError("Cognito returned no authentication result")

        id_token = result.get("IdToken", "")
        access_token = result.get("AccessToken", "")
        refresh_token = result.get("RefreshToken", "")
        expires_in = int(result.get("ExpiresIn", 3600))

        claims = decode_jwt_payload_unverified(id_token)
        user_id = claims.get("sub") or claims.get("cognito:username") or normalized_email
        groups = claims.get("cognito:groups", [])
        display_name = claims.get("name") or claims.get("nickname") or normalized_email.split("@")[0]

        # Resolve role from Cognito Groups
        if self.config.group_admin in groups:
            role = "admin"
        elif self.config.group_officer in groups:
            role = "user"
        else:
            raise AuthenticationError(
                "Access denied: User does not belong to authorized MuleTrace Cognito groups"
            )

        user_info = {
            "id": str(user_id),
            "user_id": str(user_id),
            "email": normalized_email,
            "display_name": str(display_name),
            "role": role,
            "groups": groups,
        }

        tokens = {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

        # Issue secure server-side session
        raw_session_token = self.session_store.create_session(
            user_info=user_info,
            tokens=tokens,
            ttl_seconds=expires_in,
        )

        # Record security audit log
        self.audit_repo.record(
            actor_user_id=user_id,
            action="login_success",
            ip_address=client_ip,
            safe_metadata={"auth_provider": "cognito", "role": role},
        )

        return raw_session_token, user_info

    def validate_session(self, raw_token: str) -> dict[str, Any] | None:
        """Alias for verify_session used by MuleTraceRequestHandler."""
        return self.verify_session(raw_token)

    def verify_session(self, raw_token: str) -> dict[str, Any] | None:
        """Verify session token against the session store."""
        if not raw_token:
            return None
        session = self.session_store.get_session(raw_token)
        if not session:
            return None
        uid = session.get("user_id") or session.get("id")
        return {
            "id": uid,
            "user_id": uid,
            "email": session.get("email"),
            "display_name": session.get("display_name"),
            "role": session.get("role"),
            "groups": session.get("groups", []),
        }

    def logout(self, raw_token: str, client_ip: str | None = None) -> bool:
        """Revoke user session."""
        if not raw_token:
            return False
        session = self.session_store.get_session(raw_token)
        actor_id = session.get("user_id") if session else None
        revoked = self.session_store.revoke_session(raw_token)
        if revoked and actor_id:
            self.audit_repo.record(
                actor_user_id=actor_id,
                action="logout",
                ip_address=client_ip,
                safe_metadata={"auth_provider": "cognito"},
            )
        return revoked

    def complete_new_password_challenge(
        self,
        email: str,
        new_password: str,
        session_string: str,
        client_ip: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Respond to NEW_PASSWORD_REQUIRED challenge during first-time login."""
        normalized_email = (email or "").strip().lower()
        client = self._get_client()

        try:
            response = client.respond_to_auth_challenge(
                ClientId=self.config.app_client_id,
                ChallengeName="NEW_PASSWORD_REQUIRED",
                Session=session_string,
                ChallengeResponses={
                    "USERNAME": normalized_email,
                    "NEW_PASSWORD": new_password,
                },
            )
        except ClientError as err:
            msg = err.response.get("Error", {}).get("Message", str(err))
            raise AuthenticationError(f"Password challenge failed: {msg}")
        except Exception as err:
            raise ServiceUnavailableError(f"Password challenge service error: {err}")

        result = response.get("AuthenticationResult")
        if not result:
            raise AuthenticationError("Cognito did not return tokens after password challenge")

        id_token = result.get("IdToken", "")
        expires_in = int(result.get("ExpiresIn", 3600))
        claims = decode_jwt_payload_unverified(id_token)
        user_id = claims.get("sub") or normalized_email
        groups = claims.get("cognito:groups", [])
        display_name = claims.get("name") or normalized_email.split("@")[0]

        role = "admin" if self.config.group_admin in groups else "user"
        user_info = {
            "id": str(user_id),
            "user_id": str(user_id),
            "email": normalized_email,
            "display_name": str(display_name),
            "role": role,
            "groups": groups,
        }

        raw_session_token = self.session_store.create_session(
            user_info=user_info,
            tokens=result,
            ttl_seconds=expires_in,
        )

        self.audit_repo.record(
            actor_user_id=user_id,
            action="first_login_password_set",
            ip_address=client_ip,
            safe_metadata={"auth_provider": "cognito"},
        )

        return raw_session_token, user_info
