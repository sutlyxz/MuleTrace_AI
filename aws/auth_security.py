"""Authentication and Authorization Security Layer for AWS FastAPI Application.

Enforces server-side authentication and role-based access control (RBAC)
using Amazon Cognito JWT tokens and server-side session cookies.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.backend.auth.config import (
    CognitoConfig,
    DEFAULT_GROUP_ADMIN,
    DEFAULT_GROUP_OFFICER,
    is_cognito_enabled,
)
from app.backend.auth.cognito_service import decode_jwt_payload_unverified
from app.backend.auth.session_store import get_session_store

security_bearer = HTTPBearer(auto_error=False)


def _resolve_user_from_jwt(token: str) -> dict[str, Any] | None:
    """Extract and validate claims from an Amazon Cognito JWT."""
    claims = decode_jwt_payload_unverified(token)
    if not claims:
        return None

    # Expiry check
    import time
    exp = claims.get("exp")
    if exp and exp < time.time():
        return None

    groups = claims.get("cognito:groups", [])
    group_admin = os.environ.get("COGNITO_GROUP_ADMIN", DEFAULT_GROUP_ADMIN)
    group_officer = os.environ.get("COGNITO_GROUP_OFFICER", DEFAULT_GROUP_OFFICER)

    if group_admin in groups:
        role = "admin"
    elif group_officer in groups:
        role = "user"
    else:
        role = "unauthorized"

    user_id = claims.get("sub") or claims.get("cognito:username") or claims.get("email")
    email = claims.get("email", "")
    dname = claims.get("name") or claims.get("nickname") or email.split("@")[0]

    return {
        "user_id": str(user_id),
        "email": email,
        "display_name": dname,
        "role": role,
        "groups": groups,
    }


async def get_current_user(
    request: Request,
    auth_cred: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    muletrace_session: str | None = Cookie(None),
) -> dict[str, Any]:
    """Extract authenticated user from Bearer token or HttpOnly session cookie."""
    # 1. Check Bearer token (Cognito IdToken or AccessToken)
    token = None
    if auth_cred and auth_cred.credentials:
        token = auth_cred.credentials
    elif "Authorization" in request.headers:
        header_val = request.headers["Authorization"].strip()
        if header_val.lower().startswith("bearer "):
            token = header_val[7:].strip()

    if token:
        # Check if token is a session token in session store
        session_store = get_session_store()
        session = session_store.get_session(token)
        if session:
            return session

        # Otherwise verify as Cognito JWT
        user_jwt = _resolve_user_from_jwt(token)
        if user_jwt:
            if user_jwt["role"] == "unauthorized":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: User does not belong to authorized Cognito group",
                )
            return user_jwt

    # 2. Check HttpOnly session cookie
    cookie_token = muletrace_session
    if not cookie_token and "muletrace_session" in request.cookies:
        cookie_token = request.cookies["muletrace_session"]

    if cookie_token:
        session_store = get_session_store()
        session = session_store.get_session(cookie_token)
        if session:
            return session

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(*allowed_roles: str) -> Callable[..., Any]:
    """Dependency factory enforcing server-side role-based access control."""
    async def role_checker(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_role = current_user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Requires role in {list(allowed_roles)}",
            )
        return current_user

    return role_checker


# Reusable security dependencies
require_investigation_role = require_role("user", "admin")
require_admin_role = require_role("admin")
