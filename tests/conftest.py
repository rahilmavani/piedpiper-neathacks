"""Every test is free and private: no neatlogs export, no model calls.

There is no neatlogs key in the environment and tracing stays disabled. The two functions that
reach a model provider raise, so a test that needs a model reply must install its own fake.
"""

import pytest

from culprit import llm, tracing


def _no_model_calls(*args, **kwargs):
    raise llm.LLMError("model calls are disabled in tests")


@pytest.fixture(autouse=True)
def no_trace_export_or_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    monkeypatch.setattr(tracing, "_enabled", False)
    monkeypatch.setattr(tracing, "init", lambda: None)  # e.g. cli.main() after load_dotenv() re-adds the key
    monkeypatch.setattr(llm, "_complete_anthropic", _no_model_calls)
    monkeypatch.setattr(llm, "_complete_openrouter", _no_model_calls)
