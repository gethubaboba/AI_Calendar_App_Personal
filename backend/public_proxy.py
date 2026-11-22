"""Narrow local entry point for the public Tailscale Funnel.

Run on 127.0.0.1:8010 and point Funnel here, never at the main API port.
Only ASCII /api/* paths are forwarded; the backend's metrics and docs stay
outside this public entry point.
"""

import os
import re

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.router.redirect_slashes = False
UPSTREAM = os.getenv("PUBLIC_API_UPSTREAM", "http://127.0.0.1:8000").rstrip("/")
MAX_REQUEST_BYTES = 1024 * 1024
PUBLIC_PATH = re.compile(rb"/api/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]*\Z")
HOP_HEADERS = {
    "connection", "content-length", "content-encoding", "host",
    "keep-alive", "proxy-authenticate", "proxy-authorization",
    "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade",
}


@app.api_route(
    "/api/{api_path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def forward_api(request: Request, api_path: str) -> Response:
    # Some ASGI clients include the query in raw_path despite providing it
    # separately in query_string. Validate and forward the path only once.
    raw_path = request.scope.get("raw_path", b"").split(b"?", 1)[0]
    if not PUBLIC_PATH.fullmatch(raw_path):
        return PlainTextResponse("Not Found", status_code=404)

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            return PlainTextResponse("Request too large", status_code=413)
        body.extend(chunk)

    request_headers = {
        name: value for name, value in request.headers.items()
        if name.lower() not in HOP_HEADERS
    }
    query = request.scope.get("query_string", b"")
    if len(query) > 4096 or not query.isascii():
        return PlainTextResponse("Invalid query", status_code=400)
    target = UPSTREAM + raw_path.decode("ascii")
    if query:
        target += "?" + query.decode("ascii")

    try:
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            upstream = await client.request(
                request.method, target, content=bytes(body), headers=request_headers,
                follow_redirects=False,
            )
    except httpx.RequestError:
        return PlainTextResponse("API unavailable", status_code=502)

    response_headers = {
        name: value for name, value in upstream.headers.items()
        if name.lower() not in HOP_HEADERS and name.lower() != "location"
    }
    location = upstream.headers.get("location")
    if location:
        response_headers["location"] = (
            location[len(UPSTREAM):]
            if location.startswith(UPSTREAM + "/api/") else location
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
