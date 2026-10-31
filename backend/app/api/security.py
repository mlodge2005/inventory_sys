"""Browser request checks for an unauthenticated V1 API.

A custom header forces a CORS preflight, which blocks a foreign website from
issuing a simple cross-site state change. This is not authentication.
"""

from __future__ import annotations

from starlette.responses import JSONResponse

from app.core.config import Settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-robots-tag", b"noindex, nofollow"),
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self'; "
        b"style-src-attr 'unsafe-inline'; img-src 'self' data:; "
        b"base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    ),
)


class SecurityMiddleware:
    def __init__(self, app, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope["method"].upper()
        path = scope.get("path", "")
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope["headers"]}
        if method in UNSAFE and path.startswith("/api/"):
            if headers.get("x-cyberdeck-request") != "1":
                response = _error(
                    403,
                    "forbidden",
                    "State-changing requests must include the header X-Cyberdeck-Request: 1.",
                )
                await response(scope, receive, send)
                return
            origin = headers.get("origin")
            if origin and not _origin_allowed(origin, headers.get("host", ""), self.settings):
                response = _error(403, "forbidden", "Origin is not allowed.")
                await response(scope, receive, send)
                return
            if method in {"POST", "PUT", "PATCH"}:
                content_length = headers.get("content-length", "")
                has_body = content_length.isdigit() and int(content_length) > 0
                content_type = headers.get("content-type", "")
                allowed = content_type.startswith("application/json") or content_type.startswith(
                    "multipart/form-data"
                )
                if has_body and not allowed:
                    response = _error(415, "unsupported_media_type", "Send JSON requests as application/json.")
                    await response(scope, receive, send)
                    return
        if headers.get("content-length", "").isdigit() and int(headers["content-length"]) > self.settings.max_body_bytes:
            response = _error(413, "payload_too_large", "Request body is too large.")
            await response(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                existing = {key.lower() for key, _value in message.get("headers", [])}
                merged = list(message.get("headers", []))
                for key, value in SECURITY_HEADERS:
                    if key not in existing:
                        merged.append((key, value))
                if path.startswith("/api/") and b"cache-control" not in existing:
                    merged.append((b"cache-control", b"no-store"))
                message["headers"] = merged
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _origin_allowed(origin: str, host: str, settings: Settings) -> bool:
    if origin in set(settings.allowed_origins_list):
        return True
    if host and origin in {f"http://{host}", f"https://{host}"}:
        return True
    return False


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": {}}},
    )
