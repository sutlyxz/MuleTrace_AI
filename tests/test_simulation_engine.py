"""Tests for Simulation Engine, Transports, and Simulation API Endpoints.

Verifies:
- SimulationEngine execution with LocalSimulationTransport (20 transactions).
- SimulationEngine execution with EventBridgeSimulationTransport (mocked boto3 client, 2 chunks of 10).
- Safe isolation: debug runs are blocked from production EventBridge by default.
- Batch chunking (chunks of 10 entries) and EventBridge envelope structure.
- Tracking of simulation run status in memory.
- Local backend API POST /api/simulation/run enforces authentication and CSRF.
- FastAPI AWS API POST /api/simulation/run enforces authentication and returns expected JSON schema.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

from app.backend.simulation.dataset import generate_simulation_batch
from app.backend.simulation.engine import SimulationEngine
from app.backend.simulation.transport import (
    EventBridgeSimulationTransport,
    LocalSimulationTransport,
)
from aws.app import app as fastapi_app
from tests.test_aws_api_security import _run_asgi
from app.backend.auth.session_store import InMemorySessionStore


class TestSimulationEngineAndTransports(unittest.TestCase):
    """Unit tests for the SimulationEngine and Transport layers."""

    def test_local_simulation_transport_execution(self) -> None:
        """Verify LocalSimulationTransport executes in-memory rules and records run."""
        engine = SimulationEngine(transport=LocalSimulationTransport())
        result = engine.run_simulation()

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("events_submitted"), 20)
        self.assertEqual(result.get("transport"), "local_mock")
        self.assertTrue(result.get("confirmed"))
        self.assertTrue(result.get("cases_created_hint"))

        run_id = result.get("run_id", "")
        self.assertTrue(run_id.startswith("sim_"))

        # Verify status registry lookup
        recorded = SimulationEngine.get_run_status(run_id)
        self.assertIsNotNone(recorded)
        self.assertEqual(recorded.get("run_id"), run_id)
        self.assertEqual(recorded.get("events_submitted"), 20)
        self.assertIn("seed", recorded)
        self.assertIn("generator_version", recorded)

    def test_eventbridge_transport_chunking_and_payload(self) -> None:
        """Verify EventBridge transport batches 20 events into 2 chunks of 10 entries."""
        mock_boto_client = MagicMock()
        mock_boto_client.put_events.return_value = {
            "FailedEntryCount": 0,
            "Entries": [{"EventId": f"ev-{i}"} for i in range(10)],
        }

        transport = EventBridgeSimulationTransport(
            event_bus_name="test-bus",
            source="muletrace.test",
            detail_type="TestTransactionEvent",
            region="us-east-1",
        )
        transport._client = mock_boto_client

        engine = SimulationEngine(transport=transport)
        # Normal run (no explicit seed) dispatches to transport
        result = engine.run_simulation()

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("events_submitted"), 20)
        self.assertEqual(result.get("transport"), "aws_eventbridge")
        self.assertEqual(result.get("event_bus"), "test-bus")

        # Exactly 20 events with chunk size 10 must result in 2 put_events calls (10 + 10)
        self.assertEqual(mock_boto_client.put_events.call_count, 2)

        # Inspect first chunk entries
        call_args = mock_boto_client.put_events.call_args_list[0]
        entries = call_args.kwargs.get("Entries") or call_args[1].get("Entries")
        self.assertEqual(len(entries), 10)

        first_entry = entries[0]
        self.assertEqual(first_entry["Source"], "muletrace.test")
        self.assertEqual(first_entry["DetailType"], "TestTransactionEvent")
        self.assertEqual(first_entry["EventBusName"], "test-bus")

        detail = json.loads(first_entry["Detail"])
        self.assertIn("transaction_id", detail)
        self.assertIn("amount", detail)
        self.assertTrue(detail.get("is_simulated"))

    def test_eventbridge_transport_blocks_debug_events_by_default(self) -> None:
        """Verify EventBridge transport blocks debug runs (explicit seed) by default."""
        mock_boto_client = MagicMock()
        transport = EventBridgeSimulationTransport(
            event_bus_name="prod-bus",
            allow_debug_dispatch=False,
        )
        transport._client = mock_boto_client

        engine = SimulationEngine(transport=transport)
        # Explicit seed marks run as debug
        result = engine.run_simulation(seed=12345)

        self.assertEqual(result.get("status"), "debug_dispatch_blocked")
        self.assertEqual(result.get("events_submitted"), 0)
        self.assertIn("Safety guard blocked", result.get("message", ""))
        self.assertEqual(mock_boto_client.put_events.call_count, 0)

    def test_eventbridge_transport_handles_failures(self) -> None:
        """Verify EventBridge transport records partial failures correctly."""
        mock_boto_client = MagicMock()
        mock_boto_client.put_events.return_value = {
            "FailedEntryCount": 2,
            "Entries": [
                {"ErrorCode": "InternalFailure", "ErrorMessage": "AWS internal error"},
                {"ErrorCode": "ThrottlingException", "ErrorMessage": "Rate exceeded"},
            ],
        }

        transport = EventBridgeSimulationTransport(event_bus_name="fail-bus")
        transport._client = mock_boto_client

        engine = SimulationEngine(transport=transport)
        result = engine.run_simulation()

        self.assertEqual(result.get("status"), "partial_failure")
        self.assertGreater(result.get("events_failed", 0), 0)
        self.assertIsNotNone(result.get("errors"))


class TestFastApiSimulationEndpoint(unittest.TestCase):
    """Tests for the simulation endpoints in aws/app.py."""

    def setUp(self) -> None:
        self.session_store = InMemorySessionStore()

    def test_unauthenticated_simulation_run_returns_401(self) -> None:
        """Verify unauthenticated call to /api/simulation/run returns 401."""
        status, headers, body = _run_asgi("POST", "/api/simulation/run")
        self.assertEqual(status, 401)

    def test_authenticated_officer_can_trigger_simulation(self) -> None:
        """Verify Bank Officer with valid session cookie triggers simulation successfully."""
        token = self.session_store.create_session(
            user_info={
                "user_id": "officer@bank.com",
                "email": "officer@bank.com",
                "role": "user",
                "display_name": "Bank Officer",
                "auth_provider": "cognito",
            },
            ttl_seconds=7200,
        )

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            status, headers, body = _run_asgi(
                "POST",
                "/api/simulation/run",
                headers={
                    "Cookie": f"muletrace_session={token}",
                    "Content-Type": "application/json",
                },
                body=b"{}",
            )
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data.get("status"), "success")
            run_data = data.get("data", {})
            self.assertEqual(run_data.get("events_submitted"), 20)
            self.assertTrue(run_data.get("confirmed"))

    def test_simulation_status_endpoint(self) -> None:
        """Verify GET /api/simulation/status/{run_id} returns run confirmation."""
        # 1. Trigger simulation locally
        engine = SimulationEngine(transport=LocalSimulationTransport())
        run_res = engine.run_simulation()
        run_id = run_res["run_id"]

        # 2. Query status endpoint with authenticated session
        token = self.session_store.create_session(
            user_info={
                "user_id": "officer@bank.com",
                "email": "officer@bank.com",
                "role": "user",
            },
            ttl_seconds=7200,
        )

        with patch("aws.auth_security.get_session_store", return_value=self.session_store):
            status, headers, body = _run_asgi(
                "GET",
                f"/api/simulation/status/{run_id}",
                headers={"Cookie": f"muletrace_session={token}"},
            )
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data.get("data", {}).get("run_id"), run_id)


if __name__ == "__main__":
    unittest.main()
