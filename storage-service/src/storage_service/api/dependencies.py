from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from storage_service.application.artifact_service import ArtifactService
from storage_service.core.container import get_artifact_service_dep
from storage_service.settings import Settings, get_settings


def get_artifact_service(settings: Annotated[Settings, Depends(get_settings)]) -> ArtifactService:
    return get_artifact_service_dep(settings)


def bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""
