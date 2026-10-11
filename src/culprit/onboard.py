"""`culprit init`: set up an agent's repo for Culprit (eval module, suite) and check it once.

Everything here is a plain function so it can be tested without prompts; the CLI asks the questions.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from culprit.evalrunner import _parse_output, discover_tasks, victim_env
from culprit.providers import Provider

KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
SKIP_DIRS = {".git", ".venv", "venv", ".culprit", "node_modules", "__pycache__", ".tox", "build", "dist"}


class SetupError(RuntimeError):
    pass


def git_root(path: Path) -> Path:
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SetupError(f"{path} is not inside a git repository; Culprit bisects git history")
    return Path(proc.stdout.strip())


def current_branch(repo: Path) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True)
    return proc.stdout.strip() or "main"


def eval_modules(repo: Path) -> list[str]:
    """Modules that look like an eval runner (`eval.py`, `evals.py`, `eval/__main__.py`), nearest first."""
    found: list[tuple[int, str]] = []
    for path in repo.rglob("*.py"):
        rel = path.relative_to(repo)
        if SKIP_DIRS.intersection(rel.parts) or rel.parts[0] == "tests":
            continue
        if path.name in {"eval.py", "evals.py"}:
            parts = rel.with_suffix("").parts
        elif path.name == "__main__.py" and path.parent.name in {"eval", "evals"}:
            parts = rel.parent.parts
        else:
            continue
        if parts and parts[0] == "src":
            parts = parts[1:]
        if parts:
            found.append((len(parts), ".".join(parts)))
    return [module for _, module in sorted(set(found))]


def ignore_local_files(repo: Path) -> list[str]:
    """Add .culprit/ (run state) and, if the repo has one, .env to .gitignore; returns what was added."""
    path = repo / ".gitignore"
    present = {line.strip() for line in path.read_text().splitlines()} if path.is_file() else set()
    wanted = [".culprit/"] + ([".env"] if (repo / ".env").is_file() else [])
    missing = [entry for entry in wanted if entry not in present and entry.rstrip("/") not in present]
    if missing:
        text = path.read_text() if path.is_file() else ""
        prefix = "" if not text or text.endswith("\n") else "\n"
        path.write_text(text + prefix + "# Culprit: local keys and run state\n" + "\n".join(missing) + "\n")
    return missing


def suite_tasks(repo: Path, suite: str) -> list[str]:
    directory = Path(suite) if Path(suite).is_absolute() else repo / suite
    try:
        return discover_tasks(directory)
    except FileNotFoundError:
        return []


@dataclass(frozen=True)
class Check:
    ok: bool
    message: str


def check_eval(repo: Path, eval_module: str, task: str, victim: Provider | None, timeout_s: int = 300) -> Check:
    """Run one task the way a bisect step does and check its last line is a JSON object with `passed`."""
    env = victim_env(repo, victim)
    cmd = ["uv", "run", "--locked", "python", "-m", eval_module, "--task", task, "--seed", "0"]
    try:
        proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        return Check(False, "uv isn't installed; see https://docs.astral.sh/uv/")
    except subprocess.TimeoutExpired:
        return Check(False, f"`{' '.join(cmd)}` didn't finish within {timeout_s}s")
    tail = (proc.stderr or proc.stdout).strip()[-600:]
    try:
        out = _parse_output(proc.stdout)
    except ValueError:
        return Check(False, f"`{' '.join(cmd)}` exited {proc.returncode} without printing a JSON line.\n{tail}")
    if not isinstance(out, dict) or "passed" not in out:
        return Check(False, f"the JSON line has no \"passed\" field: {out}")
    extras = ", ".join(f"{k}={out[k]}" for k in ("cost", "latency_ms", "error") if out.get(k) is not None)
    return Check(True, f"task {task}: passed={bool(out['passed'])}" + (f" ({extras})" if extras else ""))
