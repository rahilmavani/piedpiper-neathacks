"""`culprit init` and culprit.toml: setting up an agent's repo for the installed package."""

import importlib
import json
import stat
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import onboard, project  # noqa: E402
from culprit.ledger import Ledger  # noqa: E402


@pytest.fixture()
def victim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    for name in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "VICTIM_MODEL", "CULPRIT_EVAL_MODULE",
                 "CULPRIT_VICTIM_REPO"):
        monkeypatch.delenv(name, raising=False)
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    return build(tmp_path / "victim", commits=2, breaks_at=99, unbuildable_at=None)


def test_init_writes_settings_and_checks_one_task(victim, monkeypatch):
    from culprit.cli import app

    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-key")  # the fixture's eval never calls a model
    out = CliRunner().invoke(app, ["init", "--repo", str(victim / "refunddesk"), "--yes", "--check"])
    assert out.exit_code == 0, out.output
    assert "check passed: task t01: passed=" in out.output
    settings = (victim / "culprit.toml").read_text()
    assert 'eval_module = "refunddesk.eval"' in settings and 'suite = "evals"' in settings
    assert 'suite_ref = "main"' in settings and "not-a-key" not in settings
    assert {".env", ".culprit/"} <= set((victim / ".gitignore").read_text().splitlines())


def test_init_with_yes_and_no_key_stops(victim):
    from culprit.cli import app

    out = CliRunner().invoke(app, ["init", "--repo", str(victim), "--yes"])
    assert out.exit_code == 2
    assert not (victim / "culprit.toml").exists()


def test_init_saves_the_key_it_is_given(victim):
    from culprit.cli import app

    answers = "openrouter\nsk-or-test\nrefunddesk.eval\nevals\nmain\nn\n"
    out = CliRunner().invoke(app, ["init", "--repo", str(victim)], input=answers)
    assert out.exit_code == 0, out.output
    assert "sk-or-test" not in out.output
    env_file = victim / ".env"
    assert env_file.read_text() == "OPENROUTER_API_KEY=sk-or-test\n"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_run_takes_its_settings_from_culprit_toml(victim, monkeypatch):
    from culprit.cli import app

    project.write(victim, "nosuchpkg.eval", "evals", "main")
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-key")
    monkeypatch.chdir(victim / "refunddesk")  # any directory inside the repo
    db = victim.parent / "l.sqlite"
    out = CliRunner().invoke(app, ["run", "--good", "good-v1.0", "--bad", "main", "--db", str(db)])
    assert out.exit_code == 1  # nosuchpkg.eval doesn't import at either end
    config = json.loads(Ledger(db).conn.execute("SELECT config_json FROM runs").fetchone()[0])
    assert config["eval_module"] == "nosuchpkg.eval" and config["repo"] == str(victim.resolve())


def test_resolve_order(tmp_path, monkeypatch):
    repo = tmp_path / "agent"
    (repo / ".git").mkdir(parents=True)
    project.write(repo, "agent.eval", "suites/main", "release")
    s = project.resolve(None, None, None, None, cwd=repo)
    assert (s.repo, s.eval_module, s.suite, s.suite_ref) == (repo.resolve(), "agent.eval", "suites/main", "release")
    s = project.resolve(None, "other.eval", "evals", None, cwd=repo)  # flags win over the file
    assert (s.eval_module, s.suite, s.suite_ref) == ("other.eval", "evals", "release")
    bare = tmp_path / "bare"
    (bare / ".git").mkdir(parents=True)
    monkeypatch.setattr(project, "SOURCE_CHECKOUT", False)  # as an installed package
    with pytest.raises(project.ProjectError, match="culprit init"):
        project.resolve(None, None, None, None, cwd=bare)
    assert project.resolve(None, "x.eval", None, None, cwd=bare).repo == bare.resolve()


def test_eval_modules_are_detected(tmp_path):
    for rel in ("src/shop/eval.py", "bot/evals/__main__.py", ".venv/lib/x/eval.py", "tests/eval.py", "bot/agent.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    assert onboard.eval_modules(tmp_path) == ["bot.evals", "shop.eval"]


def test_key_and_gitignore_edits_are_idempotent(tmp_path):
    (tmp_path / ".env").write_text("OTHER=1\nexport OPENROUTER_API_KEY=old\n")
    onboard.save_key(tmp_path, "OPENROUTER_API_KEY", "new")
    assert (tmp_path / ".env").read_text() == "OTHER=1\nOPENROUTER_API_KEY=new\n"
    (tmp_path / ".gitignore").write_text(".env")
    assert onboard.ignore_local_files(tmp_path) == [".culprit/"]
    assert onboard.ignore_local_files(tmp_path) == []
    assert (tmp_path / ".gitignore").read_text() == ".env\n# Culprit: local keys and run state\n.culprit/\n"
