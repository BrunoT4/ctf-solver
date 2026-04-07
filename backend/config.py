"""Pydantic Settings — credentials from .env file + environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Platform: "ctfd" or "picoctf"
    platform: str = "ctfd"

    # CTFd
    ctfd_url: str = "http://localhost:8000"
    ctfd_user: str = "admin"
    ctfd_pass: str = "admin"
    ctfd_token: str = ""

    # picoCTF (session cookies JSON — see README)
    pico_base_url: str = "https://play.picoctf.org"
    pico_cookies_file: str = ""

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Provider-specific (optional, for Bedrock/Azure/Zen fallback)
    aws_region: str = "us-east-1"
    aws_bearer_token: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    opencode_zen_api_key: str = ""

    # Infra
    sandbox_image: str = "ctf-sandbox"
    max_concurrent_challenges: int = 10
    max_attempts_per_challenge: int = 3
    container_memory_limit: str = "16g"

    # Logging / write-ups
    log_base: str = "logs"
    log_run_id: str = ""  # empty = generated per coordinator session or single run
    log_truncate_bytes: int = 2000
    writeup_enabled: bool = True
    writeup_include_flag: bool = True
    writeup_on_failure: bool = False
    writeup_force: bool = False
    writeup_dir: str = "write-ups"
    writeup_model: str = ""  # e.g. anthropic/claude-sonnet-4-20250514 — empty = auto from keys

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
