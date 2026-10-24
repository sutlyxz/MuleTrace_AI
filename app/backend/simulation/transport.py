"""Transport Layer for MuleTrace AI Transaction Simulation.

Defines the reusable transport interface and two concrete implementations:
1. LocalSimulationTransport: In-memory evaluation and execution of risk rules,
   providing fast local development and testing without live AWS dependencies.
2. EventBridgeSimulationTransport: AWS EventBridge integration adapter that batches
   and submits events to an EventBridge Event Bus for the AWS serverless pipeline.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.backend.core.risk_rules import (
    find_high_value_transfers,
    find_multiple_incoming,
    find_rapid_outgoing,
)

logger = logging.getLogger("muletrace.simulation.transport")

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Global thread-safe in-memory registry for simulation run tracking
_RUN_REGISTRY_LOCK = threading.Lock()
_RUN_REGISTRY: dict[str, dict[str, Any]] = {}
_SIMULATED_CASES: list[dict[str, Any]] = []


def _evaluate_batch_findings(events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    """Evaluate the 3 core AML risk rules on the simulation batch and record flagged cases."""
    if not events:
        return {
            "total_findings": 0,
            "rule_matches": {"multiple_incoming": 0, "rapid_outgoing": 0, "high_value": 0},
            "cases": [],
        }

    df = pd.DataFrame(events)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["amount"] = pd.to_numeric(df["amount"])

    multiple_df = find_multiple_incoming(df)
    rapid_df = find_rapid_outgoing(df)
    high_val_df = find_high_value_transfers(df)

    flagged_accounts: list[str] = []
    for res_df in (multiple_df, rapid_df, high_val_df):
        if not res_df.empty and "account_id" in res_df.columns:
            for acc in res_df["account_id"].tolist():
                if acc not in flagged_accounts:
                    flagged_accounts.append(acc)

    short_tag = run_id.split("_")[-1][:4].upper() if "_" in run_id else "SIM"
    batch_transactions = [
        {
            "id": str(ev.get("transaction_id", "")),
            "from": str(ev.get("source_account", "")),
            "to": str(ev.get("target_account", "")),
            "amount": float(ev.get("amount", 0.0)),
            "time": str(ev.get("timestamp", "")).replace(" ", "T")[:19],
        }
        for ev in events
    ]
    created_cases: list[dict[str, Any]] = []
    for idx, acc in enumerate(flagged_accounts, start=1):
        in_tx = df[df["target_account"] == acc]
        acc_tx = df[(df["target_account"] == acc) | (df["source_account"] == acc)]
        if not in_tx.empty:
            max_idx = in_tx["amount"].idxmax()
            trigger_row = in_tx.loc[max_idx]
            src = str(trigger_row["source_account"])
            tgt = str(trigger_row["target_account"])
            amt = float(in_tx["amount"].max())
            tx_id = str(trigger_row["transaction_id"])
            tx_time = trigger_row["timestamp"].strftime("%Y-%m-%dT%H:%M:%S")
        elif not acc_tx.empty:
            max_idx = acc_tx["amount"].idxmax()
            trigger_row = acc_tx.loc[max_idx]
            src = str(trigger_row["source_account"])
            tgt = str(trigger_row["target_account"])
            amt = float(acc_tx["amount"].max())
            tx_id = str(trigger_row["transaction_id"])
            tx_time = trigger_row["timestamp"].strftime("%Y-%m-%dT%H:%M:%S")
        else:
            src = "-"
            tgt = acc
            amt = 0.0
            tx_id = ""
            tx_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        created_cases.append({
            "caseId": f"SIM-{short_tag}-{idx:02d}",
            "source": src,
            "target": tgt,
            "amount": amt,
            "time": tx_time,
            "status": "new",
            "risk": "HIGH",
            "priorityScore": max(78, 94 - (idx - 1) * 4),
            "transactionId": tx_id,
            "description": f"ตรวจพบความเสี่ยงจากการจำลองธุรกรรม (Run: {short_tag}) บัญชี {tgt} มีรูปแบบรับ-โอนเงินผิดปกติเข้าข่ายบัญชีม้า",
            "run_id": run_id,
            "transactions": batch_transactions,
        })

    return {
        "total_findings": len(multiple_df) + len(rapid_df) + len(high_val_df),
        "rule_matches": {
            "multiple_incoming": len(multiple_df),
            "rapid_outgoing": len(rapid_df),
            "high_value": len(high_val_df),
        },
        "cases": created_cases,
    }


class SimulationTransport(ABC):
    """Abstract interface for submitting simulation transaction events."""

    @abstractmethod
    def send_events(self, events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        """Submit a batch of simulation events."""


class LocalSimulationTransport(SimulationTransport):
    """Local / mock transport executing risk detection in-memory for testing and local mode."""

    def send_events(self, events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        eval_info = _evaluate_batch_findings(events, run_id)
        total_findings = eval_info["total_findings"]
        first_ev = events[0] if events else {}

        result_record: dict[str, Any] = {
            "status": "success",
            "run_id": run_id,
            "events_submitted": len(events),
            "transport": "local_mock",
            "confirmed": True,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "message": f"Successfully submitted {len(events)} simulated transactions locally",
            "cases_created_hint": total_findings > 0,
            "total_findings": total_findings,
            "rule_matches": eval_info["rule_matches"],
            "seed": first_ev.get("seed"),
            "base_timestamp": first_ev.get("base_timestamp"),
            "generator_version": first_ev.get("generator_version"),
            "dataset_ref": first_ev.get("dataset_ref"),
            "metadata": {
                "seed": first_ev.get("seed"),
                "base_timestamp": first_ev.get("base_timestamp"),
                "generator_version": first_ev.get("generator_version"),
                "dataset_ref": first_ev.get("dataset_ref"),
            },
        }

        with _RUN_REGISTRY_LOCK:
            _RUN_REGISTRY[run_id] = result_record
            for c in eval_info["cases"]:
                if not any(existing.get("caseId") == c["caseId"] for existing in _SIMULATED_CASES):
                    _SIMULATED_CASES.append(c)

        return result_record


class EventBridgeSimulationTransport(SimulationTransport):
    """AWS EventBridge transport adapter for production cloud integration.

    Submits batches of transaction events to Amazon EventBridge in chunks of up to 10
    (EventBridge PutEvents API limit).
    """

    def __init__(
        self,
        event_bus_name: str | None = None,
        source: str | None = None,
        detail_type: str | None = None,
        region: str | None = None,
        allow_debug_dispatch: bool = False,
    ) -> None:
        if not os.environ.get("AWS_ACCESS_KEY_ID") and (PROJECT_ROOT / ".env").is_file():
            try:
                from app.backend.config import load_environment
                os.environ.update(load_environment(PROJECT_ROOT))
            except Exception:
                pass

        self.bus_name = event_bus_name or os.environ.get("EVENTBRIDGE_BUS_NAME", "muletrace-transactions")
        self.source = source or os.environ.get("EVENTBRIDGE_SOURCE", "muletrace.simulation")
        self.detail_type = detail_type or os.environ.get("EVENTBRIDGE_DETAIL_TYPE", "TransactionEvent")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.allow_debug_dispatch = (
            allow_debug_dispatch
            or os.environ.get("ALLOW_DEBUG_EVENTBRIDGE_DISPATCH", "0").strip().lower() in ("1", "true")
        )
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config
            cfg = Config(connect_timeout=2, read_timeout=4, retries={"max_attempts": 1})
            self._client = boto3.client("events", region_name=self.region, config=cfg)

            return self._client
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize AWS EventBridge client: {exc}")

    def send_events(self, events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        # Guard: Never resend historical debug events to production EventBridge bus by default
        is_debug_batch = any(ev.get("is_debug", False) for ev in events) or os.environ.get("MULETRACE_DEBUG_RUN") == "1"
        if is_debug_batch and not self.allow_debug_dispatch:
            logger.warning("Blocked dispatching debug simulation events to production EventBridge bus.")
            return {
                "status": "debug_dispatch_blocked",
                "run_id": run_id,
                "events_submitted": 0,
                "transport": "aws_eventbridge",
                "message": "Safety guard blocked sending historical debug events to production EventBridge bus.",
                "confirmed": False,
            }

        client = self._get_client()

        # EventBridge allows max 10 entries per PutEvents request
        CHUNK_SIZE = 10
        total_submitted = 0
        failed_count = 0
        error_details: list[dict[str, Any]] = []

        now_utc = datetime.now(timezone.utc)
        first_ev = events[0] if events else {}

        for i in range(0, len(events), CHUNK_SIZE):
            chunk = events[i : i + CHUNK_SIZE]
            entries: list[dict[str, Any]] = []

            for ev in chunk:
                # Construct EventBridge event envelope
                entry = {
                    "Time": now_utc,
                    "Source": self.source,
                    "Resources": [f"muletrace:run:{run_id}"],
                    "DetailType": self.detail_type,
                    "Detail": json.dumps(ev),
                    "EventBusName": self.bus_name,
                }
                entries.append(entry)

            try:
                response = client.put_events(Entries=entries)
                failed = response.get("FailedEntryCount", 0)
                failed_count += failed
                total_submitted += (len(entries) - failed)

                for item in response.get("Entries", []):
                    if "ErrorCode" in item:
                        error_details.append({
                            "code": item.get("ErrorCode"),
                            "message": item.get("ErrorMessage"),
                        })
            except Exception as err:
                logger.error(f"EventBridge put_events failed for chunk: {err}")
                raise RuntimeError(f"EventBridge dispatch failed: {err}")

        eval_info = _evaluate_batch_findings(events, run_id)

        result_record: dict[str, Any] = {
            "status": "success" if failed_count == 0 else "partial_failure",
            "run_id": run_id,
            "events_submitted": total_submitted,
            "events_failed": failed_count,
            "transport": "aws_eventbridge",
            "event_bus": self.bus_name,
            "confirmed": total_submitted > 0,
            "submitted_at": now_utc.isoformat(),
            "message": f"Submitted {total_submitted}/{len(events)} events to EventBridge '{self.bus_name}'",
            "cases_created_hint": eval_info["total_findings"] > 0,
            "total_findings": eval_info["total_findings"],
            "rule_matches": eval_info["rule_matches"],
            "seed": first_ev.get("seed"),
            "base_timestamp": first_ev.get("base_timestamp"),
            "generator_version": first_ev.get("generator_version"),
            "dataset_ref": first_ev.get("dataset_ref"),
            "metadata": {
                "seed": first_ev.get("seed"),
                "base_timestamp": first_ev.get("base_timestamp"),
                "generator_version": first_ev.get("generator_version"),
                "dataset_ref": first_ev.get("dataset_ref"),
            },
            "errors": error_details if error_details else None,
        }

        with _RUN_REGISTRY_LOCK:
            _RUN_REGISTRY[run_id] = result_record
            if total_submitted > 0:
                for c in eval_info["cases"]:
                    if not any(existing.get("caseId") == c["caseId"] for existing in _SIMULATED_CASES):
                        _SIMULATED_CASES.append(c)

        return result_record


def get_run_record(run_id: str) -> dict[str, Any] | None:
    """Retrieve run record from the in-memory registry."""
    with _RUN_REGISTRY_LOCK:
        return _RUN_REGISTRY.get(run_id)


def get_simulated_cases() -> list[dict[str, Any]]:
    """Return a copy of simulated risk cases generated during the current session."""
    with _RUN_REGISTRY_LOCK:
        return list(_SIMULATED_CASES)