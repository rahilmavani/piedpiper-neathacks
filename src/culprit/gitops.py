"""Read-only git queries against the victim repo. Nothing here touches its checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def resolve(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def first_parent_range(repo: Path, good: str, bad: str) -> list[str]:
    """Commits after `good` up to and including `bad`, oldest first, first-parent only."""
    out = git(repo, "rev-list", "--first-parent", "--reverse", f"{good}..{bad}")
    return [line for line in out.splitlines() if line]


def subject(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--format=%s", sha).strip()


def message(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--format=%B", sha).strip()


def diff(repo: Path, sha: str) -> str:
    return git(repo, "show", "--format=", "--patch", "--no-color", sha)
