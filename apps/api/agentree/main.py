"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentree.core.config import Settings, get_settings
from agentree.core.db import create_app_engine, create_session_factory
from agentree.core.db_roles import UnsafeDatabaseRoleError, assert_safe_app_role
from agentree.core.logging import configure_logging
from agentree.health.api import router as health_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_app_engine(settings)
        try:
            await assert_safe_app_role(engine)
        except UnsafeDatabaseRoleError:
            await engine.dispose()
            raise  # refuse to start with a role that could bypass tenant isolation
        except Exception as exc:
            # DB unreachable at startup: start anyway; /readyz re-checks role safety.
            logger.warning("startup role check skipped", extra={"error_type": type(exc).__name__})
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Agentree API", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    return app
