"""JQE FastAPI Application Entrypoint.

Initializes the FastAPI application with CORS support, exception handlers,
and dashboard API routes.
"""

from __future__ import annotations

import ipaddress
import os

# The API is an observation surface. Never let a shared dotenv file or an
# inherited process variable arm its order endpoint. Execution belongs to a
# separately launched, explicitly armed Weltrade supervisor process.
os.environ["JQE_BROKER_EXECUTION_ENABLED"] = "false"

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router
from api.observation import router as observation_router
from api.research import router as research_router
from api.watchlist import router as watchlist_router
from api.assistant import router as assistant_router
from api.notifications import router as notifications_router
from api.market_scan import router as market_scan_router
from config.settings import settings
from core.exceptions import JQEError

if settings.broker_execution_enabled:
    raise RuntimeError("API refuses execution-enabled settings; launch a separate supervisor")


def create_app() -> FastAPI:
    """Constructs and configures the FastAPI application."""
    app = FastAPI(
        title="JQE Quant Trading API",
        description="Observability and analytics API boundary for the JQE Quantitative Trading Platform.",
        version="0.5.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # The workstation API is local-only; hosted browser origins require an
    # authenticated backend boundary and are intentionally not trusted here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def workstation_only(request: Request, call_next):
        client_host = request.client.host if request.client is not None else ""
        try:
            is_loopback = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = client_host == "testclient"
        if not is_loopback:
            return JSONResponse(status_code=403, content={"detail": "Workstation-local API only"})
        return await call_next(request)

    @app.exception_handler(JQEError)
    async def jqe_error_handler(request: Request, exc: JQEError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": exc.__class__.__name__, "message": str(exc)},
        )

    app.include_router(router)
    app.include_router(observation_router)
    app.include_router(research_router)
    app.include_router(watchlist_router)
    app.include_router(assistant_router)
    app.include_router(notifications_router)
    app.include_router(market_scan_router)

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
