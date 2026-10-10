"""Commit intent from Entire (`entire checkpoint explain <sha>`), with leakage filter and fallback.

Only the context of the commit under examination is fetched, never its neighbours. Before any
Entire text reaches an LLM, lines that could leak benchmark labels are stripped and counted.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from culprit.gitops import diff, git, message

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LEAK_PATTERNS = [
    re.compile(r"\bR[1-6]\b"),
    *(re.compile(word, re.IGNORECASE) for word in
      ("hist/", "scenario", "culprit", "regression", "seed", "gap", "pause")),
]
# The default branch names carry no benchmark information and appear in ordinary prose.
HARMLESS_REFS = {"HEAD", "main", "master", "origin", "origin/HEAD", "origin/main", "origin/master"}


@dataclass(frozen=True)
class Intent:
    available: bool
    checkpoint_id: str | None
    text: str
    lines_removed: int
    source: str  # "entire" or "fallback: <reason>"


def ref_names(repo: Path) -> list[str]:
    out = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/tags", "refs/remotes")
    return sorted({r for r in out.splitlines() if r and r not in HARMLESS_REFS})


def leak_filter(text: str, refs: list[str]) -> tuple[str, int]:
    patterns = LEAK_PATTERNS + [re.compile(rf"(?<![\w/.-]){re.escape(r)}(?![\w/-])") for r in refs]
    kept, removed = [], 0
    for line in text.splitlines():
        if any(p.search(line) for p in patterns):
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), removed


def explain(repo: Path, sha: str, timeout_s: int = 120) -> tuple[int, str]:
    proc = subprocess.run(
        ["entire", "checkpoint", "explain", sha, "--no-pager"],
        cwd=repo, capture_output=True, text=True, timeout=timeout_s,
    )
    return proc.returncode, ANSI.sub("", proc.stdout + proc.stderr)


def commit_intent(repo: Path, sha: str) -> Intent:
    refs = ref_names(repo)
    try:
        code, out = explain(repo, sha)
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, out = -1, f"entire unavailable: {exc}"
    match = re.search(r"Checkpoint\s+([0-9A-Z]{20,})", out)
    if code == 0 and match:
        text, removed = leak_filter(out, refs)
        return Intent(True, match.group(1), text, removed, "entire")
    reason = out.strip().splitlines()[0] if out.strip() else f"exit {code}"
    # The diff is code, not Entire text, so only the commit message goes through the filter.
    msg, removed = leak_filter(message(repo, sha), refs)
    return Intent(False, None, f"Commit message:\n{msg}\n\nDiff:\n{diff(repo, sha)}", removed, f"fallback: {reason}")
