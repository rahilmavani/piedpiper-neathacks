"""Per-repo settings in `culprit.toml`, written by `culprit init` at the root of the agent's repo.

Commands run inside that repo pick up the victim repo, eval module and suite from it, so
`culprit run --good v1.0 --bad HEAD` needs no other flags. A flag or environment variable always wins
over the file. Without a file, a clone of this repo falls back to the RefundDesk demo it was built
on; an installed package uses the current directory and asks for the eval module.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from culprit.config import PROJECT_ROOT, SOURCE_CHECKOUT

FILENAME = "culprit.toml"


class ProjectError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    repo: Path
    eval_module: str
    suite: str
    suite_ref: str


def find(start: Path) -> Path | None:
    """The nearest culprit.toml in `start` or a parent directory, stopping at the git root."""
    for directory in [start, *start.parents]:
        if (directory / FILENAME).is_file():
            return directory / FILENAME
        if (directory / ".git").exists():
            return None
    return None


def load(path: Path) -> dict[str, str]:
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ProjectError(f"{path} is not valid TOML: {exc}") from exc
    return {k: str(v) for k, v in data.items() if k in {"eval_module", "suite", "suite_ref"}}


def resolve(repo: Path | None, eval_module: str | None, suite: str | None, suite_ref: str | None,
            *, cwd: Path | None = None) -> Settings:
    """Fill each unset value from culprit.toml, then from the defaults."""
    cwd = cwd or Path.cwd()
    path = find((repo or cwd).resolve())
    stored = load(path) if path else {}
    if repo is None:
        repo = path.parent if path else (PROJECT_ROOT.parent / "refunddesk" if SOURCE_CHECKOUT else cwd)
    eval_module = eval_module or stored.get("eval_module") or ("refunddesk.eval" if SOURCE_CHECKOUT else None)
    if not eval_module:
        raise ProjectError(f"no eval module for {repo.resolve()}: run `culprit init` there, or pass --eval-module")
    return Settings(repo.resolve(), eval_module, suite or stored.get("suite") or "evals",
                    suite_ref or stored.get("suite_ref") or "main")


def write(repo: Path, eval_module: str, suite: str, suite_ref: str) -> Path:
    path = repo / FILENAME
    lines = ["# Culprit settings for this repo (https://culprit-site.vercel.app). Keys go in .env, never here.",
             f"eval_module = {json.dumps(eval_module)}  # python -m <eval_module> --task <id> --seed <n>",
             f"suite = {json.dumps(suite)}  # one file per task; the copy at suite_ref judges every commit",
             f"suite_ref = {json.dumps(suite_ref)}", ""]
    path.write_text("\n".join(lines))
    return path
