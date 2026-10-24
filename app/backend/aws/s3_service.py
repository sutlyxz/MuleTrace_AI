"""Amazon S3 integration service for MuleTrace AI.

Provides utilities for storing and retrieving AML investigation reports,
managing datasets on S3, and hosting frontend static assets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]

DEFAULT_REGION = "us-east-1"
DEFAULT_BUCKET_NAME = "muletrace-ai-storage"


def is_s3_available() -> bool:
    """Return True if boto3 is installed and importable."""
    return boto3 is not None


def get_default_bucket_name(environment: Mapping[str, str] | None = None) -> str:
    """Retrieve default S3 bucket name from environment or constant."""
    env = environment if environment is not None else os.environ
    return env.get("S3_BUCKET_NAME", DEFAULT_BUCKET_NAME).strip() or DEFAULT_BUCKET_NAME


def get_s3_client(
    region_name: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_session_token: str | None = None,
    profile_name: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> Any:
    """Create and return a boto3 S3 client."""
    if boto3 is None:
        raise RuntimeError(
            "The 'boto3' package is required to connect to Amazon S3. "
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

    client_kwargs: dict[str, Any] = {"service_name": "s3"}
    if region:
        client_kwargs["region_name"] = region
    if access_key and secret_key:
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key
        if session_token:
            client_kwargs["aws_session_token"] = session_token

    return session.client(**client_kwargs)


def ensure_s3_bucket(
    bucket_name: str | None = None,
    client: Any = None,
    region_name: str | None = None,
) -> bool:
    """Check if an S3 bucket exists, or attempt creation if it does not."""
    target_bucket = bucket_name or get_default_bucket_name()
    s3_client = client or get_s3_client(region_name=region_name)
    region = region_name or getattr(s3_client.meta, "region_name", DEFAULT_REGION) or DEFAULT_REGION

    try:
        s3_client.head_bucket(Bucket=target_bucket)
        return True
    except Exception:
        pass

    try:
        create_kwargs: dict[str, Any] = {"Bucket": target_bucket}
        if region and region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3_client.create_bucket(**create_kwargs)
        return True
    except Exception:
        return False


def upload_report_to_s3(
    case_id: str,
    report_data: dict[str, Any],
    bucket_name: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Upload structured case investigation report to S3 as JSON."""
    target_bucket = bucket_name or get_default_bucket_name()
    key = f"reports/{case_id}/investigation_summary.json"

    try:
        s3_client = client or get_s3_client()
        body = json.dumps(report_data, ensure_ascii=False, indent=2).encode("utf-8")
        s3_client.put_object(
            Bucket=target_bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        return {
            "status": "success",
            "bucket": target_bucket,
            "key": key,
            "url": f"s3://{target_bucket}/{key}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "bucket": target_bucket,
            "key": key,
        }


def get_report_from_s3(
    case_id: str,
    bucket_name: str | None = None,
    client: Any = None,
) -> dict[str, Any] | None:
    """Retrieve structured case investigation report JSON from S3."""
    target_bucket = bucket_name or get_default_bucket_name()
    key = f"reports/{case_id}/investigation_summary.json"

    try:
        s3_client = client or get_s3_client()
        response = s3_client.get_object(Bucket=target_bucket, Key=key)
        content = response["Body"].read().decode("utf-8")
        return json.loads(content)
    except Exception:
        return None


def upload_dataset_to_s3(
    file_path: Path | str,
    s3_key: str | None = None,
    bucket_name: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Upload a raw or processed CSV dataset to S3."""
    path = Path(file_path)
    if not path.is_file():
        return {"status": "error", "message": f"File not found: {path}"}

    target_bucket = bucket_name or get_default_bucket_name()
    target_key = s3_key or f"datasets/{path.name}"

    try:
        s3_client = client or get_s3_client()
        with path.open("rb") as handle:
            s3_client.put_object(
                Bucket=target_bucket,
                Key=target_key,
                Body=handle,
                ContentType="text/csv",
            )
        return {
            "status": "success",
            "bucket": target_bucket,
            "key": target_key,
            "url": f"s3://{target_bucket}/{target_key}",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc), "bucket": target_bucket, "key": target_key}
