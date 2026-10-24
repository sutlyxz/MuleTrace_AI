"""Unit tests for Amazon DynamoDB integration service."""
from __future__ import annotations

from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

from app.backend.aws.dynamodb_service import (
    DEFAULT_TABLE_NAME,
    _desanitize_from_dynamodb,
    _sanitize_for_dynamodb,
    ensure_dynamodb_table,
    get_default_table_name,
    get_dynamodb_resource,
    get_investigation_alert,
    is_dynamodb_available,
    save_investigation_alert,
)


class TestDynamoDBService(unittest.TestCase):
    def test_availability_check(self):
        self.assertTrue(is_dynamodb_available())

    def test_get_default_table_name(self):
        self.assertEqual(get_default_table_name({}), DEFAULT_TABLE_NAME)
        self.assertEqual(
            get_default_table_name({"DYNAMODB_TABLE_NAME": "CustomAlerts"}),
            "CustomAlerts",
        )

    def test_get_dynamodb_resource_missing_boto3(self):
        with patch("app.backend.aws.dynamodb_service.boto3", None):
            with self.assertRaises(RuntimeError):
                get_dynamodb_resource()

    def test_sanitize_and_desanitize(self):
        data = {"score": 85.5, "list": [1.2, "test", 3]}
        sanitized = _sanitize_for_dynamodb(data)
        self.assertIsInstance(sanitized["score"], Decimal)
        self.assertIsInstance(sanitized["list"][0], Decimal)

        restored = _desanitize_from_dynamodb(sanitized)
        self.assertEqual(restored["score"], 85.5)
        self.assertEqual(restored["list"][0], 1.2)

    def test_ensure_dynamodb_table(self):
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_table.load.return_value = None

        res = ensure_dynamodb_table("test-table", dynamodb=mock_resource)
        self.assertTrue(res)

    def test_save_investigation_alert_success(self):
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_resource.Table.return_value = mock_table

        alert_data = {"score": 90, "priority": "High", "finding_count": 3}
        res = save_investigation_alert("CASE001", alert_data, table_name="test-table", dynamodb=mock_resource)

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["case_id"], "CASE001")
        mock_table.put_item.assert_called_once()

    def test_save_investigation_alert_graceful_error(self):
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.put_item.side_effect = Exception("ProvisionedThroughputExceeded")
        mock_resource.Table.return_value = mock_table

        res = save_investigation_alert("CASE001", {}, table_name="test-table", dynamodb=mock_resource)
        self.assertEqual(res["status"], "error")
        self.assertIn("ProvisionedThroughputExceeded", res["message"])

    def test_get_investigation_alert_success(self):
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "case_id": "CASE001",
                "score": Decimal("90"),
                "priority": "High",
            }
        }
        mock_resource.Table.return_value = mock_table

        res = get_investigation_alert("CASE001", table_name="test-table", dynamodb=mock_resource)
        self.assertIsNotNone(res)
        self.assertEqual(res["score"], 90)

    def test_get_investigation_alert_not_found(self):
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_resource.Table.return_value = mock_table

        res = get_investigation_alert("CASE999", table_name="test-table", dynamodb=mock_resource)
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
