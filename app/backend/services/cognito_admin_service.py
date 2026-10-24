"""Amazon Cognito Admin Management Service.

Implements administrator account management operations backed by AWS Cognito:
- Listing Cognito users with group resolution
- Provisioning Bank Officer accounts into the BankOfficer Cognito group
- Enabling and disabling accounts with immediate global sign out
- Resetting passwords with password policy enforcement
- Querying application security audit logs
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]

from ..auth.config import CognitoConfig
from ..auth.audit_repository import AuditRepository, default_memory_audit_repo
from ..auth.session_store import SessionStore, get_session_store
from ..auth.security import (
    normalize_email,
    validate_email_format,
    validate_password_policy,
)
from .admin_service import (
    ValidationError,
    ConflictError,
    NotFoundError,
    ForbiddenError,
    ServiceUnavailableError,
)


class CognitoAdminService:
    """Administrator management operations backed by Amazon Cognito User Pool."""

    def __init__(
        self,
        config: CognitoConfig | None = None,
        cognito_client: Any = None,
        audit_repo: AuditRepository | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.config = config or CognitoConfig.from_environment()
        self._cognito_client = cognito_client
        self.audit_repo = audit_repo or default_memory_audit_repo
        self.session_store = session_store or get_session_store()

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

    def list_users(
        self,
        limit: int = 25,
        offset: int = 0,
        pagination_token: str | None = None,
    ) -> dict[str, Any]:
        """List Cognito users and map their group memberships."""
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "UserPoolId": self.config.user_pool_id,
            "Limit": min(limit, 60),
        }
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token

        try:
            res = client.list_users(**kwargs)
        except ClientError as err:
            msg = err.response.get("Error", {}).get("Message", str(err))
            raise ServiceUnavailableError(f"Cognito ListUsers error: {msg}")
        except Exception as err:
            raise ServiceUnavailableError(f"Failed to query Cognito users: {err}")

        raw_users = res.get("Users", [])
        next_token = res.get("PaginationToken")

        user_list: list[dict[str, Any]] = []
        for raw in raw_users:
            username = raw.get("Username", "")
            enabled = raw.get("Enabled", True)
            created = raw.get("UserCreateDate")
            updated = raw.get("UserLastModifiedDate")

            attrs: dict[str, str] = {}
            for item in raw.get("Attributes", []):
                attrs[item["Name"]] = item["Value"]

            email = attrs.get("email", username)
            dname = attrs.get("name") or attrs.get("nickname") or email.split("@")[0]

            # Resolve group for user
            role = "user"
            try:
                groups_res = client.admin_list_groups_for_user(
                    UserPoolId=self.config.user_pool_id,
                    Username=username,
                )
                group_names = [g.get("GroupName") for g in groups_res.get("Groups", [])]
                if self.config.group_admin in group_names:
                    role = "admin"
                elif self.config.group_officer in group_names:
                    role = "user"
            except Exception:
                # Fallback to user if group lookup fails
                pass

            user_list.append({
                "id": username,
                "email": email,
                "display_name": dname,
                "role": role,
                "is_active": bool(enabled),
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else str(updated or ""),
            })

        # Stable sort: Admins first, then by email
        user_list.sort(key=lambda u: (0 if u["role"] == "admin" else 1, u["email"]))

        return {
            "users": user_list,
            "total": len(user_list),
            "limit": limit,
            "offset": offset,
            "pagination_token": next_token,
        }

    def create_bank_officer(
        self,
        admin_user_id: str | None = None,
        email: str = "",
        password: str = "",
        display_name: str | None = None,
        client_ip: str | None = None,
        actor_id: str | None = None,
        admin_actor_id: str | None = None,
        client_supplied_role: str | None = None,
        role: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new Bank Officer user in Cognito and add to the BankOfficer group."""
        effective_admin_id = admin_user_id or admin_actor_id or actor_id or ""

        role_to_check = client_supplied_role or role or kwargs.get("role")
        if role_to_check and str(role_to_check).strip().lower() == "admin":
            raise ForbiddenError("Cannot create an administrator account through this endpoint.")

        if not email or not email.strip():
            raise ValidationError("Email is required.")

        normalized_email = normalize_email(email)
        if not validate_email_format(normalized_email):
            raise ValidationError("Invalid email address format.")

        if not password or not password.strip():
            raise ValidationError("Password is required.")

        is_valid, msg = validate_password_policy(password)
        if not is_valid:
            raise ValidationError(msg)

        dname = (display_name or "").strip() or normalized_email.split("@")[0]
        client = self._get_client()

        try:
            res = client.admin_create_user(
                UserPoolId=self.config.user_pool_id,
                Username=normalized_email,
                UserAttributes=[
                    {"Name": "email", "Value": normalized_email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": dname},
                ],
                TemporaryPassword=password,
                MessageAction="SUPPRESS",
            )
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            msg = err.response.get("Error", {}).get("Message", str(err))

            if code == "UsernameExistsException":
                raise ConflictError(f"Email '{normalized_email}' already exists in Cognito")
            elif code == "InvalidPasswordException":
                raise ValidationError(f"Password does not satisfy Cognito policy: {msg}")
            else:
                raise ServiceUnavailableError(f"Failed to create Cognito user: {msg}")
        except Exception as err:
            raise ServiceUnavailableError(f"Cognito service error: {err}")

        # Set permanent password so demo accounts don't get blocked with FORCE_CHANGE_PASSWORD
        try:
            client.admin_set_user_password(
                UserPoolId=self.config.user_pool_id,
                Username=normalized_email,
                Password=password,
                Permanent=True,
            )
        except Exception:
            # If permanent password cannot be set, user remains in FORCE_CHANGE_PASSWORD
            pass

        # Add user to BankOfficer group
        try:
            client.admin_add_user_to_group(
                UserPoolId=self.config.user_pool_id,
                Username=normalized_email,
                GroupName=self.config.group_officer,
            )
        except ClientError as err:
            msg = err.response.get("Error", {}).get("Message", str(err))
            raise ServiceUnavailableError(f"Failed to assign user to group: {msg}")

        user_record = {
            "id": normalized_email,
            "email": normalized_email,
            "display_name": dname,
            "role": "user",
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Audit log
        self.audit_repo.record(
            actor_user_id=effective_admin_id,
            action="user_created",
            target_user_id=normalized_email,
            ip_address=client_ip,
            safe_metadata={"role": "user", "display_name": dname, "auth_provider": "cognito"},
        )

        return user_record

    def set_user_status(
        self,
        admin_user_id: str | None = None,
        target_user_id: str = "",
        is_active: bool = True,
        client_ip: str | None = None,
        actor_id: str | None = None,
        admin_actor_id: str | None = None,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Enable or disable a user account in Cognito."""
        effective_admin_id = admin_user_id or admin_actor_id or actor_id or ""
        target_username = (target_user_id or user_id or "").strip()
        if not target_username:
            raise ValidationError("Target user ID is required")

        client = self._get_client()

        # Check user details and prevent modifying Administrator accounts
        try:
            groups_res = client.admin_list_groups_for_user(
                UserPoolId=self.config.user_pool_id,
                Username=target_username,
            )
            group_names = [g.get("GroupName") for g in groups_res.get("Groups", [])]
            if self.config.group_admin in group_names:
                raise ForbiddenError("Cannot modify active status of Administrator account")
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                raise NotFoundError(f"User '{target_username}' not found in Cognito")
            raise ServiceUnavailableError(f"Cognito query failed: {err}")

        try:
            if is_active:
                client.admin_enable_user(
                    UserPoolId=self.config.user_pool_id,
                    Username=target_username,
                )
                action = "user_activated"
            else:
                client.admin_disable_user(
                    UserPoolId=self.config.user_pool_id,
                    Username=target_username,
                )
                # Revoke all Cognito tokens and server sessions
                try:
                    client.admin_user_global_sign_out(
                        UserPoolId=self.config.user_pool_id,
                        Username=target_username,
                    )
                except Exception:
                    pass
                self.session_store.revoke_all_for_user(target_username)
                action = "user_deactivated"
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            msg = err.response.get("Error", {}).get("Message", str(err))
            if code == "UserNotFoundException":
                raise NotFoundError(f"User '{target_username}' not found in Cognito")
            raise ServiceUnavailableError(f"Failed to update user status in Cognito: {msg}")

        # Audit log
        self.audit_repo.record(
            actor_user_id=admin_user_id,
            action=action,
            target_user_id=target_username,
            ip_address=client_ip,
            safe_metadata={"is_active": is_active, "auth_provider": "cognito"},
        )

        return {
            "id": target_username,
            "is_active": is_active,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def reset_password(
        self,
        admin_user_id: str | None = None,
        target_user_id: str = "",
        new_password: str = "",
        client_ip: str | None = None,
        actor_id: str | None = None,
        admin_actor_id: str | None = None,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Reset a user's password in Cognito and revoke existing sessions."""
        effective_admin_id = admin_user_id or admin_actor_id or actor_id or ""
        target_username = (target_user_id or user_id or "").strip()
        if not target_username:
            raise ValidationError("Target user ID is required")

        if not new_password or not new_password.strip():
            raise ValidationError("Password is required.")

        is_valid, msg = validate_password_policy(new_password)
        if not is_valid:
            raise ValidationError(msg)

        client = self._get_client()

        # Check user details and prevent modifying Administrator accounts
        try:
            groups_res = client.admin_list_groups_for_user(
                UserPoolId=self.config.user_pool_id,
                Username=target_username,
            )
            group_names = [g.get("GroupName") for g in groups_res.get("Groups", [])]
            if self.config.group_admin in group_names:
                raise ForbiddenError("Cannot reset password of Administrator account via Officer management")
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                raise NotFoundError(f"User '{target_username}' not found in Cognito")
            raise ServiceUnavailableError(f"Cognito query failed: {err}")

        try:
            client.admin_set_user_password(
                UserPoolId=self.config.user_pool_id,
                Username=target_username,
                Password=new_password,
                Permanent=True,
            )
            # Invalidate all existing tokens globally
            try:
                client.admin_user_global_sign_out(
                    UserPoolId=self.config.user_pool_id,
                    Username=target_username,
                )
            except Exception:
                pass
            self.session_store.revoke_all_for_user(target_username)
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            msg = err.response.get("Error", {}).get("Message", str(err))
            if code == "UserNotFoundException":
                raise NotFoundError(f"User '{target_username}' not found in Cognito")
            elif code == "InvalidPasswordException":
                raise ValidationError(f"Password rejected by Cognito policy: {msg}")
            raise ServiceUnavailableError(f"Failed to reset password: {msg}")

        # Audit log
        self.audit_repo.record(
            actor_user_id=effective_admin_id,
            action="password_reset",
            target_user_id=target_username,
            ip_address=client_ip,
            safe_metadata={"auth_provider": "cognito"},
        )

        return {"message": "Password reset successfully", "user_id": target_username}

    def reset_user_password(self, **kwargs: Any) -> dict[str, Any]:
        """Alias for reset_password used by MuleTraceRequestHandler."""
        return self.reset_password(**kwargs)

    def list_audit_logs(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Query application security audit logs."""
        logs, total = self.audit_repo.list_logs(limit=limit, offset=offset)
        return {
            "logs": logs,
            "audit_logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
