import pandas as pd
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "transactions.csv"


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



def find_multiple_incoming(df, min_senders=10):
    """Flag accounts receiving from several distinct senders."""
    results = []

    for account, group in df.groupby("target_account"):
        distinct_senders = group["source_account"].nunique()

        if distinct_senders >= min_senders:
            transaction_ids = sorted(
                group["transaction_id"].astype(str).unique()
            )

            results.append({
                "account_id": account,
                "rule": "multiple_incoming",
                "evidence": distinct_senders,
                "transaction_ids": ", ".join(transaction_ids),
                "reason": (
                    f"Received from {distinct_senders} distinct accounts"
                ),
            })

    return pd.DataFrame(
        results,
        columns=[
            "account_id",
            "rule",
            "evidence",
            "transaction_ids",
            "reason",
        ],
    )




def find_rapid_outgoing(df, window_minutes=5):
    """Flag incoming/outgoing pairs close in time.
    These are candidate links, not proof of fund flow.
    """
    flagged = []

    for account in sorted(
        set(df["target_account"]) & set(df["source_account"])
    ):
        incoming = df[df["target_account"] == account]
        outgoing = df[df["source_account"] == account]

        for _, inc in incoming.iterrows():
            for _, out in outgoing.iterrows():
                minutes = (
                    out["timestamp"] - inc["timestamp"]
                ).total_seconds() / 60

                if 0 <= minutes <= window_minutes:
                    flagged.append({
                        "account_id": account,
                        "rule": "rapid_outgoing",
                        "evidence": round(minutes, 2),
                        "incoming_transaction_id": inc["transaction_id"],
                        "outgoing_transaction_id": out["transaction_id"],
                        "incoming_amount": inc["amount"],
                        "outgoing_amount": out["amount"],
                        "amount_difference": round(
                            float(inc["amount"]) - float(out["amount"]), 2
                        ),
                        "reason": (
                            f"Incoming {inc['transaction_id']} "
                            f"({inc['amount']}) followed by outgoing "
                            f"{out['transaction_id']} ({out['amount']}) "
                            f"after {minutes:.1f} minutes"
                        ),
                    })

    return pd.DataFrame(flagged)


def find_high_value_transfers(df, threshold=50000):
    """Flag transactions with amount >= threshold.
    This is a project-defined screening threshold,
    not a universal regulatory standard.
    """
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

    amounts = pd.to_numeric(df["amount"], errors="coerce")
    flagged = df.loc[amounts >= threshold].copy()

    if flagged.empty:
        return pd.DataFrame(columns=[
            "account_id",
            "rule",
            "evidence",
            "transaction_ids",
            "reason",
        ])

    return pd.DataFrame({
        "account_id": flagged["source_account"],
        "rule": "high_value_transfer",
        "evidence": flagged["amount"],
        "transaction_ids": flagged["transaction_id"].astype(str),
        "reason": flagged.apply(
            lambda row: (
                f"Transaction {row['transaction_id']} "
                f"has amount {row['amount']} THB "
                f"(threshold: {threshold} THB)"
            ),
            axis=1,
        ),
    }).reset_index(drop=True)


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