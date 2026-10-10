"""Commit intent from Entire (`entire checkpoint explain <sha>`), with leakage filter and fallback.

Only the context of the commit under examination is fetched, never its neighbours. Before any
Entire text reaches an LLM, lines that could leak benchmark labels are stripped and counted.
"""

from __future__ import annotations

import json
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


def explain(repo: Path, sha: str, *flags: str, timeout_s: int = 120) -> tuple[int, str]:
    proc = subprocess.run(
        ["entire", "checkpoint", "explain", sha, "--no-pager", *flags],
        cwd=repo, capture_output=True, text=True, timeout=timeout_s,
    )
    return proc.returncode, ANSI.sub("", proc.stdout + proc.stderr)


def intent_line(explain_text: str) -> str:
    """The `## Intent` section of `entire checkpoint explain`; empty if it is a harness tag or placeholder."""
    match = re.search(r"## Intent\s*\n(.*?)\n## ", explain_text, re.DOTALL)
    intent = match.group(1).strip() if match else ""
    return "" if not intent or intent.startswith(("<", "*(")) else intent  # tag or "*(no prompt recorded)*"


def session_prompts(repo: Path, sha: str, limit_chars: int = 4000) -> list[str]:
    """Genuine user prompts from the checkpoint's own session transcript (`--transcript` JSONL).

    Entire's Intent can be a harness event (e.g. `<task-notification>`) when the commit's turn was
    not started by the user, so the session's typed prompts are the fallback source of intent.
    """
    code, out = explain(repo, sha, "--transcript")
    if code != 0:
        return []
    prompts: list[str] = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = event.get("message", {}).get("content") if event.get("type") == "user" else None
        if isinstance(content, str):
            text = re.sub(r"</?pasted_content[^>]*>", "", content).strip()
            if text and not text.startswith("<"):
                prompts.append(text[:limit_chars])
    return prompts


def commit_intent(repo: Path, sha: str) -> Intent:
    refs = ref_names(repo)
    try:
        code, out = explain(repo, sha)
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, out = -1, f"entire unavailable: {exc}"
    match = re.search(r"Checkpoint\s+([0-9A-Z]{20,})", out)
    if code == 0 and match:
        intent = intent_line(out)
        source = "entire"
        if not intent:
            intent = "\n\n".join(session_prompts(repo, sha))
            source = "entire: session prompts (Intent field empty or a harness event)"
        elif intent.endswith(("...", "…")):
            # The Intent field is a shortened preview; the transcript holds the full prompt.
            prefix = intent.rstrip(".…").rstrip()
            full = next((p for p in session_prompts(repo, sha) if p.startswith(prefix)), None)
            if full:
                intent, source = full, "entire: full prompt from the transcript (Intent field was truncated)"
        text, removed = leak_filter(f"Intent:\n{intent}\n\nCheckpoint context:\n{out}", refs)
        return Intent(bool(intent.strip()), match.group(1), text, removed, source)
    reason = out.strip().splitlines()[0] if out.strip() else f"exit {code}"
    # The diff is code, not Entire text, so only the commit message goes through the filter.
    msg, removed = leak_filter(message(repo, sha), refs)
    return Intent(False, None, f"Commit message:\n{msg}\n\nDiff:\n{diff(repo, sha)}", removed, f"fallback: {reason}")
