"""Unified Authentication and Administration Factory for MuleTrace AI.

Resolves either Local (PostgreSQL + Argon2id) or AWS (Amazon Cognito) services
based on the MULETRACE_AUTH_PROVIDER environment variable, strictly enforcing
fail-closed behavior without silent fallback.
"""
from __future__ import annotations

import os
from typing import Any

from ..auth.config import (
    AUTH_PROVIDER_ENV,
    get_auth_provider,
    CognitoConfig,
)
from .auth_service import AuthService, default_auth_service, ServiceUnavailableError
from .admin_service import AdminService, default_admin_service


def get_active_auth_service() -> Any:
    """Return the active authentication service based on environment configuration."""
    provider = get_auth_provider()

    if provider == "cognito":
        try:
            from ..auth.cognito_service import CognitoAuthService
            config = CognitoConfig.from_environment()
            return CognitoAuthService(config=config)
        except Exception as exc:
            # Strictly Fail-Closed: NEVER fall back to local authentication
            raise ServiceUnavailableError(
                f"Cognito authentication is configured but initialization failed: {exc}"
            )

    return default_auth_service


def get_active_admin_service() -> Any:
    """Return the active administration service based on environment configuration."""
    provider = get_auth_provider()

    if provider == "cognito":
        try:
            from .cognito_admin_service import CognitoAdminService
            config = CognitoConfig.from_environment()
            return CognitoAdminService(config=config)
        except Exception as exc:
            # Strictly Fail-Closed
            raise ServiceUnavailableError(
                f"Cognito admin service is configured but initialization failed: {exc}"
            )

    return default_admin_service
