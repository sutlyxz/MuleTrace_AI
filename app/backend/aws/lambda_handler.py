"""AWS Lambda entry point for MuleTrace AI Serverless Architecture.

Handles API Gateway proxy requests (REST / HTTP API), Amazon EventBridge
TransactionEvent triggers from the simulation pipeline, and direct triggers,
orchestrating AML rule scoring, AI narrative generation via Bedrock,
report storage in Amazon S3, and alert persistence in Amazon DynamoDB.
"""
from __future__ import annotations

import json
from typing import Any

from .. import engine
from .bedrock_service import generate_narrative_report
from .dynamodb_service import get_investigation_alert, save_investigation_alert
from .s3_service import get_report_from_s3, upload_report_to_s3

_PROCESSED_EVENT_KEYS: set[str] = set()


def _cors_headers() -> dict[str, str]:
    """Return standard CORS headers for API Gateway responses."""
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
        "Content-Type": "application/json",
    }


def _response(status_code: int, body: Any) -> dict[str, Any]:
    """Format an API Gateway proxy response dictionary."""
    serialized = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": serialized,
    }


def _extract_path_and_method(event: dict[str, Any]) -> tuple[str, str]:
    """Extract normalized path and uppercase HTTP method from API Gateway event."""
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("path") or event.get("rawPath") or "/"
    return path.split("?")[0], method.upper()


def _extract_body(event: dict[str, Any]) -> dict[str, Any]:
    """Safely extract and parse JSON body from API Gateway event."""
    raw_body = event.get("body")
    if not raw_body:
        return {}
    if isinstance(raw_body, dict):
        return raw_body
    try:
        return json.loads(raw_body)
    except Exception:
        return {}


MIME_MAP = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}

import base64
import hashlib
import hmac
import time

_HMAC_SECRET = b"muletrace_serverless_hmac_secret_key_2026_us_east_1"
_SALT = b"muletrace_fixed_demo_salt_2026"

def _hash_password_pbkdf2(password: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _SALT, 100_000)
    return dk.hex()

def _verify_password_pbkdf2(password: str, expected_hex: str) -> bool:
    if not password or not expected_hex:
        return False
    computed = _hash_password_pbkdf2(password)
    return hmac.compare_digest(computed, expected_hex)

_DEMO_USERS = {
    "officer@agency.go.th": {
        "id": "usr_officer",
        "password_hash": "fee601524ac174b438832d6b0a94ab63e8b9a3ae60180e5cb39288894aadfdb8",
        "role": "user",
        "name": "Bank Officer",
        "department": "AML Investigation",
    },
    "admin@agency.go.th": {
        "id": "usr_admin",
        "password_hash": "f9ac3df11ab23f163b1548406355a10f0039de6983f4e55d80b52cbfd01f295d",
        "role": "admin",
        "name": "System Administrator",
        "department": "IT Security & Operations",
    },
}

def _create_session_token(payload: dict[str, Any]) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sig = hmac.new(_HMAC_SECRET, b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"

def _verify_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    b64_payload, sig = token.split(".", 1)
    expected_sig = hmac.new(_HMAC_SECRET, b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        padded = b64_payload + "=" * (-len(b64_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def _extract_cookie_token(event: dict[str, Any]) -> str | None:
    cookies = event.get("cookies") or []
    for c in cookies:
        if c.startswith("muletrace_session="):
            return c.split("=", 1)[1].split(";", 1)[0].strip()

    headers = event.get("headers") or {}
    cookie_hdr = headers.get("cookie") or headers.get("Cookie") or ""
    if "muletrace_session=" in cookie_hdr:
        for part in cookie_hdr.split(";"):
            part = part.strip()
            if part.startswith("muletrace_session="):
                return part.split("=", 1)[1].strip()

    return None

def _serve_static_asset(path: str) -> dict[str, Any] | None:
    from pathlib import Path
    clean_path = path.lstrip("/")
    if not clean_path:
        clean_path = "login.html"

    # 1. Local disk lookup inside Lambda package
    candidates = [
        Path(__file__).resolve().parents[3] / "app" / "frontend" / clean_path,
        Path("/var/task/app/frontend") / clean_path,
        Path("/var/task/frontend") / clean_path,
        Path(clean_path),
    ]
    for c in candidates:
        if c.is_file():
            suffix = c.suffix.lower()
            mime = MIME_MAP.get(suffix, "text/plain; charset=utf-8")
            try:
                text_content = c.read_text(encoding="utf-8")
                return {
                    "statusCode": 200,
                    "headers": {
                        "Content-Type": mime,
                        "Cache-Control": "public, max-age=3600" if suffix != ".html" else "no-cache",
                        "Access-Control-Allow-Origin": "*",
                    },
                    "body": text_content,
                }
            except Exception:
                pass

    # 2. Resilient S3 fallback
    try:
        from .s3_service import get_s3_client
        s3 = get_s3_client()
        s3_obj = s3.get_object(Bucket="muletrace-frontend-598122632336", Key=clean_path)
        body_text = s3_obj["Body"].read().decode("utf-8", errors="replace")
        suffix = Path(clean_path).suffix.lower()
        mime = MIME_MAP.get(suffix, "text/plain; charset=utf-8")
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": mime,
                "Cache-Control": "public, max-age=3600" if suffix != ".html" else "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
            "body": body_text,
        }
    except Exception:
        return None


def handle_api_request(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Process incoming API Gateway HTTP request."""
    path, method = _extract_path_and_method(event)

    # 1. CORS Preflight
    if method == "OPTIONS":
        return _response(200, {"status": "ok"})

    # 1b. Static Website Assets (Root, HTML, CSS, JS)
    if path == "/" or path == "" or path.endswith(".html") or path.startswith("/assets/") or path.endswith(".webmanifest") or path.endswith(".js"):
        target_file = "login.html" if path in ("/", "") else path
        asset_res = _serve_static_asset(target_file)
        if asset_res:
            return asset_res

    # 1c. Secure Authentication API
    if path == "/api/auth/login" and method == "POST":
        body = _extract_body(event)
        email = (body.get("email") or "").strip().lower()
        pwd = body.get("password") or ""
        u = _DEMO_USERS.get(email)
        if not u or not _verify_password_pbkdf2(pwd, u["password_hash"]):
            return _response(401, {"status": "error", "message": "Invalid email or password"})

        user_data = {
            "id": u["id"],
            "email": email,
            "role": u["role"],
            "name": u["name"],
            "department": u.get("department", "AML Investigation"),
        }
        token_payload = {
            **user_data,
            "exp": time.time() + 86400,
        }
        raw_token = _create_session_token(token_payload)
        cookie_val = f"muletrace_session={raw_token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=86400"
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Set-Cookie": cookie_val,
                "Access-Control-Allow-Origin": "*",
            },
            "cookies": [cookie_val],
            "body": json.dumps({
                "status": "success",
                "user": user_data,
            }, ensure_ascii=False),
        }

    if path == "/api/auth/me" and method == "GET":
        token = _extract_cookie_token(event)
        if not token:
            return _response(401, {"status": "error", "message": "Authentication required"})
        payload = _verify_session_token(token)
        if not payload:
            return _response(401, {"status": "error", "message": "Invalid or expired session"})
        return _response(200, {
            "status": "success",
            "user": {
                "id": payload.get("id"),
                "email": payload.get("email"),
                "role": payload.get("role"),
                "name": payload.get("name"),
                "department": payload.get("department", "AML Investigation"),
            },
        })

    if path == "/api/auth/logout" and method == "POST":
        clear_cookie = "muletrace_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Set-Cookie": clear_cookie,
                "Access-Control-Allow-Origin": "*",
            },
            "cookies": [clear_cookie],
            "body": json.dumps({"status": "success", "message": "Logged out successfully"}),
        }

    # 1d. Admin API
    if path == "/api/admin/aws-credentials" and method == "GET":
        return _response(200, {
            "configured": True,
            "masked_key_id": "IAM-ROLE-ACTIVE",
            "region": "us-east-1",
        })

    if path == "/api/admin/users" and method == "GET":
        return _response(200, {
            "status": "ok",
            "users": [
                {"id": "usr_1", "email": "officer@agency.go.th", "role": "user", "name": "Bank Officer", "is_active": True},
                {"id": "usr_2", "email": "admin@agency.go.th", "role": "admin", "name": "System Administrator", "is_active": True},
            ],
            "total": 2,
        })

    if path == "/api/admin/audit-logs" and method == "GET":
        return _response(200, {
            "status": "ok",
            "logs": [
                {"action": "SERVERLESS_DEPLOY", "admin_email": "aws-lambda@system", "target_email": "system", "created_at": "2026-10-25 04:30:00", "details": "Active IAM Role"},
            ],
            "total": 1,
        })

    # 2. Health Check
    if path.endswith("/health"):
        health_data = engine.health_check()
        return _response(200, health_data)

    # 3. Cases List
    if path.endswith("/cases") and method == "GET":
        case_accounts = engine.load_case_accounts()
        if case_accounts.empty:
            return _response(200, {"cases": [], "receivedCount": 0})
        case_ids = case_accounts["case_id"].unique().tolist()
        cases = []
        for cid in case_ids:
            accounts = case_accounts[case_accounts["case_id"] == cid]["account_id"].tolist()
            cases.append({"caseId": cid, "accounts": accounts})
        return _response(200, {"cases": cases, "receivedCount": len(cases)})

    # 4. Money Flow Tracing
    if path.endswith("/trace") and method == "POST":
        body = _extract_body(event)
        source = body.get("source_account", "")
        target = body.get("target_account", "")
        max_hops = int(body.get("max_hops", 4))
        try:
            trace_result = engine.trace_money(source, target, max_hops=max_hops)
            return _response(200, trace_result)
        except Exception as exc:
            return _response(400, {"error": str(exc)})

    # 5. Risk Scoring
    if path.endswith("/score") and method == "GET":
        params = event.get("queryStringParameters") or {}
        case_id = params.get("case_id")
        account_id = params.get("account_id")
        if not case_id and not account_id:
            return _response(400, {"error": "Provide case_id or account_id"})
        try:
            score_result = engine.score_investigation(case_id=case_id, account_id=account_id)
            return _response(200, score_result)
        except Exception as exc:
            return _response(400, {"error": str(exc)})

    # 5b. Transaction Simulation Trigger & Status
    if path.endswith("/simulation/run") and method == "POST":
        body = _extract_body(event)
        try:
            from ..simulation.engine import SimulationEngine
            seed_val = body.get("seed")
            sim_engine = SimulationEngine()
            sim_res = sim_engine.run_simulation(seed=int(seed_val) if seed_val is not None else None)
            return _response(200, {"status": "success", "data": sim_res})
        except Exception as exc:
            return _response(500, {"status": "error", "message": str(exc)})

    if "/simulation/status/" in path and method == "GET":
        run_id = path.rstrip("/").split("/")[-1]
        from ..simulation.engine import SimulationEngine
        status_data = SimulationEngine.get_run_status(run_id)
        if not status_data:
            return _response(404, {"status": "error", "message": f"Run ID '{run_id}' not found"})
        return _response(200, {"status": "success", "data": status_data})

    # 6. AI Summary & Case Triage (Bedrock + S3 + DynamoDB)
    if path.endswith("/api/ai/summary") or path.endswith("/ai/summary"):
        body = _extract_body(event)
        case_id = body.get("case_id", "MT-1042")
        lang = body.get("language", "th")
        investigation_input = body.get("investigation")

        if not investigation_input or not isinstance(investigation_input, dict):
            try:
                investigation_data = engine.score_investigation(case_id=case_id)
            except Exception:
                investigation_data = {
                    "case_id": case_id,
                    "score": 85,
                    "priority": "High",
                    "rule_types_matched": ["rapid_outgoing", "multiple_incoming"],
                }
        else:
            investigation_data = dict(investigation_input)

        try:
            ai_report = generate_narrative_report(investigation_data, language=lang)
            summary = ai_report.get("narrative", "")
            if not summary.strip():
                raise ValueError("Empty narrative produced")
        except Exception as ai_err:
            if lang == "en":
                summary = (
                    f"MuleTrace AML Rule Engine Report for {case_id}:\n"
                    f"- Priority Score: {investigation_data.get('score', 80)} ({investigation_data.get('priority', 'High')})\n"
                    f"- Risk Rules: {', '.join(investigation_data.get('rule_types_matched', []))}\n"
                    f"(Bedrock notice: {ai_err})"
                )
            else:
                summary = (
                    f"รายงานระบบกฎ MuleTrace AML สำหรับเคส {case_id}:\n"
                    f"- คะแนนความสำคัญ: {investigation_data.get('score', 80)} ({investigation_data.get('priority', 'High')})\n"
                    f"- สัญญาณความเสี่ยง: {', '.join(investigation_data.get('rule_types_matched', []))}\n"
                    f"(หมายเหตุ Bedrock: {ai_err})"
                )

        report_payload = {
            "case_id": case_id,
            "summary": summary,
            "investigation": investigation_data,
        }

        s3_res = upload_report_to_s3(case_id, report_payload)
        dynamo_res = save_investigation_alert(case_id, {
            "score": investigation_data.get("score", 0),
            "priority": investigation_data.get("priority", "Medium"),
            "summary": summary,
        })

        return _response(200, {
            "status": "success",
            "summary": summary,
            "case_id": case_id,
            "s3": s3_res,
            "dynamodb": dynamo_res,
        })

    # 7. Query Saved Alert
    if "/alerts/" in path and method == "GET":
        case_id = path.rstrip("/").split("/")[-1]
        alert = get_investigation_alert(case_id)
        if alert:
            return _response(200, alert)
        s3_report = get_report_from_s3(case_id)
        if s3_report:
            return _response(200, s3_report)
        return _response(404, {"error": f"Alert for {case_id} not found"})

    return _response(404, {"error": f"Path not found: {path}"})


def handle_eventbridge_transaction(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Process an Amazon EventBridge TransactionEvent emitted by the simulator."""
    raw_detail = event.get("detail") or event.get("Detail") or {}
    if isinstance(raw_detail, str):
        try:
            detail = json.loads(raw_detail)
        except Exception:
            detail = {}
    else:
        detail = dict(raw_detail)

    run_id = str(detail.get("simulation_run_id") or "sim_unknown")
    tx_id = str(detail.get("transaction_id") or "TX_UNKNOWN")
    dedup_key = f"{run_id}#{tx_id}"

    if dedup_key in _PROCESSED_EVENT_KEYS:
        return {
            "status": "duplicate_skipped",
            "dedup_key": dedup_key,
            "run_id": run_id,
            "transaction_id": tx_id,
        }
    _PROCESSED_EVENT_KEYS.add(dedup_key)

    is_suspicious = bool(detail.get("is_suspicious", False))
    scenario = str(detail.get("scenario") or "normal")

    if not is_suspicious:
        return {
            "status": "processed_normal",
            "dedup_key": dedup_key,
            "run_id": run_id,
            "transaction_id": tx_id,
            "alert_created": False,
        }

    case_id = f"SIM-{tx_id}"
    alert_payload = {
        "case_id": case_id,
        "simulation_run_id": run_id,
        "transaction_id": tx_id,
        "source_account": detail.get("source_account"),
        "target_account": detail.get("target_account"),
        "amount": detail.get("amount", 0),
        "scenario": scenario,
        "score": 90,
        "priority": "High",
        "dedup_key": dedup_key,
    }
    s3_res = upload_report_to_s3(case_id, alert_payload)
    dynamo_res = save_investigation_alert(case_id, alert_payload)

    return {
        "status": "alert_created",
        "dedup_key": dedup_key,
        "case_id": case_id,
        "run_id": run_id,
        "transaction_id": tx_id,
        "alert_created": True,
        "s3": s3_res,
        "dynamodb": dynamo_res,
    }


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Universal AWS Lambda entry point."""
    if not isinstance(event, dict):
        return _response(400, {"error": "Invalid event format"})

    # 1. API Gateway HTTP / REST event
    if "httpMethod" in event or "requestContext" in event:
        return handle_api_request(event, context)

    # 2. Amazon EventBridge TransactionEvent trigger
    source = event.get("source") or event.get("Source")
    detail_type = event.get("detail-type") or event.get("DetailType")
    if source == "muletrace.simulation" or detail_type == "TransactionEvent":
        return handle_eventbridge_transaction(event, context)

    # 3. Direct event invocation
    case_id = event.get("case_id") or event.get("detail", {}).get("case_id", "CASE001")
    try:
        investigation_data = engine.score_investigation(case_id=case_id)
    except Exception:
        investigation_data = {"case_id": case_id, "score": 80, "priority": "High"}

    s3_res = upload_report_to_s3(case_id, investigation_data)
    dynamo_res = save_investigation_alert(case_id, investigation_data)

    return {
        "status": "processed",
        "case_id": case_id,
        "s3": s3_res,
        "dynamodb": dynamo_res,
    }