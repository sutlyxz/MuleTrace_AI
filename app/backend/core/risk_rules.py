import pandas as pd
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parents[2] / 'data' / 'transactions.csv'


def load_transactions(csv_path=DATA_FILE):
    df = pd.read_csv(csv_path)

    required = {
        "transaction_id",
        "timestamp",
        "source_account",
        "target_account",
        "amount",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%d/%m/%Y %H:%M" , errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(
        subset=[
            "transaction_id",
            "timestamp",
            "source_account",
            "target_account",
            "amount",
        ]
    )

    return df



def find_multiple_incoming(
    df,
    min_senders=2,
    min_transactions=5,
    window_minutes=10,
):
    """Flag accounts receiving at least min_transactions from at least min_senders
    within a rolling window_minutes window (inclusive).
    """
    results = []
    columns = ["account_id", "rule", "evidence", "transaction_ids", "reason"]
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=columns)

    required = {"transaction_id", "timestamp", "source_account", "target_account"}
    if not required.issubset(df.columns):
        return pd.DataFrame(columns=columns)

    df_clean = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_clean["timestamp"]):
        df_clean["timestamp"] = pd.to_datetime(df_clean["timestamp"], errors="coerce")

    df_clean = df_clean.dropna(
        subset=["transaction_id", "timestamp", "source_account", "target_account"]
    )
    df_clean["transaction_id"] = df_clean["transaction_id"].astype(str).str.strip()
    df_clean["source_account"] = df_clean["source_account"].astype(str).str.strip()
    df_clean["target_account"] = df_clean["target_account"].astype(str).str.strip()
    df_clean = df_clean[
        (df_clean["transaction_id"] != "")
        & (df_clean["source_account"] != "")
        & (df_clean["target_account"] != "")
    ]

    df_clean = df_clean.sort_values(["timestamp", "transaction_id"]).reset_index(drop=True)
    window_delta = pd.Timedelta(minutes=window_minutes)

    for account, group in df_clean.groupby("target_account", sort=True):
        if len(group) < min_transactions:
            continue

        txs = group.sort_values(["timestamp", "transaction_id"]).reset_index(drop=True)
        n = len(txs)
        i = 0
        while i < n:
            start_time = txs.loc[i, "timestamp"]
            end_limit = start_time + window_delta

            j = i
            while j < n and txs.loc[j, "timestamp"] <= end_limit:
                j += 1

            window = txs.iloc[i:j]
            if len(window) >= min_transactions:
                distinct_senders = int(window["source_account"].nunique())
                if distinct_senders >= min_senders:
                    tx_ids = window["transaction_id"].tolist()
                    results.append({
                        "account_id": account,
                        "rule": "multiple_incoming",
                        "evidence": distinct_senders,
                        "transaction_ids": ", ".join(tx_ids),
                        "reason": (
                            f"Received {len(tx_ids)} incoming transactions from "
                            f"{distinct_senders} distinct accounts within {window_minutes} minutes"
                        ),
                    })
                    # Avoid duplicate findings caused by overlapping rolling windows
                    i = j
                    continue

            i += 1

    return pd.DataFrame(results, columns=columns)




def find_rapid_outgoing(df, window_minutes=2):
    """Flag incoming/outgoing pairs close in time (0 <= minutes <= window_minutes).
    These are candidate links, not proof of fund flow.
    """
    flagged = []
    columns = [
        "account_id",
        "rule",
        "evidence",
        "incoming_transaction_id",
        "outgoing_transaction_id",
        "incoming_amount",
        "outgoing_amount",
        "amount_difference",
        "reason",
    ]

    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=columns)

    required = {"transaction_id", "timestamp", "source_account", "target_account", "amount"}
    if not required.issubset(df.columns):
        return pd.DataFrame(columns=columns)

    df_clean = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_clean["timestamp"]):
        df_clean["timestamp"] = pd.to_datetime(df_clean["timestamp"], errors="coerce")

    df_clean = df_clean.dropna(
        subset=["transaction_id", "timestamp", "source_account", "target_account", "amount"]
    )
    df_clean["transaction_id"] = df_clean["transaction_id"].astype(str).str.strip()
    df_clean["source_account"] = df_clean["source_account"].astype(str).str.strip()
    df_clean["target_account"] = df_clean["target_account"].astype(str).str.strip()
    df_clean["amount"] = pd.to_numeric(df_clean["amount"], errors="coerce")
    df_clean = df_clean.dropna(subset=["amount"])
    df_clean = df_clean[
        (df_clean["transaction_id"] != "")
        & (df_clean["source_account"] != "")
        & (df_clean["target_account"] != "")
    ]

    # Sort chronologically for deterministic behavior
    df_clean = df_clean.sort_values(["timestamp", "transaction_id"]).reset_index(drop=True)

    candidate_accounts = sorted(
        set(df_clean["target_account"]) & set(df_clean["source_account"])
    )
    window_seconds = window_minutes * 60.0
    seen_pairs: set[tuple[str, str]] = set()

    for account in candidate_accounts:
        incoming = df_clean[df_clean["target_account"] == account].sort_values(
            ["timestamp", "transaction_id"]
        )
        outgoing = df_clean[df_clean["source_account"] == account].sort_values(
            ["timestamp", "transaction_id"]
        )

        for _, inc in incoming.iterrows():
            inc_id = inc["transaction_id"]
            inc_time = inc["timestamp"]
            inc_amount = inc["amount"]

            for _, out in outgoing.iterrows():
                out_id = out["transaction_id"]
                out_time = out["timestamp"]
                out_amount = out["amount"]

                pair_key = (inc_id, out_id)
                if pair_key in seen_pairs:
                    continue

                diff_seconds = (out_time - inc_time).total_seconds()
                # Inclusive boundary: 0 <= diff_seconds <= window_seconds
                if 0 <= diff_seconds <= window_seconds:
                    seen_pairs.add(pair_key)
                    minutes = diff_seconds / 60.0
                    amount_diff = round(float(inc_amount) - float(out_amount), 2)
                    flagged.append({
                        "account_id": account,
                        "rule": "rapid_outgoing",
                        "evidence": round(minutes, 2),
                        "incoming_transaction_id": inc_id,
                        "outgoing_transaction_id": out_id,
                        "incoming_amount": inc_amount,
                        "outgoing_amount": out_amount,
                        "amount_difference": amount_diff,
                        "reason": (
                            f"Incoming {inc_id} ({inc_amount}) followed by outgoing "
                            f"{out_id} ({out_amount}) after {minutes:.1f} minutes"
                        ),
                    })

    return pd.DataFrame(flagged, columns=columns)


def find_high_value_transfers(
    df,
    threshold=50000,
    min_history=5,
    multiplier=3.0,
):
    """Flag outgoing transactions exceeding a dynamic historical baseline
    or a fixed fallback threshold.
    """
    columns = [
        "account_id",
        "rule",
        "evidence",
        "transaction_ids",
        "reason",
        "detection_type",
        "history_count",
        "baseline_median",
        "threshold",
    ]

    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=columns)

    required = {
        "transaction_id",
        "source_account",
        "target_account",
        "timestamp",
        "amount",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df_clean = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_clean["timestamp"]):
        df_clean["timestamp"] = pd.to_datetime(df_clean["timestamp"], errors="coerce")

    df_clean = df_clean.dropna(
        subset=["transaction_id", "source_account", "target_account", "timestamp", "amount"]
    )
    df_clean["transaction_id"] = df_clean["transaction_id"].astype(str).str.strip()
    df_clean["source_account"] = df_clean["source_account"].astype(str).str.strip()
    df_clean["target_account"] = df_clean["target_account"].astype(str).str.strip()
    df_clean["amount"] = pd.to_numeric(df_clean["amount"], errors="coerce")
    df_clean = df_clean.dropna(subset=["amount"])
    df_clean = df_clean[
        (df_clean["transaction_id"] != "")
        & (df_clean["source_account"] != "")
        & (df_clean["target_account"] != "")
    ]

    # Chronological sort for deterministic baseline evaluation
    df_clean = df_clean.sort_values(["timestamp", "transaction_id"]).reset_index(drop=True)

    flagged = []
    seen_tx_ids: set[str] = set()

    for _, tx in df_clean.iterrows():
        tx_id = tx["transaction_id"]
        if tx_id in seen_tx_ids:
            continue
        seen_tx_ids.add(tx_id)

        acc = tx["source_account"]
        tx_time = tx["timestamp"]
        amount = float(tx["amount"])

        # Historical baseline: strictly earlier than current timestamp from SAME source account
        prior = df_clean[
            (df_clean["source_account"] == acc)
            & (df_clean["timestamp"] < tx_time)
        ]
        history_count = len(prior)

        if history_count >= min_history:
            median_val = float(prior["amount"].median())
            cutoff = multiplier * median_val
            if amount >= cutoff:
                flagged.append({
                    "account_id": acc,
                    "rule": "high_value_transfer",
                    "evidence": amount,
                    "transaction_ids": tx_id,
                    "reason": (
                        f"Transaction {tx_id} has amount {amount:g} THB "
                        f"(historical_baseline_anomaly: >= {multiplier:g}x median {median_val:g} THB "
                        f"across {history_count} prior transfers)"
                    ),
                    "detection_type": "historical_baseline_anomaly",
                    "history_count": history_count,
                    "baseline_median": median_val,
                    "threshold": cutoff,
                })
        else:
            if amount >= threshold:
                flagged.append({
                    "account_id": acc,
                    "rule": "high_value_transfer",
                    "evidence": amount,
                    "transaction_ids": tx_id,
                    "reason": (
                        f"Transaction {tx_id} has amount {amount:g} THB "
                        f"(fixed_threshold_fallback: >= {threshold:g} THB "
                        f"with {history_count} prior transfers)"
                    ),
                    "detection_type": "fixed_threshold_fallback",
                    "history_count": history_count,
                    "baseline_median": None,
                    "threshold": float(threshold),
                })

    return pd.DataFrame(flagged, columns=columns)


def find_case_overlap(case_accounts_df, min_cases=2):
    """Flag accounts associated with multiple distinct cases."""
    required_columns = {"case_id", "account_id"}
    missing = required_columns - set(case_accounts_df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {', '.join(sorted(missing))}"
        )

    df = case_accounts_df[["case_id", "account_id"]].copy()
    df = df.dropna(subset=["case_id", "account_id"])
    df["case_id"] = df["case_id"].astype(str).str.strip()
    df["account_id"] = df["account_id"].astype(str).str.strip()
    df = df[(df["case_id"] != "") & (df["account_id"] != "")]
    df = df.drop_duplicates()

    results = []

    for account_id, group in df.groupby("account_id"):
        case_ids = sorted(group["case_id"].unique())

        if len(case_ids) >= min_cases:
            results.append({
                "account_id": account_id,
                "rule": "cross_case_overlap",
                "evidence": len(case_ids),
                "case_ids": ", ".join(case_ids),
                "reason": (
                    f"Account {account_id} appears in "
                    f"{len(case_ids)} distinct cases: "
                    f"{', '.join(case_ids)}"
                ),
            })

    columns = [
        "account_id",
        "rule",
        "evidence",
        "case_ids",
        "reason",
    ]
    return pd.DataFrame(results, columns=columns)


def main():
    df = load_transactions()

    multiple = find_multiple_incoming(df)
    rapid = find_rapid_outgoing(df)
    high_value = find_high_value_transfers(df, threshold=50000)

    # R005: Cross-Case Account Overlap
    case_file = Path(__file__).resolve().parent.parent / "data" / "case_accounts.csv"

    if case_file.exists():
        case_df = pd.read_csv(case_file)
        case_overlap = find_case_overlap(case_df)
    else:
        print(f"Warning: Case file not found: {case_file}")
        case_overlap = pd.DataFrame(columns=[
            "account_id", "rule", "evidence", "case_ids", "reason"
        ])

    results = pd.concat(
        [multiple, rapid, high_value, case_overlap],
        ignore_index=True,
        sort=False
    )

    output_file = Path(__file__).resolve().parent / "risk_results.csv"
    results.to_csv(output_file, index=False)

    print(f"Transactions checked: {len(df)}")
    print(
        f"Accounts flagged by rules: "
        f"{results['account_id'].nunique() if not results.empty else 0}"
    )
    print(f"Rule findings: {len(results)}")
    print(f"Results saved to: {output_file}")

    if results.empty:
        print("No findings under the current rule thresholds.")
    else:
        print(results.to_string(index=False))



if __name__ == "__main__":
    main()