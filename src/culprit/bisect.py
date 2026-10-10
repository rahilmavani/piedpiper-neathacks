"""Deterministic bisect controller with `git bisect skip` semantics (PRD §8.1).

The controller knows nothing about evals: it asks `classify(sha)` for GOOD, BAD or SKIP and
narrows the range. `good` is implicitly GOOD and the last candidate (`bad`) is implicitly BAD.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"
    SKIP = "SKIP"


@dataclass
class BisectResult:
    first_bad: str | None
    """The culprit when the boundary is exact; None when skipped commits make it ambiguous."""
    suspects: list[str]
    """Commits that may contain the culprit, oldest first (one entry when exact)."""
    tested: list[tuple[str, Verdict]] = field(default_factory=list)


def probe_order(lo: int, hi: int) -> list[int]:
    """Indices strictly between lo and hi, midpoint first, then alternating right/left."""
    mid = (lo + hi) // 2
    order = [mid]
    for step in range(1, hi - lo):
        for idx in (mid + step, mid - step):
            if lo < idx < hi:
                order.append(idx)
    return order


def bisect(candidates: list[str], classify: Callable[[str], Verdict]) -> BisectResult:
    """`candidates` is `git rev-list --first-parent --reverse good..bad`, so the last one is `bad`."""
    if not candidates:
        raise ValueError("empty commit range: good and bad are the same commit")
    lo, hi = -1, len(candidates) - 1
    skipped: set[int] = set()
    tested: list[tuple[str, Verdict]] = []
    while hi - lo > 1:
        untested = [i for i in probe_order(lo, hi) if i not in skipped]
        if not untested:
            break
        idx = untested[0]
        verdict = classify(candidates[idx])
        tested.append((candidates[idx], verdict))
        if verdict is Verdict.GOOD:
            lo = idx
        elif verdict is Verdict.BAD:
            hi = idx
        else:
            skipped.add(idx)
    suspects = candidates[lo + 1 : hi + 1]
    return BisectResult(first_bad=suspects[0] if len(suspects) == 1 else None, suspects=suspects, tested=tested)
