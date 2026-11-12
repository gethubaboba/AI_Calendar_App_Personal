"""Low-cardinality Prometheus metrics for HTTP requests."""

from time import perf_counter
from typing import Callable

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response


registry = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Completed HTTP requests, excluding the metrics scrape endpoint.",
    ("method", "route", "status"),
    registry=registry,
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds, excluding the metrics scrape endpoint.",
    ("method", "route"),
    registry=registry,
)

_KNOWN_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class RequestMetricsMiddleware:
    """ASGI middleware that records route templates, never raw paths or queries."""

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        method = method if method in _KNOWN_METHODS else "OTHER"
        status_code = 500
        started = perf_counter()

        async def record_status(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, record_status)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "/unmatched")
            HTTP_REQUESTS.labels(method, route_template, str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method, route_template).observe(perf_counter() - started)


def render_metrics() -> Response:
    """Render the registry using the Prometheus text exposition format."""
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

