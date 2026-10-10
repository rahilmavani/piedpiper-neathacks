# Culprit report: run `ff50e3620fdd`

**Verdict: found.** Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)

- Culprit: `397c42743be8cd80ae1d1e30c058772c1bd16add` 'perf(agent): run tool calls in parallel and drop per-result validation'
- Confidence: 95% Wilson
- Range: `good-v1.0..origin/hist/b` (14 commits) in `/Volumes/DevSSD/Projects/piedpiper-neathacks-refunddesk`
- Victim: z-ai/glm-5.3 via openrouter; k = 3; suite git:main:evals @ ba86ed06d3e5be7a1ff
- Cost: $1.13 for 456 victim runs; wall time 12.5 min

## Baselines and regression gate

| End | SHA | Passes | 95% Wilson | Screen ×1 | Reused |
|---|---|---:|---|---:|---:|
| good | `0479c273fb` | 78/78 | [0.95, 1.00] | — | 0 |
| bad | `f6511b8e6b` | 57/78 | [0.62, 0.82] | — | 0 |

One-sided Fisher exact p = 1.006e-07 (alpha 0.05): significant, computed on the runs actually made.

Discriminating tasks: `email_failed_payload_three_times`, `escalate_failed_payload_three_times`, `escalate_failed_payload_twice`, `multiturn_refund_and_email_failed_repeatedly`, `refund_failed_payload_once`, `refund_failed_payload_three_times`, `refund_failed_payload_twice`

## Bisect timeline

| # | Pos | Commit | Subject | Passes | 95% Wilson | Threshold | Rounds | Verdict |
|---:|---:|---|---|---:|---|---:|---|---|
| 1 | 7 | `22a37dbfff` | build(deps): pin python-dotenv to 1.2.99 | — | — | — | install | **SKIP** |
| 2 | 8 | `81c07532c4` | revert(deps): restore the python-dotenv version range | 21/21 | [0.85, 1.00] | 0.50 | bisect | **GOOD** |
| 3 | 11 | `c9a132f01b` | test(tasks): cover loading unknown and held-out task ids | 3/21 | [0.05, 0.35] | 0.50 | bisect | **BAD** |
| 4 | 9 | `8793325134` | test(store): cover JsonStore create, load and save | 21/21 | [0.85, 1.00] | 0.50 | bisect | **GOOD** |
| 5 | 10 | `397c42743b` | perf(agent): run tool calls in parallel and drop per-result validation | 1/21 | [0.01, 0.23] | 0.50 | bisect | **BAD** |

## Skipped commits

- `22a37dbfff` 'build(deps): pin python-dotenv to 1.2.99': install failed, treated like `git bisect skip`.
  >   ╰─▶ Because there is no version of python-dotenv==1.2.99 and your project
  >       depends on python-dotenv==1.2.99, we can conclude that your project's
  >       requirements are unsatisfiable.

## Intent

```text
Commit message:
perf(agent): run tool calls in parallel and drop per-result validation

Each response's tool calls now run on a thread pool. Lookups run first so
refunds in the same batch see them, and calls to the same tool stay in
ToolRuntime gains an RLock around the call log, ids, fault plan and store
writes.

validate_tool_result is removed: only timeouts are retried now, and failed
results go straight back to the model.

Entire-Checkpoint: 01M4JM8P2C4NDS2AAQ0MPVR8YR
```

## Diff

```diff
diff --git a/README.md b/README.md
index c43b1a2..1f017fb 100644
--- a/README.md
+++ b/README.md
@@ -27,7 +27,7 @@ and caches that decision in `.cache/refunddesk/sampling.json`. The eval output r
 ## Layout
 
 - `src/refunddesk/llm.py` is the only module that talks to a model provider.
-- `src/refunddesk/agent.py` holds the agent loop. It has the system prompt with the business rules, strict tool-argument parsing, validation of every tool result, retries (`MAX_RETRIES = 3`) and a history window.
+- `src/refunddesk/agent.py` holds the agent loop. It has the system prompt with the business rules, strict tool-argument parsing, parallel execution of each response's tool calls, timeout retries (`MAX_RETRIES = 3`) and a history window.
 - `src/refunddesk/tools.py` has the mock tools over a local JSON store (`store.py`), with deterministic fault injection from `faults.py`.
 - `evals/*.json` holds 20 tasks and `evals/heldout/*.json` holds 6 more. Each task has turns, an initial store, faults and deterministic checks (`checks.py`).
 
diff --git a/src/refunddesk/agent.py b/src/refunddesk/agent.py
index 72f49e1..d63938e 100644
--- a/src/refunddesk/agent.py
+++ b/src/refunddesk/agent.py
@@ -3,8 +3,10 @@
 from __future__ import annotations
 
 import json
+import contextvars
 import logging
 import math
+from concurrent.futures import ThreadPoolExecutor
 from dataclasses import dataclass, field
 from typing import Any, Protocol
 
@@ -95,32 +97,6 @@ def parse_tool_arguments(call: ToolCall) -> dict[str, Any]:
     return args
 
 
-def validate_tool_result(tool: str, result: Any) -> tuple[bool, bool, str]:
-    """Check a tool result before the agent acts on it.
-
-    Returns ``(valid, retryable, reason)``. A valid result can be handed to the
-    model. An invalid one is retried when ``retryable`` is true.
-    """
-    if not isinstance(result, dict) or "status" not in result:
-        return False, True, "malformed tool result"
-    status = result["status"]
-    if status == "failed":
-        return False, True, result.get("error", "tool reported failure")
-    if status in ("not_found", "rejected"):
-        return True, False, status
-    if status != "ok":
-        return False, True, f"unexpected status {status!r}"
-    if tool == "lookup_order":
-        order = result.get("order")
-        if not isinstance(order, dict) or not {"order_id", "amount", "status"} <= order.keys():
-            return False, True, "order record missing required fields"
-        if not isinstance(order["amount"], (int, float)) or order["amount"] < 0:
-            return False, True, "order amount is invalid"
-    if tool == "issue_refund" and not isinstance(result.get("refund"), dict):
-        return False, True, "refund confirmation missing"
-    return True, False, "ok"
-
-
 @dataclass
 class RefundDeskAgent:
     llm: ChatModel
@@ -165,21 +141,14 @@ class RefundDeskAgent:
     def _execute_with_retries(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
         func = TOOL_FUNCTIONS[name]
         last_error = "unknown error"
-        # One initial attempt plus MAX_RETRIES retries. Timeouts and failed or
-        # malformed results are retried; not_found/rejected are final answers.
+        # One initial attempt plus MAX_RETRIES retries. Only timeouts are
+        # retried; any returned result goes straight back to the model.
         for attempt in range(MAX_RETRIES + 1):
             try:
-                result = func(**args)
+                return func(**args)
             except ToolTimeout as exc:
                 last_error = str(exc)
                 logger.debug("%s attempt %d timed out", name, attempt + 1)
-                continue
-            valid, retryable, reason = validate_tool_result(name, result)
-            if valid:
-                return result
-            last_error = reason
-            if not retryable:
-                break
         return {
             "status": "error",
             "error": f"{name} failed after {MAX_RETRIES} retries: {last_error}",
@@ -203,10 +172,38 @@ class RefundDeskAgent:
             if result.get("status") == "ok":
                 self.verified_orders[args["order_id"]] = result["order"]
                 self.failed_lookups.discard(args["order_id"])
-            elif result.get("status") == "error":
+            elif result.get("status") in ("error", "failed"):
                 self.failed_lookups.add(args["order_id"])
         return result
 
+    def _run_tool_calls(self, calls: list[ToolCall]) -> list[dict[str, Any]]:
+        """Run one response's tool calls in parallel; results keep call order.
+
+        Calls to the same tool run in order on one thread, so the per-tool fault
+        counters see the same sequence for the same task and seed. Lookups finish
+        before other tools start, so a refund in the same batch sees its lookup.
+        """
+        results: dict[int, dict[str, Any]] = {}
+
+        def run_group(group: list[int]) -> None:
+            for i in group:
+                results[i] = self._run_tool_call(calls[i])
+
+        lookups = [i for i, c in enumerate(calls) if c.name == "lookup_order"]
+        others: dict[str, list[int]] = {}
+        for i, c in enumerate(calls):
+            if c.name != "lookup_order":
+                others.setdefault(c.name, []).append(i)
+        phases = [[lookups] if lookups else [], list(others.values())]
+        with ThreadPoolExecutor(max_workers=max(1, len(others))) as pool:
+            for groups in phases:
+                # Each thread gets a copy of this context so it sees the tool
+                # runtime and the current neatlogs span.
+                futures = [pool.submit(contextvars.copy_context().run, run_group, g) for g in groups]
+                for future in futures:
+                    future.result()
+        return [results[i] for i in range(len(calls))]
+
     # -------------------------------------------------------------- main loop
 
     def handle_turn(self, customer_message: str) -> str:
@@ -240,16 +237,14 @@ class RefundDeskAgent:
             )
             if not response.tool_calls:
                 return response.text
-            results = []
-            for call in response.tool_calls:
-                result = self._run_tool_call(call)
-                results.append(
-                    {
-                        "tool_call_id": call.id,
-                        "name": call.name,
-                        "content": json.dumps(result, sort_keys=True),
-                        "is_error": result.get("status") in ("error", "failed"),
-                    }
-                )
+            results = [
+                {
+                    "tool_call_id": call.id,
+                    "name": call.name,
+                    "content": json.dumps(result, sort_keys=True),
+                    "is_error": result.get("status") in ("error", "failed"),
+                }
+                for call, result in zip(response.tool_calls, self._run_tool_calls(response.tool_calls))
+            ]
             self.history.append({"role": "tool_results", "results": results})
         return "I'm sorry, I couldn't finish handling your request. A human agent will follow up."
diff --git a/src/refunddesk/tools.py b/src/refunddesk/tools.py
index 9f67678..3dd2768 100644
--- a/src/refunddesk/tools.py
+++ b/src/refunddesk/tools.py
@@ -2,12 +2,15 @@
 
 Each tool execution is one neatlogs TOOL span. Injected faults happen before the
 tool touches the store, so a timed-out or failed call never has side effects.
+Tools may run on several threads at once; ``ToolRuntime.lock`` guards the call
+log, id counters, fault plan and every store read-modify-write.
 """
 
 from __future__ import annotations
 
 import contextvars
 import itertools
+import threading
 from dataclasses import dataclass, field
 from typing import Any, Callable, TypedDict
 
@@ -43,14 +46,17 @@ class ToolRuntime:
     log: list[ToolLogEntry] = field(default_factory=list)
     _seq: Any = field(default_factory=lambda: itertools.count(1))
     _ids: Any = field(default_factory=lambda: itertools.count(1))
+    lock: threading.RLock = field(default_factory=threading.RLock)
 
     def record(self, tool: str, args: dict[str, Any], outcome: str, result: Any = None) -> None:
-        self.log.append(
-            {"seq": next(self._seq), "tool": tool, "args": args, "outcome": outcome, "result": result}
-        )
+        with self.lock:
+            self.log.append(
+                {"seq": next(self._seq), "tool": tool, "args": args, "outcome": outcome, "result": result}
+            )
 
     def new_id(self, prefix: str) -> str:
-        return f"{prefix}-{next(self._ids):04d}"
+        with self.lock:
+            return f"{prefix}-{next(self._ids):04d}"
 
 
 _runtime: contextvars.ContextVar[ToolRuntime] = contextvars.ContextVar("refunddesk_tool_runtime")
@@ -66,7 +72,8 @@ def current_runtime() -> ToolRuntime:
 
 def _maybe_inject_fault(tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
     rt = current_runtime()
-    fault = rt.faults.next_fault(tool)
+    with rt.lock:
+        fault = rt.faults.next_fault(tool)
     if fault == "timeout":
         rt.record(tool, args, "timeout")
         raise ToolTimeout(f"{tool} timed out")
@@ -106,22 +113,23 @@ def issue_refund(order_id: str, amount: float, reason: str) -> dict[str, Any]:
     if (failure := _maybe_inject_fault("issue_refund", args)) is not None:
         return failure
     rt = current_runtime()
-    state = rt.store.load()
-    order = state["orders"].get(order_id)
-    if order is None:
-        return _finish("issue_refund", args, {"status": "rejected", "error": "unknown order"})
-    remaining = round(order["amount"] - order.get("refunded_amount", 0.0), 2)
-    if amount <= 0 or amount > remaining:
-        return _finish(
-            "issue_refund",
-            args,
-            {"status": "rejected", "error": f"amount must be > 0 and <= {remaining:.2f}"},
-        )
-    refund = {"refund_id": rt.new_id("RF"), "order_id": order_id, "amount": round(amount, 2), "reason": reason}
-    state["refunds"].append(refund)
-    order["refunded_amount"] = round(order.get("refunded_amount", 0.0) + amount, 2)
-    order["status"] = "refunded" if order["refunded_amount"] >= order["amount"] else order["status"]
-    rt.store.save(state)
+    with rt.lock:
+        state = rt.store.load()
+        order = state["orders"].get(order_id)
+        if order is None:
+            return _finish("issue_refund", args, {"status": "rejected", "error": "unknown order"})
+        remaining = round(order["amount"] - order.get("refunded_amount", 0.0), 2)
+        if amount <= 0 or amount > remaining:
+            return _finish(
+                "issue_refund",
+                args,
+                {"status": "rejected", "error": f"amount must be > 0 and <= {remaining:.2f}"},
+            )
+        refund = {"refund_id": rt.new_id("RF"), "order_id": order_id, "amount": round(amount, 2), "reason": reason}
+        state["refunds"].append(refund)
+        order["refunded_amount"] = round(order.get("refunded_amount", 0.0) + amount, 2)
+        order["status"] = "refunded" if order["refunded_amount"] >= order["amount"] else order["status"]
+        rt.store.save(state)
     return _finish("issue_refund", args, {"status": "ok", "refund": refund})
 
 
@@ -131,10 +139,11 @@ def escalate_to_human(order_id: str, reason: str) -> dict[str, Any]:
     if (failure := _maybe_inject_fault("escalate_to_human", args)) is not None:
         return failure
     rt = current_runtime()
-    state = rt.store.load()
-    ticket = {"ticket_id": rt.new_id("ESC"), "order_id": order_id, "reason": reason}
-    state["escalations"].append(ticket)
-    rt.store.save(state)
+    with rt.lock:
+        state = rt.store.load()
+        ticket = {"ticket_id": rt.new_id("ESC"), "order_id": order_id, "reason": reason}
+        state["escalations"].append(ticket)
+        rt.store.save(state)
     return _finish("escalate_to_human", args, {"status": "ok", "ticket": ticket})
 
 
@@ -144,10 +153,11 @@ def send_customer_email(to: str, subject: str, body: str) -> dict[str, Any]:
     if (failure := _maybe_inject_fault("send_customer_email", args)) is not None:
         return failure
     rt = current_runtime()
-    state = rt.store.load()
-    email = {"message_id": rt.new_id("MSG"), "to": to, "subject": subject, "body": body}
-    state["emails"].append(email)
-    rt.store.save(state)
+    with rt.lock:
+        state = rt.store.load()
+        email = {"message_id": rt.new_id("MSG"), "to": to, "subject": subject, "body": body}
+        state["emails"].append(email)
+        rt.store.save(state)
     return _finish("send_customer_email", args, {"status": "ok", "message_id": email["message_id"]})
 
 
diff --git a/tests/test_agent.py b/tests/test_agent.py
index 236aad9..8bd2c61 100644
--- a/tests/test_agent.py
+++ b/tests/test_agent.py
@@ -7,7 +7,6 @@ from refunddesk.agent import (
     RefundDeskAgent,
     ToolArgumentError,
     parse_tool_arguments,
-    validate_tool_result,
 )
 from refunddesk.llm import ToolCall
 
@@ -46,15 +45,6 @@ def test_parsing_accepts_valid():
     assert parse_tool_arguments(call("get_refund_policy", "")) == {}
 
 
-def test_validate_tool_result():
-    assert validate_tool_result("lookup_order", {"status": "failed"})[:2] == (False, True)
-    assert validate_tool_result("lookup_order", {"status": "not_found"})[:2] == (True, False)
-    assert validate_tool_result("lookup_order", {"status": "ok", "order": {"order_id": "A"}})[:2] == (False, True)
-    assert validate_tool_result("lookup_order", "garbage")[:2] == (False, True)
-    good = {"status": "ok", "order": {"order_id": "A", "amount": 1.0, "status": "delivered"}}
-    assert validate_tool_result("lookup_order", good)[0]
-
-
 def test_retries_until_success(make_runtime, scripted):
     rt = make_runtime(faults=[{"tool": "lookup_order", "kind": "timeout", "calls": [1, 2, 3]}])
     agent = RefundDeskAgent(llm=scripted([]))
@@ -63,8 +53,16 @@ def test_retries_until_success(make_runtime, scripted):
     assert "A1" in agent.verified_orders
 
 
+def test_failed_result_is_returned_without_retry(make_runtime, scripted):
+    rt = make_runtime(faults=[{"tool": "lookup_order", "kind": "failed", "calls": [1]}])
+    agent = RefundDeskAgent(llm=scripted([]))
+    assert agent._run_tool_call(call("lookup_order", {"order_id": "A1"}))["status"] == "failed"
+    assert [e["outcome"] for e in rt.log] == ["failed"]
+    assert "A1" in agent.failed_lookups
+
+
 def test_retries_exhausted_marks_lookup_failed(make_runtime, scripted):
-    rt = make_runtime(faults=[{"tool": "lookup_order", "kind": "failed", "always": True}])
+    rt = make_runtime(faults=[{"tool": "lookup_order", "kind": "timeout", "always": True}])
     agent = RefundDeskAgent(llm=scripted([]))
     result = agent._run_tool_call(call("lookup_order", {"order_id": "A1"}))
     assert result["status"] == "error"
@@ -118,3 +116,37 @@ def test_history_window_cuts_at_user_messages(scripted):
     window = agent._window()
     assert window[0] == {"role": "user", "content": "2"}
     assert len(window) == 4
+
+
+def test_parallel_batch_runs_lookup_first_and_keeps_order(make_runtime, scripted):
+    rt = make_runtime()
+    llm = scripted([
+        [
+            ("issue_refund", '{"order_id": "A1", "amount": 20.0, "reason": "broken"}'),
+            ("lookup_order", '{"order_id": "A1"}'),
+            ("send_customer_email", '{"to": "t@example.com", "subject": "s", "body": "b"}'),
+            ("escalate_to_human", '{"order_id": "BIG", "reason": "over limit"}'),
+        ],
+        "Done.",
+    ])
+    agent = RefundDeskAgent(llm=llm)
+    agent.handle_turn("refund A1")
+    results = agent.history[2]["results"]
+    assert [r["name"] for r in results] == ["issue_refund", "lookup_order", "send_customer_email", "escalate_to_human"]
+    assert all(not r["is_error"] for r in results)
+    assert rt.log[0]["tool"] == "lookup_order"
+    state = rt.store.load()
+    assert len(state["refunds"]) == 1 and len(state["emails"]) == 1 and len(state["escalations"]) == 1
+
+
+def test_parallel_same_tool_calls_keep_fault_order(make_runtime, scripted):
+    rt = make_runtime(faults=[{"tool": "send_customer_email", "kind": "failed", "calls": [2]}])
+    llm = scripted([
+        [("send_customer_email", f'{{"to": "{n}@example.com", "subject": "s", "body": "b"}}') for n in "abc"],
+        "Done.",
+    ])
+    agent = RefundDeskAgent(llm=llm)
+    agent.handle_turn("email")
+    statuses = [json.loads(r["content"])["status"] for r in agent.history[2]["results"]]
+    assert statuses == ["ok", "failed", "ok"]
+    assert [e["to"] for e in rt.store.load()["emails"]] == ["a@example.com", "c@example.com"]
```

## Trace IDs

- Culprit run (neatlogs, workflow `culprit`, session `ff50e3620fdd`): `d80e61a81918c7eb3ffd917a2509efb0`, `5eb9938ad68d8edd3170eeb54aba5133`, `03cd4982b4f1e9e2e203764819423b2a`, `b1556c00c1dae54668e264f26b6ba43a`
- Victim task runs: 240 traces
  - good `0479c273fb`: `1e67e3454c4f51ef38963de1df4c7193`, `91b3e873d1c829366bf670fe8b30133c`, `80c8ae95205794e8ae048df081701cfa`, `d33941b08d905d9a19e66017125ef852`, `7eb165d74e27662874da0dc09ccb854c`, `363d86c0b2d5dfc936730fd5fe1c9292`, `cb9c22e9b605322d6341597da5c8f10f`, `b5106a4a5c7a9512742c9d3c69463fc7`, `04b19a1926d26d78727cd83900ea31d0`, `06cf342a7d52c1bd38e08929467b35fa`, `7ea3227f7c1044b3938d170308a6413c`, `e24c2bb7b2ae60bf82d982fe851a3f03`, `7b1a3e44ab7f43d8dfe1d5a6621e0dc7`, `0ac04a5c00286712412d3e42fc9a0b8a`, `e8a13d2198421ddd85ca06250597377a`, `94f7e39acc4ea9760239efc574bfc632`, `80303af4b2f5c295fff78f2c26ecc1d4`, `1dd28b900d0be2cdbeb4d9bb8c9e3985`, `11a2348496e7262c7af6f6c4c753a28e`, `af8eec66634bfd98ca3a13f7a0940372`, `d1405f05546a8224eea6f41f68f02f91`, `0e8cebb1544ee1a24e290e1f445002da`, `2819f64520b801cc918ab1d4a850f642`, `dfd0662f5768bd96ce7c520ac83b1033`, `633e7dfb2ba7607f76f29562fd418e1b`, `8e80ac9846cc3b9a15169faa812edb24`, `d879756682c1c4863f90d503a2333935`, `a854e59007af0b8a867ed599903a6fdc`, `d16c56c1173ca304d8388b9cbcea6895`, `e7b4f6e5626bb8e8783214a75525f0ad`, `74d5e5d896647602b802a9bb20f6577d`, `bd9d8a4ab1bbfa930ac9e8318d788351`, `b516564a602c01ab537fe8e46f151140`, `d29f1edce27b85c6acf5ded27ec5dd55`, `2acbf9c5e258528c37452392d2185aa1`, `76c9075d719d14114bc377a4ed8c878f`, `411baa75b94a45d90121ba850a029209`, `46160079687964df1524f3c8f6b406ad`, `ea84a9fe85d0d4fdc5b26c61b5a587ce`, `3c8f193b3bef9a312efd95b361475f85`, `632a15317320aa729770a270bc54462e`, `291bbdba2bb327071c4c74a225a5542f`, `7aac63a96a8ec47e99b41617eae18ac8`, `0f44c80302ef909f43e8686c379104b2`, `444221117a7f543bd926ea016402efba`, `c782e5362a2760e642653aede255b645`, `969d12c8f69a7f51f98c24434de6c01e`, `8454316e2bb9151c1f9d5966bed55a51`, `c31d48a87a719bd4ce44fffb079a0799`, `dc0e63d8f92ea6e5b7e66d502418fbc3`, `b9f345df579fe8cfa9b4829ecb07b532`, `f5b85ad868c5a731be1797db8fe1fa50`, `f228d2d34c00c6cc12b479b2f7b64be6`, `251b7f00cef067147dbcea192ba4e2ae`, `b0be4c1c67cd225fbde62193931f7a3f`, `1fdad3d229ad481d75845380def0a386`, `858e1d9c295f8e65dd6aba308e0b8926`, `e21ece72d664ed17c53bb5ffdf74c658`, `e0cc528612ff5ebf6edb1e5bf18f6f8e`, `ed5ae5a7a60de43bf190344f42e676b1`, `517fcd247fdd748350643008af0e78a8`, `5e4466d286eb368aaacb3d2cdd055094`, `35e51ce6a69c08b7493b705034026e5f`, `28e97f152f218419a6d2812b85bc6c57`, `d1c945f6c506b698e79e02c317cce744`, `cad7973faa119d709441175bf1938db3`, `d0d6f2eaf92bba62ee1aae578d525999`, `302dfeabe17721de5ee7a80ede3894c2`, `add06060848546855b814420a4a20315`, `4d6fda9d14d654e2d6e1956859204f7a`, `f7c6a7d203c4283c10f706faf895f566`, `aab6ac7d3b5ff33ec0bfd8fc55f94d5c`, `636b2f15ac845a9027b44e5cb96abd2f`, `9d0df7f25472ca6255fa214735729dc2`, `10d585ad9cf525093e8b170c109fcae1`, `3f6064d9c9c546d5626ee729ff74cfd6`, `f38d48105f72aeda9cf3a531d5691d54`, `745b8eb5716aede1da34d54c48d60433`
  - bad `f6511b8e6b`: `8ea18dbe3d713716a0fdb3e5e8f2ef95`, `0a4071e00cd0b1fdb8391aff9de8728b`, `cc7a4ed9bbd4ec42d0c328179d73a2f1`, `31e20042ecb44811c6ca52e5fd23a79a`, `157b4dab185e23ec179359d110736e64`, `d39a78b51021d306a3450ad50d15f639`, `730b9f52b6a7e1dfc78d3554bec700aa`, `c3e85b6a3c08a49c029d19201a7e0b15`, `c338ec459ad885392b413a121b7939b2`, `394be7788f729526b4b029a943295b8c`, `e47e3c19c9ee0de6e92dde4c24946315`, `7368742aed1c7f49124e2d29b8b78e45`, `db7aa0daad835dc9cc4ecc54c24a72fe`, `f65c9ee12fff9adbb3fee8487fa1e251`, `b418cbb9c113a24abb48246d983b3006`, `e4f06927515a43105fd0124160749e0d`, `3063ef2b1dd0685610994a9784b9c424`, `9b3857055a7230eec5f41d1e1cb014a2`, `e68900bdcd8f13b3f64fba5940b26fea`, `75987173daa2fd703b38911c65ecb597`, `300805f6124726f681a3fdbe43b4c3e8`, `e77f4b84cf03a8265706f1dff706dcc9`, `38e00b8d83aba5c77f562ba2c3e2357e`, `e1a0394d2ca857ab9c4b1a6099cd7a14`, `fd6cb2654b24fae036c7872a3476b0b9`, `343fb97ed6e64d4313c332000b15cd27`, `67a307901aff7f5d765065fac5476d35`, `6812bc9110dd7f073a7d072cda83ab2e`, `9ac91c5b957f7ec02ff0cbdbc3830246`, `302a7d25adc5362b646b906058b2b2a7`, `0ca6b791e422913bda026a80f4bd6c08`, `a8e7eb82592bd963cbc3072c44131628`, `eb18b79a65023748d97acf8a9f442eee`, `c86cf4e5c44700542f96d09405ad2cf4`, `463d3e700292cae7e45a20abc6092a84`, `9064d631d579b0ef83d6a62b9315ec8a`, `74f54bae2f727f40b15dcf4ac6e588d8`, `8129358b40672cd9dfda55808671dd9d`, `4856a76a3367e61b973cb1936a0f7535`, `078717ab725b03f8b469fe6db69c53a6`, `fdc68a78cbf3782c13777de368366491`, `f7037b14394da385b2e29b6004b884ca`, `3a308491e53668f52bec5d8fbee1e0d9`, `91fc994e1b26b8c3c87b51864f8fdfc7`, `0dd3c29cef7a506915554c11ac3e52f9`, `95344391ca1cf27a92b57b1ddc77d5bb`, `552c9912f4193aab42f9465c58931d6b`, `678d8344f7abab296cb5712c7b01cace`, `8e7c0c203388c8affcde6af87b4d95eb`, `9949082b4375638b8560d198213b8e77`, `a2060f0ebcdca0d308629a960206e2df`, `e774a24f889cb58ae90ed8b670e55962`, `9507f0936ae6afdca91fc7b280d2c56e`, `1e7e405d19256b891b73ba8734fc5cbc`, `b61d3c6f43237c8afcc28e2cc835f2d5`, `9d30600cb1ae2af1bc12e9f28c435ab4`, `ab3b97861cc5157b1638833e6d02b83e`, `bfeb472cade308eb962202c5496f7ef8`, `d56a9f28a97586d6907d3c48b15a211c`, `74d9c5cd85f8339612a893034bb0361d`, `0e503feadda323bfe3a0f79b2bbd8d43`, `f4de88c2aae69b1b3c37df816320dc53`, `963fba4be61aa407795c8814387652d9`, `dd94cba44693a2406bfc7085921fd093`, `f4afa56af62420a55420616e6511df00`, `a93218a973432672aa900052bd73c38b`, `77d7a7e982fe8eae072a44b4ec83745a`, `f066131328740d930b932676c2592867`, `b8f8b1d506773628ca30047606ecda74`, `43c6826d6a6e7308dc99f110f0d29582`, `de8a75a6652006d2f8eee4c85d30a0a0`, `224c54a45da40c23b7e4088189ba8690`, `30f08dfa352f1c727c32709284d25e17`, `8d004b7ee61f91c8363fe17d46804d8d`, `dea86b1ec62fe67dce02a5f8bbc20fec`, `d7a340a684dbf16f76cf77809585318e`, `576b48091dbb3a7b8f70af1f5c200c49`, `3510723f57a40f4960dc54b66c8d538b`
  - `81c07532c4`: `b09d3e38f47c56720af5766494ca11cb`, `79fab83f3cff8c6dfb5b6654486ce5b6`, `ab81b0f62ea56979701b3934c6cf8e0f`, `f5cf035f4df82b480e3d1f9630688b99`, `9b2b0e15c47060c550399acba23a242f`, `2aa38f0f3adfdd906be576114b206281`, `4891d9e3fbf263a3a082b73f0be758ec`, `c2d5f4ae3c252542fe253522efd4aff1`, `dd279700c863abb174e656ac35496e78`, `b7240dcfb3b7e46858bcc1957d07b6db`, `238e8df099c0bd4d71e250d5c481b63b`, `84d16233ff14f2752eecb80f2c8d9edd`, `dc87c531d6ee95c597e9918fb36a1d16`, `cb4dc98c0f4acf8213b4b583e4cdb122`, `8719fd1470b896af96219e30eebacc52`, `ca940ae033a70910b7afd38cd9ba33dd`, `7087b3c1bb9708aa7941c585f2555410`, `7e5e68325d6e5f85c49a527f5758e4de`, `7f92ec7948c64876539316435b6f2ec4`, `37a213baa1e0db284a5b75aba1570b0a`, `8e16319b55e57aa374c464c849ba566d`
  - `c9a132f01b`: `c2e25f40b55ac9954f8eb6b29fbbfd9a`, `ed576546de4772e406e0d003f41dbe60`, `7a84ce4f066d177f24ca642af1ade726`, `49b95b8895676676d4affca87a31791e`, `88fccec6f7e8e1aa560b209894726483`, `f44d69462a0fe77fc8ae91a649a3fced`, `ecdb2b0544f28f0cd2a41419529bedaf`, `8fe9f938e1688a492d7e70293b106edc`, `86fcec5631d8bbb416ec945ea2a4eef6`, `8bfc6b328fc9c60ce1b2313c0a5e58cf`, `fa891ecd0f1b3232f0bc5f3810193e7b`, `675a49ab961dead849c42bb800a792c1`, `d5750fbbb850402ffb8ff0f90ea682e8`, `383f3fea1a52e17a07033586ff2cc29d`, `f8f1ab5b556100e76659183025e73fdc`, `54f1ac34b25a99221e136b2bb78c30f7`, `f7b02f5efd5ce5d709b3e86bff9acf8e`, `3b037205154e203ee42d4200c3eb2597`, `49a5e29793476a0017c2b9fa3f687838`, `311de53e439e5d84303b4f4978a6d97d`, `622fa3c4018704f1ce249465065549bc`
  - `8793325134`: `fa61f2382d1e21637e9b33189ca454da`, `bd7bfdd870414a3ef53ea83ece9e24ef`, `30c9c7e0ede4646c311072d1ac55fc47`, `a7ef19c44ad8d9d794d3733316c470b2`, `877dfc7c62fa1c49899f20b776a060d3`, `caa3c61883661703d69a5d01789b84bd`, `e667633414fe30add2e1bea1cafcfd9d`, `b72335e23204df522e1c255d5b7c6fbd`, `7e374fd69f158f7192cc03c6c634c4e3`, `0ea1e227a66423a125d2cc985ce7d141`, `5e6c5f7326437f948dbec5a6ed7e4b22`, `e32a7ca7a712f2564357be9416d6c00f`, `46bed2ccfbd414fc9a26ad0ff1761d75`, `1555d1eb23b14aa8a87890946d336043`, `7903a46711148548c971a05950722c1c`, `12dc162ab4fd2ba6e9f7f9ff9c3139ce`, `3d99d71887e50b3fa7137696ca1148d4`, `471b85392848192b107512fec4c2b712`, `ee5150c8a51d36cab4e68c5fd07450cb`, `c2cbfe1c60725d84e85885b256039ff3`, `2b38e348252439fb56cb0a9529bde58d`
  - `397c42743b`: `dea4c9514ad0458e192f03ed28f139e7`, `54dc6d56ace90b277cbaa27dd2932d2a`, `be053a969183fd4547ffcaa8e08d3af1`, `1c031a6510059b0dc02521f8ba05834a`, `ce97263d1739d4d75a90b7211eebcc73`, `27800e5ca0039653b33f50184588bccd`, `1df0eea819e1ac6e5f9d69a3925e4961`, `c9e51e2255f71396b76578b5b1707bed`, `31a061e743922da525c14b5d2f3f7057`, `c69fcb49012e99edf8b11ae359b8bb23`, `3fc0d2cfa5a3e337048181f9f1e3cfe3`, `73fbc65ea6cb33b24e7970c282eaf123`, `8182b686a4bc880625b391d8c87500a6`, `cdb7a262daffe051c0bc973564233ec6`, `4e67459646b1f1bab2cbeb462bd0a5d1`, `e6fc7eefb21bea6bb470822ef29ddd63`, `1427b629b096f4cf18ac4f7ca96649c4`, `75c98824bf86ab395f12575c95bdabca`, `a5030062a752d93a8cd217201eb44ad2`, `e5a06a62e23dff5af764d6aa6a703c15`, `788f98104bb88bedc266f06df4955dd7`

## Costs

| Item | Value |
|---|---:|
| Victim runs executed | 456 |
| … measuring the ends | 156 |
| … bisecting | 84 |
| … localising | 84 |
| … fixing and verifying | 132 |
| Reused from earlier runs (not paid again) | 0 |
| Victim cost | $1.07 |
| Culprit LLM cost | $0.0633 |
| **Total** | **$1.13** |
| Per victim run | $0.0024 |
| Wall time | 12.5 min |
