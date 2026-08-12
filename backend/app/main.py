"""FastAPI application factory and entry point.

This file only *assembles* the application:

    FastAPI instance -> middleware -> exception handlers -> routers

There is no business logic here on purpose. Anything that decides *what* an
endpoint does belongs in routes/, agents/ or services/.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import api_router
from app.utils.errors import register_exception_handlers

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run once on startup, and once on shutdown after the `yield`.

    Phase 3 will open the MongoDB connection here and close it on shutdown.
    """
    logger.info("%s v%s starting", settings.APP_NAME, settings.APP_VERSION)
    logger.info("CORS allowed origins: %s", settings.cors_origins_list)

    # Warn about unset secrets by NAME only — never log their values.
    missing = settings.missing_secrets()
    if missing:
        logger.warning(
            "Not configured yet (expected during early phases): %s",
            ", ".join(missing),
        )

    yield

    logger.info("%s shutting down", settings.APP_NAME)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        lifespan=lifespan,
        title=settings.APP_NAME,
        description=(
            "REST API for the AI-Powered Content Creation and Developer "
            "Productivity Agents platform."
        ),
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # --- Middleware ---
    # Browsers block cross-origin requests by default. The React dev server on
    # port 5173 and this API on port 8000 are different origins, so without
    # this the frontend cannot call us at all.
    # Origins come from config and are never "*", because "*" is invalid when
    # allow_credentials=True and would break cookie/Authorization handling.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )

    # --- Exception handlers ---
    # Registered before routers so that any failure raised inside a route is
    # converted into our standard error envelope.
    register_exception_handlers(app)

    # --- Routers ---
    app.include_router(api_router, prefix=API_PREFIX)

    return app


app = create_app()
