"""Register and instantiate platform connectors. Add new CTFs via register_platform()."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.platforms.base import CompetitionPlatform

if TYPE_CHECKING:
    from backend.config import Settings

logger = logging.getLogger(__name__)

_factories: dict[str, Callable[[Settings], CompetitionPlatform]] = {}


def register_platform(platform_id: str, factory: Callable[[Settings], CompetitionPlatform]) -> None:
    """Register or replace a platform factory. ``platform_id`` is matched case-insensitively to ``Settings.platform``."""
    key = platform_id.strip().lower()
    if not key:
        raise ValueError("platform_id must be non-empty")
    _factories[key] = factory
    logger.debug("Registered CTF platform connector: %s", key)


def list_registered_platforms() -> list[str]:
    """Sorted ids of platforms that can be selected (e.g. via PLATFORM= in .env)."""
    return sorted(_factories)


def build_platform_client(settings: Settings) -> CompetitionPlatform:
    """Build the connector for ``settings.platform`` using the registered factory."""
    pid = (getattr(settings, "platform", "ctfd") or "ctfd").strip().lower()
    factory = _factories.get(pid)
    if factory is None:
        known = ", ".join(list_registered_platforms()) or "(none)"
        raise RuntimeError(
            f'Unknown platform "{pid}". Registered platforms: {known}. '
            "Add a package under backend/platforms/ and call register_platform(), "
            "or set PLATFORM in .env to a supported id."
        )
    return factory(settings)


def _load_builtin_connectors() -> None:
    """Import built-in platform packages so they self-register."""
    from backend.platforms import ctfd as _ctfd  # noqa: F401
    from backend.platforms import picoctf as _pico  # noqa: F401


_load_builtin_connectors()
