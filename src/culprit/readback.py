"""neatlogs readback through the public CLI, using the saved OAuth login (or NEATLOGS_TOKEN).

The ingest key never authorises reads, so it is removed from the CLI's environment; when a
service token is set, it is passed on alone.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_SPANS = 1000


class ReadbackError(RuntimeError):
    pass


def cli_binary() -> str:
    """The public CLI (npm `neatlogs-cli`). The Python SDK installs its own `neatlogs` script into the
    virtualenv, so that directory is excluded from the search; NEATLOGS_CLI overrides it."""
    if os.environ.get("NEATLOGS_CLI"):
        return os.environ["NEATLOGS_CLI"]
    venv_bin = os.path.realpath(os.path.join(sys.prefix, "bin"))
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                           if os.path.realpath(p) != venv_bin)
    found = shutil.which("neatlogs", path=path)
    if found is None:
        raise ReadbackError("neatlogs CLI not found; install neatlogs-cli or set NEATLOGS_CLI")
    return found


def cli(*args: str, timeout_s: int = 120) -> Any:
    env = {k: v for k, v in os.environ.items() if k != "NEATLOGS_API_KEY"}
    proc = subprocess.run([cli_binary(), "--json", *args], env=env, capture_output=True, text=True, timeout=timeout_s)
    try:
        body = json.loads(proc.stdout or proc.stderr)
    except json.JSONDecodeError as exc:
        raise ReadbackError(f"neatlogs {' '.join(args)}: exit {proc.returncode}: {proc.stderr[-300:]}") from exc
    if proc.returncode != 0 or not body.get("success", False):
        raise ReadbackError(f"neatlogs {' '.join(args)}: {json.dumps(body)[:300]}")
    return body["data"]


def trace(trace_id: str) -> dict[str, Any]:
    return cli("traces", "get", trace_id)


def raw_spans(trace_id: str) -> list[dict[str, Any]]:
    data = cli("traces", "raw-spans", trace_id, "--limit", "50", "--all", "--max-items", str(MAX_SPANS))
    spans = data["spans"] if isinstance(data, dict) else data
    if len(spans) >= MAX_SPANS:
        raise ReadbackError(f"trace {trace_id} has ≥{MAX_SPANS} spans; collection limit reached")
    return spans


def payload_input(trace_id: str, span_id: str) -> str:
    field_ = cli("traces", "payload", trace_id, span_id, "--fields", "input")["fields"]["input"]
    if field_.get("truncated"):
        raise ReadbackError(f"span {span_id}: input payload is truncated even in full payload")
    return field_.get("value") or ""


def session_traces(session_id: str, workflow: str) -> list[dict[str, Any]]:
    data = cli("traces", "list", "--session", session_id, "--workflow", workflow, "--limit", "50")
    return data["traces"] if isinstance(data, dict) else data


@dataclass
class Audit:
    trace_id: str
    finalized: bool
    workflow: str
    session: str
    span_count: int
    by_name: dict[str, int]
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.finalized and not self.problems


def audit(trace_id: str, run_id: str, workflow: str = "culprit") -> Audit:
    """Check a Culprit trace: finalized, one root, every parent present, run context on every span."""
    meta = trace(trace_id)
    spans = raw_spans(trace_id)
    result = Audit(
        trace_id=trace_id,
        finalized=meta.get("finalizationStatus") == "finalized",
        workflow=meta.get("workflowName", ""),
        session=meta.get("sessionId", ""),
        span_count=len(spans),
        by_name=dict(Counter(s["spanName"] for s in spans)),
    )
    if result.workflow != workflow:
        result.problems.append(f"workflow is {result.workflow!r}, expected {workflow!r}")
    if result.session != run_id:
        result.problems.append(f"session is {result.session!r}, expected run_id {run_id!r}")
    if meta.get("spansCount") != len(spans):
        result.problems.append(f"trace reports {meta.get('spansCount')} spans, read back {len(spans)}")
    ids = {s["spanId"] for s in spans}
    roots = [s for s in spans if s["parentSpanId"] is None]
    if len(roots) != 1 or roots[0]["spanType"] != "WORKFLOW":
        result.problems.append(f"expected one WORKFLOW root, found {[(r['spanName'], r['spanType']) for r in roots]}")
    for s in spans:
        if s["parentSpanId"] is not None and s["parentSpanId"] not in ids:
            result.problems.append(f"{s['spanName']} {s['spanId']}: parent {s['parentSpanId']} missing")
        if s["spanType"] == "LLM":
            continue  # provider spans are captured by wrap(); their run context is on the AGENT parent
        text = (s.get("input") or {}).get("preview") or ""
        if (s.get("input") or {}).get("truncated"):
            text = payload_input(trace_id, s["spanId"])
        try:
            context = json.loads(text)
        except json.JSONDecodeError:
            result.problems.append(f"{s['spanName']} {s['spanId']}: input is not JSON")
            continue
        if context.get("run_id") != run_id:
            result.problems.append(f"{s['spanName']} {s['spanId']}: run_id {context.get('run_id')!r}")
        if not SHA.match(str(context.get("commit_sha", ""))):
            result.problems.append(f"{s['spanName']} {s['spanId']}: commit_sha {context.get('commit_sha')!r}")
    return result
