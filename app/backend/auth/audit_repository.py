"""Audit logging repository for AWS deployments and local mock testing.

Provides structured recording of administrative and authentication events
without storing passwords, tokens, or sensitive credentials.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import os
import secrets
import threading
from typing import Any

from .config import DYNAMODB_AUDIT_TABLE_ENV, DEFAULT_DYNAMODB_AUDIT_TABLE


class AuditRepository(ABC):
    """Abstract interface for security audit logging."""

    @abstractmethod
    def record(
        self,
        actor_user_id: str | None,
        action: str,
        target_user_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        """Record an auditable action."""

    @abstractmethod
    def list_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Return a page of audit logs and total count."""


class InMemoryAuditRepository(AuditRepository):
    """Thread-safe in-memory audit store for testing and fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logs: list[dict[str, Any]] = []

    def record(
        self,
        actor_user_id: str | None,
        action: str,
        target_user_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        entry = {
            "id": f"aud_{secrets.token_hex(12)}",
            "actor_user_id": actor_user_id or "system",
            "action": action,
            "target_user_id": target_user_id,
            "safe_metadata": safe_metadata or {},
            "ip_address": ip_address,
            "created_at": now.isoformat(),
        }

        with self._lock:
            # prepend to keep newest first
            self._logs.insert(0, entry)

        return entry

    def list_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            total = len(self._logs)
            page = self._logs[offset : offset + limit]
            return [dict(item) for item in page], total


class DynamoDBAuditRepository(AuditRepository):
    """Amazon DynamoDB implementation of audit logging."""

    def __init__(
        self,
        table_name: str | None = None,
        dynamodb_client: Any = None,
        region: str = "us-east-1",
    ) -> None:
        self.table_name = table_name or os.environ.get(
            DYNAMODB_AUDIT_TABLE_ENV, DEFAULT_DYNAMODB_AUDIT_TABLE
        )
        self.region = region
        self._client = dynamodb_client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3
        self._client = boto3.client("dynamodb", region_name=self.region)
        return self._client

    def record(
        self,
        actor_user_id: str | None,
        action: str,
        target_user_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        log_id = f"aud_{secrets.token_hex(12)}"
        now = datetime.now(timezone.utc).isoformat()
        client = self._get_client()

        item: dict[str, Any] = {
            "id": {"S": log_id},
            "actor_user_id": {"S": actor_user_id or "system"},
            "action": {"S": action},
            "created_at": {"S": now},
        }
        if target_user_id:
            item["target_user_id"] = {"S": target_user_id}
        if ip_address:
            item["ip_address"] = {"S": ip_address}
        if safe_metadata:
            item["safe_metadata"] = {"S": json.dumps(safe_metadata)}

        client.put_item(TableName=self.table_name, Item=item)

        return {
            "id": log_id,
            "actor_user_id": actor_user_id or "system",
            "action": action,
            "target_user_id": target_user_id,
            "safe_metadata": safe_metadata or {},
            "ip_address": ip_address,
            "created_at": now,
        }

    def list_logs(self, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        client = self._get_client()
        try:
            # Query or Scan from DynamoDB
            res = client.scan(TableName=self.table_name, Limit=limit + offset)
            items = res.get("Items", [])
            logs = []
            for item in items:
                metadata = {}
                raw_meta = item.get("safe_metadata", {}).get("S")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta)
                    except Exception:
                        pass
                logs.append({
                    "id": item.get("id", {}).get("S", ""),
                    "actor_user_id": item.get("actor_user_id", {}).get("S", ""),
                    "action": item.get("action", {}).get("S", ""),
                    "target_user_id": item.get("target_user_id", {}).get("S"),
                    "safe_metadata": metadata,
                    "ip_address": item.get("ip_address", {}).get("S"),
                    "created_at": item.get("created_at", {}).get("S", ""),
                })
            # sort newest first
            logs.sort(key=lambda x: x["created_at"], reverse=True)
            total = len(logs)
            return logs[offset : offset + limit], total
        except Exception:
            return [], 0


default_memory_audit_repo = InMemoryAuditRepository()
