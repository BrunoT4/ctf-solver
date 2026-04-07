"""Model resolution — Bedrock, Azure OpenAI, Zen, Google AI Studio.

Heavy imports (boto3, pydantic_ai providers) are lazy-loaded inside
``resolve_model`` / ``resolve_model_settings`` so CLI and Claude-only paths
start quickly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.model_specs import (
    CONTEXT_WINDOWS,
    DEFAULT_MODELS,
    VISION_MODELS,
    context_window,
    effort_from_spec,
    model_id_from_spec,
    provider_from_spec,
    supports_vision,
)

if TYPE_CHECKING:
    from backend.config import Settings

__all__ = [
    "CONTEXT_WINDOWS",
    "DEFAULT_MODELS",
    "VISION_MODELS",
    "context_window",
    "effort_from_spec",
    "model_id_from_spec",
    "provider_from_spec",
    "resolve_model",
    "resolve_model_settings",
    "supports_vision",
]


def resolve_model(spec: str, settings: "Settings") -> Any:
    """Resolve a 'provider/model_id' spec to a Pydantic AI Model."""
    from pydantic_ai.models.bedrock import BedrockConverseModel
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.bedrock import BedrockProvider
    from pydantic_ai.providers.google import GoogleProvider
    from pydantic_ai.providers.openai import OpenAIProvider

    import boto3

    provider = provider_from_spec(spec)
    model_id = model_id_from_spec(spec)
    match provider:
        case "bedrock":
            if settings.aws_bearer_token:
                return BedrockConverseModel(
                    model_id,
                    provider=BedrockProvider(
                        api_key=settings.aws_bearer_token,
                        region_name=settings.aws_region,
                    ),
                )
            session = boto3.Session()
            client = session.client("bedrock-runtime", region_name=settings.aws_region)
            return BedrockConverseModel(
                model_id,
                provider=BedrockProvider(bedrock_client=client),
            )
        case "azure":
            return OpenAIModel(
                model_id,
                provider=OpenAIProvider(
                    base_url=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_api_key,
                ),
            )
        case "zen":
            return OpenAIModel(
                model_id,
                provider=OpenAIProvider(
                    base_url="https://opencode.ai/zen/v1",
                    api_key=settings.opencode_zen_api_key,
                ),
            )
        case "google":
            return GoogleModel(
                model_id,
                provider=GoogleProvider(api_key=settings.gemini_api_key),
            )
        case "claude-sdk" | "codex":
            raise ValueError(
                f"Provider '{provider}' uses its own solver backend, not Pydantic AI. "
                f"resolve_model() should not be called for {spec}."
            )
        case _:
            raise ValueError(f"Unknown provider: {provider}")


def resolve_model_settings(spec: str) -> Any:
    """Get provider-specific model settings with caching enabled."""
    from pydantic_ai.models.bedrock import BedrockModelSettings
    from pydantic_ai.models.google import GoogleModelSettings
    from pydantic_ai.models.openai import OpenAIModelSettings
    from pydantic_ai.settings import ModelSettings

    provider = spec.split("/", 1)[0]
    match provider:
        case "bedrock":
            return BedrockModelSettings(
                max_tokens=128_000,
                bedrock_cache_instructions=True,
                bedrock_cache_tool_definitions=True,
                bedrock_cache_messages=True,
            )
        case "azure" | "zen":
            return OpenAIModelSettings(
                max_tokens=128_000,
            )
        case "google":
            return GoogleModelSettings(
                max_tokens=64_000,
                google_thinking_config={
                    "thinking_level": "high",
                    "include_thoughts": True,
                },
            )
        case _:
            return ModelSettings(max_tokens=128_000)
