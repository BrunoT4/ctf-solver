"""picoCTF HTTP client — session cookies + CSRF (X-CSRF-Token / token cookie)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from backend.ctfd import SubmitResult

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; ctf-solver-pico/1.0)"


def load_cookie_jar(path: str | Path) -> dict[str, str]:
    """Load cookies from JSON.

    Supported shapes:
    - ``{\"session\": \"...\", \"token\": \"...\"}`` (flat name -> value)
    - ``{\"cookies\": [{\"name\": \"...\", \"value\": \"...\"}, ...]}``
    - ``[{\"name\": \"...\", \"value\": \"...\"}, ...]`` (browser extension export)
    """
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        out: dict[str, str] = {}
        for item in data:
            if isinstance(item, dict) and "name" in item and "value" in item:
                out[str(item["name"])] = str(item["value"])
        if not out:
            raise ValueError("Cookie list is empty or missing name/value entries")
        return out
    if isinstance(data, dict):
        inner = data.get("cookies")
        if isinstance(inner, list):
            out = {}
            for item in inner:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    out[str(item["name"])] = str(item["value"])
            if not out:
                raise ValueError("cookies[] is empty or invalid")
            return out
        return {str(k): str(v) for k, v in data.items() if v is not None}
    raise ValueError("Cookie file must be a JSON object or array")


@dataclass
class PicoCTFClient:
    """HTTP client for picoCTF-style API (e.g. play.picoctf.org)."""

    base_url: str = "https://play.picoctf.org"
    cookies_path: str = ""

    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _cookies: dict[str, str] = field(default_factory=dict, repr=False)
    _pid_by_name: dict[str, str] = field(default_factory=dict, repr=False)

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self.cookies_path:
                raise RuntimeError("picoCTF requires cookies_path (exported session cookies)")
            self._cookies = load_cookie_jar(self.cookies_path)
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                cookies=self._cookies,
                follow_redirects=True,
                timeout=60.0,
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    def _csrf_headers(self) -> dict[str, str]:
        token = self._cookies.get("token", "")
        h: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            h["X-CSRF-Token"] = token
        return h

    async def _get_json(self, path: str) -> Any:
        client = await self._ensure_client()
        resp = await client.get(path)
        if resp.status_code == 401:
            raise RuntimeError("picoCTF: 401 Unauthorized — refresh exported cookies (session/token).")
        resp.raise_for_status()
        return resp.json()

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        problems = await self._get_json("/api/v1/problems")
        if not isinstance(problems, list):
            logger.warning("Unexpected /problems shape: %s", type(problems))
            return []
        stubs: list[dict[str, Any]] = []
        for p in problems:
            if not isinstance(p, dict):
                continue
            name = p.get("name", "")
            stubs.append(
                {
                    "name": name,
                    "id": p.get("pid", name),
                    "type": "hidden" if p.get("disabled") else "standard",
                }
            )
            if p.get("pid") and name:
                self._pid_by_name[name] = str(p["pid"])
        return stubs

    async def fetch_all_challenges(self) -> list[dict[str, Any]]:
        problems = await self._get_json("/api/v1/problems")
        if not isinstance(problems, list):
            return []
        out: list[dict[str, Any]] = []
        for p in problems:
            if not isinstance(p, dict):
                continue
            d = dict(p)
            d["value"] = p.get("score", 0)
            if p.get("pid") and p.get("name"):
                self._pid_by_name[str(p["name"])] = str(p["pid"])
            out.append(d)
        return out

    async def fetch_solved_names(self) -> set[str]:
        problems = await self._get_json("/api/v1/problems")
        if not isinstance(problems, list):
            return set()
        return {str(p["name"]) for p in problems if isinstance(p, dict) and p.get("solved") is True}

    async def _resolve_pid(self, challenge_name: str) -> str:
        if challenge_name in self._pid_by_name:
            return self._pid_by_name[challenge_name]
        await self.fetch_challenge_stubs()
        if challenge_name in self._pid_by_name:
            return self._pid_by_name[challenge_name]
        raise RuntimeError(f'picoCTF problem "{challenge_name}" not found (not unlocked or wrong name)')

    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        pid = await self._resolve_pid(challenge_name)
        client = await self._ensure_client()
        resp = await client.post(
            "/api/v1/submissions",
            json={"pid": pid, "key": flag.strip(), "method": "agent"},
            headers=self._csrf_headers(),
        )
        if resp.status_code == 403:
            raise RuntimeError("picoCTF: 403 — CSRF failed; ensure `token` cookie is exported.")
        if resp.status_code == 401:
            raise RuntimeError("picoCTF: 401 Unauthorized — refresh cookies.")
        try:
            data = resp.json() if resp.content else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}

        if resp.status_code == 422:
            message = str(data.get("message", resp.text))
            return SubmitResult("incorrect", message, f"SUBMIT ERROR — {message}")

        message = str(data.get("message", ""))
        if message and "can't submit flags" in message.lower():
            return SubmitResult("incorrect", message, f"SUBMIT ERROR — {message}")

        correct = data.get("correct")
        if correct is True:
            if "already" in message.lower():
                return SubmitResult(
                    "already_solved",
                    message,
                    f'ALREADY SOLVED — "{flag.strip()}" {message}'.strip(),
                )
            return SubmitResult(
                "correct",
                message,
                f'CORRECT — "{flag.strip()}" accepted. {message}'.strip(),
            )
        if resp.status_code >= 400:
            return SubmitResult("unknown", message, f"HTTP {resp.status_code} — {message or resp.text[:500]}")
        return SubmitResult("incorrect", message, f'INCORRECT — "{flag.strip()}". {message}'.strip())

    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str:
        """Write metadata.yml and download URLs found in the problem description."""
        import yaml
        from markdownify import markdownify as html2md

        name = challenge.get("name", f"challenge-{challenge.get('pid', 'unknown')}")
        slug = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', "", name.lower().strip())
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-") or "challenge"

        ch_dir = Path(output_dir) / slug
        ch_dir.mkdir(parents=True, exist_ok=True)

        desc = challenge.get("description") or ""
        try:
            desc_md = html2md(desc, heading_style="atx", escape_asterisks=False)
        except Exception:
            desc_md = desc

        hints_raw = challenge.get("hints") or []
        hints: list[dict[str, Any]] = []
        for h in hints_raw:
            if isinstance(h, dict):
                entry: dict[str, Any] = {}
                if "hint" in h:
                    entry["content"] = h["hint"]
                elif "content" in h:
                    entry["content"] = h["content"]
                if "cost" in h:
                    entry["cost"] = h["cost"]
                if entry:
                    hints.append(entry)
            elif isinstance(h, str):
                hints.append({"content": h})

        meta = {
            "name": name,
            "category": challenge.get("category", ""),
            "description": desc_md.strip(),
            "value": challenge.get("value", challenge.get("score", 0)),
            "connection_info": challenge.get("connection_info") or "",
            "tags": challenge.get("tags") or [],
            "solves": challenge.get("solves", 0),
        }
        if hints:
            meta["hints"] = hints

        (ch_dir / "metadata.yml").write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        await self._ensure_client()
        client = self._client
        assert client is not None
        dist_dir = ch_dir / "distfiles"
        dist_dir.mkdir(exist_ok=True)

        for url in _extract_urls(desc):
            if not url.startswith("http"):
                url = urljoin(self.base_url + "/", url)
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                continue
            fname = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "download"
            if not fname or fname in ("/", "."):
                fname = "file.bin"
            dest = dist_dir / fname
            if dest.exists():
                continue
            try:
                resp = await client.get(url, follow_redirects=True, timeout=120.0)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                logger.info("Downloaded %s (%d bytes)", fname, len(resp.content))
            except Exception as e:
                logger.warning("Failed to download %s: %s", url, e)

        return str(ch_dir)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def _extract_urls(html: str) -> list[str]:
    if not html:
        return []
    return list(
        dict.fromkeys(
            m.group(1)
            for m in re.finditer(
                r"""href\s*=\s*["']([^"'#?]+)["']""",
                html,
                flags=re.IGNORECASE,
            )
        )
    )
