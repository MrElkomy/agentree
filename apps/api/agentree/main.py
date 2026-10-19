"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentree.agents.api import router as agents_router
from agentree.core.config import Settings, get_settings
from agentree.core.csrf import csrf_middleware
from agentree.core.db import create_app_engine, create_session_factory
from agentree.core.db_roles import UnsafeDatabaseRoleError, assert_safe_app_role
from agentree.core.email import EmailSender, SmtpEmailSender
from agentree.core.logging import configure_logging
from agentree.health.api import router as health_router
from agentree.identity.api import router as auth_router
from agentree.knowledge.api import router as knowledge_router
from agentree.llm.base import LLMProvider, ProviderName
from agentree.llm.http_providers import PROVIDERS
from agentree.providers.api import router as providers_router
from agentree.providers.service import build_vault
from agentree.tenancy.api import router as tenancy_router

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    mailer: EmailSender | None = None,
    llm_providers: dict[ProviderName, Callable[[], LLMProvider]] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    mailer = mailer or SmtpEmailSender(settings)
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
        app.state.mailer = mailer
        app.state.vault = build_vault(settings)
        app.state.llm_providers = llm_providers or dict(PROVIDERS)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Agentree API", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(csrf_middleware(settings.allowed_origins))
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(tenancy_router)
    app.include_router(providers_router)
    app.include_router(knowledge_router)
    app.include_router(agents_router)
    return app
