# Adding a new CTF platform

This document is written for **human developers** and **coding agents** (Cursor, Copilot, etc.) who need to integrate a new competition backend. Follow the sections in order.

## 1. What you are implementing

The solver talks to the CTF site through a single object that implements **`CompetitionPlatform`** ([`base.py`](base.py)). The coordinator, poller, and all solver agents call this object for:

| Concern | Method | Used by |
|--------|--------|--------|
| Lightweight list for polling | `fetch_challenge_stubs()` | [`CompetitionPoller`](../poller.py) |
| Full list + details for the coordinator UI | `fetch_all_challenges()` | [`coordinator_core.do_fetch_challenges`](../agents/coordinator_core.py), **[`ctf-pull`](../pull_challenges_cli.py)** (bulk download) |
| Which challenges are already solved | `fetch_solved_names()` | Poller + coordinator |
| Submit a flag by **challenge name** (string) | `submit_flag(challenge_name, flag)` | Swarm / `do_submit_flag` |
| Download handouts and write `metadata.yml` | `pull_challenge(challenge_dict, output_dir)` | `do_spawn_swarm` when a challenge is not yet on disk; **`ctf-pull`** (per challenge) |
| Cleanup | `close()` | Coordinator shutdown, **`ctf-pull`** |

Registration is **not** automatic: you add a small package under `backend/platforms/<your_id>/`, call `register_platform()`, and **import that package** from [`registry.py`](registry.py) so it loads at startup.

Credentials must be read from **`Settings`** ([`backend/config.py`](../config.py)), which loads **`.env`** and environment variables (Pydantic `BaseSettings`).

---

## 2. Protocol reference (`CompetitionPlatform`)

Implement all of the following on your client class. Signatures must match.

```python
from typing import Any
from backend.ctfd import SubmitResult  # reuse this dataclass for submit_flag

class YourClient:
    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]: ...
    async def fetch_all_challenges(self) -> list[dict[str, Any]]: ...
    async def fetch_solved_names(self) -> set[str]: ...
    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult: ...
    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str: ...
    async def close(self) -> None: ...
```

### `SubmitResult` ([`backend/ctfd.py`](../ctfd.py))

```python
@dataclass
class SubmitResult:
    status: str   # "correct" | "already_solved" | "incorrect" | "unknown"
    message: str  # short machine-oriented message if useful
    display: str  # human-readable line shown to the model (include CORRECT / ALREADY SOLVED when applicable)
```

Solvers treat **`status` in `("correct", "already_solved")`** as a confirmed flag. The **`display`** string should contain markers like **`CORRECT`** or **`ALREADY SOLVED`** where appropriate so tool output matches [`CORRECT_MARKERS`](../solver_base.py) in some code paths.

### `fetch_challenge_stubs()`

Return a list of dicts. **Each dict must include `"name"`** (string, unique display name used everywhere else in the app).

Optional fields used today:

- `"type"`: e.g. `"hidden"` vs `"standard"` (CTFd compatibility; poller ignores type for logic but keeps names).

The poller diffs **sets of names** between polls to emit `new_challenge` / `challenge_solved` events.

### `fetch_all_challenges()`

Return full challenge records. The coordinator summarizes them in [`do_fetch_challenges`](../agents/coordinator_core.py) using:

- `name`, `category`, `value` (points), `solves`, `description` (truncated for the LLM)

If your API uses another field for points (e.g. `score`), **normalize** to **`value`** in the dicts you return so the coordinator does not show `0` for everything.

### `fetch_solved_names()`

Return a `set[str]` of **exact challenge names** as used in `fetch_all_challenges()` / stubs.

### `submit_flag(challenge_name, flag)`

Resolve **`challenge_name`** to whatever internal id the platform needs, submit, map the HTTP/API response to **`SubmitResult`**, and raise **`RuntimeError`** only for unrecoverable configuration/auth errors (optional but consistent with existing clients).

### `pull_challenge(challenge, output_dir)`

- **`challenge`**: one element from `fetch_all_challenges()` (same shape).
- **Must** create a directory under `output_dir`, write **`metadata.yml`** compatible with [`ChallengeMeta.from_yaml`](../prompts.py) (see existing CTFd / picoCTF pull logic).

Minimum `metadata.yml` fields used downstream:

- `name`, `category`, `description`, `value`, optional `connection_info`, `tags`, `solves`, optional `hints`

Return the **absolute or resolved path** to the challenge directory as a string.

### `close()`

Close HTTP clients, release resources; must be safe to call multiple times or after partial failure.

---

## 3. File layout (recommended)

Use a **package** per platform so you can split HTTP logic from wiring:

```text
backend/platforms/
  yourctf/
    __init__.py       # PLATFORM_ID, create_client(settings), register_platform(...)
    connector.py      # YourClient (optional but keeps __init__.py small)
```

**Reference implementations:**

- Minimal wiring: [`ctfd/__init__.py`](ctfd/__init__.py) (delegates to existing `CTFdClient`).
- Split wiring + HTTP: [`picoctf/__init__.py`](picoctf/__init__.py) + [`picoctf/connector.py`](picoctf/connector.py).

### `__init__.py` template

```python
"""YourCTF connector — credentials from Settings (.env)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.platforms.registry import register_platform

if TYPE_CHECKING:
    from backend.config import Settings

PLATFORM_ID = "yourctf"  # lowercase recommended; matched case-insensitively


def create_client(settings: Settings) -> YourClient:
    # Validate required env-backed fields; raise RuntimeError with a clear message if missing
    ...
    return YourClient(...)


register_platform(PLATFORM_ID, create_client)
```

---

## 4. Register the package (required)

[`registry.py`](registry.py) eagerly imports built-in connectors in **`_load_builtin_connectors()`**. **Add an import line** for your package so `register_platform` runs:

```python
def _load_builtin_connectors() -> None:
    from backend.platforms import ctfd as _ctfd  # noqa: F401
    from backend.platforms import picoctf as _pico  # noqa: F401
    from backend.platforms import yourctf as _yourctf  # noqa: F401
```

Without this import, `ctf-solve --list-platforms` will not show your platform and `build_platform_client` will fail with “Unknown platform”.

---

## 5. Configuration (`.env` + `Settings`)

1. Add fields to **`backend/config.py`** `Settings` for every credential or base URL your connector needs.
2. Document them in **`.env.example`** with placeholder values and short comments.
3. Pydantic maps env vars automatically: field `myctf_token` ↔ `MYCTF_TOKEN` (default alias behavior).

**Do not** hardcode secrets or base URLs inside `connector.py` except as safe defaults; read from `settings` in `create_client`.

### Optional: CLI overrides

If users should override credentials from the command line (like `--pico-cookies`), add options in **`backend/cli.py`** and **`backend/pull_challenges_cli.py`** (mirror the same env vars), applying them to `settings` before `build_platform_client(settings)`. Keep CLI optional—`.env` alone is enough for many setups.

---

## 6. Coordinator and naming

- The coordinator and swarms identify challenges by **`challenge_name`** string. That string must match **`name`** in your API-derived dicts.
- **`do_spawn_swarm`** looks up `challenge_name` in `fetch_all_challenges()` and calls `pull_challenge` if the challenge folder is missing.

If your platform uses numeric ids internally, maintain an internal map **name → id** on the client (see picoCTF `pid` cache).

---

## 7. Bulk pull CLI (`ctf-pull`)

The **`ctf-pull`** command ([`backend/pull_challenges_cli.py`](../pull_challenges_cli.py)) downloads every challenge (or a subset) using the **same** registry as `ctf-solve`:

1. Load **`Settings`** from `.env` (and optional CLI overrides).
2. **`build_platform_client(settings)`** → your connector.
3. **`fetch_all_challenges()`** then, for each row, **`pull_challenge(ch, output_dir)`**.

No separate “pull script” per platform: if `pull_challenge` and `fetch_all_challenges` work for the solver, they work for `ctf-pull`.

Optional flags: `--output`, `--only ChallengeName` (repeatable), `--platform`, plus the same credential overrides as `ctf-solve` (`--ctfd-url`, `--pico-cookies`, …). **`ctf-pull --list-platforms`** lists registered ids.

---

## 8. Verification checklist

After implementation:

1. **`python -m compileall -q backend`** — no syntax errors.
2. **`ctf-solve --list-platforms`** — your `PLATFORM_ID` appears.
3. Set **`PLATFORM=<your_id>`** in `.env` (or `--platform <your_id>`) and run a **dry coordinator** or **single challenge** run if you have fixtures.
4. Confirm **`submit_flag`** returns **`SubmitResult`** with correct `status` for right/wrong/already-solved cases.
5. Confirm **`pull_challenge`** produces a folder with **`metadata.yml`** that loads via `ChallengeMeta.from_yaml`.
6. Run **`ctf-pull --platform <id> --output /tmp/test-pull`** (or `PLATFORM` in `.env`) against a test instance.

---

## 9. What you usually do *not* change

- Swarm logic, Docker sandbox, model routing — unchanged.
- **`CoordinatorDeps.ctfd`** — misleading name; it holds **any** `CompetitionPlatform` instance.
- Poller interval / event kinds — unchanged unless the new API cannot support polling (rare).

---

## 10. Troubleshooting for agents

| Symptom | Likely cause |
|--------|----------------|
| Unknown platform | Missing `register_platform` call or missing import in `_load_builtin_connectors`. |
| Poller never sees new challenges | `fetch_challenge_stubs()` missing or wrong `"name"` keys; or solved set inconsistent with challenge list. |
| Coordinator shows 0 points | Challenges lack `value` (normalize from `score` etc.). |
| Submit always incorrect | Name→id resolution wrong; flag format; auth headers. |
| Spawn fails after pull | Invalid or incomplete `metadata.yml` for `ChallengeMeta`. |
| `ctf-pull` pulls zero / wrong platform | `PLATFORM` / `--platform` not set; or `fetch_all_challenges` empty for that account. |

---

## 11. Summary flow

```text
.env / CLI → Settings
     ↓
settings.platform → build_platform_client(settings) → your create_client(settings)
     ↓
CompetitionPlatform instance → poller + coordinator + swarms (+ ctf-pull)
```

When in doubt, mirror **`backend/platforms/picoctf/`** for HTTP-heavy platforms or **`backend/platforms/ctfd/`** for thin wrappers around an existing client class.
