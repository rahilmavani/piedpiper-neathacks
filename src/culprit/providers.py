"""Which model provider to use, picked from the keys that are present.

Anthropic (Claude Sonnet 5.5) when `ANTHROPIC_API_KEY` is set, otherwise OpenRouter (GLM 5.3) when
`OPENROUTER_API_KEY` is set. `CULPRIT_MODEL` / `VICTIM_MODEL` override the model, but must belong
to the chosen provider. Prices are the only source of truth for cost (ledger, budget, cfo.ai).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ANTHROPIC = "anthropic"
OPENROUTER = "openrouter"
# Both endpoints are fixed. The Anthropic SDK would otherwise honour ANTHROPIC_BASE_URL, which a cloned
# repo's .env (loaded by the installed CLI) could set to send the user's key to another server.
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODELS = {ANTHROPIC: "claude-sonnet-5-5", OPENROUTER: "z-ai/glm-5.3"}
KEY_VARS = {ANTHROPIC: "ANTHROPIC_API_KEY", OPENROUTER: "OPENROUTER_API_KEY"}

# USD per million tokens (input, output). Anthropic first-party list prices as of 2026-10-06; OpenRouter
# prices from its /api/v1/models listing on 2026-10-10. An unknown model reports cost as None, not a guess.
# neatlogs prices claude-sonnet-5-5 at $3/$15; see BLOCKERS.md.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "z-ai/glm-5.3": (0.07, 4.80),  # $0.039 input on 10 Oct; runs recorded before 11 Oct ~15:30 IST used $0.039
    # Victim-model comparison, OpenRouter listing on 11 Oct 2026
    "qwen/qwen3.8-flash": (0.15, 0.47),
    "meta-llama/llama-3.1-8b-instruct": (0.05, 0.08),
    "deepseek/deepseek-v4.1-flash": (0.30, 1.20),
    "google/gemini-3.8-flash": (0.75, 3.75),
}


class ProviderError(RuntimeError):
    pass


# What Culprit's own process takes from the .env of the repo it runs in. Nothing else is read from it:
# variables such as HTTPS_PROXY with SSL_CERT_FILE, an SDK's base URL or NEATLOGS_CLI would let a cloned
# repo route Culprit's calls, with the user's keys, through another server or run another program. The
# agent's own runs still get that whole .env (culprit.evalrunner.victim_env); they are the repo's code.
REPO_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "VICTIM_MODEL", "CULPRIT_MODEL")


def load_repo_env(path: Path) -> list[str]:
    """Set the allowed variables from `path` that aren't already set; returns their names."""
    if not path.is_file():
        return []
    from dotenv import dotenv_values

    values = dotenv_values(path)
    loaded = [name for name in REPO_ENV_VARS if values.get(name) and not os.environ.get(name)]
    for name in loaded:
        os.environ[name] = values[name]
    return loaded


@dataclass(frozen=True)
class Provider:
    name: str
    model: str

    @property
    def price(self) -> tuple[float, float] | None:
        return PRICES.get(self.model)

    def cost(self, tokens_in: int, tokens_out: int) -> float | None:
        price = self.price
        return None if price is None else (tokens_in * price[0] + tokens_out * price[1]) / 1e6

    def require_key(self) -> None:
        if not os.environ.get(KEY_VARS[self.name]):
            raise ProviderError(f"{KEY_VARS[self.name]} is not set, but this run uses {self.name} ({self.model})")


def available() -> str:
    """The provider the present keys allow: Anthropic first, OpenRouter as the fallback."""
    for name in (ANTHROPIC, OPENROUTER):
        if os.environ.get(KEY_VARS[name]):
            return name
    raise ProviderError("set ANTHROPIC_API_KEY (Claude Sonnet 5.5) or OPENROUTER_API_KEY (GLM 5.3)")


def select(model_var: str) -> Provider:
    """Provider from the keys; model from `model_var` if set, else that provider's default."""
    name = available()
    model = os.environ.get(model_var, "").strip() or DEFAULT_MODELS[name]
    is_openrouter_id = "/" in model  # OpenRouter ids are "vendor/model"; Anthropic ids have no slash
    if is_openrouter_id != (name == OPENROUTER):
        raise ProviderError(
            f"{model_var}={model!r} is not a {name} model id, and {name} is the provider the keys select "
            f"({'ANTHROPIC_API_KEY is set' if name == ANTHROPIC else 'only OPENROUTER_API_KEY is set'}). "
            f"Unset {model_var} to use {DEFAULT_MODELS[name]}."
        )
    return Provider(name, model)
