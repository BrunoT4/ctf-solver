"""picoCTF HTTP client — session cookies + CSRF (X-CSRF-Token / token cookie)."""

from __future__ import annotations

import asyncio
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

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def load_cookie_jar(path: str | Path) -> dict[str, str]:
    """Load cookies from JSON.

    Supported shapes:
    - ``{\"session\": \"...\", \"token\": \"...\"}`` (flat name -> value)
    - ``{\"Request Cookies\": {\"sessionid\": \"...\", \"csrftoken\": \"...\"}}`` (devtools export)
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
        rc = data.get("Request Cookies")
        if isinstance(rc, dict) and rc:
            data = {
                str(k): str(v)
                for k, v in rc.items()
                if v is not None and not isinstance(v, (dict, list))
            }
        inner = data.get("cookies") if isinstance(data, dict) else None
        if isinstance(inner, list):
            out = {}
            for item in inner:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    out[str(item["name"])] = str(item["value"])
            if not out:
                raise ValueError("cookies[] is empty or invalid")
            return out
        if isinstance(data, dict):
            return {
                str(k): str(v)
                for k, v in data.items()
                if k not in ("cookies", "Request Cookies")
                and v is not None
                and not isinstance(v, (dict, list))
            }
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
            origin = self.base_url.rstrip("/")
            self._client = httpx.AsyncClient(
                base_url=origin,
                cookies=self._cookies,
                follow_redirects=True,
                timeout=60.0,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Referer": origin + "/",
                },
            )
        return self._client

    def _csrf_headers(self) -> dict[str, str]:
        token = (self._cookies.get("csrftoken") or self._cookies.get("token") or "").strip()
        h: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            h["X-CSRF-Token"] = token
            h["X-CSRFToken"] = token
        return h

    async def _get_json(self, path: str) -> Any:
        client = await self._ensure_client()
        resp = await client.get(path)
        if resp.status_code == 401:
            raise RuntimeError(
                "picoCTF: 401 Unauthorized — refresh exported cookies (sessionid / csrftoken)."
            )
        resp.raise_for_status()
        return resp.json()

    async def _iter_challenge_list_pages(self) -> list[dict[str, Any]]:
        """DRF-paginated GET /api/challenges."""
        client = await self._ensure_client()
        out: list[dict[str, Any]] = []
        next_url: str | None = "/api/challenges?page_size=100"
        while next_url:
            resp = await client.get(next_url)
            if resp.status_code == 401:
                raise RuntimeError(
                    "picoCTF: 401 Unauthorized — refresh exported cookies (sessionid / csrftoken)."
                )
            resp.raise_for_status()
            page = resp.json()
            if not isinstance(page, dict):
                break
            batch = page.get("results")
            if isinstance(batch, list):
                out.extend(c for c in batch if isinstance(c, dict))
            nxt = page.get("next")
            if nxt:
                parsed = urlparse(str(nxt))
                next_url = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            else:
                next_url = None
        return out

    @staticmethod
    def _category_name(ch: dict[str, Any]) -> str:
        c = ch.get("category")
        if isinstance(c, dict):
            return str(c.get("name") or "")
        return str(c) if c else ""

    @staticmethod
    def _tag_names(ch: dict[str, Any]) -> list[str]:
        tags = ch.get("tags")
        if not isinstance(tags, list):
            return []
        names: list[str] = []
        for t in tags:
            if isinstance(t, dict) and t.get("name"):
                names.append(str(t["name"]))
            elif isinstance(t, str):
                names.append(t)
        return names

    async def _merge_with_instance(self, summary: dict[str, Any]) -> dict[str, Any]:
        cid = summary.get("id")
        if cid is None:
            return dict(summary)
        inst: dict[str, Any] = {}
        try:
            raw = await self._get_json(f"/api/challenges/{int(cid)}/instance/")
            if isinstance(raw, dict):
                inst = raw
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 404):
                logger.warning(
                    "picoCTF: skipping instance for challenge %s (%s)",
                    cid,
                    e.response.status_code,
                )
            else:
                raise
        merged = dict(summary)
        merged["pid"] = str(cid)
        merged["description"] = inst.get("description") or merged.get("description") or ""
        merged["hints"] = inst.get("hints") or []
        eps = inst.get("endpoints")
        if isinstance(eps, list) and eps:
            merged["connection_info"] = "\n".join(str(e) for e in eps)
        elif isinstance(eps, str) and eps:
            merged["connection_info"] = eps
        merged["value"] = merged.get("event_points", merged.get("score", 0))
        merged["score"] = merged["value"]
        merged["category"] = self._category_name(merged)
        merged["tags"] = self._tag_names(merged)
        merged["solves"] = merged.get("users_solved", 0)
        merged["solved"] = bool(merged.get("solved_by_user"))
        return merged

    async def provision_fresh_instance(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Tear down any existing instance, start a new one, poll until endpoints exist.

        Mirrors the web UI \"Start instance\" flow so ``connection_info`` / description
        are populated for challenges backed by CMGR-style instances. Static challenges
        return 404/405 on POST; we skip waiting and merge from GET only.
        """
        merged_base = dict(summary)
        cid = merged_base.get("id")
        if cid is None:
            return await self._merge_with_instance(merged_base)
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            return await self._merge_with_instance(merged_base)

        client = await self._ensure_client()
        del_resp = await client.delete(
            f"/api/challenges/{cid_int}/instance/",
            headers=self._csrf_headers(),
        )
        if del_resp.status_code not in (200, 204, 404, 405):
            logger.debug(
                "picoCTF instance DELETE ch=%s -> %s",
                cid_int,
                del_resp.status_code,
            )

        post_resp = await client.post(
            f"/api/challenges/{cid_int}/instance/",
            json={},
            headers=self._csrf_headers(),
        )
        poll: bool
        if post_resp.status_code in (200, 201, 202, 204):
            poll = True
        elif post_resp.status_code == 400:
            logger.info(
                "picoCTF instance POST 400 for ch=%s: %s",
                cid_int,
                (post_resp.text or "")[:400],
            )
            poll = True
        elif post_resp.status_code in (404, 405):
            logger.debug(
                "picoCTF ch=%s: no instance POST (%s); static or unsupported",
                cid_int,
                post_resp.status_code,
            )
            poll = False
        else:
            logger.warning(
                "picoCTF instance POST ch=%s -> %s %s",
                cid_int,
                post_resp.status_code,
                (post_resp.text or "")[:400],
            )
            poll = post_resp.status_code not in (401, 403)

        if not poll:
            return await self._merge_with_instance(merged_base)

        for i in range(60):
            merged = await self._merge_with_instance(merged_base)
            if (merged.get("connection_info") or "").strip():
                if i:
                    logger.info(
                        "picoCTF instance ready for ch=%s after ~%ds",
                        cid_int,
                        i * 2,
                    )
                return merged
            try:
                raw = await self._get_json(f"/api/challenges/{cid_int}/instance/")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    break
                raise
            if isinstance(raw, dict):
                st = str(raw.get("status") or raw.get("state") or "").lower()
                err = raw.get("error") or raw.get("detail")
                if err and st in ("error", "failed"):
                    logger.warning("picoCTF instance failed ch=%s: %s", cid_int, err)
                    break
            await asyncio.sleep(2)

        return await self._merge_with_instance(merged_base)

    async def provision_fresh_instance_for_challenge_name(
        self, challenge_name: str
    ) -> dict[str, Any] | None:
        """Look up challenge by API name and provision; ``None`` if not listed."""
        summaries = await self._iter_challenge_list_pages()
        p = next((s for s in summaries if str(s.get("name", "")) == challenge_name), None)
        if not p:
            logger.warning('picoCTF: challenge "%s" not found in /api/challenges', challenge_name)
            return None
        return await self.provision_fresh_instance(p)

    def patch_local_metadata_from_merged_challenge(
        self, challenge_dir: str | Path, merged: dict[str, Any]
    ) -> None:
        """Update ``metadata.yml`` with API fields (description, connection_info, hints)."""
        import yaml
        from markdownify import markdownify as html2md

        ch_dir = Path(challenge_dir)
        meta_path = ch_dir / "metadata.yml"
        if not meta_path.is_file():
            logger.warning("picoCTF: no metadata.yml to patch under %s", ch_dir)
            return
        try:
            data: dict[str, Any] = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

        desc = merged.get("description") or ""
        if desc:
            try:
                desc_md = html2md(str(desc), heading_style="atx", escape_asterisks=False)
            except Exception:
                desc_md = str(desc)
            if desc_md.strip():
                data["description"] = desc_md.strip()

        conn = merged.get("connection_info") or ""
        if isinstance(conn, str) and conn.strip():
            data["connection_info"] = conn.strip()

        hints_raw = merged.get("hints") or []
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
        if hints:
            data["hints"] = hints

        for key in ("value", "solves"):
            if key in merged and merged[key] is not None:
                data[key] = merged[key]

        meta_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        summaries = await self._iter_challenge_list_pages()
        stubs: list[dict[str, Any]] = []
        for p in summaries:
            name = str(p.get("name") or "")
            cid = p.get("id")
            stubs.append(
                {
                    "name": name,
                    "id": str(cid) if cid is not None else name,
                    "type": "standard" if not p.get("retired") else "hidden",
                }
            )
            if cid is not None and name:
                self._pid_by_name[name] = str(cid)
        return stubs

    async def fetch_all_challenges(
        self, only_names: frozenset[str] | None = None
    ) -> list[dict[str, Any]]:
        summaries = await self._iter_challenge_list_pages()
        if only_names:
            summaries = [s for s in summaries if str(s.get("name", "")) in only_names]
        out: list[dict[str, Any]] = []
        for p in summaries:
            merged = await self._merge_with_instance(p)
            if merged.get("name"):
                self._pid_by_name[str(merged["name"])] = str(merged.get("pid", ""))
            out.append(merged)
        return out

    async def fetch_solved_names(self) -> set[str]:
        summaries = await self._iter_challenge_list_pages()
        return {
            str(p["name"])
            for p in summaries
            if isinstance(p, dict) and p.get("solved_by_user") is True and p.get("name")
        }

    async def _resolve_pid(self, challenge_name: str) -> str:
        if challenge_name in self._pid_by_name:
            return self._pid_by_name[challenge_name]
        await self.fetch_challenge_stubs()
        if challenge_name in self._pid_by_name:
            return self._pid_by_name[challenge_name]
        raise RuntimeError(f'picoCTF problem "{challenge_name}" not found (not unlocked or wrong name)')

    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        pid = await self._resolve_pid(challenge_name)
        try:
            challenge_id = int(pid)
        except ValueError as e:
            raise RuntimeError(f"picoCTF: invalid challenge id {pid!r}") from e
        client = await self._ensure_client()
        resp = await client.post(
            "/api/submissions/",
            json={"challenge": challenge_id, "flag": flag.strip()},
            headers=self._csrf_headers(),
        )
        if resp.status_code == 403:
            raise RuntimeError(
                "picoCTF: 403 — CSRF or permission denied; export `csrftoken` (and sessionid)."
            )
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

        message = str(data.get("message", data.get("detail", "")))
        if isinstance(data.get("detail"), list):
            message = json.dumps(data["detail"])
        if message and "can't submit flags" in message.lower():
            return SubmitResult("incorrect", message, f"SUBMIT ERROR — {message}")

        correct = data.get("correct")
        if correct is True:
            historical = data.get("historical")
            if historical is True:
                return SubmitResult(
                    "already_solved",
                    message,
                    f'ALREADY SOLVED — "{flag.strip()}"'.strip(),
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
