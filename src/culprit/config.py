"""Run configuration. Every field is recorded in the ledger with the run (PRD §8.2)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(os.environ.get("CULPRIT_STATE_DIR", PROJECT_ROOT / ".culprit"))
WORKTREE_DIR = STATE_DIR / "worktrees"
DEFAULT_DB = STATE_DIR / "ledger.sqlite"


@dataclass(frozen=True)
class Config:
    repo: str
    good_ref: str
    bad_ref: str
    suite: str = "evals"  # directory at `suite_ref` in the victim, or a directory on disk (see culprit.suite)
    suite_ref: str = "main"
    k: int = 3
    z: float = 1.96
    gate_alpha: float = 0.05  # one-sided Fisher test: is good really better than bad?
    infra_retries: int = 2  # re-runs of a victim task that failed for infrastructure reasons
    infra_backoff_s: float = 5.0  # first retry waits this long, then 4× longer each time
    budget_usd: float = 3.00
    global_budget_usd: float = 75.00
    max_resample_rounds: int = 2
    discriminating_size: int = 8
    install_timeout_s: int = 600
    task_timeout_s: int = 300
    eval_module: str = "refunddesk.eval"
    # The victim's model, chosen once from the keys when the run starts (culprit.providers) and passed to
    # every victim run, so all commits are judged by the same model. Empty: the victim's own environment.
    victim_provider: str = ""
    victim_model: str = ""
    task_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def suite_target(self) -> str:
        """Where the victim reads its suite, relative to the worktree root."""
        from culprit.suite import is_path_suite

        return "evals" if is_path_suite(self.suite) else self.suite

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Config:
        data = json.loads(text)
        data["task_ids"] = tuple(data.get("task_ids", ()))
        return cls(**data)
