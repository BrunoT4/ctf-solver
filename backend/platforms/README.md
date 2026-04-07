# CTF platform connectors

Each subfolder is one platform. Credentials come from `.env` via `backend.config.Settings`.

| Folder    | `PLATFORM` value | Env vars (see `.env.example`)        |
|-----------|------------------|--------------------------------------|
| `ctfd/`   | `ctfd`           | `CTFD_URL`, `CTFD_TOKEN`, …          |
| `picoctf/`| `picoctf`        | `PICO_BASE_URL`, `PICO_COOKIES_FILE` |

## Adding a platform

For **step-by-step instructions** (protocol details, `SubmitResult`, `metadata.yml`, registry import, verification), read **[ADDING_A_PLATFORM.md](./ADDING_A_PLATFORM.md)**.

Short version:

1. Implement `CompetitionPlatform` in a new package under `backend/platforms/<id>/`.
2. Call `register_platform(PLATFORM_ID, create_client)` from that package’s `__init__.py`.
3. **Import your package** in `backend/platforms/registry.py` inside `_load_builtin_connectors()`.
4. Extend `Settings` and `.env.example` for credentials.
5. Run `ctf-solve --list-platforms` to confirm registration.

Bulk-download all challenges to disk: **`ctf-pull`** (same `PLATFORM` and `.env` as `ctf-solve`). See [ADDING_A_PLATFORM.md §7](ADDING_A_PLATFORM.md#7-bulk-pull-cli-ctf-pull).
