"""Failing victim runs' tool-call sequences, read back from neatlogs for the Localiser (PRD §8.3).

Every victim run is one neatlogs trace (its ID is in the ledger), and each tool attempt is a TOOL
span named after the tool, with the arguments as input and the result as output. The Localiser's
ranking prompt gets a compact summary of up to `max_runs` failing runs: per tool call, its name,
arguments and result status, in order.

Bounded: at most `max_runs` traces, `max_spans` spans read per trace, `max_calls` calls shown per
run, and a timeout on every CLI call. Optional: a failed readback is reported, never raised, and
the ranking goes ahead without traces. Leak-filtered like Entire text, because trace content is
free text that the Localiser's model reads.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from culprit import readback
from culprit.entire import leak_filter
from culprit.ledger import TaskRun

MAX_ARGS_CHARS = 160
MAX_ERROR_CHARS = 160


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: str
    outcome: str  # the result's `status` (ok, failed, not_found, …), or "error: <message>" for an ERROR span


@dataclass
class Summary:
    text: str  # for the prompt; empty when nothing could be read
    note: str  # what was read, skipped or failed, for the log and the ledger
    trace_ids: list[str] = field(default_factory=list)
    lines_removed: int = 0


def tool_calls(spans: list[dict[str, Any]]) -> list[ToolCall]:
    """The TOOL spans of one trace, in start order."""
    calls = []
    for s in sorted((s for s in spans if s.get("spanType") == "TOOL"), key=lambda s: s.get("startedAt") or ""):
        args = (s.get("input") or {}).get("preview") or ""
        if s.get("status") == "ERROR":  # e.g. a timeout: error = {"type": "….ToolTimeout", "messagePreview": "…"}
            error = s.get("error") or {}
            if isinstance(error, dict):
                kind = str(error.get("type") or "").rsplit(".", 1)[-1]
                message = ": ".join(x for x in (kind, str(error.get("messagePreview") or "")) if x)
            else:
                message = str(error)
            outcome = f"error: {(message or 'span marked ERROR')[:MAX_ERROR_CHARS]}"
        else:
            try:
                result = json.loads((s.get("output") or {}).get("preview") or "")
                outcome = str(result.get("status", "?")) if isinstance(result, dict) else "?"
            except json.JSONDecodeError:  # a preview cut short, or not JSON
                outcome = "?"
        calls.append(ToolCall(str(s.get("spanName", "?")), " ".join(args.split())[:MAX_ARGS_CHARS], outcome))
    return calls


def read_spans(trace_id: str, max_spans: int, timeout_s: int) -> list[dict[str, Any]]:
    data = readback.cli("traces", "raw-spans", trace_id, "--limit", str(min(50, max_spans)), "--all",
                        "--max-items", str(max_spans), timeout_s=timeout_s)
    return data["spans"] if isinstance(data, dict) else data


def summarise(failing: list[TaskRun], refs: list[str], max_runs: int = 3, max_spans: int = 200,
              max_calls: int = 25, timeout_s: int = 30,
              read: Callable[[str, int, int], list[dict[str, Any]]] = read_spans) -> Summary:
    """Tool-call sequences of up to `max_runs` failing runs, one per task in the given order."""
    chosen: list[TaskRun] = []
    for r in failing:
        if not r.passed and r.trace_id and r.task_id not in {c.task_id for c in chosen}:
            chosen.append(r)
    chosen = chosen[:max_runs]
    if not chosen:
        return Summary("", "no failing run has a neatlogs trace ID")
    parts, problems, read_ids = [], [], []
    for r in chosen:
        try:
            calls = tool_calls(read(r.trace_id, max_spans, timeout_s))  # type: ignore[arg-type]
        except (readback.ReadbackError, subprocess.TimeoutExpired, OSError, KeyError, TypeError, ValueError) as exc:
            problems.append(f"{r.trace_id}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        read_ids.append(r.trace_id)  # type: ignore[arg-type]
        lines = [f"\n### {r.task_id} (failed run, {len(calls)} tool calls)\n"]
        lines += [f"{i}. {c.name} {c.args} → {c.outcome}\n" for i, c in enumerate(calls[:max_calls], 1)]
        if len(calls) > max_calls:
            lines.append(f"… {len(calls) - max_calls} more calls\n")
        parts.append("".join(lines))
    text, removed = leak_filter("".join(parts), refs)
    note = f"read {len(read_ids)}/{len(chosen)} failing traces from neatlogs"
    if problems:
        note += "; readback failed for " + "; ".join(problems)
    if removed:
        note += f"; leakage filter removed {removed} lines"
    return Summary(text.strip() and text + "\n", note, read_ids, removed)
