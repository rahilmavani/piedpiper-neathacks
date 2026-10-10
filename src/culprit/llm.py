"""The only module that talks to a model.

`LLM_PROVIDER` is `anthropic` (default) or `openrouter` (OpenAI-compatible); `CULPRIT_MODEL` picks
the model. Structured outputs are validated with pydantic; on a validation failure the model gets
a repair prompt, at most twice.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from culprit import tracing

T = TypeVar("T", bound=BaseModel)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_REPAIRS = 2
# USD per million tokens (input, output), Anthropic first-party list prices as of 2026-10-06.
# Unknown models report cost as None rather than a guess. OpenRouter reports cost itself.
ANTHROPIC_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Usage:
    model: str
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None


@dataclass(frozen=True)
class Reply[R]:
    value: R
    usage: list[Usage]

    @property
    def cost_usd(self) -> float | None:
        costs = [u.cost_usd for u in self.usage]
        return None if any(c is None for c in costs) else sum(costs)  # type: ignore[misc]


def model_name() -> str:
    name = os.environ.get("CULPRIT_MODEL")
    if not name:
        raise LLMError("CULPRIT_MODEL is not set")
    return name


def provider() -> str:
    value = os.environ.get("LLM_PROVIDER", "anthropic")
    if value not in {"anthropic", "openrouter"}:
        raise LLMError(f"LLM_PROVIDER must be anthropic or openrouter, not {value!r}")
    return value


def _complete(system: str, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, Usage]:
    model = model_name()
    if provider() == "anthropic":
        import anthropic

        client = tracing.wrap(anthropic.Anthropic())
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
        if resp.stop_reason == "refusal":
            raise LLMError("model refused the request")
        text = "".join(b.text for b in resp.content if b.type == "text")
        tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
        price = ANTHROPIC_PRICES.get(model)
        cost = None if price is None else (tin * price[0] + tout * price[1]) / 1e6
        return text, Usage(model, tin, tout, cost)

    import openai

    client = tracing.wrap(openai.OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"]))
    resp = client.chat.completions.create(
        model=model, max_tokens=max_tokens, messages=[{"role": "system", "content": system}, *messages],
        extra_body={"usage": {"include": True}},
    )
    usage = resp.usage
    cost = getattr(usage, "cost", None) if usage else None
    return resp.choices[0].message.content or "", Usage(
        model, usage.prompt_tokens if usage else None, usage.completion_tokens if usage else None,
        None if cost is None else float(cost),
    )


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def structured(system: str, prompt: str, schema: type[T], max_tokens: int = 4000) -> Reply[T]:
    """Ask for JSON matching `schema`; repair invalid output at most MAX_REPAIRS times."""
    instructions = (
        f"{system}\n\nRespond with a single JSON object and nothing else. It must validate against this "
        f"JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    )
    messages = [{"role": "user", "content": prompt}]
    usages: list[Usage] = []
    for attempt in range(MAX_REPAIRS + 1):
        text, usage = _complete(instructions, messages, max_tokens)
        usages.append(usage)
        try:
            return Reply(schema.model_validate_json(_extract_json(text)), usages)
        except ValidationError as exc:
            if attempt == MAX_REPAIRS:
                raise LLMError(f"invalid structured output after {MAX_REPAIRS} repairs: {exc}") from exc
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON was invalid:\n{exc}\nReturn only the corrected JSON object."},
            ]
    raise AssertionError("unreachable")
