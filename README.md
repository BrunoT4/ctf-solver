# ctf-solver

This repository **builds on** [**verialabs/ctf-agent**](https://github.com/verialabs/ctf-agent) (MIT), the autonomous Capture The Flag solver from [Veria Labs](https://verialabs.com) that runs a coordinator plus parallel model “swarms” against challenges in Docker. The upstream project [documented a full clear](https://github.com/verialabs/ctf-agent) at BSidesSF 2026 (52/52) and supports categories such as pwn, rev, crypto, forensics, web, and misc. **We are not Veria Labs**; this is an independent fork that keeps their architecture and extends it.

**What this fork adds**

- **Pluggable CTF platforms** — connectors live under [`backend/platforms/`](backend/platforms/); set `PLATFORM` in `.env` or use `--platform`.  [adding a site](backend/platforms/ADDING_A_PLATFORM.md) means a new package + registry entry.
- **Swarm logs** — per-run directories under `logs/` with `manifest.json` and JSONL traces per model.
- **Write-ups** — optional educational Markdown under `write-ups/`, generated from logs + challenge text (when API keys are configured).
- **`ctf-pull`** — bulk download of challenges to disk using the **same** connector as `ctf-solve` (no separate CTFd-only script path).

Upstream changes can be merged from `https://github.com/verialabs/ctf-agent.git` (this repo uses it as **`git remote upstream`** when configured that way).

## How It Works

A **coordinator** LLM manages the competition while **solver swarms** attack individual challenges. Each swarm runs multiple models simultaneously — the first to find the flag wins.

```
                        +-----------------+
                        |  CTF platform   |
                        +--------+--------+
                                 |
                        +--------v--------+
                        |  Poller (5s)    |
                        +--------+--------+
                                 |
                        +--------v--------+
                        | Coordinator LLM |
                        | (Claude/Codex)  |
                        +--------+--------+
                                 |
              +------------------+------------------+
              |                  |                  |
     +--------v--------+ +------v---------+ +------v---------+
     | Swarm:          | | Swarm:         | | Swarm:         |
     | challenge-1     | | challenge-2    | | challenge-N    |
     |                 | |                | |                |
     |  Opus (med)     | |  Opus (med)    | |                |
     |  Opus (max)     | |  Opus (max)    | |     ...        |
     |  GPT-5.4        | |  GPT-5.4       | |                |
     |  GPT-5.4-mini   | |  GPT-5.4-mini  | |                |
     |  GPT-5.3-codex  | |  GPT-5.3-codex | |                |
     +--------+--------+ +--------+-------+ +----------------+
              |                    |
     +--------v--------+  +-------v--------+
     | Docker Sandbox  |  | Docker Sandbox |
     | (isolated)      |  | (isolated)     |
     |                 |  |                |
     | pwntools, r2,   |  | pwntools, r2,  |
     | gdb, python...  |  | gdb, python... |
     +-----------------+  +----------------+
```

Each solver runs in an isolated Docker container with CTF tools pre-installed. Solvers never give up — they keep trying different approaches until the flag is found.

## Quick Start

```bash
# Install (editable package + deps — required so `ctf-pull` / `ctf-solve` can import `backend`)
uv sync

# If you see `ModuleNotFoundError: No module named 'backend'`, reinstall the project from the repo root:
#   uv pip install -e .
# Or run via uv (adds the package to the path):
#   uv run ctf-pull --help
# Or from the repo root without an editable install:
#   PYTHONPATH=. .venv/bin/python -m backend.pull_challenges_cli --help

# Build sandbox image
docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .

# Configure credentials
cp .env.example .env
# Edit .env with your API keys and CTFd token

# Run against a CTFd instance
uv run ctf-solve \
  --ctfd-url https://ctf.example.com \
  --ctfd-token ctfd_your_token \
  --challenges-dir challenges \
  --max-challenges 10 \
  -v
```

### CTF platforms (`backend/platforms/`)

Connectors live under [`backend/platforms/`](backend/platforms/): each package registers an id (e.g. `ctfd`, `picoctf`). Set `PLATFORM` in `.env` or pass `--platform <id>`. Run `ctf-solve --list-platforms` to see what is registered. Credentials are read from `.env` via `Settings` (see `.env.example`). **Adding a new site:** see [`backend/platforms/ADDING_A_PLATFORM.md`](backend/platforms/ADDING_A_PLATFORM.md).

### picoCTF (session cookies)

Use [play.picoctf.org](https://play.picoctf.org/)’s HTTP API (`/api/challenges`, per-challenge `/api/challenges/<id>/instance/`, and `POST /api/submissions/`) with cookies from your logged-in browser. Export cookies as JSON: flat `{"sessionid":"...","csrftoken":"...",...}`, a `[{"name","value"},...]` array, or a devtools-style object with a **`Request Cookies`** map. The client sends `csrftoken` (or legacy `token`) as `X-CSRFToken` / `X-CSRF-Token` on submissions.

```bash
uv run ctf-solve \
  --platform picoctf \
  --pico-cookies ./pico_cookies.json \
  --challenges-dir challenges \
  --max-challenges 5 \
  -v
```

### Pull challenges to disk (`ctf-pull`)

Bulk download uses the **same** platform connector as the solver (`PLATFORM` in `.env` or `--platform`). Configure credentials in `.env`, then:

```bash
uv run ctf-pull --output ./challenges
uv run ctf-pull --platform ctfd --ctfd-url https://ctf.example.com --ctfd-token ctfd_...
uv run ctf-pull --platform picoctf --pico-cookies ./pico_cookies.json --output ./challenges
```

`python pull_challenges.py` from the repo root is a thin wrapper after `pip install -e .` / `uv sync`.

### Swarm logs and write-ups

Each swarm writes a bundle under `logs/<run_id>/<challenge-slug>/`: `manifest.json` plus per-model JSONL traces in `swarm/`. After a run, if `WRITEUP_ENABLED` is true and `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set, an educational Markdown file is created under `write-ups/` from the logs and challenge description. Use `--log-truncate-bytes 0` for full trace payloads (large on disk). Use `--writeup-on-failure` for postmortems when no flag is recovered.

## Coordinator Backends

```bash
# Claude SDK coordinator (default)
uv run ctf-solve --coordinator claude ...

# Codex coordinator (GPT-5.4 via JSON-RPC)
uv run ctf-solve --coordinator codex ...
```

## Solver Models

Default model lineup (configurable in `backend/models.py`):

| Model | Provider | Notes |
|-------|----------|-------|
| Claude Opus 4.6 (medium) | Claude SDK | Balanced speed/quality |
| Claude Opus 4.6 (max) | Claude SDK | Deep reasoning |
| GPT-5.4 | Codex | Best overall solver |
| GPT-5.4-mini | Codex | Fast, good for easy challenges |
| GPT-5.3-codex | Codex | Reasoning model (xhigh effort) |

## Sandbox Tooling

Each solver gets an isolated Docker container pre-loaded with CTF tools:

| Category | Tools |
|----------|-------|
| **Binary** | radare2, GDB, objdump, binwalk, strings, readelf |
| **Pwn** | pwntools, ROPgadget, angr, unicorn, capstone |
| **Crypto** | SageMath, RsaCtfTool, z3, gmpy2, pycryptodome, cado-nfs |
| **Forensics** | volatility3, Sleuthkit (mmls/fls/icat), foremost, exiftool |
| **Stego** | steghide, stegseek, zsteg, ImageMagick, tesseract OCR |
| **Web** | curl, nmap, Python requests, flask |
| **Misc** | ffmpeg, sox, Pillow, numpy, scipy, PyTorch, podman |

## Features

- **Multi-model racing** — multiple AI models attack each challenge simultaneously
- **Auto-spawn** — new challenges detected and attacked automatically
- **Coordinator LLM** — reads solver traces, crafts targeted technical guidance
- **Cross-solver insights** — findings shared between models via message bus
- **Docker sandboxes** — isolated containers with full CTF tooling
- **Operator messaging** — send hints to running solvers mid-competition

## Configuration

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
CTFD_URL=https://ctf.example.com
CTFD_TOKEN=ctfd_your_token
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
```

All settings can also be passed as environment variables or CLI flags.

## Requirements

- Python 3.12+
- Docker
- API keys for at least one provider (Anthropic, OpenAI, Google)
- `codex` CLI (for Codex solver/coordinator)
- `claude` CLI (bundled with claude-agent-sdk)

## Acknowledgements

- [es3n1n/Eruditus](https://github.com/es3n1n/Eruditus) — CTFd interaction patterns; free-hint unlock flow in [`backend/ctfd.py`](backend/ctfd.py) `pull_challenge`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — new CTF sites should add a package under [`backend/platforms/`](backend/platforms/) (detailed steps in [ADDING_A_PLATFORM.md](backend/platforms/ADDING_A_PLATFORM.md)).
