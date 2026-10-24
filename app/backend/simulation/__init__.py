"""Simulation package for MuleTrace AI.

Provides deterministic transaction simulation datasets, reusable simulation engine,
local and AWS EventBridge transport adapters, and API endpoints for the Overview UI.
"""
from __future__ import annotations

from .dataset import generate_simulation_batch, validate_simulation_batch
from .engine import SimulationEngine
from .transport import EventBridgeSimulationTransport, LocalSimulationTransport, SimulationTransport

__all__ = [
    "SimulationEngine",
    "SimulationTransport",
    "LocalSimulationTransport",
    "EventBridgeSimulationTransport",
    "generate_simulation_batch",
    "validate_simulation_batch",
]
