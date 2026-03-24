# Author: gadwant
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from mcpool.cloudwatch import CloudWatchPublisher
from mcpool.metrics import PoolMetrics


class TestCloudWatchPublisher:
    def test_import_error_when_no_boto3(self):
        """Should raise ImportError if boto3 is missing."""
        publisher = CloudWatchPublisher(namespace="TestSpace")
        with patch.dict("sys.modules", {"boto3": None}):
            with pytest.raises(ImportError, match="boto3 is required"):
                publisher.publish(PoolMetrics())

    def test_publish_success(self):
        """Should successfully publish metrics via boto3."""
        metrics = PoolMetrics()
        metrics.borrow_count = 42
        metrics.errors = 2

        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            publisher = CloudWatchPublisher(
                namespace="MyNS",
                dimensions={"Env": "Prod"},
                region_name="us-east-1"
            )
            publisher.publish(metrics)

        # Verify client created with region
        mock_boto3.client.assert_called_once_with("cloudwatch", region_name="us-east-1")
        
        # Verify put_metric_data called
        mock_client.put_metric_data.assert_called_once()
        call_kwargs = mock_client.put_metric_data.call_args[1]
        
        assert call_kwargs["Namespace"] == "MyNS"
        metric_data = call_kwargs["MetricData"]
        
        # Verify some specific metrics made it
        metric_names = [m["MetricName"] for m in metric_data]
        assert "BorrowCount" in metric_names
        assert "Errors" in metric_names
        assert "ActiveSessions" in metric_names
        
        # Verify dimensions
        for m in metric_data:
            assert m["Dimensions"] == [{"Name": "Env", "Value": "Prod"}]
            
        # Verify specific values
        borrow_metric = next(m for m in metric_data if m["MetricName"] == "BorrowCount")
        assert borrow_metric["Value"] == 42.0

    def test_publish_exception_handled(self, caplog):
        """Exceptions during publish should be swallowed and logged."""
        metrics = PoolMetrics()
        
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_client.put_metric_data.side_effect = Exception("AWS Error")
        mock_boto3.client.return_value = mock_client
        
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            publisher = CloudWatchPublisher()
            publisher.publish(metrics)  # Should not raise

        assert "Failed to publish metrics to CloudWatch" in caplog.text
