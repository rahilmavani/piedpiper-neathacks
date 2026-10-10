"""Entire intent: the truncated `## Intent` preview is replaced by the full prompt from the transcript."""

import json
import subprocess
from pathlib import Path

import pytest

from culprit import entire

FULL = ("RefundDesk is too slow. Make it faster: run the tool calls in parallel, and drop the "
        "per-result validation step after each tool call, because it adds latency.")


def explain_text(intent: str) -> str:
    return (f"● Checkpoint 01M4JM8P2C4NDS2AAQ0MPVR8YR\n## Intent\n\n{intent}\n\n## Summary\n\n"
            "*Not generated yet.*\n")


def transcript(*prompts: str) -> str:
    return "\n".join(json.dumps({"type": "user", "message": {"content": p}}) for p in prompts)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def fake_explain(intent: str, prompts: tuple[str, ...]):
    def explain(repo, sha, *flags, timeout_s=120):
        return 0, transcript(*prompts) if "--transcript" in flags else explain_text(intent)

    return explain


def test_truncated_intent_is_completed_from_the_transcript(monkeypatch, repo):
    monkeypatch.setattr(entire, "explain", fake_explain(FULL[:70] + "...", ("hi", FULL, "proceed anyway")))
    intent = entire.commit_intent(repo, "a" * 40)
    assert intent.available
    assert "truncated" in intent.source
    assert intent.text.startswith(f"Intent:\n{FULL}\n")


def test_full_intent_is_used_as_is(monkeypatch, repo):
    monkeypatch.setattr(entire, "explain", fake_explain(FULL, ("something else",)))
    intent = entire.commit_intent(repo, "a" * 40)
    assert intent.source == "entire"
    assert intent.text.startswith(f"Intent:\n{FULL}\n")


def test_truncated_intent_without_a_matching_prompt_keeps_the_preview(monkeypatch, repo):
    monkeypatch.setattr(entire, "explain", fake_explain("Make it faster...", ("unrelated prompt",)))
    intent = entire.commit_intent(repo, "a" * 40)
    assert intent.source == "entire"
    assert intent.text.startswith("Intent:\nMake it faster...\n")
