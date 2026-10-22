"""Idempotent importer: data/*.csv (and optionally alerts.json) -> PostgreSQL.

Never updates or deletes existing rows. Re-running inserts nothing new.
Rows whose primary key already exists with *different* values are reported as
conflicts and left untouched for a human to review.

Usage (DATABASE_URL must be set, schema migrated with `alembic upgrade head`):
    python -m db.seed --dry-run          # show what would be inserted
    python -m db.seed                    # import CSVs
    python -m db.seed --with-alerts      # also import data/alerts.json
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
import argparse
import json

import pandas as pd

from db.config import DATABASE_URL_ENV, PROJECT_ROOT, get_database_url, redact_url

DATA_DIR = PROJECT_ROOT / "data"
TRUE_VALUES = {"true", "1", "yes", "y"}
TX_COMPARE_FIELDS = ("timestamp", "source_account", "target_account", "amount",
                     "scenario", "is_suspicious")


@dataclass
class SeedPlan:
    accounts: list[str] = field(default_factory=list)
    cases: list[str] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    case_accounts: list[tuple[str, str]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def read_transactions(path: Path, plan: SeedPlan) -> None:
    """Validate rows with the same rules engine.load_transactions() applies."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {"transaction_id", "timestamp", "source_account", "target_account", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")

    seen: dict[str, dict[str, Any]] = {}
    for line_no, raw in enumerate(df.to_dict(orient="records"), start=2):
        tx_id = _clean(raw.get("transaction_id"))
        source = _clean(raw.get("source_account"))
        target = _clean(raw.get("target_account"))
        timestamp = pd.to_datetime(_clean(raw.get("timestamp")) or None, errors="coerce")
        try:
            amount = Decimal(_clean(raw.get("amount")))
        except InvalidOperation:
            amount = None
        if not tx_id or not source or not target or pd.isna(timestamp) or amount is None:
            plan.skipped.append(f"{path.name}:{line_no} invalid/missing required value")
            continue
        if amount.as_tuple().exponent < -2 or amount < 0:
            plan.skipped.append(f"{path.name}:{line_no} amount {amount} not NUMERIC(18,2) >= 0")
            continue
        row = {
            "transaction_id": tx_id,
            "timestamp": timestamp.to_pydatetime(),
            "source_account": source,
            "target_account": target,
            "amount": amount,
            "scenario": _clean(raw.get("scenario")) or "unknown",
            "is_suspicious": _clean(raw.get("is_suspicious")).lower() in TRUE_VALUES,
        }
        if tx_id in seen:
            if seen[tx_id] != row:
                plan.skipped.append(f"{path.name}:{line_no} duplicate {tx_id} with different values")
            continue
        seen[tx_id] = row
    plan.transactions = list(seen.values())


def read_case_accounts(path: Path, plan: SeedPlan) -> None:
    if not path.exists():
        return
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = {"case_id", "account_id"} - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    pairs: dict[tuple[str, str], None] = {}
    for raw in df.to_dict(orient="records"):
        case_id, account_id = _clean(raw.get("case_id")), _clean(raw.get("account_id"))
        if case_id and account_id:
            pairs[(case_id, account_id)] = None
    plan.case_accounts = list(pairs)


def read_account_ids(path: Path) -> list[str]:
    """Only account_id is imported; accounts.csv aggregates are stale/derived."""
    if not path.exists():
        return []
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "account_id" not in df.columns:
        raise ValueError(f"{path.name} is missing column: account_id")
    return [a for a in (_clean(v) for v in df["account_id"]) if a]


def read_alerts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError(f"{path.name} must contain a JSON list of alert objects")
    for item in data:
        if not str(item.get("alert_id", "")).startswith("ALT-"):
            raise ValueError(f"{path.name} contains an alert without a valid alert_id")
    return data


def build_plan(data_dir: Path = DATA_DIR, with_alerts: bool = False) -> SeedPlan:
    plan = SeedPlan()
    read_transactions(data_dir / "transactions.csv", plan)
    read_case_accounts(data_dir / "case_accounts.csv", plan)
    accounts: dict[str, None] = {}
    for tx in plan.transactions:
        accounts[tx["source_account"]] = None
        accounts[tx["target_account"]] = None
    for _, account_id in plan.case_accounts:
        accounts[account_id] = None
    for account_id in read_account_ids(data_dir / "accounts.csv"):
        accounts[account_id] = None
    plan.accounts = list(accounts)
    plan.cases = list(dict.fromkeys(case_id for case_id, _ in plan.case_accounts))
    if with_alerts:
        plan.alerts = read_alerts(data_dir / "alerts.json")
    return plan


def apply_plan(plan: SeedPlan, engine, dry_run: bool = False) -> dict[str, Any]:
    """Insert only rows whose keys are not present yet. Returns a report."""
    from sqlalchemy import select, tuple_
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from db.models import Account, Alert, Case, CaseAccount, Transaction
    from db.repositories import AlertRepository
    from db.session import session_scope

    report: dict[str, Any] = {"dry_run": dry_run, "skipped_rows": plan.skipped, "conflicts": []}

    with session_scope(engine) as session:
        existing = set(session.scalars(
            select(Account.account_id).where(Account.account_id.in_(plan.accounts))
        )) if plan.accounts else set()
        new_accounts = [a for a in plan.accounts if a not in existing]

        existing = set(session.scalars(
            select(Case.case_id).where(Case.case_id.in_(plan.cases))
        )) if plan.cases else set()
        new_cases = [c for c in plan.cases if c not in existing]

        tx_ids = [tx["transaction_id"] for tx in plan.transactions]
        existing_tx = {
            row.transaction_id: row
            for row in session.scalars(
                select(Transaction).where(Transaction.transaction_id.in_(tx_ids))
            )
        } if tx_ids else {}
        new_tx = []
        for tx in plan.transactions:
            current = existing_tx.get(tx["transaction_id"])
            if current is None:
                new_tx.append(tx)
                continue
            diffs = [f for f in TX_COMPARE_FIELDS if getattr(current, f) != tx[f]]
            if diffs:
                report["conflicts"].append(
                    f"transaction {tx['transaction_id']} differs in {diffs}; existing row kept"
                )

        existing = set(session.execute(
            select(CaseAccount.case_id, CaseAccount.account_id).where(
                tuple_(CaseAccount.case_id, CaseAccount.account_id).in_(plan.case_accounts)
            )
        ).tuples()) if plan.case_accounts else set()
        new_links = [p for p in plan.case_accounts if p not in existing]

        alert_ids = [a["alert_id"] for a in plan.alerts]
        existing = set(session.scalars(
            select(Alert.alert_id).where(Alert.alert_id.in_(alert_ids))
        )) if alert_ids else set()
        new_alerts = [a for a in plan.alerts if a["alert_id"] not in existing]

        if not dry_run:
            if new_accounts:
                session.execute(pg_insert(Account.__table__).on_conflict_do_nothing(),
                                [{"account_id": a} for a in new_accounts])
            if new_cases:
                session.execute(pg_insert(Case.__table__).on_conflict_do_nothing(),
                                [{"case_id": c} for c in new_cases])
            if new_tx:
                session.execute(pg_insert(Transaction.__table__).on_conflict_do_nothing(), new_tx)
            if new_links:
                session.execute(pg_insert(CaseAccount.__table__).on_conflict_do_nothing(),
                                [{"case_id": c, "account_id": a} for c, a in new_links])

    inserted_alerts = new_alerts
    if new_alerts and not dry_run:
        inserted_alerts = AlertRepository(engine).insert_many(new_alerts)

    verb = "would_insert" if dry_run else "inserted"
    report[verb] = {
        "accounts": len(new_accounts),
        "cases": len(new_cases),
        "transactions": len(new_tx),
        "case_accounts": len(new_links),
        "alerts": len(inserted_alerts),
    }
    report["source_rows"] = {
        "accounts": len(plan.accounts),
        "cases": len(plan.cases),
        "transactions": len(plan.transactions),
        "case_accounts": len(plan.case_accounts),
        "alerts": len(plan.alerts),
    }
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import MuleTrace CSV/JSON data into PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    parser.add_argument("--with-alerts", action="store_true", help="Also import data/alerts.json")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--url-env", default=DATABASE_URL_ENV,
                        help="Environment variable holding the database URL")
    args = parser.parse_args(argv)

    from db.session import get_engine

    url = get_database_url(args.url_env)
    print(f"Target database: {redact_url(url)}")
    plan = build_plan(args.data_dir, with_alerts=args.with_alerts)
    report = apply_plan(plan, get_engine(url), dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
