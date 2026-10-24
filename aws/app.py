import uuid
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Any

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

app = FastAPI(title="MuleTrace AI Local Backend", version="0.1.0")

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

# ---------- Endpoints ----------
@app.get("/health", response_model=HealthResponse)
def get_health():
    data = health_check()
    return HealthResponse(**data, request_id=_request_id())

@app.get("/cases", response_model=CasesResponse)
def get_cases():
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
def get_case_detail(case_id: str):
    case_accounts = load_case_accounts()
    row = case_accounts[case_accounts["case_id"] == case_id]
    if row.empty:
        raise HTTPException(status_code=404, detail="Case not found")
    account_id = row.iloc[0]["account_id"]
    profile = get_account_profile(account_id)
    return JSONResponse(content={"case": profile, "request_id": _request_id()})

@app.post("/trace", response_model=TraceResponse)
def post_trace(req: TraceRequest):
    try:
        result = trace_money(req.source_account, req.target_account, req.max_hops)
        return TraceResponse(**result, request_id=_request_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/score", response_model=ScoreResponse)
def get_score(case_id: Optional[str] = Query(None), account_id: Optional[str] = Query(None)):
    if not case_id and not account_id:
        raise HTTPException(status_code=400, detail="Provide case_id or account_id")
    try:
        result = score_investigation(case_id=case_id, account_id=account_id)
        return ScoreResponse(**result, request_id=_request_id())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/evidence", response_model=EvidenceResponse)
def get_evidence_endpoint(transaction_ids: str = Query(...)):
    ids = [tid.strip() for tid in transaction_ids.split(",") if tid.strip()]
    result = get_evidence(ids)
    return EvidenceResponse(**result, request_id=_request_id())
