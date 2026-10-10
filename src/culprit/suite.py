"""Pinned eval suite: every commit in a run is judged by the same tasks.

The suite comes from one snapshot, either a directory at a victim ref (default `evals/` at `main`)
or a directory on disk. It is materialised once under `.culprit/suites/` and copied into each
worktree before evaluation, replacing whatever suite that commit had. The ledger records the
snapshot (commit SHA, or content digest for a path), and resume reuses that snapshot even if
the ref has moved since.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from culprit.config import STATE_DIR
from culprit.gitops import git, resolve

SUITES_DIR = STATE_DIR / "suites"


class SuiteError(RuntimeError):
    pass


@dataclass(frozen=True)
class PinnedSuite:
    source: str  # "git:<ref>:<dir>" or "path:<absolute dir>"
    sha: str  # suite commit SHA, or "sha256:<digest>" for a path
    path: Path  # materialised copy


def is_path_suite(suite: str) -> bool:
    """`--suite` names a directory on disk when it is absolute or contains a separator and exists."""
    return (os.path.isabs(suite) or os.sep in suite) and Path(suite).is_dir()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _from_git(repo: Path, sha: str, directory: str, source: str) -> PinnedSuite:
    dest = SUITES_DIR / f"{sha[:12]}-{directory.replace('/', '_')}"
    if not (dest / directory).is_dir():
        if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}:{directory}"]).returncode != 0:
            raise SuiteError(f"{directory!r} does not exist at {sha[:12]}")
        archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha, directory],
                                 capture_output=True, check=True).stdout
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(dest, filter="data")
    return PinnedSuite(source, sha, dest / directory)


def _from_path(directory: Path) -> PinnedSuite:
    digest = tree_digest(directory)
    dest = SUITES_DIR / f"sha256-{digest[:12]}"
    if not dest.is_dir():
        shutil.copytree(directory, dest)
    return PinnedSuite(f"path:{directory}", f"sha256:{digest}", dest)


def pin(repo: Path, suite: str, suite_ref: str) -> PinnedSuite:
    """Take a new snapshot: `suite` at `suite_ref` in the victim, or the directory `suite` on disk."""
    if is_path_suite(suite):
        return _from_path(Path(suite).resolve())
    return _from_git(repo, resolve(repo, suite_ref), suite, f"git:{suite_ref}:{suite}")


def restore(repo: Path, source: str, sha: str) -> PinnedSuite:
    """Rebuild the snapshot recorded in the ledger; never re-resolve the ref."""
    if source.startswith("path:"):
        pinned = _from_path(Path(source.removeprefix("path:")))
        if pinned.sha != sha:
            raise SuiteError(f"suite at {source} changed since the run started ({sha} → {pinned.sha})")
        return pinned
    _, _, directory = source.removeprefix("git:").partition(":")
    git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    return _from_git(repo, sha, directory, source)


def install_into(pinned: PinnedSuite, worktree: Path, target: str) -> None:
    dest = worktree / target
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(pinned.path, dest)
