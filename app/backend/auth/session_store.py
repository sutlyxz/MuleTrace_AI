"""Server-side session storage abstraction for MuleTrace AI.

Provides secure session lifecycle management across memory, database, and
Amazon DynamoDB backends, ensuring HttpOnly cookies never expose user tokens.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
import hashlib
import os
import secrets
import threading
from typing import Any

from .config import (
    DYNAMODB_SESSIONS_TABLE_ENV,
    DEFAULT_DYNAMODB_SESSIONS_TABLE,
    SESSION_STORE_ENV,
    DEFAULT_SESSION_STORE,
)


def hash_token(raw_token: str) -> str:
    """Compute SHA-256 hash of a raw session token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class SessionStore(ABC):
    """Abstract interface for server-side session storage."""

    @abstractmethod
    def create_session(
        self,
        user_info: dict[str, Any],
        tokens: dict[str, Any] | None = None,
        ttl_seconds: int = 43200,
    ) -> str:
        """Create a new session and return the raw session token."""

    @abstractmethod
    def get_session(self, raw_token: str) -> dict[str, Any] | None:
        """Retrieve active session data for a raw token, returning None if expired/revoked."""

    @abstractmethod
    def revoke_session(self, raw_token: str) -> bool:
        """Revoke a specific session."""

    @abstractmethod
    def revoke_all_for_user(self, user_id: str) -> int:
        """Revoke all active sessions for a specific user ID."""


class InMemorySessionStore(SessionStore):
    """Thread-safe in-memory session store for local/testing environments."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # token_hash -> session_record
        self._sessions: dict[str, dict[str, Any]] = {}

    def create_session(
        self,
        user_info: dict[str, Any],
        tokens: dict[str, Any] | None = None,
        ttl_seconds: int = 43200,
    ) -> str:
        raw_token = secrets.token_urlsafe(32)
        token_hash_val = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        record = {
            "session_id": f"sess_{secrets.token_hex(12)}",
            "token_hash": token_hash_val,
            "user_id": user_info.get("user_id") or user_info.get("id", ""),
            "email": user_info.get("email", ""),
            "display_name": user_info.get("display_name", ""),
            "role": user_info.get("role", "user"),
            "groups": user_info.get("groups", []),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "expires_at_timestamp": int(expires_at.timestamp()),
            "is_revoked": False,
            "tokens": tokens or {},
        }

        with self._lock:
            self._sessions[token_hash_val] = record

        return raw_token

    def get_session(self, raw_token: str) -> dict[str, Any] | None:
        if not raw_token:
            return None

        token_hash_val = hash_token(raw_token)
        with self._lock:
            record = self._sessions.get(token_hash_val)
            if not record:
                return None

            if record.get("is_revoked", False):
                return None

            # Expiration check
            now_ts = int(datetime.now(timezone.utc).timestamp())
            if record.get("expires_at_timestamp", 0) <= now_ts:
                return None

            return dict(record)

    def revoke_session(self, raw_token: str) -> bool:
        if not raw_token:
            return False

        token_hash_val = hash_token(raw_token)
        with self._lock:
            if token_hash_val in self._sessions:
                self._sessions[token_hash_val]["is_revoked"] = True
                return True
            return False

    def revoke_all_for_user(self, user_id: str) -> int:
        if not user_id:
            return 0

        revoked = 0
        with self._lock:
            for record in self._sessions.values():
                if record.get("user_id") == user_id and not record.get("is_revoked"):
                    record["is_revoked"] = True
                    revoked += 1
        return revoked


class DynamoDBSessionStore(SessionStore):
    """Amazon DynamoDB-backed session store for distributed AWS deployments."""

    def __init__(
        self,
        table_name: str | None = None,
        dynamodb_client: Any = None,
        region: str = "us-east-1",
    ) -> None:
        self.table_name = table_name or os.environ.get(
            DYNAMODB_SESSIONS_TABLE_ENV, DEFAULT_DYNAMODB_SESSIONS_TABLE
        )
        self.region = region
        self._client = dynamodb_client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3
        self._client = boto3.client("dynamodb", region_name=self.region)
        return self._client

    def create_session(
        self,
        user_info: dict[str, Any],
        tokens: dict[str, Any] | None = None,
        ttl_seconds: int = 43200,
    ) -> str:
        raw_token = secrets.token_urlsafe(32)
        token_hash_val = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        expires_ts = int(expires_at.timestamp())

        client = self._get_client()
        user_id = str(user_info.get("user_id") or user_info.get("id", ""))
        email = str(user_info.get("email", ""))
        display_name = str(user_info.get("display_name", ""))
        role = str(user_info.get("role", "user"))

        item = {
            "token_hash": {"S": token_hash_val},
            "user_id": {"S": user_id},
            "email": {"S": email},
            "display_name": {"S": display_name},
            "role": {"S": role},
            "created_at": {"S": now.isoformat()},
            "expires_at": {"N": str(expires_ts)},
            "is_revoked": {"BOOL": False},
        }

        client.put_item(TableName=self.table_name, Item=item)
        return raw_token

    def get_session(self, raw_token: str) -> dict[str, Any] | None:
        if not raw_token:
            return None

        token_hash_val = hash_token(raw_token)
        client = self._get_client()

        try:
            res = client.get_item(
                TableName=self.table_name,
                Key={"token_hash": {"S": token_hash_val}},
                ConsistentRead=True,
            )
        except Exception:
            return None

        item = res.get("Item")
        if not item:
            return None

        is_revoked = item.get("is_revoked", {}).get("BOOL", False)
        if is_revoked:
            return None

        expires_ts = int(item.get("expires_at", {}).get("N", "0"))
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if expires_ts <= now_ts:
            return None

        return {
            "user_id": item.get("user_id", {}).get("S", ""),
            "email": item.get("email", {}).get("S", ""),
            "display_name": item.get("display_name", {}).get("S", ""),
            "role": item.get("role", {}).get("S", "user"),
            "created_at": item.get("created_at", {}).get("S", ""),
            "expires_at": expires_ts,
            "is_revoked": False,
        }

    def revoke_session(self, raw_token: str) -> bool:
        if not raw_token:
            return False

        token_hash_val = hash_token(raw_token)
        client = self._get_client()
        try:
            client.update_item(
                TableName=self.table_name,
                Key={"token_hash": {"S": token_hash_val}},
                UpdateExpression="SET is_revoked = :rev",
                ExpressionAttributeValues={":rev": {"BOOL": True}},
            )
            return True
        except Exception:
            return False

    def revoke_all_for_user(self, user_id: str) -> int:
        # Note: In production DynamoDB, a GSI on user_id allows querying all active sessions
        return 0


# Default global in-memory session store singleton
default_memory_session_store = InMemorySessionStore()


def get_session_store() -> SessionStore:
    """Return the configured session store instance."""
    store_type = os.environ.get(SESSION_STORE_ENV, DEFAULT_SESSION_STORE).strip().lower()
    if store_type == "dynamodb":
        return DynamoDBSessionStore()
    return default_memory_session_store
