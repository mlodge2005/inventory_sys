"""FastAPI application serving the JSON API and, when built, the web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from app import __version__
from app.api.docs_page import DOCS_CSS, render_docs
from app.api.security import SecurityMiddleware
from app.api.v1.router import router
from app.core.config import Settings, get_settings
from app.core.errors import InventoryError, error_payload
from app.db.session import make_engine, make_session_factory
from app.services.network import detect_addresses, exposure_warnings

logger = logging.getLogger("cyberdeck.inventory")

API_DESCRIPTION = """
Local inventory API for Cyberdeck drawers.

There is no user authentication in version 1. Do not publish this port on the
internet, and do not enable Tailscale Funnel. State-changing requests must send
`X-Cyberdeck-Request: 1` plus `Content-Type: application/json`. That header is a
browser cross-site check, not a credential.

Quantity totals are the sum of drawer allocations. `initial_quantity` is a fixed
baseline and is not changed by restocking. `threshold_configured` is false when
the baseline is zero and no absolute override is set (`baseline_state` is then
`BASELINE_NOT_SET`). Transaction `quantity_before` and `quantity_after` describe
the primary drawer slot, not the part total.
""".strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.resolved_database_path, immediate=True)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.environment == "production" and not settings.database_path.is_absolute():
            raise RuntimeError("INVENTORY_DATABASE_PATH must be absolute when INVENTORY_ENVIRONMENT=production")
        settings.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
        for warning in exposure_warnings(settings.host, detect_addresses()):
            logger.warning("%s", warning)
        logger.info("Cyberdeck Inventory %s listening for %s", __version__, settings.resolved_database_path)
        yield
        engine.dispose()

    app = FastAPI(
        title="Cyberdeck Inventory API",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.include_router(router)
    app.add_exception_handler(InventoryError, _inventory_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)

    if settings.allowed_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins_list),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-Cyberdeck-Request", "X-Cyberdeck-Client"],
        )
    app.add_middleware(SecurityMiddleware, settings=settings)

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.get("/docs", include_in_schema=False)
    def docs() -> Response:
        return Response(render_docs(app.openapi()), media_type="text/html; charset=utf-8")

    @app.get("/docs.css", include_in_schema=False)
    def docs_css() -> Response:
        return Response(DOCS_CSS, media_type="text/css; charset=utf-8")

    @app.get("/", include_in_schema=False)
    def frontend_root() -> Response:
        return _frontend_file(settings.resolved_frontend_dist, "")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "API route not found.", "details": {}}},
            )
        return _frontend_file(settings.resolved_frontend_dist, full_path)

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schema["components"]["securitySchemes"]["BrowserRequestHeader"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-Cyberdeck-Request",
            "description": "Send the value 1 on POST, PATCH, and DELETE. This is not a password.",
        }
        for _path, methods in schema.get("paths", {}).items():
            for method, operation in methods.items():
                if method in {"post", "put", "patch", "delete"} and isinstance(operation, dict):
                    operation.setdefault("security", []).append({"BrowserRequestHeader": []})
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


def _frontend_file(dist: Path, full_path: str) -> Response:
    root = dist.resolve()
    index = root / "index.html"
    if full_path:
        candidate = (root / full_path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=404, detail="Not found")
        if candidate.is_file():
            headers = {}
            if full_path.startswith("assets/"):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(candidate, headers=headers)
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not found")
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return PlainTextResponse(
        "Cyberdeck Inventory API is running. The web interface has not been built yet.\n"
        "API docs: /docs\nOpenAPI: /openapi.json\n",
        status_code=200,
    )


async def _inventory_error(_request: Request, exc: InventoryError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc))


def _validation_field(location: tuple) -> str | None:
    parts = [str(part) for part in location if part not in {"body", "query", "path"}]
    return parts[-1] if parts else None


def _validation_message(field: str | None) -> tuple[str, str]:
    if field in {"quantity", "new_quantity", "initial_quantity"} or (field or "").endswith("quantity"):
        message = "Enter a whole number greater than zero."
    elif field in {"slot_number", "from_slot", "to_slot"}:
        message = "Enter a drawer number. Select an existing drawer or create a new one."
    elif field == "name":
        message = "Enter a name."
    else:
        message = "Check the highlighted field and try again."
    return message, message


async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for error in exc.errors():
        item = {"type": error.get("type"), "loc": error.get("loc"), "msg": error.get("msg")}
        details.append(item)
    field = _validation_field(exc.errors()[0].get("loc", ())) if exc.errors() else None
    message, guidance = _validation_message(field)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": message,
                "field": field,
                "guidance": guidance,
                "details": {"errors": details},
            }
        },
    )


async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "http_error",
                "message": message,
                "field": None,
                "guidance": None,
                "details": {},
            }
        },
    )


async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Cyberdeck Inventory could not complete that action. Try again in a moment.",
                "field": None,
                "guidance": None,
                "details": {},
            }
        },
    )


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=1,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
