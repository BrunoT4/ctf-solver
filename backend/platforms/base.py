"""Shared contract for CTF platform connectors (list / pull / submit)."""

from __future__ import annotations

from typing import Any, Protocol

from backend.ctfd import SubmitResult


class CompetitionPlatform(Protocol):
    """Async client used by the poller, coordinator, and solvers."""

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]: ...
    async def fetch_all_challenges(
        self, only_names: frozenset[str] | None = None
    ) -> list[dict[str, Any]]: ...
    async def fetch_solved_names(self) -> set[str]: ...
    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult: ...
    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str: ...
    async def close(self) -> None: ...
