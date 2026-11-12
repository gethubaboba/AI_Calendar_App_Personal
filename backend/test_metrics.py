"""Tests for HTTP instrumentation and the Prometheus scrape endpoint."""

import re
import unittest

from fastapi.testclient import TestClient

from main import app


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_request_count_uses_route_template_and_status(self):
        before = self.client.get("/metrics").text
        response = self.client.get("/health")
        after = self.client.get("/metrics")

        self.assertEqual(200, response.status_code)
        metric_line = re.search(
            r'http_requests_total\{method="GET",route="/health",status="200"\} (\d+(?:\.\d+)?)',
            after.text,
        )
        self.assertIsNotNone(metric_line)
        previous = re.search(
            r'http_requests_total\{method="GET",route="/health",status="200"\} (\d+(?:\.\d+)?)',
            before,
        )
        self.assertGreater(float(metric_line.group(1)), float(previous.group(1)) if previous else 0)

    def test_metrics_endpoint_is_not_counted(self):
        before = self.client.get("/metrics").text
        self.client.get("/metrics")
        after = self.client.get("/metrics").text
        self.assertEqual(before, after)
        self.assertNotIn('route="/metrics"', after)

    def test_raw_path_and_query_values_are_not_exposed(self):
        private_path = "/api/events/987654321"
        secret_query = "private-query-marker"
        self.client.get(private_path + "?search=" + secret_query)
        metrics = self.client.get("/metrics").text

        self.assertNotIn(private_path, metrics)
        self.assertNotIn(secret_query, metrics)
        self.assertIn('route="/api/events/{event_id}"', metrics)

    def test_duration_metric_is_exported(self):
        self.client.get("/health")
        metrics = self.client.get("/metrics")
        self.assertEqual(200, metrics.status_code)
        self.assertIn("http_request_duration_seconds_count{method=\"GET\",route=\"/health\"}", metrics.text)
        self.assertIn("text/plain", metrics.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
