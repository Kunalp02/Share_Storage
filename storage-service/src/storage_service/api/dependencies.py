from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from platform_auth import AuthError, PlatformPrincipal

from storage_service.application.artifact_service import ArtifactService
from storage_service.core.container import get_artifact_service_dep, get_container
from storage_service.core.exceptions import ServiceError
from storage_service.settings import Settings, get_settings


def get_artifact_service(settings: Annotated[Settings, Depends(get_settings)]) -> ArtifactService:
    return get_artifact_service_dep(settings)


async def get_platform_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> PlatformPrincipal:
    try:
        return await get_container(settings).platform_auth.authenticate(authorization)
    except AuthError as exc:
        raise ServiceError(exc.code, exc.message, exc.status_code) from exc


def get_bearer_token(principal: Annotated[PlatformPrincipal, Depends(get_platform_principal)]) -> str:
    return principal.token
