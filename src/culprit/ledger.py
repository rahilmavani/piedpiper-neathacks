"""SQLite run ledger (PRD §12).

Every write is idempotent: steps are unique per (run_id, kind, commit_sha) and task runs per
(step_id, task_id, repetition). Resume works by replaying the deterministic controller, which
reuses any recorded step or task run instead of executing it again.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    good_ref TEXT NOT NULL,
    bad_ref TEXT NOT NULL,
    suite_hash TEXT NOT NULL,
    suite_source TEXT,
    suite_sha TEXT,
    good_sha TEXT,
    bad_sha TEXT,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    culprit_sha TEXT,
    confidence TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    decision TEXT,
    wilson_low REAL,
    wilson_high REAL,
    n INTEGER,
    passes INTEGER,
    cost_usd REAL,
    latency_ms_p50 REAL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    flags TEXT,
    UNIQUE (run_id, kind, commit_sha)
);
CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id INTEGER NOT NULL REFERENCES steps(step_id),
    task_id TEXT NOT NULL,
    repetition INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    cost_usd REAL,
    latency_ms REAL,
    tokens_in INTEGER,
    tokens_out INTEGER,
    neatlogs_trace_id TEXT,
    error TEXT,
    UNIQUE (step_id, task_id, repetition)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    step_id INTEGER,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    neatlogs_trace_id TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    path_or_text TEXT NOT NULL,
    UNIQUE (run_id, kind)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskRun:
    task_id: str
    repetition: int
    passed: bool
    cost_usd: float | None
    latency_ms: float | None
    tokens_in: int | None
    tokens_out: int | None
    trace_id: str | None
    error: str | None = None


class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(steps)")}
        if "flags" not in columns:  # ledgers created before M2
            self.conn.execute("ALTER TABLE steps ADD COLUMN flags TEXT")
        run_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(runs)")}
        # ledgers created before the suite was pinned, or before refs were resolved once per run
        for column in ("suite_source", "suite_sha", "good_sha", "bad_sha"):
            if column not in run_columns:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # runs -----------------------------------------------------------------
    def create_run(self, repo: str, good: str, bad: str, suite_hash: str, config_json: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._tx() as c:
            c.execute(
                "INSERT INTO runs (run_id, repo, good_ref, bad_ref, suite_hash, config_json, status, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                (run_id, repo, good, bad, suite_hash, config_json, _now()),
            )
        return run_id

    def get_run(self, run_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run_id {run_id}")
        return row

    def update_config(self, run_id: str, suite_hash: str, config_json: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE runs SET suite_hash = ?, config_json = ? WHERE run_id = ?",
                      (suite_hash, config_json, run_id))

    def set_suite(self, run_id: str, source: str, sha: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE runs SET suite_source = ?, suite_sha = ? WHERE run_id = ?", (source, sha, run_id))

    def set_range(self, run_id: str, good_sha: str, bad_sha: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE runs SET good_sha = ?, bad_sha = ? WHERE run_id = ?", (good_sha, bad_sha, run_id))

    def finish_run(
        self, run_id: str, status: str, culprit_sha: str | None, confidence: str | None, summary: str
    ) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE runs SET status = ?, finished_at = ?, culprit_sha = ?, confidence = ?, summary = ?,"
                " total_cost_usd = ? WHERE run_id = ?",
                (status, _now(), culprit_sha, confidence, summary, self.run_cost(run_id), run_id),
            )

    def run_cost(self, run_id: str) -> float:
        victim = self.conn.execute(
            "SELECT COALESCE(SUM(t.cost_usd), 0) FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ?",
            (run_id,),
        ).fetchone()[0]
        llm = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        return float(victim) + float(llm)

    def total_cost(self) -> float:
        """Cost across every run in this ledger, for the global (event-wide) cap."""
        victim = self.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM task_runs").fetchone()[0]
        llm = self.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls").fetchone()[0]
        return float(victim) + float(llm)

    # steps ----------------------------------------------------------------
    def get_step(self, run_id: str, kind: str, commit_sha: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM steps WHERE run_id = ? AND kind = ? AND commit_sha = ?", (run_id, kind, commit_sha)
        ).fetchone()

    def open_step(self, run_id: str, kind: str, commit_sha: str) -> int:
        with self._tx() as c:
            c.execute(
                "INSERT INTO steps (run_id, kind, commit_sha, status, started_at) VALUES (?, ?, ?, 'running', ?)"
                " ON CONFLICT (run_id, kind, commit_sha) DO NOTHING",
                (run_id, kind, commit_sha, _now()),
            )
        row = self.get_step(run_id, kind, commit_sha)
        assert row is not None
        return int(row["step_id"])

    def close_step(
        self,
        step_id: int,
        status: str,
        *,
        decision: str | None = None,
        wilson_low: float | None = None,
        wilson_high: float | None = None,
        n: int | None = None,
        passes: int | None = None,
        cost_usd: float | None = None,
        latency_ms_p50: float | None = None,
        error: str | None = None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE steps SET status = ?, decision = ?, wilson_low = ?, wilson_high = ?, n = ?, passes = ?,"
                " cost_usd = ?, latency_ms_p50 = ?, error = ?, finished_at = ? WHERE step_id = ?",
                (status, decision, wilson_low, wilson_high, n, passes, cost_usd, latency_ms_p50, error, _now(), step_id),
            )

    def set_decision(
        self, step_id: int, decision: str, flags: str | None, wilson_low: float, wilson_high: float,
        n: int, passes: int,
    ) -> None:
        """Decision over the commit's combined runs so far (initial step plus any resamples)."""
        with self._tx() as c:
            c.execute(
                "UPDATE steps SET decision = ?, flags = ?, wilson_low = ?, wilson_high = ?, n = ?, passes = ?"
                " WHERE step_id = ?",
                (decision, flags, wilson_low, wilson_high, n, passes, step_id),
            )

    def steps(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM steps WHERE run_id = ? ORDER BY step_id", (run_id,)).fetchall()

    # task runs --------------------------------------------------------------
    def task_runs(self, step_id: int) -> dict[tuple[str, int], TaskRun]:
        rows = self.conn.execute("SELECT * FROM task_runs WHERE step_id = ?", (step_id,)).fetchall()
        return {
            (r["task_id"], r["repetition"]): TaskRun(
                r["task_id"], r["repetition"], bool(r["passed"]), r["cost_usd"], r["latency_ms"],
                r["tokens_in"], r["tokens_out"], r["neatlogs_trace_id"], r["error"],
            )
            for r in rows
        }

    def record_task_run(self, step_id: int, tr: TaskRun) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO task_runs (step_id, task_id, repetition, passed, cost_usd, latency_ms, tokens_in,"
                " tokens_out, neatlogs_trace_id, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (step_id, task_id, repetition) DO NOTHING",
                (step_id, tr.task_id, tr.repetition, int(tr.passed), tr.cost_usd, tr.latency_ms,
                 tr.tokens_in, tr.tokens_out, tr.trace_id, tr.error),
            )

    # llm calls / artifacts ----------------------------------------------------
    def record_llm_call(
        self, run_id: str, step_id: int | None, purpose: str, model: str,
        tokens_in: int | None, tokens_out: int | None, cost_usd: float | None, trace_id: str | None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO llm_calls (run_id, step_id, purpose, model, tokens_in, tokens_out, cost_usd,"
                " neatlogs_trace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, step_id, purpose, model, tokens_in, tokens_out, cost_usd, trace_id),
            )

    def put_artifact(self, run_id: str, kind: str, text: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO artifacts (run_id, kind, path_or_text) VALUES (?, ?, ?)"
                " ON CONFLICT (run_id, kind) DO UPDATE SET path_or_text = excluded.path_or_text",
                (run_id, kind, text),
            )

    def get_artifact(self, run_id: str, kind: str) -> str | None:
        row = self.conn.execute(
            "SELECT path_or_text FROM artifacts WHERE run_id = ? AND kind = ?", (run_id, kind)
        ).fetchone()
        return None if row is None else str(row[0])
