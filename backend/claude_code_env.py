"""Env for Claude Code CLI subprocesses (`.env` is not merged into ``os.environ`` by default)."""

from __future__ import annotations

from typing import Any


def claude_subprocess_env(settings: Any) -> dict[str, str]:
    """Vars merged into the Claude Code child process (in addition to inherited env)."""
    env: dict[str, str] = {"CLAUDECODE": ""}
    key = (getattr(settings, "anthropic_api_key", None) or "").strip()
    if key:
        env["ANTHROPIC_API_KEY"] = key
    return env


def claude_cli_path_or_none(settings: Any) -> str | None:
    """Optional explicit `claude` binary (same one you used for `claude auth login`)."""
    p = (getattr(settings, "claude_code_cli_path", None) or "").strip()
    return p or None
