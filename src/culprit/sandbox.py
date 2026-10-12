"""Per-commit worktree sandbox: `git worktree add` + `uv sync --locked`.

`--locked` is deliberate: plain `uv sync` would silently re-resolve a broken pin, and
`--frozen` would ignore it. An install or import failure means the commit is SKIPped.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from culprit.config import WORKTREE_DIR
from culprit.gitops import git


@dataclass(frozen=True)
class Install:
    ok: bool
    worktree: Path
    log: str


def clean_env() -> dict[str, str]:
    """Environment for victim subprocesses, without Culprit's own virtualenv leaking in."""
    return {k: v for k, v in os.environ.items() if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}}


def worktree_path(sha: str, label: str = "") -> Path:
    return WORKTREE_DIR / (sha[:12] + (f"-{label}" if label else ""))


def add_worktree(repo: Path, sha: str, label: str = "") -> Path:
    path = worktree_path(sha, label)
    if path.exists():
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
        if head.returncode == 0 and head.stdout.strip() == sha:
            # Undo the pinned suite copied in last time; ignored files such as .venv survive.
            reset = subprocess.run(["git", "-C", str(path), "reset", "-q", "--hard", sha], capture_output=True)
            clean = subprocess.run(["git", "-C", str(path), "clean", "-q", "-fd"], capture_output=True)
            if reset.returncode == 0 and clean.returncode == 0:
                return path
        remove_worktree(repo, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", "--force", str(path), sha)
    return path


def remove_worktree(repo: Path, path: Path) -> None:
    git(repo, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git(repo, "worktree", "prune", check=False)


def apply(worktree: Path, patch: str, reverse: bool = False) -> tuple[bool, str]:
    """Apply (or reverse-apply) `patch` to the worktree's files; (applied, git's output)."""
    proc = subprocess.run(["git", "-C", str(worktree), "apply", *(["-R"] if reverse else []), "--whitespace=nowarn",
                           "-"], input=patch, capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout + proc.stderr


def install(worktree: Path, import_module: str, timeout_s: int) -> Install:
    env = clean_env()
    logs: list[str] = []
    try:
        sync = subprocess.run(["uv", "sync", "--locked"], cwd=worktree, env=env, capture_output=True,
                              text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return Install(False, worktree, f"uv sync --locked timed out after {timeout_s}s")
    logs.append(f"$ uv sync --locked (exit {sync.returncode})\n{sync.stdout}{sync.stderr}")
    if sync.returncode != 0:
        return Install(False, worktree, "\n".join(logs))
    probe = subprocess.run([str(python_of(worktree)), "-c", f"import {import_module}"], cwd=worktree, env=env,
                           capture_output=True, text=True, timeout=120)
    logs.append(f"$ python -c 'import {import_module}' (exit {probe.returncode})\n{probe.stderr}")
    return Install(probe.returncode == 0, worktree, "\n".join(logs))


def python_of(worktree: Path) -> Path:
    return worktree / ".venv" / "bin" / "python"
