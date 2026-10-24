"""Unit tests for Amazon S3 integration service."""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from app.backend.aws.s3_service import (
    DEFAULT_BUCKET_NAME,
    ensure_s3_bucket,
    get_default_bucket_name,
    get_report_from_s3,
    get_s3_client,
    is_s3_available,
    upload_dataset_to_s3,
    upload_report_to_s3,
)


class TestS3Service(unittest.TestCase):
    def test_availability_check(self):
        self.assertTrue(is_s3_available())

    def test_get_default_bucket_name(self):
        self.assertEqual(get_default_bucket_name({}), DEFAULT_BUCKET_NAME)
        self.assertEqual(
            get_default_bucket_name({"S3_BUCKET_NAME": "custom-mule-bucket"}),
            "custom-mule-bucket",
        )

    def test_get_s3_client_missing_boto3(self):
        with patch("app.backend.aws.s3_service.boto3", None):
            with self.assertRaises(RuntimeError):
                get_s3_client()

    def test_ensure_s3_bucket(self):
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}
        res = ensure_s3_bucket("test-bucket", client=mock_client)
        self.assertTrue(res)
        mock_client.head_bucket.assert_called_with(Bucket="test-bucket")

    def test_upload_report_to_s3_success(self):
        mock_client = MagicMock()
        mock_client.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}

        report_data = {"score": 85, "priority": "High"}
        result = upload_report_to_s3("CASE001", report_data, bucket_name="test-bucket", client=mock_client)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["bucket"], "test-bucket")
        self.assertIn("reports/CASE001/investigation_summary.json", result["key"])
        mock_client.put_object.assert_called_once()

    def test_upload_report_to_s3_graceful_error(self):
        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("S3 access denied")

        result = upload_report_to_s3("CASE001", {}, bucket_name="test-bucket", client=mock_client)
        self.assertEqual(result["status"], "error")
        self.assertIn("access denied", result["message"])

    def test_get_report_from_s3_success(self):
        mock_client = MagicMock()
        sample_data = {"case_id": "CASE001", "score": 90}
        body_stream = io.BytesIO(json.dumps(sample_data).encode("utf-8"))
        mock_client.get_object.return_value = {"Body": body_stream}

        data = get_report_from_s3("CASE001", bucket_name="test-bucket", client=mock_client)
        self.assertIsNotNone(data)
        self.assertEqual(data["score"], 90)

    def test_get_report_from_s3_not_found(self):
        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("NoSuchKey")

        data = get_report_from_s3("CASE999", bucket_name="test-bucket", client=mock_client)
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
