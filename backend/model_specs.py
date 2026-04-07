"""Lightweight model spec parsing — no boto3 / pydantic_ai provider imports.

Import this from the CLI and coordinator so `ctf-solve` starts without pulling
Bedrock/Google stacks (which can block on network or slow package init).
"""

from __future__ import annotations

# Default model specs — claude-sdk and codex providers use the new solver backends
DEFAULT_MODELS: list[str] = [
    "claude-sdk/claude-opus-4-6/medium",
    "claude-sdk/claude-opus-4-6/max",
]

CONTEXT_WINDOWS: dict[str, int] = {
    "us.anthropic.claude-opus-4-6-v1": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "gpt-5.4": 1_000_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.3-codex": 1_000_000,
    "gpt-5.3-codex-spark": 128_000,
    "gemini-3-flash-preview": 1_000_000,
}

VISION_MODELS: set[str] = {
    "us.anthropic.claude-opus-4-6-v1",
    "claude-opus-4-6",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gemini-3-flash-preview",
}


def model_id_from_spec(spec: str) -> str:
    parts = spec.split("/")
    return parts[1] if len(parts) >= 2 else spec


def provider_from_spec(spec: str) -> str:
    return spec.split("/", 1)[0]


def effort_from_spec(spec: str) -> str | None:
    parts = spec.split("/")
    if len(parts) >= 3 and parts[2] in ("low", "medium", "high", "max"):
        return parts[2]
    return None


def supports_vision(spec: str) -> bool:
    return model_id_from_spec(spec) in VISION_MODELS


def context_window(spec: str) -> int:
    return CONTEXT_WINDOWS.get(model_id_from_spec(spec), 200_000)
