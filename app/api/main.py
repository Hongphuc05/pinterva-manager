from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.deps import WebAuthRedirect
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

    @app.exception_handler(WebAuthRedirect)
    def _redirect_to_login(request, exc):
        return RedirectResponse("/login", status_code=302)

    return app


app = create_app()
