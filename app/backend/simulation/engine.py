"""Simulation Engine for MuleTrace AI.

Coordinates simulation batch generation, schema validation, transport dispatch,
and run tracking.
"""
from __future__ import annotations

import os
from typing import Any

from .dataset import generate_run_id, generate_simulation_batch, validate_simulation_batch
from .transport import (
    EventBridgeSimulationTransport,
    LocalSimulationTransport,
    SimulationTransport,
    get_run_record,
)


class SimulationEngine:
    """Core simulation coordinator."""

    def __init__(self, transport: SimulationTransport | None = None) -> None:
        self.transport = transport or self._resolve_default_transport()

    def _resolve_default_transport(self) -> SimulationTransport:
        """Resolve transport based on environment configuration."""
        configured = os.environ.get("MULETRACE_SIMULATION_TRANSPORT", "").strip().lower()
        if configured == "eventbridge":
            return EventBridgeSimulationTransport()
        return LocalSimulationTransport()

    def run_simulation(
        self,
        seed: int | None = None,
        base_time: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a single simulation run.

        1. Generates unique Simulation Run ID.
        2. Produces dynamic, controlled 20-transaction mixed dataset (reproducible with explicit seed/base_time).
        3. Validates dataset against canonical schema and simulation rules.
        4. Submits batch via active transport.
        5. Returns confirmation details.
        """
        run_id = generate_run_id()
        events = generate_simulation_batch(run_id=run_id, seed=seed, base_time=base_time)

        is_valid, error_msg = validate_simulation_batch(events)
        if not is_valid:
            raise ValueError(f"Simulation batch validation failed: {error_msg}")

        result = self.transport.send_events(events, run_id=run_id)
        return result

    @staticmethod
    def get_run_status(run_id: str) -> dict[str, Any] | None:
        """Retrieve execution record for a previous run ID."""
        return get_run_record(run_id)
