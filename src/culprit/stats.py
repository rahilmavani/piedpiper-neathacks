"""Wilson score interval and the deterministic GOOD / BAD / INCONCLUSIVE rule (PRD §8.2)."""

from __future__ import annotations

import math
from enum import StrEnum


class Decision(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"
    INCONCLUSIVE = "INCONCLUSIVE"


def wilson(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% (by default) Wilson score interval for `passes` successes in `n` trials."""
    if n <= 0:
        return 0.0, 1.0
    if not 0 <= passes <= n:
        raise ValueError(f"passes={passes} outside [0, {n}]")
    p = passes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def decide(passes: int, n: int, threshold: float, z: float = 1.96) -> tuple[Decision, float, float]:
    low, high = wilson(passes, n, z)
    if low >= threshold:
        return Decision.GOOD, low, high
    if high <= threshold:
        return Decision.BAD, low, high
    return Decision.INCONCLUSIVE, low, high


def intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]
