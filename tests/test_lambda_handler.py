"""Unit tests for AWS Lambda API Gateway handler."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.backend.aws.lambda_handler import (
    handle_api_request,
    lambda_handler,
)


class TestLambdaHandler(unittest.TestCase):
    def test_lambda_api_gateway_options(self):
        event = {
            "httpMethod": "OPTIONS",
            "path": "/api/ai/summary",
        }
        res = lambda_handler(event)
        self.assertEqual(res["statusCode"], 200)
        self.assertIn("Access-Control-Allow-Origin", res["headers"])

    def test_lambda_api_gateway_health(self):
        event = {
            "httpMethod": "GET",
            "path": "/health",
        }
        res = lambda_handler(event)
        self.assertEqual(res["statusCode"], 200)
        body = json.loads(res["body"])
        self.assertIn("status", body)

    def test_lambda_api_gateway_cases(self):
        event = {
            "httpMethod": "GET",
            "path": "/cases",
        }
        res = lambda_handler(event)
        self.assertEqual(res["statusCode"], 200)
        body = json.loads(res["body"])
        self.assertIn("cases", body)

    def test_lambda_static_login_asset(self):
        event = {
            "httpMethod": "GET",
            "path": "/login.html",
        }
        res = lambda_handler(event)
        self.assertEqual(res["statusCode"], 200)
        self.assertIn("text/html", res["headers"]["Content-Type"])

    def test_lambda_auth_login_and_me(self):
        login_event = {
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "body": json.dumps({"email": "officer@agency.go.th", "password": "OfficerPass123!@#"}),
        }
        res = lambda_handler(login_event)
        self.assertEqual(res["statusCode"], 200)
        data = json.loads(res["body"])
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["user"]["role"], "user")

        me_event = {
            "httpMethod": "GET",
            "path": "/api/auth/me",
        }
        me_res = lambda_handler(me_event)
        self.assertEqual(me_res["statusCode"], 200)
    def test_lambda_api_gateway_ai_summary(self):
        event = {
            "httpMethod": "POST",
            "path": "/api/ai/summary",
            "body": json.dumps({
                "case_id": "CASE001",
                "language": "th",
                "investigation": {
                    "score": 92,
                    "priority": "High",
                    "rule_types_matched": ["rapid_outgoing", "multiple_incoming"],
                },
            }),
        }
        with patch("app.backend.aws.lambda_handler.upload_report_to_s3") as mock_s3, \
             patch("app.backend.aws.lambda_handler.save_investigation_alert") as mock_dynamo, \
             patch("app.backend.aws.lambda_handler.generate_narrative_report") as mock_bedrock:

            mock_s3.return_value = {"status": "success", "url": "s3://test/key"}
            mock_dynamo.return_value = {"status": "success", "table": "test-table"}
            mock_bedrock.return_value = {"narrative": "ข้อสรุปการตรวจพบบัญชีม้า: พฤติกรรมโอนเข้าออกรวดเร็ว"}

            res = lambda_handler(event)
            self.assertEqual(res["statusCode"], 200)
            body = json.loads(res["body"])
            self.assertEqual(body["status"], "success")
            self.assertIn("ข้อสรุปการตรวจพบบัญชีม้า", body["summary"])
            mock_s3.assert_called_once()
            mock_dynamo.assert_called_once()

    def test_lambda_eventbridge_trigger(self):
        """Test direct / event trigger invocation without API Gateway wrapper."""
        event = {
            "source": "aws.custom",
            "detail-type": "MuleTraceTransactionEvaluated",
            "detail": {"case_id": "CASE001"},
        }
        with patch("app.backend.aws.lambda_handler.upload_report_to_s3") as mock_s3, \
             patch("app.backend.aws.lambda_handler.save_investigation_alert") as mock_dynamo:

            mock_s3.return_value = {"status": "success"}
            mock_dynamo.return_value = {"status": "success"}

            res = lambda_handler(event)
            self.assertEqual(res["status"], "processed")
            self.assertEqual(res["case_id"], "CASE001")


if __name__ == "__main__":
    unittest.main()
