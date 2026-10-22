
import pandas as pd
from collections import defaultdict, deque
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "transactions.csv"


def load_transactions(csv_path=DATA_FILE):
    """Load and validate transaction data."""
    df = pd.read_csv(csv_path)

    required_columns = {
        "transaction_id",
        "timestamp",
        "source_account",
        "target_account",
        "amount",
    }

    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%d/%m/%Y %H:%M", errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    df = df.dropna(
        subset=[
            "timestamp",
            "source_account",
            "target_account",
            "amount",
        ]
    )

    return df



def find_paths(df, start_account, end_account, max_hops=4):
    """Find transaction paths that follow chronological order."""
    if max_hops < 1:
        raise ValueError("max_hops must be at least 1")

    graph = defaultdict(list)

    for _, transaction in df.iterrows():
        graph[transaction["source_account"]].append(transaction)

    # Sort outgoing transactions by timestamp.
    for account in graph:
        graph[account].sort(key=lambda tx: tx["timestamp"])

    results = []
    queue = deque([(start_account, [start_account], [], None)])

    while queue:
        account, visited, path, last_timestamp = queue.popleft()

        if len(path) >= max_hops:
            continue

        for transaction in graph[account]:
            next_account = transaction["target_account"]
            tx_time = transaction["timestamp"]

            # A transfer cannot occur before the preceding transfer.
            if last_timestamp is not None and tx_time < last_timestamp:
                continue

            # Avoid revisiting an account in the same path.
            if next_account in visited:
                continue

            next_path = path + [transaction]

            if next_account == end_account:
                results.append(next_path)
            else:
                queue.append((
                    next_account,
                    visited + [next_account],
                    next_path,
                    tx_time
                ))

    return results



def main():
    df = load_transactions()

    print("MuleTrace AI - Transaction Path Investigation")
    print(f"Transactions loaded: {len(df)}")

    start = input("Enter source account: ").strip()
    end = input("Enter target account: ").strip()

    try:
        max_hops = int(input("Maximum transfers (default 4): ") or "4")
        paths = find_paths(df, start, end, max_hops)
    except ValueError as error:
        print(f"Input error: {error}")
        return

    if not paths:
        print(f"No path found from {start} to {end}.")
        return

    print(f"\nFound {len(paths)} path(s).\n")

    output_rows = []

    for path_number, path in enumerate(paths, start=1):
        print(f"Path {path_number}: {start}", end="")

        for transaction in path:
            print(f" -> {transaction['target_account']}", end="")

        print()

        for transaction in path:
            row = transaction.to_dict()
            row["path_number"] = path_number
            output_rows.append(row)

            print(
                f"  Transaction: {transaction['transaction_id']} | "
                f"{transaction['timestamp']} | "
                f"Amount: {transaction['amount']}"
            )

            if "scenario" in transaction.index:
                print(f"  Scenario: {transaction['scenario']}")

            if "is_suspicious" in transaction.index:
                print(
                    "  Dataset suspicious label: "
                    f"{transaction['is_suspicious']}"
                )

        print()

    output_file = Path(__file__).resolve().parent / "path_results.csv"
    pd.DataFrame(output_rows).to_csv(output_file, index=False)

    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    main()
