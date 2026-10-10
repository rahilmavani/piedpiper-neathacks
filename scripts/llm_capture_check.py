"""Fixture check for the LLM capture path: one structured call inside WORKFLOW → AGENT spans.

    uv run python scripts/llm_capture_check.py   # prints run_id and trace_id for readback
"""

import uuid

from dotenv import load_dotenv
from pydantic import BaseModel

from culprit import llm, tracing
from culprit.config import PROJECT_ROOT


class Answer(BaseModel):
    commits: list[str]


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    tracing.init()
    run_id = f"llmcheck-{uuid.uuid4().hex[:8]}"
    sha = "0" * 40
    try:
        with tracing.run_context(run_id=run_id), tracing.span("llm_capture_check", "WORKFLOW", commit_sha=sha):
            print("run_id", run_id, "trace_id", tracing.current_trace_id())
            with tracing.span("structured_call", "AGENT", input={"purpose": "capture check"}) as sp:
                reply = llm.structured("You list git commits.", "Return the commits ['a1', 'b2'] as JSON.", Answer)
                sp.output({"value": reply.value.model_dump(), "cost_usd": reply.cost_usd})
                print("reply", reply.value, "usage", reply.usage)
    finally:
        tracing.shutdown()


if __name__ == "__main__":
    main()
