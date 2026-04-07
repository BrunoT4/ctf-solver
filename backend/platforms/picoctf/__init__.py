"""picoCTF connector — base URL and cookie file from ``Settings`` (.env)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.platforms.picoctf.connector import PicoCTFClient
from backend.platforms.registry import register_platform

if TYPE_CHECKING:
    from backend.config import Settings

PLATFORM_ID = "picoctf"


def create_client(settings: Settings) -> PicoCTFClient:
    path = (getattr(settings, "pico_cookies_file", "") or "").strip()
    if not path:
        raise RuntimeError(
            "platform=picoctf requires PICO_COOKIES_FILE in .env or --pico-cookies "
            "(path to JSON cookie export including session and token)."
        )
    return PicoCTFClient(
        base_url=settings.pico_base_url.rstrip("/"),
        cookies_path=path,
    )


register_platform(PLATFORM_ID, create_client)
