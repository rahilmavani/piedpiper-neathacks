"""The only module that talks to a model.

The provider follows the keys (see `culprit.providers`): Claude Sonnet 5.5 via Anthropic when
`ANTHROPIC_API_KEY` is set, otherwise GLM 5.3 via OpenRouter. `CULPRIT_MODEL` overrides the model.
Structured outputs are validated with pydantic; on a validation failure the model gets a repair
prompt, at most twice.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from culprit import providers, tracing

T = TypeVar("T", bound=BaseModel)

MAX_REPAIRS = 2


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


def provider() -> providers.Provider:
    try:
        return providers.select("CULPRIT_MODEL")
    except providers.ProviderError as exc:
        raise LLMError(str(exc)) from exc


def _complete(system: str, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, Usage]:
    chosen = provider()
    if chosen.name == providers.ANTHROPIC:
        return _complete_anthropic(chosen, system, messages, max_tokens)
    return _complete_openrouter(chosen, system, messages, max_tokens)


def _complete_anthropic(
    chosen: providers.Provider, system: str, messages: list[dict[str, str]], max_tokens: int
) -> tuple[str, Usage]:
    import anthropic

    client = tracing.wrap(anthropic.Anthropic())
    resp = client.messages.create(model=chosen.model, max_tokens=max_tokens, system=system, messages=messages)
    if resp.stop_reason == "refusal":
        raise LLMError("model refused the request")
    text = "".join(b.text for b in resp.content if b.type == "text")
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    return text, Usage(chosen.model, tin, tout, chosen.cost(tin, tout))


def _complete_openrouter(
    chosen: providers.Provider, system: str, messages: list[dict[str, str]], max_tokens: int
) -> tuple[str, Usage]:
    import openai

    client = tracing.wrap(openai.OpenAI(base_url=providers.OPENROUTER_BASE_URL,
                                        api_key=os.environ[providers.KEY_VARS[providers.OPENROUTER]]))
    resp = client.chat.completions.create(
        model=chosen.model, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, *messages],
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    tin = getattr(usage, "prompt_tokens", None) if usage else None
    tout = getattr(usage, "completion_tokens", None) if usage else None
    cost = None if tin is None or tout is None else chosen.cost(tin, tout)
    return text, Usage(chosen.model, tin, tout, cost)


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
