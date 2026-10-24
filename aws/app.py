import uuid
import sys
from pathlib import Path
from typing import List, Optional, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Import existing engine functions
from app.backend.engine import (
    health_check,
    get_evidence,
    trace_money,
    score_investigation,
    load_case_accounts,
    load_transactions,
    get_account_profile,
)

# Import security dependencies and services
from aws.auth_security import (
    get_current_user,
    require_investigation_role,
    require_admin_role,
)
from app.backend.services.auth_factory import (
    get_active_auth_service,
    get_active_admin_service,
)
from app.backend.services.auth_service import (
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)
from app.backend.services.admin_service import (
    ValidationError as AdminValidationError,
    ConflictError as AdminConflictError,
    NotFoundError as AdminNotFoundError,
    ForbiddenError as AdminForbiddenError,
    ServiceUnavailableError as AdminServiceUnavailableError,
)

app = FastAPI(title="MuleTrace AI AWS Backend", version="0.1.0")

# ---------- Strict CORS Configuration ----------
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.cloudfront\.net",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


def _request_id() -> str:
    return str(uuid.uuid4())


# ---------- Pydantic Models ----------
class HealthResponse(BaseModel):
    status: str
    transactions_file_exists: bool
    case_accounts_file_exists: bool
    available_tools: List[str]
    request_id: str = Field(default_factory=_request_id)


class CaseItem(BaseModel):
    caseId: str
    source: Optional[str] = None
    target: Optional[str] = None
    amount: Optional[float] = None
    time: Optional[str] = None
    status: Optional[str] = None
    risk: Optional[str] = None
    priorityScore: Optional[int] = None
    transactionId: Optional[str] = None
    description: Optional[str] = None
    request_id: str = Field(default_factory=_request_id)


class CasesResponse(BaseModel):
    cases: List[CaseItem]
    source: str = "api"
    receivedCount: int
    limited: bool = False
    request_id: str = Field(default_factory=_request_id)


class TraceRequest(BaseModel):
    source_account: str = Field(..., alias="source_account")
    target_account: str = Field(..., alias="target_account")
    max_hops: int = Field(4, ge=1, le=8)


class TraceResponse(BaseModel):
    source_account: str
    target_account: str
    max_hops: int
    path_count: int
    paths: List[Any]
    evidence_transaction_ids: List[str]
    evidence: List[dict]
    message: str
    request_id: str = Field(default_factory=_request_id)


class ScoreResponse(BaseModel):
    case_id: Optional[str] = None
    account_id: Optional[str] = None
    accounts_in_scope: List[str]
    score: int
    priority: str
    rule_types_matched: List[str]
    reasons: List[str]
    finding_count: int
    evidence_transaction_ids: List[str]
    evidence: List[dict]
    disclaimer: str
    request_id: str = Field(default_factory=_request_id)


class EvidenceResponse(BaseModel):
    count: int
    transactions: List[dict]
    missing_transaction_ids: List[str]
    request_id: str = Field(default_factory=_request_id)


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None
    role: str = "user"


class StatusUpdateRequest(BaseModel):
    is_active: bool


class PasswordResetRequest(BaseModel):
    new_password: str


# ---------- Public Health Endpoint ----------
@app.get("/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse)
def get_health():
    data = health_check()
    return HealthResponse(**data, request_id=_request_id())


# ---------- Authentication Endpoints ----------
@app.post("/api/auth/login")
@app.post("/auth/login")
async def login(req: LoginRequest, request: Request, response: Response):
    auth_service = get_active_auth_service()
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        raw_token, user_info = auth_service.login(
            req.email, req.password, client_ip=client_ip
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    # Set secure HttpOnly session cookie
    response.set_cookie(
        key="muletrace_session",
        value=raw_token,
        max_age=43200,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )

    return {
        "status": "success",
        "user": user_info,
        "session_token": raw_token,
    }


@app.get("/api/auth/me")
@app.get("/auth/me")
async def get_current_user_profile(user: dict[str, Any] = Depends(get_current_user)):
    return {
        "status": "success",
        "user": user,
    }


@app.post("/api/auth/logout")
@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    cookie_token = request.cookies.get("muletrace_session")
    auth_service = get_active_auth_service()

    if cookie_token:
        try:
            auth_service.logout(cookie_token)
        except Exception:
            pass

    response.delete_cookie(key="muletrace_session", path="/")
    return {"status": "success", "message": "Logged out successfully"}


# ---------- Protected Investigation Endpoints ----------
@app.get("/cases", response_model=CasesResponse)
@app.get("/api/cases", response_model=CasesResponse)
def get_cases(current_user: dict[str, Any] = Depends(require_investigation_role)):
    case_accounts = load_case_accounts()
    if case_accounts.empty:
        return CasesResponse(cases=[], receivedCount=0, request_id=_request_id())
    case_ids = case_accounts["case_id"].unique().tolist()
    cases: List[CaseItem] = []
    for cid in case_ids:
        accounts = case_accounts[case_accounts["case_id"] == cid]["account_id"].tolist()
        target = accounts[0] if accounts else None
        tx = None
        if target:
            df = load_transactions()
            matches = df[df["target_account"] == target]
            if not matches.empty:
                tx = matches.iloc[0]
        case_obj = CaseItem(
            caseId=cid,
            source=tx["source_account"] if tx is not None else None,
            target=target,
            amount=float(tx["amount"]) if tx is not None else None,
            time=tx["timestamp"].isoformat() if tx is not None else None,
            transactionId=tx["transaction_id"] if tx is not None else None,
        )
        cases.append(case_obj)
    return CasesResponse(
        cases=cases,
        source="api",
        receivedCount=len(case_ids),
        limited=False,
        request_id=_request_id(),
    )


@app.get("/cases/{case_id}")
@app.get("/api/cases/{case_id}")
def get_case_detail(case_id: str, current_user: dict[str, Any] = Depends(require_investigation_role)):
    case_accounts = load_case_accounts()
    row = case_accounts[case_accounts["case_id"] == case_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="Case not found")
    account_id = row.iloc[0]["account_id"]
    profile = get_account_profile(account_id)
    return JSONResponse(content={"case": profile, "request_id": _request_id()})


@app.post("/trace", response_model=TraceResponse)
@app.post("/api/trace", response_model=TraceResponse)
def post_trace(req: TraceRequest, current_user: dict[str, Any] = Depends(require_investigation_role)):
    try:
        result = trace_money(req.source_account, req.target_account, req.max_hops)
        return TraceResponse(**result, request_id=_request_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/score", response_model=ScoreResponse)
@app.get("/api/score", response_model=ScoreResponse)
def get_score(
    case_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    current_user: dict[str, Any] = Depends(require_investigation_role),
):
    if not case_id and not account_id:
        raise HTTPException(status_code=400, detail="Provide case_id or account_id")
    try:
        result = score_investigation(case_id=case_id, account_id=account_id)
        return ScoreResponse(**result, request_id=_request_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/evidence", response_model=EvidenceResponse)
@app.get("/api/evidence", response_model=EvidenceResponse)
def get_evidence_endpoint(
    transaction_ids: str = Query(...),
    current_user: dict[str, Any] = Depends(require_investigation_role),
):
    ids = [tid.strip() for tid in transaction_ids.split(",") if tid.strip()]
    result = get_evidence(ids)
    return EvidenceResponse(**result, request_id=_request_id())


# ---------- Protected Admin Portal Endpoints ----------
@app.get("/api/admin/users")
def admin_list_users(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pagination_token: Optional[str] = Query(None),
    current_user: dict[str, Any] = Depends(require_admin_role),
):
    admin_service = get_active_admin_service()
    try:
        if hasattr(admin_service, "list_users"):
            import inspect
            sig = inspect.signature(admin_service.list_users)
            if "pagination_token" in sig.parameters:
                data = admin_service.list_users(limit=limit, offset=offset, pagination_token=pagination_token)
            else:
                data = admin_service.list_users(limit=limit, offset=offset)
        else:
            data = admin_service.list_users(limit=limit, offset=offset)
        return {"status": "success", **data}
    except AdminServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list users: {exc}")


@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def admin_create_user(
    req: CreateUserRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(require_admin_role),
):
    admin_service = get_active_admin_service()
    admin_id = current_user.get("user_id", "admin")
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        user_record = admin_service.create_bank_officer(
            admin_user_id=admin_id,
            email=req.email,
            password=req.password,
            display_name=req.display_name or req.email.split("@")[0],
            client_ip=client_ip,
        )
        return {"status": "success", "user": user_record}
    except AdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except AdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AdminForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except AdminServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.patch("/api/admin/users/{user_id}/status")
def admin_update_user_status(
    user_id: str,
    req: StatusUpdateRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(require_admin_role),
):
    admin_service = get_active_admin_service()
    admin_id = current_user.get("user_id", "admin")
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        res = admin_service.set_user_status(
            admin_user_id=admin_id,
            target_user_id=user_id,
            is_active=req.is_active,
            client_ip=client_ip,
        )
        return {"status": "success", "user": res}
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AdminForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except AdminServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    req: PasswordResetRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(require_admin_role),
):
    admin_service = get_active_admin_service()
    admin_id = current_user.get("user_id", "admin")
    client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        res = admin_service.reset_password(
            admin_user_id=admin_id,
            target_user_id=user_id,
            new_password=req.new_password,
            client_ip=client_ip,
        )
        return {"status": "success", **res}
    except AdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AdminForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except AdminServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/admin/audit-logs")
def admin_list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict[str, Any] = Depends(require_admin_role),
):
    admin_service = get_active_admin_service()
    try:
        data = admin_service.list_audit_logs(limit=limit, offset=offset)
        return {"status": "success", **data}
    except AdminServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list audit logs: {exc}")


# ---------- Simulation Endpoints ----------
@app.post("/api/simulation/run")
@app.post("/simulation/run")
def run_simulation(
    payload: dict[str, Any] = Body(default={}),
    current_user: dict[str, Any] = Depends(require_investigation_role),
):
    """Execute a single mixed transaction simulation batch."""
    try:
        from datetime import datetime
        from app.backend.simulation.engine import SimulationEngine

        seed_val = payload.get("seed") if isinstance(payload, dict) else None
        if seed_val is not None:
            try:
                seed_val = int(seed_val)
            except (ValueError, TypeError):
                seed_val = None

        base_time_raw = (payload.get("base_timestamp") or payload.get("base_time")) if isinstance(payload, dict) else None
        base_time_dt = None
        if base_time_raw and isinstance(base_time_raw, str):
            try:
                base_time_dt = datetime.fromisoformat(base_time_raw.replace("Z", "+00:00"))
            except Exception:
                base_time_dt = None

        engine_inst = SimulationEngine()
        sim_res = engine_inst.run_simulation(seed=seed_val, base_time=base_time_dt)
        return {"status": "success", "data": sim_res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {exc}")


@app.get("/api/simulation/status/{run_id}")
@app.get("/simulation/status/{run_id}")
def get_simulation_status(
    run_id: str,
    current_user: dict[str, Any] = Depends(require_investigation_role),
):
    """Retrieve execution confirmation for a simulation run ID."""
    from app.backend.simulation.engine import SimulationEngine
    status_data = SimulationEngine.get_run_status(run_id)
    if not status_data:
        raise HTTPException(status_code=404, detail=f"Simulation run '{run_id}' not found")
    return {"status": "success", "data": status_data}
