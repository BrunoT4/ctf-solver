"""
CTF platform connectors live in subpackages (e.g. ``ctfd``, ``picoctf``).

Each package registers a factory with :func:`register_platform`. Set ``PLATFORM``
in ``.env`` (or ``--platform``) to the platform id to use that connector.

To add a platform, create ``backend/platforms/myctf/__init__.py`` with
``PLATFORM_ID``, ``create_client(settings)``, and call ``register_platform``.
"""

from backend.platforms.base import CompetitionPlatform
from backend.platforms.registry import (
    build_platform_client,
    list_registered_platforms,
    register_platform,
)

__all__ = [
    "CompetitionPlatform",
    "build_platform_client",
    "list_registered_platforms",
    "register_platform",
]
