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
    suite: str = "evals"
    k: int = 3
    z: float = 1.96
    budget_usd: float = 3.00
    global_budget_usd: float = 75.00
    max_resample_rounds: int = 2
    discriminating_size: int = 8
    install_timeout_s: int = 600
    task_timeout_s: int = 300
    eval_module: str = "refunddesk.eval"
    task_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Config:
        data = json.loads(text)
        data["task_ids"] = tuple(data.get("task_ids", ()))
        return cls(**data)
