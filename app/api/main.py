from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import allocation_api as allocation_api_routes
from app.api.routes import auth as auth_routes
from app.api.routes import designer_tasks_api as designer_tasks_api_routes
from app.api.routes import health as health_routes
from app.api.routes import kanban_api as kanban_api_routes
from app.api.routes import orders_api as orders_api_routes
from app.api.routes import platforms_api as platforms_api_routes
from app.api.routes import protected_example
from app.api.routes import users_api as users_api_routes
from app.config import get_settings

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
CRAWLED_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "crawled_assets"


def create_app() -> FastAPI:
    app = FastAPI(title="Tacahu Ops Dashboard")
    settings = get_settings()
    allowed_origins = [
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ]
    # CopyImage posts a gallery from the operator's authenticated Chrome session.
    # It uses a platform-scoped bearer token, so allowing Chrome extension origins
    # does not grant browser extensions access to the normal web API.
    extension_origin_regex = r"chrome-extension://[a-z0-9]+"
    origin_regex = (
        f"(?:{settings.cors_origin_regex})|(?:{extension_origin_regex})"
        if settings.cors_origin_regex
        else extension_origin_regex
    )
    if "*" in allowed_origins:
        app.add_middleware(
            CORSMiddleware,
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
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(users_api_routes.router, prefix="/api")
    app.include_router(platforms_api_routes.router, prefix="/api")
    app.include_router(orders_api_routes.router, prefix="/api")
    app.include_router(allocation_api_routes.router, prefix="/api")
    app.include_router(designer_tasks_api_routes.router, prefix="/api")
    app.include_router(kanban_api_routes.router, prefix="/api")
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
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
