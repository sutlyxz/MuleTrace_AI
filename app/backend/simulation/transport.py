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

# Global thread-safe in-memory registry for simulation run tracking
_RUN_REGISTRY_LOCK = threading.Lock()
_RUN_REGISTRY: dict[str, dict[str, Any]] = {}


class SimulationTransport(ABC):
    """Abstract interface for submitting simulation transaction events."""

    @abstractmethod
    def send_events(self, events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        """Submit a batch of simulation events.

        Args:
            events: Validated list of transaction event dictionaries.
            run_id: Unique simulation run ID.

        Returns:
            Dictionary containing submission status and metadata.
        """


class LocalSimulationTransport(SimulationTransport):
    """Local / mock transport executing risk detection in-memory for testing and local mode."""

    def send_events(self, events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        df = pd.DataFrame(events)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["amount"] = pd.to_numeric(df["amount"])

        # Execute exactly the 3 risk detection rules
        multiple_df = find_multiple_incoming(df)
        rapid_df = find_rapid_outgoing(df)
        high_val_df = find_high_value_transfers(df)

        flagged_accounts: set[str] = set()
        if not multiple_df.empty:
            flagged_accounts.update(multiple_df["account_id"].tolist())
        if not rapid_df.empty:
            flagged_accounts.update(rapid_df["account_id"].tolist())
        if not high_val_df.empty:
            flagged_accounts.update(high_val_df["account_id"].tolist())

        total_findings = len(multiple_df) + len(rapid_df) + len(high_val_df)
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
            "rule_matches": {
                "multiple_incoming": len(multiple_df),
                "rapid_outgoing": len(rapid_df),
                "high_value": len(high_val_df),
            },
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
            self._client = boto3.client("events", region_name=self.region)
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
            "cases_created_hint": True,
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

        return result_record


def get_run_record(run_id: str) -> dict[str, Any] | None:
    """Retrieve run record from the in-memory registry."""
    with _RUN_REGISTRY_LOCK:
        return _RUN_REGISTRY.get(run_id)
