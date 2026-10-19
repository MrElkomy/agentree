"""Liveness and readiness probes."""

import logging

from fastapi import APIRouter, Request, Response, status

from agentree.core.db import ping

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Process is alive. Does not touch dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, str]:
    """Process can serve traffic: the database answers."""
    try:
        await ping(request.app.state.engine)
    except Exception as exc:
        # Log only the exception type: driver messages can include connection details.
        logger.warning("readiness check failed", extra={"error_type": type(exc).__name__})
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
