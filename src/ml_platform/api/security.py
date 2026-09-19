"""Bounded ASGI ingress controls for a single API worker.

Credential checks and size limits run before JSON parsing/model/DB work. No
forwarding header is used as a rate-limit identity. Shared keys share a quota.
"""

import base64
import hashlib
import math
import re
import secrets
from time import monotonic
from uuid import uuid4

import anyio
from pydantic import SecretStr
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ml_platform.core.config import Settings
from ml_platform.observability.telemetry import Metrics

PUBLIC_PATHS = frozenset({"/health", "/ready", "/api/v1/dashboard", "/docs", "/openapi.json"})
PROBES = frozenset({"/health", "/ready"})
ADMIN_PATHS = frozenset({"/api/v1/labels", "/api/v1/models/reload", "/api/v1/monitoring/snapshot"})


def matches(expected: SecretStr | None, supplied: str) -> bool:
    # bytes comparison also handles non-ASCII malicious headers without TypeError.
    return bool(expected and expected.get_secret_value()) and secrets.compare_digest(
        expected.get_secret_value().encode() if expected else b"", supplied.encode()
    )


def content_policy(html: str, *, documentation: bool = False) -> str:
    def hashes(tag: str) -> str:
        blocks = re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", html, flags=re.DOTALL)
        return (
            " ".join(
                "'sha256-"
                + base64.b64encode(hashlib.sha256(block.encode()).digest()).decode()
                + "'"
                for block in blocks
                if block.strip()
            )
            or "'none'"
        )

    external = " https://cdn.jsdelivr.net" if documentation else ""
    return (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
        f"script-src {hashes('script')}{external}; style-src {hashes('style')}{external}; "
        "connect-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com"
    )


class WindowLimiter:
    """At most capacity identities retained; exhaustion denies new identities."""

    def __init__(self, capacity: int = 2048) -> None:
        self.capacity = capacity
        self.windows: dict[str, tuple[float, int]] = {}

    def allow(self, identity: str, limit: int, now: float) -> tuple[bool, int]:
        # Synchronous calls on the ASGI event loop cannot interleave this update.
        self.windows = {k: v for k, v in self.windows.items() if now - v[0] < 60}
        if identity not in self.windows and len(self.windows) >= self.capacity:
            return False, 60
        start, count = self.windows.get(identity, (now, 0))
        retry = max(1, math.ceil(60 - (now - start)))
        if count >= limit:
            return False, retry
        self.windows[identity] = (start, count + 1)
        return True, retry


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, metrics: Metrics) -> None:
        self.app, self.settings, self.metrics = app, settings, metrics
        self.limiter = WindowLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        config = self.settings
        headers = Headers(scope=scope)
        path = scope["path"].rstrip("/") or "/"
        request_id = headers.get("x-request-id", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id) is None:
            request_id = uuid4().hex

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                out = MutableHeaders(scope=message)
                out["X-Content-Type-Options"] = "nosniff"
                out["X-Frame-Options"] = "DENY"
                out["Referrer-Policy"] = "no-referrer"
                out["Cache-Control"] = "no-store"
                out["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if config.environment == "production":
                    out["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                # CORS must also apply to errors rejected before downstream middleware.
                origin = headers.get("origin")
                if origin is not None and origin in config.cors_origins:
                    out["Access-Control-Allow-Origin"] = origin
                    if "origin" not in out.get("Vary", "").lower():
                        out["Vary"] = ", ".join(filter(None, [out.get("Vary", ""), "Origin"]))
                out.setdefault("X-Request-ID", request_id)
                out.setdefault(
                    "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
                )
            await send(message)

        async def reject(status: int, detail: str, extra: dict[str, str] | None = None) -> None:
            self.metrics.requests.labels("security", str(status)).inc()
            response = JSONResponse({"detail": detail}, status_code=status, headers=extra)
            await response(scope, receive, secured_send)

        admin_values, api_values = headers.getlist("x-admin-key"), headers.getlist("x-api-key")
        if len(admin_values) > 1 or len(api_values) > 1:
            await reject(400, "Duplicate authentication headers")
            return
        role = "anonymous"
        if matches(config.admin_key, headers.get("x-admin-key", "")):
            role = "admin"
        elif matches(config.api_key, headers.get("x-api-key", "")):
            role = "api"
        preflight = scope["method"] == "OPTIONS" and "access-control-request-method" in headers
        if path not in PROBES:
            peer = str((scope.get("client") or ("unknown", 0))[0])
            identity = role if role != "anonymous" else "peer:" + peer
            limit = (
                config.rate_limit_per_minute
                if role != "anonymous"
                else config.anonymous_rate_limit_per_minute
            )
            allowed, retry = self.limiter.allow(identity, limit, monotonic())
            if not allowed:
                await reject(429, "Request limit exceeded", {"Retry-After": str(retry)})
                return
        if not preflight:
            if config.auth_enabled and path not in PUBLIC_PATHS and role == "anonymous":
                await reject(401, "A valid X-API-Key or X-Admin-Key is required")
                return
            if config.auth_enabled and path in ADMIN_PATHS and role != "admin":
                await reject(403, "An admin key is required")
                return
        if headers.get("content-encoding", "identity").lower() != "identity":
            await reject(415, "Compressed request bodies are not supported")
            return
        lengths = headers.getlist("content-length")
        if len(lengths) > 1 or (lengths and "transfer-encoding" in headers):
            await reject(400, "Ambiguous request framing")
            return
        length = None
        if lengths:
            if not lengths[0].isascii() or not lengths[0].isdecimal():
                await reject(400, "Invalid Content-Length")
                return
            if len(lengths[0]) > 12 or int(lengths[0]) > config.max_request_bytes:
                await reject(413, "Request body is too large")
                return
            length = int(lengths[0])
        body = bytearray()
        try:
            with anyio.fail_after(config.request_body_timeout_seconds):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    part = message.get("body", b"")
                    if len(body) + len(part) > config.max_request_bytes:
                        await reject(413, "Request body is too large")
                        return
                    body.extend(part)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "Request body timed out")
            return
        if length is not None and len(body) != length:
            await reject(400, "Request body length does not match Content-Length")
            return
        if body and scope["method"] in {"POST", "PUT", "PATCH"}:
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                await reject(415, "Use application/json")
                return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, secured_send)
