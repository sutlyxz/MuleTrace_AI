"""Unit tests for MuleTrace AI Unified Web & API Server."""
from __future__ import annotations

import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from app.backend.server import MuleTraceRequestHandler


class DummySocket:
    def __init__(self, input_bytes: bytes):
        self.rfile = io.BytesIO(input_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str = "rb", buffering: int = -1):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes) -> None:
        self.wfile.write(b)

    def send(self, b: bytes) -> int:
        self.wfile.write(b)
        return len(b)

    def getpeername(self):
        return ("127.0.0.1", 12345)

    def getsockname(self):
        return ("127.0.0.1", 8000)


class DummyServer:
    def __init__(self):
        self.server_name = "127.0.0.1"
        self.server_port = 8000


class TestServerEndpoints(unittest.TestCase):
    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.frontend_dir = str(self.project_root / "app" / "frontend")

    def _execute_request(self, request_bytes: bytes) -> tuple[int, dict[str, str], bytes]:
        socket = DummySocket(request_bytes)
        server = DummyServer()
        handler = MuleTraceRequestHandler(socket, ("127.0.0.1", 12345), server, directory=self.frontend_dir)
        raw_output = socket.wfile.getvalue()

        # Parse status line and headers
        parts = raw_output.split(b"\r\n\r\n", 1)
        header_text = parts[0].decode("iso-8859-1")
        body = parts[1] if len(parts) > 1 else b""

        lines = header_text.split("\r\n")
        status_line = lines[0]
        status_code = int(status_line.split(" ")[1])

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        return status_code, headers, body

    def test_options_cors_preflight(self):
        req = b"OPTIONS /api/ai/summary HTTP/1.1\r\nHost: localhost\r\n\r\n"
        status, headers, _ = self._execute_request(req)
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertIn("POST", headers.get("access-control-allow-methods", ""))

    def test_get_api_health(self):
        req = b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("content-type", ""))
        data = json.loads(body.decode("utf-8"))
        self.assertIn("status", data)
        self.assertIn("available_tools", data)

    def test_get_api_cases(self):
        req = b"GET /api/cases HTTP/1.1\r\nHost: localhost\r\n\r\n"
        status, headers, body = self._execute_request(req)
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "success")
        self.assertIn("cases", data)
        self.assertTrue(len(data["cases"]) > 0)

    def test_post_ai_summary_success(self):
        req_payload = json.dumps({
            "case_id": "MT-1042",
            "investigation": {"priority_score": 85, "risk_level": "High"}
        }).encode("utf-8")

        req = (
            b"POST /api/ai/summary HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(req_payload)).encode("ascii") + b"\r\n\r\n"
            + req_payload
        )

        with patch("app.backend.aws.bedrock_service.generate_narrative_report") as mock_report:
            mock_report.return_value = {
                "status": "success",
                "narrative": "AI Summary: High-velocity fan-in flow detected.",
            }
            status, headers, body = self._execute_request(req)

        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "success")
        self.assertIn("High-velocity fan-in flow detected", data.get("summary", ""))

    def test_post_ai_summary_passes_language_to_bedrock(self):
        req_payload = json.dumps({
            "case_id": "CASE001",
            "language": "th",
        }).encode("utf-8")

        req = (
            b"POST /api/ai/summary HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(req_payload)).encode("ascii") + b"\r\n\r\n"
            + req_payload
        )

        with patch("app.backend.aws.bedrock_service.generate_narrative_report") as mock_report:
            mock_report.return_value = {"status": "success", "narrative": "??????????"}
            status, headers, body = self._execute_request(req)
            self.assertEqual(status, 200)
            mock_report.assert_called_once()
            self.assertEqual(mock_report.call_args[1].get("language"), "th")

    def test_post_ai_summary_fallback_on_bedrock_error(self):
        req_payload = json.dumps({"case_id": "CASE001", "language": "en"}).encode("utf-8")
        req = (
            b"POST /api/ai/summary HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(req_payload)).encode("ascii") + b"\r\n\r\n"
            + req_payload
        )

        with patch("app.backend.aws.bedrock_service.generate_narrative_report", side_effect=RuntimeError("Offline")):
            status, headers, body = self._execute_request(req)

        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("status"), "success")
        self.assertIn("MuleTrace AML Rule Engine Report", data.get("summary", ""))


if __name__ == "__main__":
    unittest.main()
