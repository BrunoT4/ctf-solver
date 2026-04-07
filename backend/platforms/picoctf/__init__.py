"""picoCTF connector — base URL and cookie file from ``Settings`` (.env)."""

from __future__ import annotations

from pathlib import Path
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
    p = Path(path).expanduser()
    if not p.is_file():
        raise RuntimeError(
            f"picoCTF cookie file not found (set PICO_COOKIES_FILE or --pico-cookies): {p}"
        )
    return PicoCTFClient(
        base_url=settings.pico_base_url.rstrip("/"),
        cookies_path=str(p.resolve()),
    )


register_platform(PLATFORM_ID, create_client)
