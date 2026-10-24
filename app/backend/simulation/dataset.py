"""Dynamic, Controlled, and Reproducible Simulation Dataset Generator and Validator.

Upgraded to generate exactly 20 transactions per run using:
1. Dynamic Data: Randomizes suitable account assignments, transaction amounts,
   and event timestamps from canonical accounts.
2. Controlled Scenarios: Exercises exactly three risk detection rules:
   - Rule 1 (Multiple Incoming): 5 transfers to mule account within 10 minutes.
   - Rule 2 (Rapid Outgoing): Funds transferred out from mule within 120 seconds.
   - Rule 3 (High-Value Transfer):
     * Historical Baseline Anomaly: >= 3x median over 5 earlier qualifying transfers.
     * Fixed Threshold Fallback: >= 50,000 THB with 0 earlier transfers.
   - AI Tool Multi-hop Support: Connected trail (Smurf -> Mule -> Relay -> Dest)
     traversable by trace_money without generating false risk alerts.
3. Reproducibility:
   - Accepts an optional explicit seed and base timestamp for local debugging.
   - The same seed and base timestamp strictly reproduce the same logical transactions.
   - Unique run IDs and event IDs are generated to prevent collision.
   - Metadata (seed, base_timestamp, generator_version, dataset_ref) is recorded.
"""
from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

GENERATOR_VERSION = "2.0.0-dynamic"
DATASET_REF = "accounts.csv:v1"
TOTAL_BATCH_SIZE = 20

CANONICAL_COLUMNS = [
    "transaction_id",
    "timestamp",
    "source_account",
    "target_account",
    "amount",
    "scenario",
    "is_suspicious",
]

# Account pools loaded from app/data/accounts.csv
ACCOUNTS_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "accounts.csv"

# Pre-categorized account pools from accounts.csv
BASELINE_CANDIDATES = ["N012", "N011", "N018", "N007", "N008", "N003", "N005"]
MULE_CANDIDATES = ["M001", "B782", "B900", "B901", "B902"]
SMURF_POOL = [
    "S001", "S002", "S003", "S004", "S005",
    "H001", "H002", "H003", "H004", "H005",
    "J001", "J002", "J003", "R001", "R002",
]
RELAY_CANDIDATES = ["B777", "B778", "D201", "A777", "A778"]
DEST_CANDIDATES = ["C777", "C778", "C779", "C900", "C991", "E450"]
FALLBACK_CANDIDATES = ["A900", "A014", "A027", "A035", "A042", "A056", "P001", "Q001"]
FALLBACK_DEST_CANDIDATES = ["C900", "C777", "C991", "E450", "P002", "Q002"]
ROUTINE_NORMAL_POOL = [f"N{i:03d}" for i in range(1, 21)]


def _load_valid_accounts() -> set[str]:
    """Load valid account IDs from canonical accounts.csv."""
    if ACCOUNTS_CSV_PATH.exists():
        df = pd.read_csv(ACCOUNTS_CSV_PATH)
        return set(df["account_id"].astype(str).str.strip())
    # Fallback to hardcoded known pool if file is missing during mock test
    return set(
        BASELINE_CANDIDATES
        + MULE_CANDIDATES
        + SMURF_POOL
        + RELAY_CANDIDATES
        + DEST_CANDIDATES
        + FALLBACK_CANDIDATES
        + FALLBACK_DEST_CANDIDATES
        + ROUTINE_NORMAL_POOL
    )


VALID_ACCOUNTS = _load_valid_accounts()


def generate_run_id() -> str:
    """Generate a unique, high-entropy simulation run ID."""
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_hex = secrets.token_hex(4)
    return f"sim_{now_str}_{rand_hex}"


def generate_simulation_batch(
    run_id: str | None = None,
    seed: int | None = None,
    base_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Generate exactly 20 dynamic, controlled, and reproducible simulation transactions.

    Args:
        run_id: Optional unique run ID. If None, generates a fresh run ID.
        seed: Optional integer seed for deterministic reproduction of logical transactions.
              If None, generates a cryptographically random 32-bit seed.
        base_time: Optional base reference timestamp. Defaults to current UTC time.

    Returns:
        List of exactly 20 event dictionaries conforming to the canonical schema
        plus simulation metadata.
    """
    effective_run_id = run_id or generate_run_id()
    effective_seed = seed if seed is not None else secrets.randbits(32)

    # Use run_id suffix to guarantee globally unique transaction IDs even if seed is reused
    run_parts = effective_run_id.split("_")
    short_id = (run_parts[-1] if len(run_parts) > 1 else effective_run_id[:8]).upper()

    # Determine reference start time
    is_debug = (seed is not None) or (base_time is not None)
    if base_time is None:
        start_dt = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=45)
    else:
        start_dt = base_time

    rng = random.Random(effective_seed)

    # 1. Dynamic Account Selection
    baseline_acc = rng.choice(BASELINE_CANDIDATES)
    mule_acc = rng.choice([m for m in MULE_CANDIDATES if m != baseline_acc])
    smurfs = rng.sample([s for s in SMURF_POOL if s not in (baseline_acc, mule_acc)], 5)
    relay_acc = rng.choice([r for r in RELAY_CANDIDATES if r not in (baseline_acc, mule_acc) and r not in smurfs])
    dest_acc = rng.choice([d for d in DEST_CANDIDATES if d not in (baseline_acc, mule_acc, relay_acc) and d not in smurfs])
    fallback_acc = rng.choice([f for f in FALLBACK_CANDIDATES if f not in (baseline_acc, mule_acc, relay_acc, dest_acc) and f not in smurfs])
    fallback_dest = rng.choice([fd for fd in FALLBACK_DEST_CANDIDATES if fd != fallback_acc and fd not in (baseline_acc, mule_acc)])

    avail_normal = [n for n in ROUTINE_NORMAL_POOL if n not in (baseline_acc, mule_acc, relay_acc, dest_acc, fallback_acc)]
    rng.shuffle(avail_normal)

    # 2. Dynamic Controlled Amounts
    # 5 baseline transfers from baseline_acc
    baseline_amts = [round(rng.uniform(1050.0, 2400.0), 2) for _ in range(5)]
    baseline_median = float(pd.Series(baseline_amts).median())
    high_val_median_amt = round(baseline_median * rng.uniform(3.2, 4.2), 2)

    fallback_amt = round(rng.uniform(55000.0, 92000.0), 2)

    smurf_amts = [round(rng.uniform(1200.0, 3200.0), 2) for _ in range(5)]
    rapid_amt = round(rng.uniform(7500.0, 14000.0), 2)
    continuation_amt = round(rapid_amt * rng.uniform(0.75, 0.95), 2)

    normal_amts = [round(rng.uniform(1500.0, 3800.0), 2) for _ in range(6)]

    # 3. Dynamic Controlled Chronological Offsets
    # Time budget:
    # Multiple incoming window: 5 transfers spaced so t_inc5 - t_inc1 <= 600s (10 min)
    # Ensure t_inc5 - t_inc4 >= 85s so that t_rapid (50s after inc 5) is > 120s after inc 4!
    t_inc_start = 1800 + rng.randint(0, 40)
    t_inc1 = t_inc_start
    t_inc2 = t_inc1 + rng.randint(60, 80)
    t_inc3 = t_inc2 + rng.randint(70, 90)
    t_inc4 = t_inc3 + rng.randint(70, 90)
    t_inc5 = t_inc4 + rng.randint(85, 110)

    t_rapid = t_inc5 + rng.randint(45, 60) # diff from inc5 is 45-60s (<= 120s); diff from inc4 is >= 130s (> 120s)
    t_high_median = t_rapid + rng.randint(25, 45)
    t_continuation = t_rapid + rng.randint(180, 240) # diff > 120s from rapid
    t_fallback = t_continuation + rng.randint(120, 200)

    offsets = [
        0,                                   # 1. baseline 1
        rng.randint(200, 350),               # 2. normal 1
        rng.randint(450, 600),               # 3. baseline 2
        rng.randint(700, 850),               # 4. normal 2
        rng.randint(950, 1100),              # 5. baseline 3
        rng.randint(1200, 1350),             # 6. normal 3
        rng.randint(1450, 1600),             # 7. baseline 4
        t_inc1,                              # 8. inc 1
        (t_inc1 + t_inc2) // 2,              # 9. baseline 5 (completes 5 baseline transfers before inc 2)
        t_inc2,                              # 10. inc 2
        (t_inc2 + t_inc3) // 2,              # 11. normal 4
        t_inc3,                              # 12. inc 3
        (t_inc3 + t_inc4) // 2,              # 13. normal 5
        t_inc4,                              # 14. inc 4
        t_inc5,                              # 15. inc 5 (multiple incoming completes: 5 in <= 600s)
        t_rapid,                             # 16. rapid outgoing (from mule within 120s of inc 5)
        t_high_median,                       # 17. high-val median (from baseline_acc >= 3x median)
        t_continuation,                      # 18. continuation (relay -> dest, multi-hop trail)
        t_continuation + rng.randint(30, 60),# 19. normal 6
        t_fallback,                          # 20. high-val fallback (from fallback_acc >= 50,000)
    ]

    # Exactly 20 transaction specifications
    specs = [
        # 1. baseline 1
        {"src": baseline_acc, "tgt": avail_normal[0], "amt": baseline_amts[0], "scen": "normal", "susp": False},
        # 2. normal 1
        {"src": avail_normal[1], "tgt": avail_normal[2], "amt": normal_amts[0], "scen": "normal", "susp": False},
        # 3. baseline 2
        {"src": baseline_acc, "tgt": avail_normal[3], "amt": baseline_amts[1], "scen": "normal", "susp": False},
        # 4. normal 2
        {"src": avail_normal[4], "tgt": avail_normal[5], "amt": normal_amts[1], "scen": "normal", "susp": False},
        # 5. baseline 3
        {"src": baseline_acc, "tgt": avail_normal[6], "amt": baseline_amts[2], "scen": "normal", "susp": False},
        # 6. normal 3
        {"src": avail_normal[7], "tgt": avail_normal[8], "amt": normal_amts[2], "scen": "normal", "susp": False},
        # 7. baseline 4
        {"src": baseline_acc, "tgt": avail_normal[9], "amt": baseline_amts[3], "scen": "normal", "susp": False},
        # 8. inc 1
        {"src": smurfs[0], "tgt": mule_acc, "amt": smurf_amts[0], "scen": "smurfing", "susp": True},
        # 9. baseline 5 (completes 5 baseline transfers)
        {"src": baseline_acc, "tgt": avail_normal[10], "amt": baseline_amts[4], "scen": "normal", "susp": False},
        # 10. inc 2
        {"src": smurfs[1], "tgt": mule_acc, "amt": smurf_amts[1], "scen": "smurfing", "susp": True},
        # 11. normal 4
        {"src": avail_normal[11], "tgt": avail_normal[0], "amt": normal_amts[3], "scen": "normal", "susp": False},
        # 12. inc 3
        {"src": smurfs[2], "tgt": mule_acc, "amt": smurf_amts[2], "scen": "smurfing", "susp": True},
        # 13. normal 5
        {"src": avail_normal[2], "tgt": avail_normal[3], "amt": normal_amts[4], "scen": "normal", "susp": False},
        # 14. inc 4
        {"src": smurfs[3], "tgt": mule_acc, "amt": smurf_amts[3], "scen": "smurfing", "susp": True},
        # 15. inc 5
        {"src": smurfs[4], "tgt": mule_acc, "amt": smurf_amts[4], "scen": "smurfing", "susp": True},
        # 16. rapid outgoing
        {"src": mule_acc, "tgt": relay_acc, "amt": rapid_amt, "scen": "rapid_movement", "susp": True},
        # 17. high-val median
        {"src": baseline_acc, "tgt": avail_normal[4], "amt": high_val_median_amt, "scen": "high_value", "susp": True},
        # 18. continuation
        {"src": relay_acc, "tgt": dest_acc, "amt": continuation_amt, "scen": "multi_hop_pass", "susp": False},
        # 19. normal 6
        {"src": avail_normal[5], "tgt": avail_normal[6], "amt": normal_amts[5], "scen": "normal", "susp": False},
        # 20. high-val fallback
        {"src": fallback_acc, "tgt": fallback_dest, "amt": fallback_amt, "scen": "high_value", "susp": True},
    ]

    events: list[dict[str, Any]] = []
    for idx, (spec, offset) in enumerate(zip(specs, offsets), start=1):
        tx_time = start_dt + timedelta(seconds=offset)
        ev: dict[str, Any] = {
            # Canonical transaction schema
            "transaction_id": f"TXSIM_{short_id}_{idx:02d}",
            "timestamp": tx_time.strftime("%Y-%m-%d %H:%M:%S"),
            "source_account": spec["src"],
            "target_account": spec["tgt"],
            "amount": float(spec["amt"]),
            "scenario": spec["scen"],
            "is_suspicious": bool(spec["susp"]),
            # Simulation metadata
            "event_id": f"EVT_{short_id}_{idx:02d}",
            "simulation_run_id": effective_run_id,
            "is_simulated": True,
            "sequence_number": idx,
            "total_in_batch": TOTAL_BATCH_SIZE,
            "seed": effective_seed,
            "base_timestamp": start_dt.isoformat(),
            "generator_version": GENERATOR_VERSION,
            "dataset_ref": DATASET_REF,
            "is_debug": is_debug,
        }
        events.append(ev)

    return events


def validate_simulation_batch(events: list[dict[str, Any]]) -> tuple[bool, str]:
    """Validate that a simulation batch strictly adheres to schema requirements.

    Returns:
        (True, "") if valid, or (False, error_reason) if invalid.
    """
    if not events:
        return False, "Simulation batch is empty"

    if len(events) != TOTAL_BATCH_SIZE:
        return False, f"Expected {TOTAL_BATCH_SIZE} transactions, got {len(events)}"

    seen_ids: set[str] = set()
    seen_event_ids: set[str] = set()
    prev_time: datetime | None = None

    valid_accounts = VALID_ACCOUNTS

    for idx, ev in enumerate(events, start=1):
        # 1. Column existence
        for col in CANONICAL_COLUMNS:
            if col not in ev:
                return False, f"Transaction {idx} missing required column '{col}'"

        tx_id = str(ev.get("transaction_id", "")).strip()
        if not tx_id:
            return False, f"Transaction {idx} has empty transaction_id"
        if tx_id in seen_ids:
            return False, f"Duplicate transaction_id '{tx_id}' at index {idx}"
        seen_ids.add(tx_id)

        evt_id = str(ev.get("event_id", "")).strip()
        if not evt_id:
            return False, f"Transaction {idx} has empty event_id"
        if evt_id in seen_event_ids:
            return False, f"Duplicate event_id '{evt_id}' at index {idx}"
        seen_event_ids.add(evt_id)

        # 2. Account identifiers
        src = str(ev.get("source_account", "")).strip()
        tgt = str(ev.get("target_account", "")).strip()
        if not src or not tgt:
            return False, f"Transaction {tx_id} has empty source or target account"
        if src == tgt:
            return False, f"Transaction {tx_id} has identical source and target account"
        if src not in valid_accounts:
            return False, f"Transaction {tx_id} references invalid source account '{src}'"
        if tgt not in valid_accounts:
            return False, f"Transaction {tx_id} references invalid target account '{tgt}'"

        # 3. Numeric amount
        try:
            amt = float(ev.get("amount", 0))
            if amt <= 0:
                return False, f"Transaction {tx_id} has non-positive amount {amt}"
        except (ValueError, TypeError):
            return False, f"Transaction {tx_id} has non-numeric amount"

        # 4. Chronological order
        try:
            ts = datetime.strptime(str(ev.get("timestamp")), "%Y-%m-%d %H:%M:%S")
            if prev_time is not None and ts < prev_time:
                return False, f"Transaction {tx_id} violates chronological order ({ts} < {prev_time})"
            prev_time = ts
        except ValueError:
            return False, f"Transaction {tx_id} has invalid timestamp format: {ev.get('timestamp')}"

        # 5. Metadata verification
        if not ev.get("is_simulated", False):
            return False, f"Transaction {tx_id} must have is_simulated=True"
        if not ev.get("simulation_run_id"):
            return False, f"Transaction {tx_id} missing simulation_run_id"
        if ev.get("sequence_number") != idx:
            return False, f"Transaction {tx_id} sequence number mismatch ({ev.get('sequence_number')} != {idx})"

        # 6. Absence of hardcoded alerts, case IDs, or AI explanations
        forbidden_keys = {"case_id", "alert_id", "risk_score", "ai_explanation", "narrative"}
        for fkey in forbidden_keys:
            if fkey in ev:
                return False, f"Forbidden hardcoded key '{fkey}' found in transaction {tx_id}"

    return True, ""
