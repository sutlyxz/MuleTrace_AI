"""MuleTrace AI investigation engine.

This module exposes small, JSON-friendly functions for the AI/Bedrock Tool Use
layer. It uses the project's existing investigation rules and tracing code.
All results are investigation leads, not proof of wrongdoing.

Expected project layout:
    engine.py
    data/transactions.csv
    data/case_accounts.csv
    investigation/risk_rules.py
    investigation/tracing.py

Data backend (env MULETRACE_DATA_BACKEND):
    csv       (default) read the CSV files above
    postgres  read the same data from PostgreSQL / Amazon RDS via DATABASE_URL
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import math

import pandas as pd

from .core.risk_rules import (
    find_high_value_transfers,
    find_multiple_incoming,
    find_rapid_outgoing,
    find_case_overlap,
)
from .core.tracing import find_paths
from app.backend.db.config import (
    data_backend,
    dataset_name,
    get_transactions_path,
    get_accounts_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSACTIONS_FILE = PROJECT_ROOT / "data" / "transactions.csv"
CASE_ACCOUNTS_FILE = PROJECT_ROOT / "data" / "case_accounts.csv"
REQUIRED_TRANSACTION_COLUMNS = {
    "transaction_id", "timestamp", "source_account", "target_account", "amount"
}


def _clean_id(value: Any, field_name: str = "account_id") -> str:
    """Validate and normalize an account/case/transaction identifier."""
    if value is None:
        raise ValueError(f"{field_name} is required")
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"nan", "none", "null"}:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values to ordinary JSON-serializable Python values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return [_json_safe(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return _json_safe(value.to_dict())
    if isinstance(value, (pd.Timestamp,)):
        return None if pd.isna(value) else value.isoformat(sep=" ")
    # numpy scalar types expose item(); this avoids importing numpy directly.
    if hasattr(value, "item") and callable(value.item):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value) if not isinstance(value, (str, bytes, list, tuple, dict, set)) else False:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def load_transactions() -> pd.DataFrame:
    """Load and validate transaction data (CSV or PostgreSQL backend)."""
    if data_backend() == "postgres":
        from app.backend.db.repositories import TransactionRepository  # lazy: optional dependency
        df = TransactionRepository().as_dataframe()
    else:
        tx_file = get_transactions_path()
        if not tx_file.exists():
            raise FileNotFoundError(f"Transaction data not found: {tx_file}")
        df = pd.read_csv(tx_file)
    missing = REQUIRED_TRANSACTION_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"transactions file is missing columns: {sorted(missing)}")

    df = df.copy()
    for column in ("transaction_id", "source_account", "target_account"):
        df[column] = df[column].astype("string").str.strip()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["transaction_id", "timestamp", "source_account", "target_account", "amount"])
    df = df[
        (df["transaction_id"] != "")
        & (df["source_account"] != "")
        & (df["target_account"] != "")
    ].copy()
    df["transaction_id"] = df["transaction_id"].astype(str)
    df["source_account"] = df["source_account"].astype(str)
    df["target_account"] = df["target_account"].astype(str)
    if "scenario" not in df.columns:
        df["scenario"] = "unknown"
    if "is_suspicious" not in df.columns:
        df["is_suspicious"] = False
    df["is_suspicious"] = (
        df["is_suspicious"].astype(str).str.strip().str.lower()
        .isin({"true", "1", "yes", "y"})
    )
    return df.sort_values(["timestamp", "transaction_id"]).reset_index(drop=True)


def load_accounts() -> pd.DataFrame:
    """Load and validate account summary data from the active accounts CSV."""
    accounts_file = get_accounts_path()
    if not accounts_file.exists():
        return pd.DataFrame(columns=["account_id", "incoming_count", "outgoing_count", "total_incoming", "total_outgoing"])
    df = pd.read_csv(accounts_file)
    required = {"account_id", "incoming_count", "outgoing_count", "total_incoming", "total_outgoing"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"accounts file is missing columns: {sorted(missing)}")
    df = df.copy()
    df["account_id"] = df["account_id"].astype(str).str.strip()
    for col in ("incoming_count", "outgoing_count", "total_incoming", "total_outgoing"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("account_id").reset_index(drop=True)


def load_case_accounts() -> pd.DataFrame:
    """Load the synthetic case/account links; return an empty frame if absent."""
    if data_backend() == "postgres":
        from app.backend.db.repositories import CaseRepository  # lazy: optional dependency
        df = CaseRepository().as_dataframe()
    else:
        if not CASE_ACCOUNTS_FILE.exists():
            return pd.DataFrame(columns=["case_id", "account_id"])
        df = pd.read_csv(CASE_ACCOUNTS_FILE, dtype="string")
    required = {"case_id", "account_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"case_accounts.csv is missing columns: {sorted(missing)}")
    df = df[["case_id", "account_id"]].dropna().copy()
    for column in ("case_id", "account_id"):
        df[column] = df[column].astype(str).str.strip()
    df = df[(df["case_id"] != "") & (df["account_id"] != "")]
    return df.drop_duplicates().reset_index(drop=True)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return dataframe rows as JSON-friendly dictionaries."""
    return _json_safe(df.to_dict(orient="records"))


def _transaction_ids(value: Any) -> list[str]:
    """Normalize common risk-rule transaction_ids formats into a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return []
        # Current rule outputs store IDs comma-separated in a CSV-like string.
        items = text.split(",")
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def get_evidence(transaction_ids: str | Iterable[str]) -> dict[str, Any]:
    """Fetch exact transaction rows for an evidence chain by Transaction ID."""
    if isinstance(transaction_ids, str):
        requested = _transaction_ids(transaction_ids)
    else:
        requested = _transaction_ids(list(transaction_ids))
    if not requested:
        return {"count": 0, "transactions": [], "missing_transaction_ids": []}

    df = load_transactions()
    matched = df[df["transaction_id"].isin(requested)].copy()
    matched = matched.sort_values(["timestamp", "transaction_id"])
    found = set(matched["transaction_id"].astype(str))
    return {
        "count": len(matched),
        "transactions": _records(matched),
        "missing_transaction_ids": [tx_id for tx_id in requested if tx_id not in found],
    }


def _all_risk_findings() -> pd.DataFrame:
    """Run primary transaction risk rules (multiple_incoming, rapid_outgoing, high_value_transfer)."""
    transactions = load_transactions()
    frames: list[pd.DataFrame] = []

    for detector in (find_multiple_incoming, find_rapid_outgoing, find_high_value_transfers):
        result = detector(transactions.copy())
        if isinstance(result, pd.DataFrame) and not result.empty:
            frames.append(result.copy())

    if not frames:
        return pd.DataFrame(columns=["account_id", "rule", "evidence", "transaction_ids", "reason"])
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if "account_id" not in combined.columns:
        combined["account_id"] = None
    if "rule" not in combined.columns:
        combined["rule"] = "unknown_rule"
    if "transaction_ids" not in combined.columns:
        combined["transaction_ids"] = ""
    return combined


def detect_risk(account_id: str | None = None) -> dict[str, Any]:
    """Run transaction risk rules (multiple_incoming, rapid_outgoing, high_value_transfer);
    optionally filter by account.
    """
    findings = _all_risk_findings()
    if account_id is not None:
        account_id = _clean_id(account_id)
        findings = findings[findings["account_id"].astype(str) == account_id]
    results = _records(findings)
    return {
        "count": len(results),
        "findings": results,
        "disclaimer": "Risk indicators support triage; they are not proof of wrongdoing.",
    }


def get_account_profile(account_id: str) -> dict[str, Any]:
    """Summarize an account's observed transactions, counterparties, and findings."""
    account_id = _clean_id(account_id)
    df = load_transactions()
    incoming = df[df["target_account"] == account_id]
    outgoing = df[df["source_account"] == account_id]
    related = df[(df["source_account"] == account_id) | (df["target_account"] == account_id)]

    case_accounts = load_case_accounts()
    case_ids = []
    if not case_accounts.empty:
        case_ids = sorted(case_accounts.loc[case_accounts["account_id"] == account_id, "case_id"].unique().tolist())

    findings = detect_risk(account_id)["findings"]
    return {
        "account_id": account_id,
        "transaction_count": int(len(related)),
        "incoming_count": int(len(incoming)),
        "outgoing_count": int(len(outgoing)),
        "total_incoming": round(float(incoming["amount"].sum()), 2),
        "total_outgoing": round(float(outgoing["amount"].sum()), 2),
        "incoming_counterparties": sorted(incoming["source_account"].unique().tolist()),
        "outgoing_counterparties": sorted(outgoing["target_account"].unique().tolist()),
        "case_ids": case_ids,
        "risk_finding_count": len(findings),
        "risk_findings": findings,
        "evidence_transaction_ids": related["transaction_id"].astype(str).tolist(),
        "note": "Aggregates are calculated from the supplied synthetic transaction dataset, not verified bank balances.",
    }


def get_transaction_history(account_id: str, limit: int = 100) -> dict[str, Any]:
    """Return recent transactions where the account is source or target."""
    account_id = _clean_id(account_id)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 to 500")
    df = load_transactions()
    related = df[(df["source_account"] == account_id) | (df["target_account"] == account_id)]
    related = related.sort_values(["timestamp", "transaction_id"], ascending=[False, False]).head(limit)
    return {"account_id": account_id, "count": len(related), "transactions": _records(related)}


def expand_network(account_id: str, max_hops: int = 3) -> dict[str, Any]:
    """Expand incoming/outgoing account links breadth-first, preserving transaction evidence."""
    account_id = _clean_id(account_id)
    if isinstance(max_hops, bool) or not isinstance(max_hops, int) or not 1 <= max_hops <= 6:
        raise ValueError("max_hops must be an integer from 1 to 6")

    df = load_transactions()
    visited_depth = {account_id: 0}
    frontier = {account_id}
    edges_by_id: dict[str, dict[str, Any]] = {}

    for depth in range(1, max_hops + 1):
        if not frontier:
            break
        related = df[df["source_account"].isin(frontier) | df["target_account"].isin(frontier)]
        next_frontier: set[str] = set()
        for row in related.to_dict(orient="records"):
            tx_id = str(row["transaction_id"])
            edges_by_id[tx_id] = _json_safe(row)
            for neighbor in (str(row["source_account"]), str(row["target_account"])):
                if neighbor not in visited_depth:
                    visited_depth[neighbor] = depth
                    next_frontier.add(neighbor)
        frontier = next_frontier

    nodes = [
        {"account_id": account, "hops_from_start": depth}
        for account, depth in sorted(visited_depth.items(), key=lambda item: (item[1], item[0]))
    ]
    edges = sorted(edges_by_id.values(), key=lambda row: (str(row.get("timestamp", "")), str(row.get("transaction_id", ""))))
    return {
        "start_account": account_id,
        "max_hops": max_hops,
        "account_count": len(nodes),
        "transaction_count": len(edges),
        "accounts": nodes,
        "transactions": edges,
    }


def trace_money(source_account: str, target_account: str, max_hops: int = 4) -> dict[str, Any]:
    """Find time-ordered money paths using the project's existing tracing function."""
    source_account = _clean_id(source_account, "source_account")
    target_account = _clean_id(target_account, "target_account")
    if source_account == target_account:
        raise ValueError("source_account and target_account must be different")
    if isinstance(max_hops, bool) or not isinstance(max_hops, int) or not 1 <= max_hops <= 8:
        raise ValueError("max_hops must be an integer from 1 to 8")

    df = load_transactions()
    if source_account not in set(df["source_account"]) | set(df["target_account"]):
        return {"source_account": source_account, "target_account": target_account, "max_hops": max_hops, "path_count": 0, "paths": [], "evidence": [], "message": "Source account was not found in the transaction dataset."}
    if target_account not in set(df["source_account"]) | set(df["target_account"]):
        return {"source_account": source_account, "target_account": target_account, "max_hops": max_hops, "path_count": 0, "paths": [], "evidence": [], "message": "Target account was not found in the transaction dataset."}

    paths = find_paths(df, source_account, target_account, max_hops=max_hops)
    safe_paths = _json_safe(paths)
    # Extract transaction IDs when the existing tracing function returns row dictionaries.
    known_ids = set(df["transaction_id"].astype(str))
    discovered_ids: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key) == "transaction_id" and child is not None and str(child) in known_ids:
                    discovered_ids.append(str(child))
                else:
                    walk(child)
        elif isinstance(value, (list, tuple, set)):
            for child in value:
                walk(child)
        elif isinstance(value, str) and value in known_ids:
            discovered_ids.append(value)

    # Traverse the JSON-safe representation: tracing paths may contain pandas Series.
    walk(safe_paths)
    discovered_ids = list(dict.fromkeys(discovered_ids))
    evidence = get_evidence(discovered_ids)["transactions"] if discovered_ids else []
    if isinstance(paths, (list, tuple, pd.DataFrame)):
        path_count = len(paths)
    elif paths is None:
        path_count = 0
    else:
        path_count = 1
    return {
        "source_account": source_account,
        "target_account": target_account,
        "max_hops": max_hops,
        "path_count": path_count,
        "paths": safe_paths if safe_paths is not None else [],
        "evidence_transaction_ids": discovered_ids,
        "evidence": evidence,
        "message": "Paths are candidate transaction links; they do not prove that funds are the same money unless supported by further evidence.",
    }


def search_previous_cases(account_id: str) -> dict[str, Any]:
    """Find synthetic case records linked to an account."""
    account_id = _clean_id(account_id)
    cases = load_case_accounts()
    if cases.empty:
        return {"account_id": account_id, "case_count": 0, "case_ids": [], "matches": []}
    matches = cases[cases["account_id"] == account_id].sort_values("case_id")
    return {
        "account_id": account_id,
        "case_count": int(matches["case_id"].nunique()),
        "case_ids": matches["case_id"].drop_duplicates().tolist(),
        "matches": _records(matches),
    }


def find_cross_case_links(account_id: str | None = None) -> dict[str, Any]:
    """Return accounts appearing in multiple synthetic cases (R005)."""
    cases = load_case_accounts()
    if cases.empty:
        return {"count": 0, "links": [], "message": "No case-account links are available."}
    findings = find_case_overlap(cases)
    if account_id is not None:
        account_id = _clean_id(account_id)
        findings = findings[findings["account_id"].astype(str) == account_id]
    links = _records(findings)
    return {"count": len(links), "links": links}


def score_investigation(case_id: str | None = None, account_id: str | None = None) -> dict[str, Any]:
    """Calculate a transparent triage-priority score, not a probability of guilt.

    Weights are deliberately simple and capped at 100:
      multiple_incoming +35, rapid_outgoing +30, high_value_transfer +20,
      cross_case_overlap +25. Each rule type contributes at most once per scope.
    """
    if case_id is None and account_id is None:
        raise ValueError("Provide case_id or account_id")
    if case_id is not None:
        case_id = _clean_id(case_id, "case_id")
    if account_id is not None:
        account_id = _clean_id(account_id, "account_id")

    target_accounts: set[str] = set()
    if account_id is not None:
        target_accounts.add(account_id)
    if case_id is not None:
        cases = load_case_accounts()
        target_accounts.update(cases.loc[cases["case_id"] == case_id, "account_id"].astype(str).tolist())
        if not target_accounts:
            return {
                "case_id": case_id,
                "account_id": account_id,
                "score": 0,
                "priority": "Low",
                "reasons": ["No account links found for this case in case_accounts.csv."],
                "evidence_transaction_ids": [],
                "disclaimer": "This is a triage heuristic, not a probability or finding of wrongdoing.",
            }

    tx_findings = _all_risk_findings()
    if target_accounts:
        tx_findings = tx_findings[tx_findings["account_id"].astype(str).isin(target_accounts)]

    # Cross-case overlap is calculated separately from transaction-risk findings
    cases = load_case_accounts()
    has_cross_case = False
    cross_case_count = 0
    if not cases.empty:
        case_overlap = find_case_overlap(cases)
        if not case_overlap.empty:
            matched_overlap = case_overlap[case_overlap["account_id"].astype(str).isin(target_accounts)]
            cross_case_count = len(matched_overlap)
            has_cross_case = cross_case_count > 0

    weights = {
        "multiple_incoming": 35,
        "rapid_outgoing": 30,
        "high_value_transfer": 20,
        "cross_case_overlap": 25,
    }
    rule_names = set(tx_findings.get("rule", pd.Series(dtype=str)).dropna().astype(str))
    if has_cross_case:
        rule_names.add("cross_case_overlap")

    reasons = []
    score = 0
    for rule, points in weights.items():
        if rule in rule_names:
            score += points
            reasons.append(f"{rule}: +{points} triage points")
    score = min(score, 100)
    priority = "High" if score >= 70 else "Medium" if score >= 35 else "Low"

    tx_ids: list[str] = []
    for value in tx_findings.get("transaction_ids", pd.Series(dtype=object)).tolist():
        tx_ids.extend(_transaction_ids(value))
    tx_ids = list(dict.fromkeys(tx_ids))

    total_finding_count = int(len(tx_findings)) + cross_case_count

    return {
        "case_id": case_id,
        "account_id": account_id,
        "accounts_in_scope": sorted(target_accounts),
        "score": score,
        "priority": priority,
        "rule_types_matched": sorted(rule_names),
        "reasons": reasons or ["No configured risk rules matched this scope."],
        "finding_count": total_finding_count,
        "evidence_transaction_ids": tx_ids,
        "evidence": get_evidence(tx_ids)["transactions"] if tx_ids else [],
        "disclaimer": "This is a triage heuristic, not a probability or finding of wrongdoing. A human investigator must review the underlying evidence.",
    }


def summarize_case_with_ai(case_id: str, model_id: str | None = None) -> dict[str, Any]:
    """Generate an AI-assisted narrative report for an investigation case using AWS Bedrock."""
    from .aws.bedrock_service import analyze_case_with_bedrock

    return analyze_case_with_bedrock(case_id=case_id, model_id=model_id)


def summarize_account_with_ai(account_id: str, model_id: str | None = None) -> dict[str, Any]:
    """Generate an AI-assisted narrative report for an account using AWS Bedrock."""
    from .aws.bedrock_service import analyze_account_with_bedrock

    return analyze_account_with_bedrock(account_id=account_id, model_id=model_id)


def health_check() -> dict[str, Any]:
    """Quick check for data files/database and exposed tool functions."""
    backend = data_backend()
    current_dataset = dataset_name()
    tx_file = get_transactions_path()
    status = "ok" if (tx_file.exists() if backend == "csv" else True) else "missing_data"
    database: dict[str, Any] | None = None
    if backend == "postgres":
        try:
            from app.backend.db.repositories import TransactionRepository
            count = TransactionRepository().count()
            database = {"reachable": True, "transaction_count": count}
            status = "ok" if count > 0 else "missing_data"
        except Exception as exc:  # report, never raise, from a health probe
            database = {"reachable": False, "error": type(exc).__name__}
            status = "database_unavailable"
    result = {
        "status": status,
        "transactions_file_exists": tx_file.exists(),
        "case_accounts_file_exists": CASE_ACCOUNTS_FILE.exists(),
        "available_tools": [
            "get_account_profile", "get_transaction_history", "expand_network",
            "detect_risk", "trace_money", "get_evidence",
            "search_previous_cases", "find_cross_case_links", "score_investigation", "summarize_case_with_ai", "summarize_account_with_ai",
        ],
        "data_backend": backend,
        "dataset": current_dataset,
    }
    if database is not None:
        result["database"] = database
    return result


if __name__ == "__main__":
    print(health_check())
    tx_file = get_transactions_path()
    if data_backend() == "postgres" or tx_file.exists():
        print(f"Loaded transactions: {len(load_transactions())}")
        risk_summary = detect_risk()
        print(f"Risk findings: {risk_summary['count']}")
