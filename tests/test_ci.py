"""`culprit ci` (PR regression gate) and `culprit comment` (the PR comment for any finished run)."""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger  # noqa: E402


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None)
    return repo, tmp_path / "l.sqlite", culprit.config


def sha_of(repo: Path, grep: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "log", "--format=%H", f"--grep={grep}"], text=True).strip()


def ci(config, repo, db, base, head, **kw):
    from culprit.ci import ci_run

    cfg = config.Config(repo=str(repo), good_ref=base, bad_ref=head)
    return ci_run(Ledger(db), cfg, log=lambda _: None, **kw)


def test_regressed_pr_fails_with_the_culprit_in_the_comment(env):
    repo, db, config = env
    result = ci(config, repo, db, "good-v1.0", "main", fix=True)
    culprit = sha_of(repo, "speed up tool handling")
    assert (result.status, result.exit_code) == ("found", 1)
    text = result.comment
    assert text.startswith("### ❌ Culprit: this PR regresses the agent")
    assert f"`{culprit[:10]}` speed up tool handling" in text
    assert "**Responsible change**" in text and "refunddesk/agent.py" in text
    assert "**Verified:**" in text and "```diff" in text  # no model in tests: the verified hunk revert
    assert f"Culprit run `{result.run_id}`" in text


def test_clean_pr_passes(env):
    repo, db, config = env
    clean_head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "main~3"], text=True).strip()
    result = ci(config, repo, db, "good-v1.0", clean_head)
    assert (result.status, result.exit_code) == ("no_regression", 0)
    assert result.comment.startswith("### ✅ Culprit: no significant regression")


def test_infrastructure_failure_never_blames_a_commit(env, monkeypatch):
    repo, db, config = env
    monkeypatch.setenv("FIXTURE_INFRA", "auth")
    result = ci(config, repo, db, "good-v1.0", "main")
    assert (result.status, result.exit_code) == ("infra_error", 2)
    assert result.comment.startswith("### ⚠️ Culprit couldn't finish (infra_error)")
    assert "Culprit commit" not in result.comment


def test_comment_command_renders_from_the_ledger_alone(env, tmp_path):
    from culprit.cli import app

    repo, db, config = env
    result = ci(config, repo, db, "good-v1.0", "main", localise=False)
    before = db.read_bytes()
    out = CliRunner().invoke(app, ["comment", result.run_id, "--db", str(db)])
    assert out.exit_code == 0
    assert out.output.startswith("### ❌ Culprit: this PR regresses the agent")
    assert db.read_bytes() == before  # read-only
    missing = CliRunner().invoke(app, ["comment", "nope", "--db", str(db)])
    assert missing.exit_code == 2
