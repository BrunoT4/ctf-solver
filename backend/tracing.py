"""Per-tool-call JSONL event tracing — one file per solver, streamable via tail -f."""

from __future__ import annotations

import atexit
import json
import time
from pathlib import Path


def _sanitize(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


class SolverTracer:
    """Append-only JSONL event tracer. Flushes every write for tail -f streaming."""

    def __init__(
        self,
        challenge_name: str,
        model_id: str,
        log_dir: str = "logs",
        *,
        swarm_trace_dir: str | None = None,
        log_truncate_bytes: int = 2000,
    ) -> None:
        self._truncate = log_truncate_bytes
        self._meta = {"challenge": challenge_name, "model_id": model_id}
        if swarm_trace_dir:
            Path(swarm_trace_dir).mkdir(parents=True, exist_ok=True)
            self.path = str(Path(swarm_trace_dir) / f"trace-{_sanitize(model_id)}.jsonl")
        else:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            self.path = str(
                Path(log_dir) / f"trace-{_sanitize(challenge_name)}-{_sanitize(model_id)}-{ts}.jsonl"
            )
        self._fh = open(self.path, "a")
        atexit.register(self._close)

    def _clip(self, s: str) -> str:
        if self._truncate <= 0:
            return s
        return s[: self._truncate]

    def close(self) -> None:
        """Explicitly close the trace file. Safe to call multiple times."""
        if not self._fh.closed:
            try:
                self._fh.close()
            except Exception:
                pass

    _close = close  # atexit compat

    def _write(self, event: dict) -> None:
        try:
            row = {"ts": time.time(), **self._meta, **event}
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()
        except Exception:
            pass

    def tool_call(self, tool_name: str, args: dict | str, step: int) -> None:
        args_str = args if isinstance(args, str) else json.dumps(args)
        self._write({"type": "tool_call", "tool": tool_name, "args": self._clip(args_str), "step": step})

    def tool_result(self, tool_name: str, result: str, step: int) -> None:
        self._write({"type": "tool_result", "tool": tool_name, "result": self._clip(result), "step": step})

    def model_response(self, text: str, step: int, input_tokens: int = 0, output_tokens: int = 0) -> None:
        text_out = text if self._truncate <= 0 else text[: self._truncate]
        self._write(
            {
                "type": "model_response",
                "text": text_out,
                "step": step,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )

    def usage(self, input_tokens: int, output_tokens: int, cache_read: int, cost_usd: float) -> None:
        self._write(
            {
                "type": "usage",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "cost_usd": round(cost_usd, 6),
            }
        )

    def event(self, kind: str, **kwargs) -> None:
        self._write({"type": kind, **kwargs})
