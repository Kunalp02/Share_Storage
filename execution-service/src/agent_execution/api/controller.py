from __future__ import annotations

from fastapi import APIRouter


class ApiController:
    """Base class for HTTP controllers. Subclasses bind routes in register()."""

    def __init__(self, router: APIRouter) -> None:
        self.register(router)

    def register(self, router: APIRouter) -> None:
        raise NotImplementedError
