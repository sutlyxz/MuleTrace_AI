"""Amazon DynamoDB integration service for MuleTrace AI.

Provides fast, serverless persistence and retrieval for investigation alerts,
risk scores, and compliance triage records.
"""
from __future__ import annotations

from decimal import Decimal
import os
import time
from typing import Any, Mapping

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]

DEFAULT_REGION = "us-east-1"
DEFAULT_TABLE_NAME = "MuleTraceAlerts"


def is_dynamodb_available() -> bool:
    """Return True if boto3 is installed and importable."""
    return boto3 is not None


def get_default_table_name(environment: Mapping[str, str] | None = None) -> str:
    """Retrieve default DynamoDB table name from environment or constant."""
    env = environment if environment is not None else os.environ
    return env.get("DYNAMODB_TABLE_NAME", DEFAULT_TABLE_NAME).strip() or DEFAULT_TABLE_NAME


def get_dynamodb_resource(
    region_name: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_session_token: str | None = None,
    profile_name: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> Any:
    """Create and return a boto3 DynamoDB resource."""
    if boto3 is None:
        raise RuntimeError(
            "The 'boto3' package is required to connect to Amazon DynamoDB. "
            "Install it using: pip install boto3"
        )

    env = environment if environment is not None else os.environ

    region = region_name or env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or DEFAULT_REGION
    access_key = aws_access_key_id or env.get("AWS_ACCESS_KEY_ID")
    secret_key = aws_secret_access_key or env.get("AWS_SECRET_ACCESS_KEY")
    session_token = aws_session_token or env.get("AWS_SESSION_TOKEN")
    profile = profile_name or env.get("AWS_PROFILE")

    session_kwargs: dict[str, Any] = {}
    if profile:
        session_kwargs["profile_name"] = profile
    if region:
        session_kwargs["region_name"] = region

    session = boto3.Session(**session_kwargs)

    resource_kwargs: dict[str, Any] = {"service_name": "dynamodb"}
    if region:
        resource_kwargs["region_name"] = region
    if access_key and secret_key:
        resource_kwargs["aws_access_key_id"] = access_key
        resource_kwargs["aws_secret_access_key"] = secret_key
        if session_token:
            resource_kwargs["aws_session_token"] = session_token

    return session.resource(**resource_kwargs)


def _sanitize_for_dynamodb(data: Any) -> Any:
    """Recursively convert float to Decimal for DynamoDB serialization."""
    if isinstance(data, float):
        return Decimal(str(data))
    if isinstance(data, dict):
        return {str(k): _sanitize_for_dynamodb(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize_for_dynamodb(item) for item in data]
    return data


def _desanitize_from_dynamodb(data: Any) -> Any:
    """Recursively convert Decimal back to int/float for JSON compatibility."""
    if isinstance(data, Decimal):
        return int(data) if data % 1 == 0 else float(data)
    if isinstance(data, dict):
        return {k: _desanitize_from_dynamodb(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_desanitize_from_dynamodb(item) for item in data]
    return data


def ensure_dynamodb_table(
    table_name: str | None = None,
    dynamodb: Any = None,
) -> bool:
    """Ensure the DynamoDB table exists, or create it with on-demand capacity."""
    target_table = table_name or get_default_table_name()
    resource = dynamodb or get_dynamodb_resource()

    try:
        table = resource.Table(target_table)
        table.load()
        return True
    except Exception:
        pass

    try:
        resource.create_table(
            TableName=target_table,
            KeySchema=[
                {"AttributeName": "case_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "case_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        return True
    except Exception:
        return False


def save_investigation_alert(
    case_id: str,
    alert_data: dict[str, Any],
    table_name: str | None = None,
    dynamodb: Any = None,
) -> dict[str, Any]:
    """Save or update an AML investigation alert in DynamoDB."""
    target_table = table_name or get_default_table_name()

    try:
        resource = dynamodb or get_dynamodb_resource()
        table = resource.Table(target_table)

        item = {
            "case_id": case_id,
            "timestamp": int(time.time()),
            "score": alert_data.get("score", 0),
            "priority": alert_data.get("priority", "Medium"),
            "data": _sanitize_for_dynamodb(alert_data),
        }
        table.put_item(Item=item)
        return {
            "status": "success",
            "case_id": case_id,
            "table": target_table,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "case_id": case_id,
            "table": target_table,
        }


def get_investigation_alert(
    case_id: str,
    table_name: str | None = None,
    dynamodb: Any = None,
) -> dict[str, Any] | None:
    """Fetch an investigation alert by case ID from DynamoDB."""
    target_table = table_name or get_default_table_name()

    try:
        resource = dynamodb or get_dynamodb_resource()
        table = resource.Table(target_table)
        response = table.get_item(Key={"case_id": case_id})
        item = response.get("Item")
        if not item:
            return None
        return _desanitize_from_dynamodb(item)
    except Exception:
        return None
