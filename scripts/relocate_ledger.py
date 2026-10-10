"""Point a copied ledger at the victim repo's path on this machine.

The ledger records the victim repo's absolute path in each run (`runs.repo` and `config_json.repo`).
On another machine, replays (`culprit localise/fix --replay`, `scripts/demo_replay.sh`) need that path.

    uv run python scripts/relocate_ledger.py evidence/ledger-snapshot.sqlite .culprit/ledger.sqlite ../refunddesk

Writes a new ledger (never modifies the source) with every run's repo set to the given path.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def relocate(source: Path, dest: Path, repo: Path) -> int:
    if dest.exists():
        raise SystemExit(f"{dest} already exists; move it away first (it may hold your own runs)")
    if not (repo / ".git").exists():
        raise SystemExit(f"{repo} is not a git checkout of the victim repo")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(dest) as out:
        src.backup(out)
    conn = sqlite3.connect(dest)
    rows = conn.execute("SELECT run_id, config_json FROM runs").fetchall()
    for run_id, config_json in rows:
        config = json.loads(config_json)
        config["repo"] = str(repo)
        conn.execute("UPDATE runs SET repo = ?, config_json = ? WHERE run_id = ?",
                     (str(repo), json.dumps(config, sort_keys=True), run_id))
    conn.commit()
    conn.close()
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    n = relocate(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]).resolve())
    print(f"{n} runs now point at {Path(sys.argv[3]).resolve()} → {sys.argv[2]}")
