"""Shared coordinator tool logic — called by both Claude SDK and Codex coordinators."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from backend.deps import CoordinatorDeps
from backend.prompts import ChallengeMeta
from backend.solver_base import FLAG_FOUND, SolverResult

logger = logging.getLogger(__name__)


async def finalize_swarm_log_bundle(
    manifest_path: Path,
    settings: object,
    meta: ChallengeMeta,
    result: SolverResult | None,
    *,
    no_submit: bool = False,
) -> None:
    """Update manifest.json and optionally generate a Markdown write-up."""
    solved = bool(result and result.status == FLAG_FOUND)
    flag_val = result.flag if result else None
    ended = time.time()
    try:
        mf = json.loads(manifest_path.read_text(encoding="utf-8"))
        mf["ended_ts"] = ended
        mf["outcome"] = "solved" if solved else "finished"
        mf["flag"] = flag_val
        mf["no_submit"] = no_submit
        manifest_path.write_text(json.dumps(mf, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("Could not update manifest %s", manifest_path, exc_info=True)
    if getattr(settings, "writeup_enabled", True):
        try:
            from backend.writeup import maybe_generate_writeup

            await maybe_generate_writeup(
                manifest_path=manifest_path,
                settings=settings,
                challenge_description=meta.description or "",
                solved=solved,
                flag=flag_val,
            )
        except Exception:
            logger.warning("Write-up failed for %s", manifest_path, exc_info=True)


def safe_challenge_slug(name: str) -> str:
    """Filesystem-safe slug for log dirs (shared by CLI single-challenge mode and coordinator)."""
    s = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', "", name.lower().strip())
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-") or "challenge"
    return s


async def do_fetch_challenges(deps: CoordinatorDeps) -> str:
    challenges = await deps.platform_client.fetch_all_challenges()
    solved = await deps.platform_client.fetch_solved_names()
    result = [
        {
            "name": ch.get("name", "?"),
            "category": ch.get("category", "?"),
            "value": ch.get("value", 0),
            "solves": ch.get("solves", 0),
            "status": "SOLVED" if ch.get("name") in solved else "unsolved",
            "description": (ch.get("description") or "")[:200],
        }
        for ch in challenges
    ]
    return json.dumps(result, indent=2)


async def do_get_solve_status(deps: CoordinatorDeps) -> str:
    solved = await deps.platform_client.fetch_solved_names()
    swarm_status = {name: swarm.get_status() for name, swarm in deps.swarms.items()}
    return json.dumps({"solved": sorted(solved), "active_swarms": swarm_status}, indent=2)


async def do_spawn_swarm(deps: CoordinatorDeps, challenge_name: str) -> str:
    # Retire ALL finished swarms before checking capacity
    finished = [
        name for name, swarm in deps.swarms.items()
        if swarm.cancel_event.is_set()
        or (name in deps.swarm_tasks and deps.swarm_tasks[name].done())
    ]
    for name in finished:
        del deps.swarms[name]
        deps.swarm_tasks.pop(name, None)

    active_count = len(deps.swarms)
    if active_count >= deps.max_concurrent_challenges:
        return f"At capacity ({active_count}/{deps.max_concurrent_challenges} challenges running). Wait for one to finish."

    if challenge_name in deps.swarms:
        return f"Swarm still running for {challenge_name}"

    # Auto-pull challenge if needed
    if challenge_name not in deps.challenge_dirs:
        challenges = await deps.platform_client.fetch_all_challenges()
        ch_data = next((c for c in challenges if c.get("name") == challenge_name), None)
        if not ch_data:
            return f"Challenge '{challenge_name}' not found on the platform"
        prov = getattr(deps.platform_client, "provision_fresh_instance", None)
        if prov:
            ch_data = await prov(ch_data)
        output_dir = str(Path(deps.challenges_root))
        ch_dir = await deps.platform_client.pull_challenge(ch_data, output_dir)
        deps.challenge_dirs[challenge_name] = ch_dir
        deps.challenge_metas[challenge_name] = ChallengeMeta.from_yaml(Path(ch_dir) / "metadata.yml")

    from backend.agents.swarm import ChallengeSwarm

    settings = deps.settings
    log_base = getattr(settings, "log_base", "logs")
    run_id = (deps.log_run_id or getattr(settings, "log_run_id", "") or "default").strip()
    slug = safe_challenge_slug(challenge_name)
    bundle = Path(log_base) / run_id / slug
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "swarm").mkdir(exist_ok=True)
    manifest_path = bundle / "manifest.json"
    manifest = {
        "run_id": run_id,
        "challenge_name": challenge_name,
        "challenge_slug": slug,
        "platform": getattr(settings, "platform", "ctfd"),
        "started_ts": time.time(),
        "models": list(deps.model_specs),
        "outcome": "running",
        "flag": None,
        "log_bundle_dir": str(bundle.resolve()),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    swarm = ChallengeSwarm(
        challenge_dir=deps.challenge_dirs[challenge_name],
        meta=deps.challenge_metas[challenge_name],
        platform_client=deps.platform_client,
        cost_tracker=deps.cost_tracker,
        settings=deps.settings,
        model_specs=deps.model_specs,
        no_submit=deps.no_submit,
        coordinator_inbox=deps.coordinator_inbox,
        log_bundle_dir=str(bundle.resolve()),
    )
    deps.swarms[challenge_name] = swarm

    async def _run_and_cleanup() -> None:
        result = await swarm.run()
        meta = ChallengeMeta.from_yaml(Path(deps.challenge_dirs[challenge_name]) / "metadata.yml")
        deps.challenge_metas[challenge_name] = meta
        await finalize_swarm_log_bundle(
            manifest_path, settings, meta, result, no_submit=deps.no_submit
        )
        if result and result.status == FLAG_FOUND:
            deps.results[challenge_name] = {
                "flag": result.flag,
                "submit": "DRY RUN" if deps.no_submit else "confirmed by solver",
            }

    task = asyncio.create_task(_run_and_cleanup(), name=f"swarm-{challenge_name}")
    deps.swarm_tasks[challenge_name] = task
    return f"Swarm spawned for {challenge_name} with {len(deps.model_specs)} models"


async def do_check_swarm_status(deps: CoordinatorDeps, challenge_name: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    return json.dumps(swarm.get_status(), indent=2)


async def do_submit_flag(deps: CoordinatorDeps, challenge_name: str, flag: str) -> str:
    if deps.no_submit:
        return f'DRY RUN — would submit "{flag.strip()}" for {challenge_name}'
    try:
        result = await deps.platform_client.submit_flag(challenge_name, flag)
        return result.display
    except Exception as e:
        return f"submit_flag error: {e}"


async def do_kill_swarm(deps: CoordinatorDeps, challenge_name: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    swarm.kill()
    return f"Swarm for {challenge_name} cancelled"


async def do_bump_agent(deps: CoordinatorDeps, challenge_name: str, model_spec: str, insights: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    solver = swarm.solvers.get(model_spec)
    if not solver:
        return f"No solver for {model_spec} in {challenge_name}"
    solver.bump(insights)
    return f"Bumped {model_spec} on {challenge_name}"


async def do_read_solver_trace(deps: CoordinatorDeps, challenge_name: str, model_spec: str, last_n: int = 20) -> str:
    """Read the last N trace events from a solver's JSONL log."""
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm for {challenge_name}"
    solver = swarm.solvers.get(model_spec)
    if not solver:
        return f"No solver for {model_spec}"
    trace_path = getattr(solver, "tracer", None)
    if not trace_path:
        return "No tracer on solver"
    path = trace_path.path if hasattr(trace_path, "path") else str(trace_path)
    try:
        lines = Path(path).read_text().strip().split("\n")
        recent = lines[-last_n:]
        summary = []
        for line in recent:
            try:
                d = json.loads(line)
                t = d.get("type", "?")
                if t == "tool_call":
                    args_str = str(d.get("args", ""))[:100]
                    summary.append(f"step {d.get('step','?')} CALL {d.get('tool','?')}: {args_str}")
                elif t == "tool_result":
                    result_str = str(d.get("result", ""))[:100]
                    summary.append(f"step {d.get('step','?')} RESULT {d.get('tool','?')}: {result_str}")
                elif t in ("finish", "error", "bump", "turn_failed"):
                    summary.append(f"** {t}: {json.dumps({k:v for k,v in d.items() if k != 'ts'})}")
                elif t == "usage":
                    summary.append(f"usage: in={d.get('input_tokens',0)} out={d.get('output_tokens',0)} cost=${d.get('cost_usd',0):.4f}")
                else:
                    summary.append(f"{t}: {str(d)[:80]}")
            except Exception:
                summary.append(line[:100])
        return "\n".join(summary)
    except FileNotFoundError:
        return f"Trace file not found: {path}"
    except Exception as e:
        return f"Error reading trace: {e}"


async def do_broadcast(deps: CoordinatorDeps, challenge_name: str, message: str) -> str:
    """Broadcast a message to all solvers working on a challenge."""
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    await swarm.message_bus.broadcast(message)
    return f"Broadcast to all solvers on {challenge_name}"
