from __future__ import annotations

from dataclasses import dataclass, field

from storage_service.application.artifact_service import ArtifactService
from storage_service.infrastructure.clients.platform_clients import AgentConfigClient, ExecutionClient
from storage_service.infrastructure.postgres.artifact_repository import ArtifactRepository
from storage_service.infrastructure.s3.object_store import S3ObjectStore
from storage_service.settings import Settings


@dataclass
class ApplicationContainer:
    settings: Settings
    repo: ArtifactRepository = field(init=False)
    s3: S3ObjectStore = field(init=False)
    artifact_service: ArtifactService = field(init=False)

    def __post_init__(self) -> None:
        self.repo = ArtifactRepository(self.settings.postgres_url)
        self.s3 = S3ObjectStore(self.settings)
        if self.settings.s3_access_key:
            try:
                self.s3.ensure_bucket()
            except Exception:
                pass
        self.artifact_service = ArtifactService(
            self.settings,
            self.repo,
            self.s3,
            AgentConfigClient(self.settings),
            ExecutionClient(self.settings),
        )

    async def shutdown(self) -> None:
        await self.repo.aclose()


_container: ApplicationContainer | None = None


def get_container(settings: Settings) -> ApplicationContainer:
    global _container
    if _container is None:
        _container = ApplicationContainer(settings)
    return _container


async def shutdown_container() -> None:
    global _container
    if _container is not None:
        await _container.shutdown()
        _container = None


def get_artifact_service_dep(settings: Settings) -> ArtifactService:
    return get_container(settings).artifact_service
