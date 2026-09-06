from fastapi import FastAPI

from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import protected_example


def create_app() -> FastAPI:
    app = FastAPI(title="Pinterval Ops Dashboard")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")
    return app


app = create_app()
