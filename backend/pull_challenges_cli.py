"""Bulk-download challenges to local folders using the registered platform connector.

Credentials come from ``.env`` / ``Settings`` (same as ``ctf-solve``). Override with CLI flags.

Acknowledgement: original CTFd-only bulk pull and HTML helpers were inspired by
es3n1n/Eruditus (https://github.com/es3n1n/Eruditus); CTFd hint unlock flow lives in
``backend.ctfd.CTFdClient.pull_challenge``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from backend.config import Settings


@click.command()
@click.option(
    "--list-platforms",
    is_flag=True,
    help="Print registered platform ids and exit",
)
@click.option("--platform", default=None, envvar="PLATFORM", metavar="ID", help="Platform id (default: PLATFORM from .env)")
@click.option("--output", default="challenges", type=click.Path(), help="Output directory")
@click.option(
    "--only",
    multiple=True,
    help="Only pull challenges with these exact names (can be passed multiple times)",
)
@click.option("--ctfd-url", default=None, help="Override CTFD_URL")
@click.option("--ctfd-token", default=None, help="Override CTFD_TOKEN")
@click.option("--ctfd-user", default=None, help="Override CTFD_USER")
@click.option("--ctfd-pass", default=None, help="Override CTFD_PASS")
@click.option("--pico-base-url", default=None, help="Override PICO_BASE_URL")
@click.option("--pico-cookies", default=None, type=click.Path(), help="Override PICO_COOKIES_FILE")
def main(
    list_platforms: bool,
    platform: str | None,
    output: str,
    only: tuple[str, ...],
    ctfd_url: str | None,
    ctfd_token: str | None,
    ctfd_user: str | None,
    ctfd_pass: str | None,
    pico_base_url: str | None,
    pico_cookies: str | None,
) -> None:
    """Pull all (or selected) challenges into <output>/<slug>/ via the platform connector."""
    from backend.platforms import build_platform_client, list_registered_platforms

    if list_platforms:
        for pid in list_registered_platforms():
            click.echo(pid)
        return

    settings = Settings()
    if platform:
        settings.platform = platform
    if ctfd_url:
        settings.ctfd_url = ctfd_url
    if ctfd_token:
        settings.ctfd_token = ctfd_token
    if ctfd_user:
        settings.ctfd_user = ctfd_user
    if ctfd_pass:
        settings.ctfd_pass = ctfd_pass
    if pico_base_url:
        settings.pico_base_url = pico_base_url
    if pico_cookies:
        settings.pico_cookies_file = str(pico_cookies)

    pid = settings.platform.strip().lower()
    registered = list_registered_platforms()
    if pid not in registered:
        click.echo(
            f"Unknown platform '{settings.platform}'. Registered: {', '.join(registered)}. "
            "Use --list-platforms.",
            err=True,
        )
        sys.exit(1)

    asyncio.run(_pull_all(settings, Path(output), frozenset(only)))


async def _pull_all(settings: Settings, output_dir: Path, only_names: frozenset[str]) -> None:
    from backend.platforms import build_platform_client

    output_dir.mkdir(parents=True, exist_ok=True)
    client = build_platform_client(settings)
    try:
        challenges = await client.fetch_all_challenges()
        if only_names:
            challenges = [c for c in challenges if c.get("name") in only_names]
            missing = only_names - {c.get("name") for c in challenges}
            for name in sorted(missing):
                click.echo(f"  WARN: no challenge named {name!r} (skipped)", err=True)

        if not challenges:
            click.echo("No challenges to pull.", err=True)
            return

        count = 0
        for ch in challenges:
            cname = ch.get("name", "?")
            ccat = ch.get("category", "?")
            cval = ch.get("value", ch.get("score", 0))
            click.echo(f"  [{ccat}] {cname} ({cval} pts)")
            await client.pull_challenge(ch, str(output_dir.resolve()))
            count += 1

        click.echo(f"\nDone. Pulled {count} challenge(s) to {output_dir.resolve()}")
    finally:
        await client.close()
