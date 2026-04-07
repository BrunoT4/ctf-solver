"""Generate educational Markdown write-ups from swarm JSONL logs + challenge text."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WRITEUP_SYSTEM = """You are a CTF author writing a technical, educational walkthrough.
Audience: someone learning security who wants intuition, not just commands.

Rules:
- Use clear Markdown with ## headings.
- Explain *why* each step was taken and what dead ends meant.
- Tie claims to the solver trace when possible (tool calls, outputs).
- Do NOT paste huge raw logs; summarize and quote short snippets only.
- If the challenge was not fully solved, write an honest postmortem: what was tried, what blocked progress.
"""


def _load_swarm_traces(swarm_dir: Path, max_chars: int = 120_000) -> str:
    if not swarm_dir.is_dir():
        return "(no swarm trace directory)"
    parts: list[str] = []
    total = 0
    for p in sorted(swarm_dir.glob("*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        block = f"### {p.name}\n```\n{text}\n```\n"
        if total + len(block) > max_chars:
            parts.append(f"... [trace truncated at {max_chars} chars]\n")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts) if parts else "(empty traces)"


def _resolve_writeup_model(settings: Any) -> tuple[str, str]:
    """Return (provider, model_id). provider is anthropic or openai."""
    explicit = (getattr(settings, "writeup_model", "") or "").strip()
    if explicit:
        if "/" in explicit:
            prov, mid = explicit.split("/", 1)
            return prov.strip().lower(), mid.strip()
        return "anthropic", explicit
    if getattr(settings, "anthropic_api_key", ""):
        return "anthropic", "claude-sonnet-4-20250514"
    if getattr(settings, "openai_api_key", ""):
        return "openai", "gpt-4o-mini"
    return "", ""


async def _call_anthropic(api_key: str, model: str, user_prompt: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 16_000,
                "system": WRITEUP_SYSTEM,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()
    blocks = data.get("content") or []
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))


async def _call_openai(api_key: str, model: str, user_prompt: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": WRITEUP_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


async def maybe_generate_writeup(
    *,
    manifest_path: Path,
    settings: Any,
    challenge_description: str,
    solved: bool,
    flag: str | None,
) -> None:
    if not getattr(settings, "writeup_enabled", True):
        return
    if not solved and not getattr(settings, "writeup_on_failure", False):
        return

    out_dir = Path(getattr(settings, "writeup_dir", "write-ups"))
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    slug = manifest.get("challenge_slug") or manifest_path.parent.name
    out_path = out_dir / f"{slug}.md"
    if out_path.exists() and not getattr(settings, "writeup_force", False):
        logger.info("Write-up exists, skipping (use writeup_force to overwrite): %s", out_path)
        return

    prov, model = _resolve_writeup_model(settings)
    if not prov:
        logger.warning("No API key for write-up (set ANTHROPIC_API_KEY or OPENAI_API_KEY)")
        return

    bundle = manifest_path.parent
    traces = _load_swarm_traces(bundle / "swarm")

    include_flag = getattr(settings, "writeup_include_flag", True) and solved and flag
    flag_line = f"The correct flag was: `{flag}`\n" if include_flag else ""

    user_prompt = f"""## Challenge manifest (JSON)
```json
{json.dumps(manifest, indent=2)[:8000]}
```

## Official-style description (from metadata)
{challenge_description[:12000]}

## Solver traces (JSONL exports, grouped by model)
{traces}

## Outcome
- Solved: {solved}
{flag_line}

Write the write-up with sections:
1. Problem overview
2. What we were given
3. Key observations from recon
4. Solution path (reasoning + main commands or ideas)
5. Verification / flag submission
6. Takeaways for similar problems
"""

    if prov == "anthropic":
        body = await _call_anthropic(settings.anthropic_api_key, model, user_prompt)
    elif prov == "openai":
        body = await _call_openai(settings.openai_api_key, model, user_prompt)
    else:
        logger.warning("Unknown writeup provider %s", prov)
        return

    header = f"# {manifest.get('challenge_name', slug)}\n\n_Auto-generated from solver logs._\n\n"
    out_path.write_text(header + body.strip() + "\n", encoding="utf-8")
    logger.info("Wrote write-up: %s", out_path)
