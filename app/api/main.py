from fastapi import FastAPI

from app.api.routes import auth as auth_routes
from app.api.routes import health as health_routes
from app.api.routes import protected_example
from app.api.routes import web as web_routes


def create_app() -> FastAPI:
    app = FastAPI(title="Pinterval Ops Dashboard")
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(protected_example.router, prefix="/api")
    app.include_router(web_routes.router)
    return app


app = create_app()
