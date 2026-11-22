"""Security and browser preflight checks for the public API entry point."""

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from public_proxy import UPSTREAM, app


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, method, url, **kwargs):
        self.call = (method, url, kwargs)
        return self.response


class PublicProxyTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_only_api_is_public(self):
        for path in ("/metrics", "/docs", "/openapi.json", "/health", "/api/%2e%2e/metrics"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_preflight_and_auth_headers_reach_backend(self):
        origin = "https://gethubaboba.github.io"
        fake = FakeClient(httpx.Response(200, headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "DELETE, GET, OPTIONS, POST, PUT",
        }))
        with patch("public_proxy.httpx.AsyncClient", return_value=fake):
            response = self.client.options("/api/events?month=11", headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Authorization": "Bearer demo",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], origin)
        self.assertEqual(fake.call[0], "OPTIONS")
        self.assertEqual(fake.call[1], f"{UPSTREAM}/api/events?month=11")
        self.assertEqual(fake.call[2]["headers"]["origin"], origin)
        self.assertEqual(fake.call[2]["headers"]["authorization"], "Bearer demo")

    def test_large_request_is_rejected_before_backend(self):
        response = self.client.post("/api/agent/import", content=b"x" * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
