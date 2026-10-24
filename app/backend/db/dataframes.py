"""Convert database rows into DataFrames shaped exactly like ``pd.read_csv`` output.

This matters for output parity: risk-rule ``reason`` strings embed the amount,
and ``alert_id`` hashes the reason for findings without transaction IDs.
``read_csv`` yields ``int64`` for whole-number amounts (``12000``), whereas a
NUMERIC column yields ``Decimal('12000.00')`` -> ``12000.0``. That difference
would silently change alert IDs and create duplicate alerts.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping
import math

import pandas as pd
from sqlalchemy.engine import RowMapping

TRANSACTION_COLUMNS = [
    "transaction_id",
    "timestamp",
    "source_account",
    "target_account",
    "amount",
    "scenario",
    "is_suspicious",
]
CASE_ACCOUNT_COLUMNS = ["case_id", "account_id"]


def _to_float(value: Any) -> float:
    if value is None:
        return math.nan
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def normalize_amounts(values: Iterable[Any]) -> pd.Series:
    """Mimic read_csv dtype inference: int64 if every amount is whole, else float64."""
    series = pd.Series([_to_float(v) for v in values], dtype="float64")
    if len(series) and series.notna().all() and (series % 1 == 0).all():
        return series.astype("int64")
    return series


def transactions_frame(rows: Iterable[Mapping[str, Any] | RowMapping]) -> pd.DataFrame:
    """Build the raw transaction frame that engine.load_transactions() normalizes."""
    records = [dict(row) for row in rows]
    df = pd.DataFrame(records, columns=TRANSACTION_COLUMNS)
    df["amount"] = normalize_amounts(df["amount"].tolist())
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def case_accounts_frame(rows: Iterable[Mapping[str, Any] | RowMapping]) -> pd.DataFrame:
    """Build the case/account frame with the same string dtype read_csv uses."""
    records = [dict(row) for row in rows]
    return pd.DataFrame(records, columns=CASE_ACCOUNT_COLUMNS).astype("string")
