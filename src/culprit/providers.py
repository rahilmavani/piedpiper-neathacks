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


# Settings Culprit reads, from three places; the first that sets one wins:
#   1. the shell environment,
#   2. the .env of the repo Culprit runs in (to override for one repo),
#   3. what `culprit init` saved for this user (settings_path(), readable only by them).
# Only these names are read from 2 and 3. Anything else in a repo's .env (HTTPS_PROXY with SSL_CERT_FILE,
# an SDK's base URL, NEATLOGS_CLI) could route Culprit's calls, with the user's keys, through another
# server or run another program, so it is ignored. The agent's own runs still get that whole .env
# (culprit.evalrunner.victim_env): they are the repo's own code.
SETTING_VARS = ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "NEATLOGS_API_KEY", "VICTIM_MODEL", "CULPRIT_MODEL")
REPO_ENV, SAVED = "repo .env", "culprit init"
_loaded: dict[str, tuple[str, str]] = {}  # name -> (where it came from, value)


def settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "culprit" / "credentials.env"


def _load(path: Path, source: str) -> None:
    if not path.is_file():
        return
    from dotenv import dotenv_values

    values = dotenv_values(path)
    for name in SETTING_VARS:
        if values.get(name) and name not in os.environ:  # set in the shell, even to "", wins
            os.environ[name] = values[name]
            _loaded[name] = (source, values[name])


def load_settings(repo: Path) -> None:
    """Fill unset settings from the repo's .env, then from the saved setup. Never overrides the shell."""
    _load(repo / ".env", REPO_ENV)
    _load(settings_path(), SAVED)


def source(name: str) -> str | None:
    """Where the current value of `name` came from: "shell", REPO_ENV or SAVED; None if unset."""
    value = os.environ.get(name)
    if not value:
        return None
    where, loaded = _loaded.get(name, ("shell", None))
    return where if loaded == value else "shell"


def save_settings(values: dict[str, str]) -> Path:
    """Merge `values` into the saved setup; the file is readable only by the user."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    from dotenv import dotenv_values

    current = {k: v for k, v in dotenv_values(path).items() if v} if path.is_file() else {}
    current.update({k: v for k, v in values.items() if v})
    path.touch(mode=0o600)
    path.chmod(0o600)
    path.write_text("# Saved by `culprit init`. The shell and a repo's .env override these.\n"
                    + "".join(f"{k}={v}\n" for k, v in current.items()))
    for name, value in values.items():  # this process uses what was just saved, unless the shell overrides it
        if value and source(name) in {None, SAVED}:
            os.environ[name] = value
            _loaded[name] = (SAVED, value)
    return path


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
