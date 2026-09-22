import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm.exc import StaleDataError

from app.api.concurrency import stale_order_detail
from app.api.routes import assignments_api as assignments_api_routes
from app.api.routes import auth as auth_routes
from app.api.routes import designer_tasks_api as designer_tasks_api_routes
from app.api.routes import duplicate_board_api as duplicate_board_api_routes
from app.api.routes import finance_api as finance_api_routes
from app.api.routes import health as health_routes
from app.api.routes import orders_api as orders_api_routes
from app.api.routes import platforms_api as platforms_api_routes
from app.api.routes import protected_example
from app.api.routes import submissions_api as submissions_api_routes
from app.api.routes import sync_jobs_api as sync_jobs_api_routes
from app.api.routes import telegram_admin_api as telegram_admin_api_routes
from app.api.routes import telegram_api as telegram_api_routes
from app.api.routes import users_api as users_api_routes
from app.application.auth import read_session_token
from app.application.concurrency import OrderVersionConflictError
from app.config import get_settings

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
CRAWLED_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "crawled_assets"
SPA_HTML_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}
logger = logging.getLogger(__name__)

# These routes are retained only to give deployed clients a migration window.
# Request bodies are deliberately never logged because some legacy routes carry
# account credentials or session cookies.
DEPRECATED_PATHS = {
    "/api/admin/ping",
    "/api/designer/ping",
    "/api/orders/sync-status",
    "/api/orders/sync-status/run",
    "/api/orders/sync-status/reset",
    "/api/orders/sync-printerval-status",
    "/api/orders/sync-platform-status",
    "/api/orders/printerval-credentials",
    "/api/orders/bulk-printerval-assignment",
    "/api/orders/bulk-platform-assignment",
    "/api/printerval-login/status",
    "/api/printerval-login/start",
    "/api/printerval-login/done",
    "/api/platform-login/status",
    "/api/platform-login/start",
    "/api/platform-login/done",
    "/api/orders/bulk-assign",
}
DEPRECATED_PATH_PATTERNS = (
    re.compile(r"^/api/orders/[^/]+/assign$"),
    re.compile(r"^/api/orders/[^/]+/printerval-assignment$"),
    re.compile(r"^/api/orders/[^/]+/platform-assignment$"),
)


def _request_actor_role(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    token = token or request.cookies.get("session")
    payload = read_session_token(token) if token else None
    role = payload.get("role") if payload else None
    return str(role) if role else None


def _is_deprecated_path(path: str) -> bool:
    return path in DEPRECATED_PATHS or any(pattern.fullmatch(path) for pattern in DEPRECATED_PATH_PATTERNS)


def create_app() -> FastAPI:
    app = FastAPI(title="Tacahu Ops Dashboard")
    settings = get_settings()
    allowed_origins = [
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ]
    extension_origin_regex = r"chrome-extension://[a-z0-9]+"
    origin_regex = (
        f"(?:{settings.cors_origin_regex})|(?:{extension_origin_regex})"
        if settings.cors_origin_regex
        else extension_origin_regex
    )
    if "*" in allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_origin_regex=origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    elif allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_origin_regex=origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(OrderVersionConflictError)
    async def order_version_conflict_handler(request: Request, exc: OrderVersionConflictError):
        logger.warning(
            "order_command_conflict route=%s method=%s order_id=%s expected_version=%s current_version=%s request_id=%s",
            request.url.path,
            request.method,
            exc.order_id,
            exc.expected_version,
            exc.current_version,
            request.headers.get("x-request-id") or "none",
        )
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": exc.detail()})

    @app.exception_handler(StaleDataError)
    async def stale_data_handler(_request: Request, _exc: StaleDataError):
        # Later command migrations have the locked Order available and can return
        # its revision. This fallback still prevents an ORM error leaking as a 500.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": stale_order_detail()},
        )

    @app.middleware("http")
    async def attach_request_metadata(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started_at = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        path = request.url.path
        if _is_deprecated_path(path):
            response.headers["X-Deprecated-Endpoint"] = "true"
            logger.warning(
                "deprecated_endpoint_used route=%s method=%s actor_role=%s platform_id=%s request_id=%s",
                path,
                request.method,
                _request_actor_role(request) or "anonymous",
                request.headers.get("x-platform-id") or "none",
                request_id,
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
            logger.info(
                "command_latency route=%s method=%s status_code=%s duration_ms=%.2f request_id=%s",
                path,
                request.method,
                response.status_code,
                (time.perf_counter() - started_at) * 1000,
                request_id,
            )
        return response
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(assignments_api_routes.router, prefix="/api")
    app.include_router(users_api_routes.router, prefix="/api")
    app.include_router(platforms_api_routes.router, prefix="/api")
    app.include_router(sync_jobs_api_routes.router, prefix="/api")
    app.include_router(submissions_api_routes.router, prefix="/api")
    app.include_router(orders_api_routes.router, prefix="/api")
    app.include_router(finance_api_routes.router, prefix="/api")
    app.include_router(designer_tasks_api_routes.router, prefix="/api")
    app.include_router(duplicate_board_api_routes.router, prefix="/api")
    app.include_router(telegram_api_routes.router, prefix="/api")
    app.include_router(telegram_admin_api_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")

    CRAWLED_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/crawled_assets", StaticFiles(directory=CRAWLED_ASSETS_DIR), name="crawled-assets"
    )

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets"
        )

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            if full_path.startswith("api"):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
            candidate = FRONTEND_DIST / full_path
            if (
                full_path
                and candidate.is_file()
                and candidate.resolve().is_relative_to(FRONTEND_DIST.resolve())
            ):
                headers = SPA_HTML_HEADERS if candidate.name == "index.html" else None
                return FileResponse(candidate, headers=headers)
            return FileResponse(FRONTEND_DIST / "index.html", headers=SPA_HTML_HEADERS)

    return app


app = create_app()
