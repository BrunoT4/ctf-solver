# Contributing

## Project shape

Long term, **most new work should be new CTF backends** under [`backend/platforms/`](backend/platforms/), not one-off scripts.

| Area | Purpose |
|------|--------|
| [`backend/platforms/<id>/`](backend/platforms/) | Connection logic for a CTF site (list, pull, submit). |
| [`backend/config.py`](backend/config.py) + [`.env.example`](.env.example) | Credentials and options loaded from the environment. |
| [`backend/platforms/registry.py`](backend/platforms/registry.py) | Register connectors (one import line per platform in `_load_builtin_connectors`). |

Everything else (coordinator, swarms, sandbox, `ctf-solve`, **`ctf-pull`**) goes through **`build_platform_client(settings)`** and the **`CompetitionPlatform`** protocol.

## Adding a platform

Follow **[backend/platforms/ADDING_A_PLATFORM.md](backend/platforms/ADDING_A_PLATFORM.md)** end-to-end.

## Pulling challenges

Use **`ctf-pull`** (or `python pull_challenges.py` from the repo root after install). It uses the same platform selection as **`ctf-solve`** (`PLATFORM` in `.env` or `--platform`).

```bash
ctf-pull --list-platforms
ctf-pull --platform picoctf --pico-cookies ./cookies.json --output ./challenges
```

Patches and hotfixes outside `backend/platforms/` are still welcome when they fix shared infrastructure.
