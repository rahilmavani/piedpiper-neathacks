"""Provider choice from the keys: Anthropic (Sonnet 5.5) first, OpenRouter (GLM 5.3) as the fallback."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import llm, providers  # noqa: E402
from culprit.evalrunner import victim_env  # noqa: E402
from culprit.ledger import Ledger  # noqa: E402

KEYS = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "CULPRIT_MODEL", "VICTIM_MODEL")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch):
    for var in KEYS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize(("keys", "expected"), [
    ({"ANTHROPIC_API_KEY": "a"}, ("anthropic", "claude-sonnet-5-5")),
    ({"OPENROUTER_API_KEY": "o"}, ("openrouter", "z-ai/glm-5.3")),
    ({"ANTHROPIC_API_KEY": "a", "OPENROUTER_API_KEY": "o"}, ("anthropic", "claude-sonnet-5-5")),
    ({"ANTHROPIC_API_KEY": ""}, None),  # an empty key counts as missing
    ({}, None),
])
def test_keys_pick_the_provider(monkeypatch, keys, expected):
    for var, value in keys.items():
        monkeypatch.setenv(var, value)
    if expected is None:
        with pytest.raises(providers.ProviderError, match="ANTHROPIC_API_KEY.*OPENROUTER_API_KEY"):
            providers.select("VICTIM_MODEL")
    else:
        chosen = providers.select("VICTIM_MODEL")
        assert (chosen.name, chosen.model) == expected


def test_model_override_must_match_the_provider(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    monkeypatch.setenv("VICTIM_MODEL", "claude-sonnet-5-5")  # left over from an Anthropic setup
    with pytest.raises(providers.ProviderError, match="Unset VICTIM_MODEL"):
        providers.select("VICTIM_MODEL")
    monkeypatch.setenv("VICTIM_MODEL", "z-ai/glm-5.3-flash")
    assert providers.select("VICTIM_MODEL").model == "z-ai/glm-5.3-flash"


def test_costs_use_the_price_table():
    assert providers.Provider("anthropic", "claude-sonnet-5-5").cost(1_000_000, 100_000) == pytest.approx(3.0)
    assert providers.Provider("openrouter", "z-ai/glm-5.3").cost(1_000_000, 1_000_000) == pytest.approx(4.87)
    assert providers.Provider("openrouter", "vendor/unknown").cost(10, 10) is None


def test_victim_env_overrides_the_victims_own_env_file(tmp_path: Path):
    (tmp_path / ".env").write_text("LLM_PROVIDER=anthropic\nVICTIM_MODEL=claude-sonnet-5-5\n")
    env = victim_env(tmp_path, providers.Provider("openrouter", "z-ai/glm-5.3"))
    assert env["LLM_PROVIDER"] == "openrouter"
    assert env["VICTIM_MODEL"] == "z-ai/glm-5.3"
    assert (env["VICTIM_PRICE_IN"], env["VICTIM_PRICE_OUT"]) == ("0.07", "4.8")
    assert victim_env(tmp_path)["VICTIM_MODEL"] == "claude-sonnet-5-5"  # no provider: the victim's own


def test_culprit_llm_routes_to_openrouter_without_an_anthropic_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    seen = {}

    def fake_openrouter(chosen, system, messages, max_tokens):
        seen["model"] = chosen.model
        return '{"x": 1}', llm.Usage(chosen.model, 10, 5, chosen.cost(10, 5))

    monkeypatch.setattr(llm, "_complete_openrouter", fake_openrouter)
    monkeypatch.setattr(llm, "_complete_anthropic", lambda *a: pytest.fail("Anthropic used without its key"))
    text, usage = llm._complete("sys", [{"role": "user", "content": "hi"}], 100)
    assert seen["model"] == "z-ai/glm-5.3" and usage.cost_usd is not None


def test_culprit_llm_without_keys_is_a_clear_error():
    with pytest.raises(llm.LLMError, match="OPENROUTER_API_KEY"):
        llm._complete("sys", [], 10)


def test_resume_without_the_runs_key_stops_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=4, breaks_at=3, unbuildable_at=None)
    cfg = culprit.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main",
                                victim_provider="anthropic", victim_model="claude-sonnet-5-5")
    orch = culprit.orchestrator.Orchestrator(Ledger(tmp_path / "l.sqlite"), cfg, log=lambda _: None)
    run_id = orch.start()
    outcome = orch.run(run_id)
    assert outcome.status == "infra_error"
    assert "ANTHROPIC_API_KEY is not set" in outcome.summary
    assert orch.ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == 0
