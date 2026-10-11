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
    assert ".culprit/" in (victim / ".gitignore").read_text().splitlines()


def test_init_with_yes_and_no_key_stops(victim):
    from culprit.cli import app

    out = CliRunner().invoke(app, ["init", "--repo", str(victim), "--yes"])
    assert out.exit_code == 2
    assert not (victim / "culprit.toml").exists()


def test_init_saves_keys_once_for_the_user_not_in_the_repo(victim):
    from culprit import providers
    from culprit.cli import app

    answers = "openrouter\nsk-or-test\nnl-test\nrefunddesk.eval\nevals\nmain\nn\n"
    out = CliRunner().invoke(app, ["init", "--repo", str(victim)], input=answers)
    assert out.exit_code == 0, out.output
    assert "sk-or-test" not in out.output and "nl-test" not in out.output
    saved = providers.settings_path()
    assert saved.read_text().splitlines()[1:] == ["OPENROUTER_API_KEY=sk-or-test", "NEATLOGS_API_KEY=nl-test"]
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert not (victim / ".env").exists()
    # A second repo needs no keys: init finds the saved ones and asks nothing about them.
    out = CliRunner().invoke(app, ["init", "--repo", str(victim), "--yes"])
    assert out.exit_code == 0 and "OPENROUTER_API_KEY: from culprit init" in out.output


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


def test_shell_then_repo_env_then_saved_setup(tmp_path, monkeypatch):
    import os

    from culprit import providers

    for name in providers.SETTING_VARS:
        monkeypatch.delenv(name, raising=False)
    providers.save_settings({"OPENROUTER_API_KEY": "saved", "NEATLOGS_API_KEY": "saved", "VICTIM_MODEL": "saved"})
    for name in providers.SETTING_VARS:  # start from a fresh process: nothing loaded yet
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("NEATLOGS_API_KEY=repo\nVICTIM_MODEL=repo\n")
    monkeypatch.setenv("VICTIM_MODEL", "shell")
    providers.load_settings(tmp_path)
    assert [os.environ[n] for n in ("OPENROUTER_API_KEY", "NEATLOGS_API_KEY", "VICTIM_MODEL")] == \
        ["saved", "repo", "shell"]
    assert [providers.source(n) for n in ("OPENROUTER_API_KEY", "NEATLOGS_API_KEY", "VICTIM_MODEL")] == \
        ["culprit init", "repo .env", "shell"]
    providers.save_settings({"OPENROUTER_API_KEY": "new"})  # `culprit init --keys` merges into the file
    assert "OPENROUTER_API_KEY=new" in providers.settings_path().read_text()
    assert "NEATLOGS_API_KEY=saved" in providers.settings_path().read_text()


def test_gitignore_edit_is_idempotent(tmp_path):
    (tmp_path / ".env").write_text("X=1\n")
    (tmp_path / ".gitignore").write_text(".env")
    assert onboard.ignore_local_files(tmp_path) == [".culprit/"]
    assert onboard.ignore_local_files(tmp_path) == []
    assert (tmp_path / ".gitignore").read_text() == ".env\n# Culprit: local keys and run state\n.culprit/\n"


def test_a_repo_env_sets_only_culprits_settings_in_its_process(tmp_path, monkeypatch):
    """`culprit` run inside a cloned repo reads that repo's .env, but only Culprit's own settings."""
    from culprit import cli

    planted = {"OPENROUTER_API_KEY": "sk-or-repo", "HTTPS_PROXY": "http://attacker.invalid:8080",
               "SSL_CERT_FILE": "/tmp/attacker-ca.pem", "NEATLOGS_CLI": "/tmp/evil",
               "ANTHROPIC_BASE_URL": "https://attacker.invalid", "OPENAI_BASE_URL": "https://attacker.invalid"}
    for name in planted:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in planted.items()))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "SOURCE_CHECKOUT", False)  # as an installed package
    monkeypatch.setattr(sys, "argv", ["culprit", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    import os

    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-repo"
    assert not [name for name in planted if name != "OPENROUTER_API_KEY" and name in os.environ]
