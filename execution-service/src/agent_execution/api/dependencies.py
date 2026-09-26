from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from platform_auth import AuthError, PlatformPrincipal

from agent_execution.core.container import ApplicationContainer, get_container
from agent_execution.core.exceptions import ServiceError
from agent_execution.services.agent_execution_service import AgentExecutionService
from agent_execution.services.deployment_service import DeploymentService
from agent_execution.services.thread_service import ThreadService
from agent_execution.settings import Settings, get_settings


def get_app_container(settings: Annotated[Settings, Depends(get_settings)]) -> ApplicationContainer:
    return get_container(settings)


def get_execution_service(
    container: Annotated[ApplicationContainer, Depends(get_app_container)],
) -> AgentExecutionService:
    return container.execution_service


def get_thread_service(container: Annotated[ApplicationContainer, Depends(get_app_container)]) -> ThreadService:
    return container.thread_service


def get_deployment_service(
    container: Annotated[ApplicationContainer, Depends(get_app_container)],
) -> DeploymentService:
    return container.deployment_service


async def get_platform_principal(
    container: Annotated[ApplicationContainer, Depends(get_app_container)],
    authorization: Annotated[str | None, Header()] = None,
) -> PlatformPrincipal:
    try:
        return await container.platform_auth.authenticate(authorization)
    except AuthError as exc:
        raise ServiceError(exc.code, exc.message, exc.status_code) from exc


def get_bearer_token(principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)]) -> str:
    return principal.token


def get_api_key(x_api_key: Annotated[str | None, Header()] = None) -> str:
    if not x_api_key:
        raise ServiceError("UNAUTHORIZED", "X-Api-Key is required.", 401)
    return x_api_key
