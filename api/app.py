"""JQE FastAPI Application Entrypoint.

Initializes the FastAPI application with CORS support, exception handlers,
and dashboard API routes.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router
from config.settings import settings
from core.exceptions import JQEError


def create_app() -> FastAPI:
    """Constructs and configures the FastAPI application."""
    app = FastAPI(
        title="JQE Quant Trading API",
        description="Observability and analytics API boundary for the JQE Quantitative Trading Platform.",
        version="0.5.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS for local UI development and web dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(JQEError)
    async def jqe_error_handler(request: Request, exc: JQEError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": exc.__class__.__name__, "message": str(exc)},
        )

    app.include_router(router)

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
