"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentree.agents.api import router as agents_router
from agentree.agents.config_api import router as agent_configs_router
from agentree.agents.inbox_api import router as inbox_router
from agentree.audit.api import router as audit_router
from agentree.core.config import Settings, get_settings
from agentree.core.csrf import csrf_middleware
from agentree.core.db import create_app_engine, create_session_factory
from agentree.core.db_roles import UnsafeDatabaseRoleError, assert_safe_app_role
from agentree.core.email import EmailSender, SmtpEmailSender
from agentree.core.logging import configure_logging
from agentree.core.webpush import PushSender, build_push_sender
from agentree.customers.api import router as customers_router
from agentree.health.api import router as health_router
from agentree.identity.api import router as auth_router
from agentree.knowledge.api import router as knowledge_router
from agentree.knowledge.files_api import router as knowledge_files_router
from agentree.leads.api import router as leads_router
from agentree.leads.api import tasks_router as follow_ups_router
from agentree.llm.base import LLMProvider, ProviderName
from agentree.llm.fake import DemoProvider
from agentree.llm.http_providers import PROVIDERS
from agentree.notifications.api import router as notifications_router
from agentree.providers.api import metrics_router
from agentree.providers.api import router as providers_router
from agentree.providers.service import build_vault
from agentree.public.api import owner_router as public_owner_router
from agentree.public.api import public_router
from agentree.tenancy.api import router as tenancy_router

logger = logging.getLogger(__name__)


def _demo_factory(name: ProviderName) -> Callable[[], LLMProvider]:
    return lambda: DemoProvider(name=name)


def create_app(
    settings: Settings | None = None,
    mailer: EmailSender | None = None,
    llm_providers: dict[ProviderName, Callable[[], LLMProvider]] | None = None,
    push: PushSender | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    mailer = mailer or SmtpEmailSender(settings)
    providers = llm_providers or dict(PROVIDERS)
    if llm_providers is None and settings.llm_demo_mode:
        logger.warning("LLM demo mode is on: AI providers are replaced by canned replies")
        providers = {n: _demo_factory(n) for n in ProviderName}
    configure_logging(settings.log_level)
    if push is None:
        key = settings.vapid_private_key
        push = build_push_sender(key.get_secret_value() if key else None,
                                 settings.vapid_subject or settings.public_base_url)  # fmt: skip

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
        app.state.push = push
        app.state.vault = build_vault(settings)
        app.state.llm_providers = providers
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
    app.include_router(public_owner_router)
    app.include_router(public_router)
    app.include_router(audit_router)
    app.include_router(leads_router)
    app.include_router(follow_ups_router)
    app.include_router(inbox_router)
    app.include_router(agent_configs_router)
    app.include_router(metrics_router)
    app.include_router(notifications_router)
    app.include_router(customers_router)
    app.include_router(knowledge_files_router)
    return app
