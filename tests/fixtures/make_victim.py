"""Builds a tiny throwaway victim repo for tests and local runs (no LLM, no network at eval time).

"Fragile" tasks pass with probability `FRAGILE_PASS` (0.95 at good, 0.05 after the breaking
commit, `--noisy-pass` on optional noisy commits before it). Noise is deterministic per (task, seed), so the
fixture exercises the bisect, skip and resampling paths without spending money.

    uv run python tests/fixtures/make_victim.py /tmp/victim --commits 14 --breaks-at 10 --unbuildable-at 7 \
        --noisy-from 8
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

PYPROJECT = """\
[project]
name = "refunddesk"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [{deps}]

[tool.uv]
package = false
"""

AGENT = """\
FRAGILE_PASS = {p}
"""

EVAL = '''\
"""Fake eval runner with the same interface as the real one; each run costs a nominal $0.001."""
import argparse, json, random, time
from pathlib import Path

from refunddesk import agent

FRAGILE = {{"t01", "t02", "t03", "t04", "t05"}}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    if not (Path("evals") / f"{{a.task}}.json").exists():  # like the real load_task
        print(json.dumps({{"passed": False, "cost": 0.0, "latency_ms": 0.0, "tokens": None, "trace_id": None,
                          "error": f"FileNotFoundError: no task named {{a.task!r}}"}}))
        return
    rng = random.Random(f"{{a.task}}:{{a.seed}}")
    p_pass = agent.FRAGILE_PASS if a.task in FRAGILE else 0.95
    started = time.monotonic()
    passed = rng.random() < p_pass
    print(json.dumps({{"passed": passed, "cost": 0.001, "latency_ms": (time.monotonic() - started) * 1000,
                      "tokens": {{"in": 100, "out": 20}}, "trace_id": None}}))


if __name__ == "__main__":
    main()
'''


def sh(repo: Path, *args: str) -> None:
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


def commit(repo: Path, msg: str) -> None:
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", msg)


def build(path: Path, commits: int, breaks_at: int, unbuildable_at: int | None, noisy_from: int | None = None,
          noisy_pass: float = 0.75, late_task: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=False)
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.email", "fixture@example.invalid")
    sh(path, "git", "config", "user.name", "fixture")
    pkg = path / "refunddesk"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "agent.py").write_text(AGENT.format(p=0.95))
    (pkg / "eval.py").write_text(EVAL.format())
    (path / "pyproject.toml").write_text(PYPROJECT.format(deps=""))
    (path / ".gitignore").write_text(".venv/\n")
    evals = path / "evals"
    evals.mkdir()
    for i in range(1, 11):
        (evals / f"t{i:02d}.json").write_text('{"message": "refund please"}\n')
    sh(path, "uv", "lock", "-q")
    commit(path, "initial agent")
    sh(path, "git", "tag", "good-v1.0")

    notes = path / "NOTES.md"
    for n in range(1, commits + 1):
        # The dependency pin and the agent's pass rate are independent files, so every change due at
        # commit n is applied; one never displaces another (e.g. the pin revert and a noisy commit).
        changes = []
        if unbuildable_at is not None and n == unbuildable_at:
            (path / "pyproject.toml").write_text(PYPROJECT.format(deps='"requests==99.99.99"'))
            changes.append("pin requests")
        elif unbuildable_at is not None and n == unbuildable_at + 1:
            (path / "pyproject.toml").write_text(PYPROJECT.format(deps=""))
            changes.append("revert requests pin")
        if n == breaks_at:
            (pkg / "agent.py").write_text(AGENT.format(p=0.05))
            changes.append("speed up tool handling")
        elif noisy_from is not None and n == noisy_from:
            (pkg / "agent.py").write_text(AGENT.format(p=noisy_pass))
            changes.append("tune tool timeouts")
        if late_task and n == commits:
            (evals / "t11.json").write_text('{"message": "refund the second order"}\n')
            changes.append("evals: add t11")
        if not changes:
            with notes.open("a") as f:
                f.write(f"- maintenance note {n}\n")
            changes.append(f"docs: maintenance note {n}")
        commit(path, "; ".join(changes))
    return path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--commits", type=int, default=14)
    p.add_argument("--breaks-at", type=int, default=10)
    p.add_argument("--unbuildable-at", type=int, default=7)
    p.add_argument("--noisy-from", type=int, default=None)
    p.add_argument("--noisy-pass", type=float, default=0.75)
    p.add_argument("--late-task", action="store_true", help="add task t11 only on the last commit")
    a = p.parse_args()
    print(build(a.path, a.commits, a.breaks_at, a.unbuildable_at, a.noisy_from, a.noisy_pass, a.late_task))


if __name__ == "__main__":
    main()
