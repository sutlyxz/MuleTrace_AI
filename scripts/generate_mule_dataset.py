"""Realistic AML Mule Account Dataset Generator for MuleTrace AI.

Generates transactions.csv, case_accounts.csv, accounts.csv, and triggers
alert generation with realistic financial crime typologies:
1. Smurfing / Fan-in (Multiple incoming transfers below regulatory reporting thresholds)
2. Rapid Outgoing / Pass-through (Funds aggregated and forwarded within minutes)
3. High-Value Transfers (Substantial fund movements)
4. Cross-Case Overlap (Mule accounts operating across distinct investigation cases)
5. Background Baseline Traffic (Normal peer-to-peer transfers)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend.services.alert_service import scan_risk_alerts


def build_dataset() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Baseline benchmark transactions (keeps unit tests 100% compatible)
    base_tx = [
        {"transaction_id": "TX0001", "timestamp": "2026-10-01 08:07:00", "source_account": "N004", "target_account": "N001", "amount": 2353, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0002", "timestamp": "2026-10-01 08:52:00", "source_account": "N008", "target_account": "N005", "amount": 939, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0003", "timestamp": "2026-10-01 09:11:00", "source_account": "N003", "target_account": "N019", "amount": 3556, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0004", "timestamp": "2026-10-01 09:52:00", "source_account": "N001", "target_account": "N003", "amount": 1891, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0005", "timestamp": "2026-10-01 10:15:00", "source_account": "N007", "target_account": "N006", "amount": 2096, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0006", "timestamp": "2026-10-01 10:48:00", "source_account": "N011", "target_account": "N008", "amount": 4189, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0007", "timestamp": "2026-10-01 11:22:00", "source_account": "N013", "target_account": "N009", "amount": 1284, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0008", "timestamp": "2026-10-01 12:05:00", "source_account": "N014", "target_account": "N003", "amount": 2376, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0009", "timestamp": "2026-10-01 12:40:00", "source_account": "N018", "target_account": "N004", "amount": 3887, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0010", "timestamp": "2026-10-01 13:15:00", "source_account": "N008", "target_account": "N010", "amount": 2007, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0011", "timestamp": "2026-10-01 13:58:00", "source_account": "N009", "target_account": "N006", "amount": 1828, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0012", "timestamp": "2026-10-01 14:32:00", "source_account": "N005", "target_account": "N018", "amount": 3558, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0013", "timestamp": "2026-10-01 15:05:00", "source_account": "N010", "target_account": "N007", "amount": 1450, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0014", "timestamp": "2026-10-01 15:40:00", "source_account": "N018", "target_account": "N011", "amount": 2684, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0015", "timestamp": "2026-10-01 16:15:00", "source_account": "N019", "target_account": "N014", "amount": 1950, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0016", "timestamp": "2026-10-01 16:50:00", "source_account": "N013", "target_account": "N018", "amount": 2100, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0017", "timestamp": "2026-10-01 17:25:00", "source_account": "N006", "target_account": "N013", "amount": 2105, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0018", "timestamp": "2026-10-01 18:00:00", "source_account": "N018", "target_account": "N008", "amount": 2252, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0019", "timestamp": "2026-10-01 18:45:00", "source_account": "N004", "target_account": "N009", "amount": 1850, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0020", "timestamp": "2026-10-01 19:20:00", "source_account": "N012", "target_account": "N003", "amount": 1650, "scenario": "normal", "is_suspicious": False},
    ]

    # CASE001 (Smurfing Fan-in to B782 + Rapid Outflow to C991 and D201)
    case1_tx = [
        {"transaction_id": "TX0030", "timestamp": "2026-10-02 00:40:00", "source_account": "A001", "target_account": "B782", "amount": 14081, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0031", "timestamp": "2026-10-02 00:43:00", "source_account": "A014", "target_account": "B782", "amount": 24608, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0032", "timestamp": "2026-10-02 00:46:00", "source_account": "A027", "target_account": "B782", "amount": 24504, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0033", "timestamp": "2026-10-02 00:49:00", "source_account": "A035", "target_account": "B782", "amount": 27337, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0034", "timestamp": "2026-10-02 00:52:00", "source_account": "A042", "target_account": "B782", "amount": 29338, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0035", "timestamp": "2026-10-02 00:55:00", "source_account": "A056", "target_account": "B782", "amount": 20238, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0036", "timestamp": "2026-10-02 00:58:00", "source_account": "A061", "target_account": "B782", "amount": 12376, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0037", "timestamp": "2026-10-02 01:01:00", "source_account": "A073", "target_account": "B782", "amount": 15753, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0038", "timestamp": "2026-10-02 01:04:00", "source_account": "A088", "target_account": "B782", "amount": 29595, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0039", "timestamp": "2026-10-02 01:07:00", "source_account": "A095", "target_account": "B782", "amount": 20743, "scenario": "multiple_incoming", "is_suspicious": True},
        {"transaction_id": "TX0041", "timestamp": "2026-10-02 01:20:00", "source_account": "B782", "target_account": "C991", "amount": 90000, "scenario": "rapid_outgoing", "is_suspicious": True},
        {"transaction_id": "TX0042", "timestamp": "2026-10-02 01:25:00", "source_account": "B782", "target_account": "D201", "amount": 65000, "scenario": "rapid_outgoing", "is_suspicious": True},
        {"transaction_id": "TX0045", "timestamp": "2026-10-02 04:00:00", "source_account": "A001", "target_account": "B782", "amount": 180000, "scenario": "high_value_demo", "is_suspicious": True},
    ]

    # Downstream Layering from C991 and D201 to final cashout E450
    layering_tx = [
        {"transaction_id": "TX0043", "timestamp": "2026-10-02 01:40:00", "source_account": "C991", "target_account": "E450", "amount": 40000, "scenario": "layering", "is_suspicious": True},
        {"transaction_id": "TX0044", "timestamp": "2026-10-02 01:45:00", "source_account": "D201", "target_account": "E450", "amount": 25000, "scenario": "layering", "is_suspicious": True},
    ]

    # Additional normal transactions to match original 52 rows
    filler_tx = [
        {"transaction_id": "TX0021", "timestamp": "2026-10-01 20:05:00", "source_account": "N015", "target_account": "N001", "amount": 2800, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0022", "timestamp": "2026-10-01 20:40:00", "source_account": "N016", "target_account": "N002", "amount": 485, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0023", "timestamp": "2026-10-01 21:15:00", "source_account": "N017", "target_account": "N006", "amount": 2757, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0024", "timestamp": "2026-10-01 21:50:00", "source_account": "N020", "target_account": "N009", "amount": 455, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0025", "timestamp": "2026-10-01 22:25:00", "source_account": "N015", "target_account": "N014", "amount": 1780, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0026", "timestamp": "2026-10-01 23:00:00", "source_account": "N012", "target_account": "N007", "amount": 2715, "scenario": "normal", "is_suspicious": False},
        {"transaction_id": "TX0027", "timestamp": "2026-10-01 23:35:00", "source_account": "N017", "target_account": "N013", "amount": 1940, "scenario": "normal", "is_suspicious": False},
    ]

    # Combine all
    all_records = base_tx + case1_tx + layering_tx + filler_tx
    df_tx = pd.DataFrame(all_records)

    # Build case_accounts dataframe
    case_accounts = pd.DataFrame([
        {"case_id": "CASE001", "account_id": "B782"},
        {"case_id": "CASE001", "account_id": "A001"},
        {"case_id": "CASE002", "account_id": "B782"},
        {"case_id": "CASE002", "account_id": "N004"},
    ])

    # Compute accounts summary dataframe
    incoming = df_tx.groupby("target_account").agg(
        incoming_count=("transaction_id", "count"),
        total_incoming=("amount", "sum")
    ).reset_index().rename(columns={"target_account": "account_id"})

    outgoing = df_tx.groupby("source_account").agg(
        outgoing_count=("transaction_id", "count"),
        total_outgoing=("amount", "sum")
    ).reset_index().rename(columns={"source_account": "account_id"})

    all_accounts = sorted(set(df_tx["source_account"]).union(set(df_tx["target_account"])))
    accounts_df = pd.DataFrame({"account_id": all_accounts})
    accounts_df = accounts_df.merge(incoming, on="account_id", how="left").fillna(0)
    accounts_df = accounts_df.merge(outgoing, on="account_id", how="left").fillna(0)

    for col in ("incoming_count", "outgoing_count", "total_incoming", "total_outgoing"):
        accounts_df[col] = accounts_df[col].astype(int)

    return df_tx, case_accounts, accounts_df


def save_dataset() -> None:
    data_dir = PROJECT_ROOT / "app" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    df_tx, df_ca, df_acc = build_dataset()

    tx_path = data_dir / "transactions.csv"
    ca_path = data_dir / "case_accounts.csv"
    acc_path = data_dir / "accounts.csv"

    df_tx.to_csv(tx_path, index=False, encoding="utf-8")
    df_ca.to_csv(ca_path, index=False, encoding="utf-8")
    df_acc.to_csv(acc_path, index=False, encoding="utf-8")

    print(f"[+] Saved {len(df_tx)} transactions to: {tx_path}")
    print(f"[+] Saved {len(df_ca)} case-account links to: {ca_path}")
    print(f"[+] Saved {len(df_acc)} account profiles to: {acc_path}")

    # Trigger alert scan
    print("[*] Running auto-scanner to generate risk findings and alerts.json...")
    alert_summary = scan_risk_alerts()
    print(f"[+] Total alerts active: {alert_summary.get('total_alert_count')}")
    print(f"[+] New alerts generated: {alert_summary.get('new_alert_count')}")


if __name__ == "__main__":
    save_dataset()
