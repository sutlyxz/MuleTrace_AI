"""Unit tests for AWS Bedrock integration."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.backend.aws import (
    BEDROCK_TOOL_DEFINITIONS,
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    analyze_account_with_bedrock,
    analyze_case_with_bedrock,
    dispatch_engine_tool,
    generate_narrative_report,
    get_bedrock_runtime_client,
    is_boto3_available,
    run_investigation_agent,
)
from app.backend.aws.bedrock_service import is_boto3_available as service_boto3_check
from app.backend.config import BedrockSettings


class TestBedrockConfig(unittest.TestCase):
    def test_bedrock_settings_defaults(self):
        settings = BedrockSettings.from_environment({})
        self.assertEqual(settings.region, "us-east-1")
        self.assertEqual(settings.model_id, DEFAULT_MODEL_ID)

    def test_bedrock_settings_custom_env(self):
        env = {
            "AWS_REGION": "ap-southeast-1",
            "BEDROCK_MODEL_ID": "amazon.nova-pro-v1:0",
        }
        settings = BedrockSettings.from_environment(env)
        self.assertEqual(settings.region, "ap-southeast-1")
        self.assertEqual(settings.model_id, "amazon.nova-pro-v1:0")


class TestBedrockClient(unittest.TestCase):
    def test_get_client_raises_when_boto3_missing(self):
        with patch("app.backend.aws.bedrock_service.boto3", None):
            with self.assertRaises(RuntimeError) as context:
                get_bedrock_runtime_client()
            self.assertIn("boto3", str(context.exception))

    def test_get_client_with_custom_credentials(self):
        mock_boto3 = MagicMock()
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        with patch("app.backend.aws.bedrock_service.boto3", mock_boto3):
            client = get_bedrock_runtime_client(
                region_name="ap-southeast-1",
                aws_access_key_id="TEST_KEY",
                aws_secret_access_key="TEST_SECRET",
                aws_session_token="TEST_TOKEN",
            )
            mock_session.client.assert_called_once_with(
                service_name="bedrock-runtime",
                region_name="ap-southeast-1",
                aws_access_key_id="TEST_KEY",
                aws_secret_access_key="TEST_SECRET",
                aws_session_token="TEST_TOKEN",
            )

    def test_get_client_with_profile(self):
        mock_boto3 = MagicMock()
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        with patch("app.backend.aws.bedrock_service.boto3", mock_boto3):
            get_bedrock_runtime_client(profile_name="production-auditor")
            mock_boto3.Session.assert_called_once_with(profile_name="production-auditor", region_name=DEFAULT_REGION)


class TestBedrockTools(unittest.TestCase):
    def test_tool_definitions_schema(self):
        self.assertTrue(len(BEDROCK_TOOL_DEFINITIONS) >= 7)
        tool_names = [tool["toolSpec"]["name"] for tool in BEDROCK_TOOL_DEFINITIONS]
        self.assertIn("get_account_profile", tool_names)
        self.assertIn("detect_risk", tool_names)
        self.assertIn("trace_money", tool_names)
        self.assertIn("score_investigation", tool_names)
        self.assertIn("get_evidence", tool_names)

        for tool in BEDROCK_TOOL_DEFINITIONS:
            spec = tool["toolSpec"]
            self.assertTrue(spec.get("name"))
            self.assertTrue(spec.get("description"))
            self.assertIn("inputSchema", spec)

    def test_dispatch_engine_tool_account_profile(self):
        result = dispatch_engine_tool("get_account_profile", {"account_id": "B782"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["account_id"], "B782")

    def test_dispatch_engine_tool_trace_money(self):
        result = dispatch_engine_tool(
            "trace_money",
            {"source_account": "B782", "target_account": "C991", "max_hops": 4},
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("path_count", result["result"])

    def test_dispatch_engine_tool_detect_risk(self):
        result = dispatch_engine_tool("detect_risk", {"account_id": "B782"})
        self.assertEqual(result["status"], "success")
        self.assertIn("count", result["result"])

    def test_dispatch_engine_tool_unknown(self):
        with self.assertRaises(ValueError):
            dispatch_engine_tool("unknown_tool_name", {})

    def test_dispatch_engine_tool_handles_execution_error(self):
        result = dispatch_engine_tool("get_account_profile", {"account_id": ""})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "ValueError")


class TestBedrockReporting(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Executive Summary: High risk mule account detected."}],
                }
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 120, "outputTokens": 80, "totalTokens": 200},
        }

    def test_generate_narrative_report(self):
        sample_data = {"score": 85, "priority": "CRITICAL", "account_id": "B782"}
        response = generate_narrative_report(
            sample_data, client=self.mock_client, model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
        self.assertEqual(response["status"], "success")
        self.assertIn("High risk mule account detected", response["narrative"])
        self.assertEqual(response["usage"]["totalTokens"], 200)

    def test_analyze_case_with_bedrock(self):
        result = analyze_case_with_bedrock("CASE001", client=self.mock_client)
        self.assertEqual(result["case_id"], "CASE001")
        self.assertIn("score_data", result)
        self.assertIn("High risk", result["ai_narrative"])

    def test_analyze_account_with_bedrock(self):
        result = analyze_account_with_bedrock("B782", client=self.mock_client)
        self.assertEqual(result["account_id"], "B782")
        self.assertIn("profile", result)
        self.assertIn("High risk", result["ai_narrative"])


class TestBedrockAgent(unittest.TestCase):
    def test_agent_single_turn_completion(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Investigation finished. Account B782 has pass-through behavior."}],
                }
            },
            "stopReason": "end_turn",
            "usage": {"totalTokens": 150},
        }

        result = run_investigation_agent("Investigate B782", client=mock_client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["turns_taken"], 1)
        self.assertIn("Investigation finished", result["final_answer"])
        self.assertEqual(len(result["executed_tools"]), 0)

    def test_agent_with_tool_use_execution(self):
        mock_client = MagicMock()

        turn_1_response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "call_123",
                                "name": "get_account_profile",
                                "input": {"account_id": "B782"},
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        }

        turn_2_response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Based on profile, B782 is involved in 2 cases."}],
                }
            },
            "stopReason": "end_turn",
        }

        mock_client.converse.side_effect = [turn_1_response, turn_2_response]

        result = run_investigation_agent("Investigate B782", client=mock_client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["turns_taken"], 2)
        self.assertEqual(len(result["executed_tools"]), 1)
        self.assertEqual(result["executed_tools"][0]["tool"], "get_account_profile")
        self.assertEqual(result["executed_tools"][0]["status"], "success")
        self.assertIn("involved in 2 cases", result["final_answer"])


if __name__ == "__main__":
    unittest.main()
