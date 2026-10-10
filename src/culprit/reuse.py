"""Reuse baseline task runs from earlier runs in the ledger (v2 efficiency).

A victim task run is fully determined by what it ran: the commit, the pinned suite, the victim
provider and model, the eval runner, and the repetition (which is the seed). So a baseline measured
at a commit in one run is equally valid in any later run that matches all of those, and `k` too,
as the run key asks. Matching rows are copied into the new run's step with their origin
(`reused_from_run`, `reused_from_id`), so every number in the new run stays auditable, and they
are not counted as spend a second time.

Only original measurements are copied (never a row that was itself reused), so provenance always
points at the run that paid for the result.
"""

from __future__ import annotations

import json
from collections import Counter

from culprit.config import Config
from culprit.ledger import Ledger

ARTIFACT = "baseline_reuse"

# Earlier baseline task runs at `commit_sha` whose run matches the reuse key. The oldest original
# measurement wins, so repeated reuse keeps pointing at the same source.
_SOURCES = """
SELECT t.id, t.task_id, t.repetition, s.run_id
FROM task_runs t
JOIN steps s USING (step_id)
JOIN runs r ON r.run_id = s.run_id
WHERE s.commit_sha = :sha
  AND s.kind LIKE 'baseline%'
  AND s.run_id != :run_id
  AND t.reused_from_run IS NULL
  AND r.suite_sha = :suite_sha
  AND json_extract(r.config_json, '$.victim_provider') = :provider
  AND json_extract(r.config_json, '$.victim_model') = :model
  AND json_extract(r.config_json, '$.eval_module') = :eval_module
  AND json_extract(r.config_json, '$.k') = :k
ORDER BY t.id
"""


def import_runs(ledger: Ledger, cfg: Config, run_id: str, kind: str, sha: str,
                items: list[tuple[str, int]]) -> dict[str, int]:
    """Copy matching earlier results for `items` (task, repetition) into this run's step.

    Returns {source run_id: rows copied}. Does nothing for a run without a pinned suite, or for a
    step that already holds a result (resume never replaces a recorded run).
    """
    suite_sha = ledger.get_run(run_id)["suite_sha"]
    if not (cfg.reuse_baselines and suite_sha and items):
        return {}
    wanted = set(items)
    sources: dict[tuple[str, int], tuple[int, str]] = {}
    for row in ledger.conn.execute(_SOURCES, {
        "sha": sha, "run_id": run_id, "suite_sha": suite_sha, "provider": cfg.victim_provider,
        "model": cfg.victim_model, "eval_module": cfg.eval_module, "k": cfg.k,
    }):
        key = (row["task_id"], row["repetition"])
        if key in wanted and key not in sources:
            sources[key] = (row["id"], row["run_id"])
    if not sources:
        return {}
    step_id = ledger.open_step(run_id, kind, sha)
    done = ledger.task_runs(step_id)
    copied: Counter[str] = Counter()
    for key, (source_id, source_run) in sorted(sources.items()):
        if key not in done and ledger.copy_task_run(step_id, source_id, source_run):
            copied[source_run] += 1
    if copied:
        _record(ledger, run_id, kind, sha, copied)
    return dict(copied)


def _record(ledger: Ledger, run_id: str, kind: str, sha: str, copied: Counter[str]) -> None:
    """Per-run provenance summary: {"<kind>:<sha>": {source run_id: rows}} in artifact `baseline_reuse`."""
    previous = ledger.get_artifact(run_id, ARTIFACT)
    summary = json.loads(previous) if previous else {}
    entry = summary.setdefault(f"{kind}:{sha}", {})
    for source, n in copied.items():
        entry[source] = entry.get(source, 0) + n
    ledger.put_artifact(run_id, ARTIFACT, json.dumps(summary, sort_keys=True))


def provenance(ledger: Ledger, run_id: str) -> dict[str, dict[str, int]]:
    text = ledger.get_artifact(run_id, ARTIFACT)
    return json.loads(text) if text else {}
