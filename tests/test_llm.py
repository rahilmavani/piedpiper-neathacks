import pytest
from pydantic import BaseModel

from culprit import llm


class Pick(BaseModel):
    tasks: list[str]


def fake(replies):
    calls = []

    def complete(system, messages, max_tokens):
        calls.append(list(messages))
        return replies[len(calls) - 1], llm.Usage("m", 10, 5, 0.001)

    return complete, calls


def test_structured_repairs_invalid_json(monkeypatch):
    complete, calls = fake(['{"tasks": "t1"}', '```json\n{"tasks": ["t1"]}\n```'])
    monkeypatch.setattr(llm, "_complete", complete)
    reply = llm.structured("sys", "pick", Pick)
    assert reply.value.tasks == ["t1"]
    assert len(calls) == 2 and "invalid" in calls[1][-1]["content"]
    assert reply.cost_usd == pytest.approx(0.002)


def test_structured_gives_up_after_two_repairs(monkeypatch):
    complete, calls = fake(["nope"] * 3)
    monkeypatch.setattr(llm, "_complete", complete)
    with pytest.raises(llm.LLMError):
        llm.structured("sys", "pick", Pick)
    assert len(calls) == 3
