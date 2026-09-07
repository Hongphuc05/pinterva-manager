from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import orders_api as orders_api_routes
from app.api.routes import protected_example

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Pinterval Ops Dashboard")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(orders_api_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets"
        )

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            if full_path.startswith("api"):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
