"""Tests never export traces: no neatlogs key in the environment, and tracing stays disabled."""

import pytest

from culprit import tracing


@pytest.fixture(autouse=True)
def no_trace_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    monkeypatch.setattr(tracing, "_enabled", False)
    monkeypatch.setattr(tracing, "init", lambda: None)  # e.g. cli.main() after load_dotenv() re-adds the key
