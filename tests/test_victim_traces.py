"""Failing victim runs' tool-call sequences from neatlogs: parsing, bounds, leak filter, and failures that never raise."""

import json
import subprocess

from culprit import readback, victim_traces
from culprit.ledger import TaskRun


def span(name, start, args=None, result=None, kind="TOOL", status="OK", error=None, preview=None):
    return {"spanType": kind, "spanName": name, "startedAt": start, "status": status, "error": error,
            "input": {"preview": json.dumps(args or {})},
            "output": {"preview": preview if preview is not None else json.dumps(result or {})}}


SPANS = [
    span("issue_refund", "2026-10-10T10:00:03Z", {"order_id": "A1", "amount": 89}, {"status": "ok"}),
    span("openai.chat.completions.create", "2026-10-10T10:00:01Z", kind="LLM"),
    span("lookup_order", "2026-10-10T10:00:02Z", {"order_id": "A1"}, {"status": "failed", "error": "upstream"}),
    span("lookup_order", "2026-10-10T10:00:00Z", {"order_id": "A1"}, status="ERROR",
         error={"messagePreview": "lookup_order timed out", "truncated": False,
                "type": "refunddesk.faults.ToolTimeout"}),  # the shape neatlogs returns
    span("send_customer_email", "2026-10-10T10:00:04Z", {"to": "a@b.c"}, preview='{"status": "ok", "message'),
]


def run(task, rep, passed=False, trace="t"):
    return TaskRun(task, rep, passed, 0.001, 10.0, 1, 1, trace and f"{trace}-{task}-{rep}")


def test_tool_calls_are_the_tool_spans_in_start_order():
    calls = victim_traces.tool_calls(SPANS)
    assert [(c.name, c.outcome) for c in calls] == [
        ("lookup_order", "error: ToolTimeout: lookup_order timed out"),
        ("lookup_order", "failed"),
        ("issue_refund", "ok"),
        ("send_customer_email", "?"),  # preview cut short
    ]
    assert calls[2].args == '{"order_id": "A1", "amount": 89}'


def test_summary_is_bounded_one_run_per_task_and_leak_filtered():
    seen = []

    def read(trace_id, max_spans, timeout_s):
        seen.append((trace_id, max_spans, timeout_s))
        return SPANS + [span("escalate_to_human", f"2026-10-10T10:01:{i:02d}Z", {"reason": "x"}, {"status": "ok"})
                        for i in range(30)] + [
            span("escalate_to_human", "2026-10-10T10:00:05Z", {"reason": "see hist/b"}, {"status": "ok"})]

    failing = [run("t1", 0, passed=True), run("t1", 1), run("t1", 2), run("t2", 0, trace=None), run("t2", 1),
               run("t3", 0), run("t4", 0)]
    summary = victim_traces.summarise(failing, refs=["good-v1.0"], max_runs=3, max_spans=120, max_calls=5,
                                      timeout_s=7, read=read)
    assert [t for t, _, _ in seen] == ["t-t1-1", "t-t2-1", "t-t3-0"]  # one per task, passed and untraced skipped
    assert all((m, s) == (120, 7) for _, m, s in seen)
    assert summary.trace_ids == ["t-t1-1", "t-t2-1", "t-t3-0"]
    assert summary.text.count("### ") == 3 and "1. lookup_order" in summary.text
    assert "… 30 more calls" in summary.text  # 35 tool calls (the LLM span isn't one), 5 shown
    assert "hist/" not in summary.text and summary.lines_removed == 3  # the 5th call, once per run
    assert summary.note == "read 3/3 failing traces from neatlogs; leakage filter removed 3 lines"

    leaky = victim_traces.summarise([run("t1", 0)], refs=["good-v1.0"], read=lambda *_: [
        span("lookup_order", "1", {"order_id": "A1", "note": "good-v1.0"}, {"status": "ok"}),
        span("issue_refund", "2", {"order_id": "A1", "reason": "seed 3"}, {"status": "ok"}),
        span("send_customer_email", "3", {"to": "a@b.c"}, {"status": "ok"})])
    assert "good-v1.0" not in leaky.text and "seed" not in leaky.text and "send_customer_email" in leaky.text
    assert leaky.lines_removed == 2 and "leakage filter removed 2 lines" in leaky.note


def test_readback_failures_are_reported_never_raised():
    def read(trace_id, max_spans, timeout_s):
        if trace_id.endswith("t1-0"):
            raise readback.ReadbackError("neatlogs traces raw-spans: 404")
        if trace_id.endswith("t2-0"):
            raise subprocess.TimeoutExpired("neatlogs", timeout_s)
        return SPANS

    summary = victim_traces.summarise([run("t1", 0), run("t2", 0), run("t3", 0)], refs=[], read=read)
    assert summary.trace_ids == ["t-t3-0"] and "### t3" in summary.text
    assert summary.note.startswith("read 1/3 failing traces") and "ReadbackError" in summary.note
    assert "TimeoutExpired" in summary.note

    def broken(*_):
        raise readback.ReadbackError("neatlogs CLI not found")

    nothing = victim_traces.summarise([run("t1", 0)], refs=[], read=broken)
    assert nothing.text == "" and "read 0/1" in nothing.note
    assert victim_traces.summarise([run("t1", 0, trace=None)], refs=[]).note == \
        "no failing run has a neatlogs trace ID"


def test_read_spans_asks_the_cli_for_a_bounded_page(monkeypatch):
    calls = []

    def cli(*args, timeout_s):
        calls.append((args, timeout_s))
        return {"spans": SPANS}

    monkeypatch.setattr(readback, "cli", cli)
    assert victim_traces.read_spans("abc", 200, 30) == SPANS
    assert calls == [(("traces", "raw-spans", "abc", "--limit", "50", "--all", "--max-items", "200"), 30)]
