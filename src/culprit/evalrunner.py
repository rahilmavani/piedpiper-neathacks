"""Drives the victim's eval runner: `python -m <eval_module> --task <id> --seed <n>`.

The runner prints one JSON object (passed, cost, latency, tokens, trace_id). Culprit tags every
victim trace through CULPRIT_RUN_ID, COMMIT_SHA, TASK_ID and REPETITION.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from culprit.ledger import TaskRun
from culprit.sandbox import clean_env, python_of


def victim_env(repo: Path) -> dict[str, str]:
    """Culprit's environment overlaid with the victim's own (gitignored) `.env`, if present."""
    env = clean_env()
    env_file = repo / ".env"
    if env_file.exists():
        env.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    return env


def discover_tasks(worktree: Path, suite: str) -> list[str]:
    suite_dir = worktree / suite
    if not suite_dir.is_dir():
        raise FileNotFoundError(f"suite directory {suite_dir} not found")
    return sorted(
        p.stem for p in suite_dir.iterdir()
        if p.is_file() and not p.name.startswith(("_", ".")) and p.suffix in {".json", ".yaml", ".yml", ".py", ".toml"}
    )


def _parse_output(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("eval runner printed no JSON object") from exc


def _tokens(raw: Any) -> tuple[int | None, int | None]:
    if isinstance(raw, Mapping):
        tin = raw.get("in", raw.get("input", raw.get("input_tokens", raw.get("prompt_tokens"))))
        tout = raw.get("out", raw.get("output", raw.get("output_tokens", raw.get("completion_tokens"))))
        return (None if tin is None else int(tin)), (None if tout is None else int(tout))
    if isinstance(raw, int | float):
        return int(raw), None
    return None, None


def run_task(
    worktree: Path, base_env: Mapping[str, str], eval_module: str, task_id: str, repetition: int,
    *, run_id: str, commit_sha: str, timeout_s: int,
) -> TaskRun:
    env = dict(base_env) | {
        "CULPRIT_RUN_ID": run_id,
        "COMMIT_SHA": commit_sha,
        "TASK_ID": task_id,
        "REPETITION": str(repetition),
    }
    cmd = [str(python_of(worktree)), "-m", eval_module, "--task", task_id, "--seed", str(repetition)]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=worktree, env=env, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return TaskRun(task_id, repetition, False, None, timeout_s * 1000.0, None, None, None,
                       f"timeout after {timeout_s}s")
    wall_ms = (time.monotonic() - started) * 1000.0
    try:
        out = _parse_output(proc.stdout)
    except ValueError as exc:
        tail = (proc.stderr or proc.stdout)[-400:]
        return TaskRun(task_id, repetition, False, None, wall_ms, None, None, None,
                       f"exit {proc.returncode}: {exc}: {tail}")
    tin, tout = _tokens(out.get("tokens"))
    # `latency_ms` is taken as-is; a bare `latency` is the runner's seconds value.
    if out.get("latency_ms") is not None:
        latency_ms = float(out["latency_ms"])
    elif out.get("latency") is not None:
        latency_ms = float(out["latency"]) * 1000.0
    else:
        latency_ms = wall_ms
    return TaskRun(
        task_id=task_id,
        repetition=repetition,
        passed=bool(out.get("passed")),
        cost_usd=None if out.get("cost") is None else float(out["cost"]),
        latency_ms=latency_ms,
        tokens_in=tin,
        tokens_out=tout,
        trace_id=out.get("trace_id"),
        error=out.get("error"),
    )
