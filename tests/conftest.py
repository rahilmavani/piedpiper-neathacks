"""Every test is free and private: no neatlogs export or readback, no model calls.

There is no neatlogs key in the environment and tracing stays disabled. The user's saved Culprit
keys are out of reach (a temporary XDG_CONFIG_HOME). The two functions that reach a model provider
raise, and so does finding the neatlogs CLI, so a test that needs a model reply or a trace must
install its own fake.
"""

import pytest

from culprit import llm, readback, tracing


def _no_model_calls(*args, **kwargs):
    raise llm.LLMError("model calls are disabled in tests")


def _no_readback():
    raise readback.ReadbackError("neatlogs readback is disabled in tests")


@pytest.fixture(autouse=True)
def no_trace_export_or_model_calls(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    # `culprit init` saves keys under XDG_CONFIG_HOME; never read or write the real ~/.config.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))
    monkeypatch.setattr(tracing, "_enabled", False)
    monkeypatch.setattr(tracing, "init", lambda: None)  # e.g. cli.main() after load_dotenv() re-adds the key
    monkeypatch.setattr(llm, "_complete_anthropic", _no_model_calls)
    monkeypatch.setattr(llm, "_complete_openrouter", _no_model_calls)
    monkeypatch.setattr(readback, "cli_binary", _no_readback)
