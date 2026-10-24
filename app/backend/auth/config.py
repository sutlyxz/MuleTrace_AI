"""Environment-driven authentication configuration supporting local and AWS Cognito modes.

Provides configuration validation, provider resolution, and security constants
for MuleTrace AI authentication and session management.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[3]

AUTH_PROVIDER_ENV = "MULETRACE_AUTH_PROVIDER"
DEFAULT_AUTH_PROVIDER: Literal["local", "cognito"] = "local"
SUPPORTED_AUTH_PROVIDERS = ("local", "cognito")

# AWS Cognito Environment Variable Names
AWS_REGION_ENV = "AWS_REGION"
DEFAULT_AWS_REGION = "us-east-1"
COGNITO_USER_POOL_ID_ENV = "COGNITO_USER_POOL_ID"
COGNITO_APP_CLIENT_ID_ENV = "COGNITO_APP_CLIENT_ID"
COGNITO_GROUP_ADMIN_ENV = "COGNITO_GROUP_ADMIN"
COGNITO_GROUP_OFFICER_ENV = "COGNITO_GROUP_OFFICER"
DEFAULT_GROUP_ADMIN = "Admin"
DEFAULT_GROUP_OFFICER = "BankOfficer"

# Session Store Configuration
SESSION_STORE_ENV = "MULETRACE_SESSION_STORE"
DEFAULT_SESSION_STORE = "memory"  # memory | dynamodb | database

# DynamoDB Table Names
DYNAMODB_SESSIONS_TABLE_ENV = "DYNAMODB_SESSIONS_TABLE"
DEFAULT_DYNAMODB_SESSIONS_TABLE = "muletrace_sessions"
DYNAMODB_AUDIT_TABLE_ENV = "DYNAMODB_AUDIT_TABLE"
DEFAULT_DYNAMODB_AUDIT_TABLE = "muletrace_audit_logs"


class CognitoConfig:
    """Validated Amazon Cognito configuration container."""

    def __init__(
        self,
        region: str,
        user_pool_id: str,
        app_client_id: str,
        group_admin: str = DEFAULT_GROUP_ADMIN,
        group_officer: str = DEFAULT_GROUP_OFFICER,
    ) -> None:
        if not region:
            raise ValueError(f"Cognito region is required ({AWS_REGION_ENV})")
        if not user_pool_id:
            raise ValueError(f"Cognito User Pool ID is required ({COGNITO_USER_POOL_ID_ENV})")
        if not app_client_id:
            raise ValueError(f"Cognito App Client ID is required ({COGNITO_APP_CLIENT_ID_ENV})")

        self.region = region
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.group_admin = group_admin or DEFAULT_GROUP_ADMIN
        self.group_officer = group_officer or DEFAULT_GROUP_OFFICER

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None) -> CognitoConfig:
        source = env if env is not None else os.environ
        region = source.get(AWS_REGION_ENV, DEFAULT_AWS_REGION).strip()
        user_pool_id = source.get(COGNITO_USER_POOL_ID_ENV, "").strip()
        app_client_id = source.get(COGNITO_APP_CLIENT_ID_ENV, "").strip()
        group_admin = source.get(COGNITO_GROUP_ADMIN_ENV, DEFAULT_GROUP_ADMIN).strip()
        group_officer = source.get(COGNITO_GROUP_OFFICER_ENV, DEFAULT_GROUP_OFFICER).strip()

        return cls(
            region=region,
            user_pool_id=user_pool_id,
            app_client_id=app_client_id,
            group_admin=group_admin,
            group_officer=group_officer,
        )


def get_auth_provider() -> str:
    """Return the active authentication provider ('local' or 'cognito')."""
    raw = os.environ.get(AUTH_PROVIDER_ENV, DEFAULT_AUTH_PROVIDER).strip().lower()
    if raw not in SUPPORTED_AUTH_PROVIDERS:
        raise ValueError(
            f"Invalid {AUTH_PROVIDER_ENV}: '{raw}'. Must be one of {SUPPORTED_AUTH_PROVIDERS}"
        )
    return raw


def is_cognito_enabled() -> bool:
    """Return True if AWS Cognito is the configured authentication provider."""
    return get_auth_provider() == "cognito"
