"""scripts/demo_replay.sh: replays a recorded story with no model call, no victim run and no network."""

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import llm  # noqa: E402
from culprit.ledger import Ledger  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_replay.sh"
GUARD = ROOT / "scripts" / "no_network"


def test_the_guard_blocks_internet_access_but_not_local_sockets():
    code = (
        "import socket\n"
        "for attempt in (lambda: socket.create_connection(('127.0.0.1', 9), timeout=1),\n"
        "                lambda: socket.getaddrinfo('openrouter.ai', 443)):\n"
        "    try:\n"
        "        attempt()\n"
        "    except OSError as exc:\n"
        "        print(type(exc).__name__)\n"
        "a, b = socket.socketpair()\n"
        "a.sendall(b'ok'); print(b.recv(2).decode())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(GUARD)},
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["NetworkBlocked", "NetworkBlocked", "ok"]


@pytest.fixture()
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fixture hero story in a ledger: bisect, localise and fix, with a fake model."""
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.finished
    import culprit.fix
    import culprit.localise
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator, culprit.finished,
                culprit.localise, culprit.fix):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="multi")
    db = tmp_path / "ledger.sqlite"
    ledger = Ledger(db)
    orch = culprit.orchestrator.Orchestrator(
        ledger, culprit.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main"), log=lambda _: None)
    run_id = orch.start()
    assert orch.run(run_id).status == "found"
    return culprit, ledger, db, run_id


def replay(db: Path, run_id: str) -> subprocess.CompletedProcess:
    # Real-looking keys in the environment: the script must blank them, so nothing can be spent.
    env = {**os.environ, "CULPRIT_DB": str(db), "DEMO_PAUSE": "0", "ANTHROPIC_API_KEY": "sk-ant-not-a-key",
           "OPENROUTER_API_KEY": "sk-or-not-a-key", "NEATLOGS_API_KEY": "not-a-key"}
    env.pop("CULPRIT_STATE_DIR", None)
    return subprocess.run([str(SCRIPT), run_id], env=env, capture_output=True, text=True, timeout=600)


def fake_model(monkeypatch, replies):
    calls = []

    def complete(system, messages, max_tokens):
        calls.append(1)
        return json.dumps(replies[len(calls) - 1]), llm.Usage("fake-model", 100, 20, 0.0001)

    monkeypatch.setattr(llm, "_complete", complete)


def test_replay_tells_the_recorded_story_without_spending_or_writing(recorded, monkeypatch):
    c, ledger, db, run_id = recorded
    fake_model(monkeypatch, [{"ranking": [{"hunk": 4, "reason": "timeouts"}, {"hunk": 3, "reason": "pass rate"}]},
                             {"intended_gain": "latency", "gain_reason": "faster", "explanation": "restore",
                              "edits": [{"file": "refunddesk/agent.py", "old": "RETRY_PASS = 0.05",
                                         "new": "RETRY_PASS = 0.95"}]}])
    c.localise.localise_run(ledger, run_id, log=lambda _: None)
    assert c.fix.fix_run(ledger, run_id, log=lambda _: None).status == "verified_fix"
    ledger.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    out = replay(db, run_id)
    assert out.returncode == 0, out.stdout + out.stderr
    text = out.stdout
    assert "**Verdict: found.**" in text and "## Bisect timeline" in text and "## Intent" in text
    assert "## Diff" not in text  # the report is cut after the start of the intent
    assert "localise:h4: 1/15" in text and "→ BAD" in text and "localise:h3: 14/15" in text
    assert "responsible: hunk 3 (refunddesk/agent.py:3)" in text
    assert "fix:1: 34/36" in text and "VERIFIED" in text and "fix: verified_fix" in text
    assert "median latency per run: good 300 ms, bad 100 ms, fix 100 ms" in text
    assert "replayed from the ledger: 0 new victim runs, 0 new model calls, $0" in text
    assert "suite pinned" not in text
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before  # the real ledger is only read


def test_replay_refuses_work_the_ledger_does_not_hold(recorded):
    c, ledger, db, run_id = recorded  # bisected, but never localised
    with pytest.raises(c.finished.StageError, match="needs a hunk ranking"):
        c.localise.localise_run(ledger, run_id, log=lambda _: None, replay=True)
    assert ledger.get_artifact(run_id, "localisation") is None
    ledger.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    out = replay(db, run_id)
    assert out.returncode != 0
    assert "needs a hunk ranking (a model call), which the ledger doesn't hold" in out.stdout + out.stderr


def test_replay_never_runs_an_unrecorded_victim_batch(recorded):
    c, ledger, _, run_id = recorded
    # A ranking is recorded but no revert was ever run: replay must stop before starting any victim run.
    ledger.put_artifact(run_id, "hunk_ranking", json.dumps({"order": [3, 4, 1], "reasons": {}, "source": "llm"}))
    before = ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
    with pytest.raises(c.finished.StageError, match="needs victim runs for the reverts"):
        c.localise.localise_run(ledger, run_id, log=lambda _: None, replay=True)
    assert ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == before
    assert ledger.get_artifact(run_id, "localisation") is None
