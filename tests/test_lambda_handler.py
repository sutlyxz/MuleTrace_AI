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
        with patch("app.backend.aws.lambda_handler.get_investigation_alert", return_value=None):
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
        # 1. Reject invalid credentials
        bad_login = {
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "body": json.dumps({"email": "officer@agency.go.th", "password": "WrongPassword!"}),
        }
        bad_res = lambda_handler(bad_login)
        self.assertEqual(bad_res["statusCode"], 401)

        # 2. Reject unauthenticated /me
        no_cookie_me = {
            "httpMethod": "GET",
            "path": "/api/auth/me",
        }
        no_res = lambda_handler(no_cookie_me)
        self.assertEqual(no_res["statusCode"], 401)

        # 3. Successful login returns cryptographically signed cookie
        login_event = {
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "body": json.dumps({"email": "officer@agency.go.th", "password": "OfficerPass123!@#"}),
        }
        res = lambda_handler(login_event)
        self.assertEqual(res["statusCode"], 200)
        data = json.loads(res["body"])
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["user"]["role"], "user")
        self.assertIn("cookies", res)

        # 4. Valid session cookie verifies successfully
        cookie_header = res["cookies"][0].split(";")[0]
        me_event = {
            "httpMethod": "GET",
            "path": "/api/auth/me",
            "headers": {"cookie": cookie_header},
        }
        me_res = lambda_handler(me_event)
        self.assertEqual(me_res["statusCode"], 200)
        me_data = json.loads(me_res["body"])
        self.assertEqual(me_data["status"], "success")
        self.assertEqual(me_data["user"]["role"], "user")

        # 5. Tampered cookie is rejected
        tampered_event = {
            "httpMethod": "GET",
            "path": "/api/auth/me",
            "headers": {"cookie": cookie_header + "tampered"},
        }
        self.assertEqual(lambda_handler(tampered_event)["statusCode"], 401)
    def test_lambda_admin_user_crud_and_login_flow(self):
        # 1. Create a brand new Bank Officer
        create_event = {
            "httpMethod": "POST",
            "path": "/api/admin/users",
            "body": json.dumps({
                "email": "new.officer@bank.go.th",
                "password": "SecurePassword123!@#",
                "display_name": "Special Agent Somchai",
            }),
        }
        create_res = lambda_handler(create_event)
        self.assertEqual(create_res["statusCode"], 201)
        created_data = json.loads(create_res["body"])
        self.assertEqual(created_data["status"], "success")
        new_user = created_data["user"]
        self.assertEqual(new_user["email"], "new.officer@bank.go.th")
        user_id = new_user["id"]

        # 2. Log in with the newly created user!
        new_login_event = {
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "body": json.dumps({
                "email": "new.officer@bank.go.th",
                "password": "SecurePassword123!@#",
            }),
        }
        login_res = lambda_handler(new_login_event)
        self.assertEqual(login_res["statusCode"], 200)
        login_data = json.loads(login_res["body"])
        self.assertEqual(login_data["status"], "success")
        self.assertEqual(login_data["user"]["role"], "user")

        # 3. Deactivate the new user
        deactivate_event = {
            "httpMethod": "PATCH",
            "path": f"/api/admin/users/{user_id}/status",
            "body": json.dumps({"is_active": False}),
        }
        deact_res = lambda_handler(deactivate_event)
        self.assertEqual(deact_res["statusCode"], 200)

        # 4. Deactivated user cannot log in
        blocked_res = lambda_handler(new_login_event)
        self.assertEqual(blocked_res["statusCode"], 401)

        # 5. Reset password
        reset_event = {
            "httpMethod": "POST",
            "path": f"/api/admin/users/{user_id}/reset-password",
            "body": json.dumps({"new_password": "BrandNewPassword999!@#"}),
        }
        reset_res = lambda_handler(reset_event)
        self.assertEqual(reset_res["statusCode"], 200)

        # 6. Reactivate user
        reactivate_event = {
            "httpMethod": "PATCH",
            "path": f"/api/admin/users/{user_id}/status",
            "body": json.dumps({"is_active": True}),
        }
        self.assertEqual(lambda_handler(reactivate_event)["statusCode"], 200)

        # 7. Log in with the new password
        success_after_reset = {
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "body": json.dumps({
                "email": "new.officer@bank.go.th",
                "password": "BrandNewPassword999!@#",
            }),
        }
        self.assertEqual(lambda_handler(success_after_reset)["statusCode"], 200)
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
