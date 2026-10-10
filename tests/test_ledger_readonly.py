"""Read-only ledgers: an old-schema ledger is readable with current queries and is never written."""

import hashlib
import sqlite3
from pathlib import Path

from culprit.ledger import Ledger


def test_readonly_reads_a_ledger_from_before_a_migration_without_writing_it(tmp_path: Path):
    db = tmp_path / "old.sqlite"
    ledger = Ledger(db)
    run_id = ledger.create_run("repo", "g", "b", "h", "{}")
    step = ledger.open_step(run_id, "baseline", "abc")
    ledger.conn.execute("INSERT INTO task_runs (step_id, task_id, repetition, passed, cost_usd) VALUES (?, 't', 0, 1, 0.25)",
                        (step,))
    for column in ("reused_from_run", "reused_from_id"):  # make it look like a ledger from before reuse
        ledger.conn.execute(f"ALTER TABLE task_runs DROP COLUMN {column}")
    ledger.conn.close()
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    readonly = Ledger(db, readonly=True)
    assert readonly.run_cost(run_id) == 0.25  # this query uses reused_from_run
    try:
        readonly.conn.execute("UPDATE runs SET status = 'x'")
        raise AssertionError("a read-only ledger accepted a write")
    except sqlite3.OperationalError:
        pass

    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    columns = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(task_runs)")}
    assert "reused_from_run" not in columns  # the file itself was not migrated
