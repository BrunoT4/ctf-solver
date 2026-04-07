"""CTFd connector — URL, token, or username/password from ``Settings`` (.env)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.ctfd import CTFdClient
from backend.platforms.registry import register_platform

if TYPE_CHECKING:
    from backend.config import Settings

PLATFORM_ID = "ctfd"


def create_client(settings: Settings) -> CTFdClient:
    return CTFdClient(
        base_url=settings.ctfd_url,
        token=settings.ctfd_token,
        username=settings.ctfd_user,
        password=settings.ctfd_pass,
    )


register_platform(PLATFORM_ID, create_client)
