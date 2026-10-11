"""Point a copied ledger at the victim repos' paths on this machine.

The ledger records each run's victim repo as an absolute path (`runs.repo` and `config_json.repo`).
On another machine, replays (`culprit localise/fix --replay`, `scripts/demo_replay.sh`) need those
paths. Runs are matched to a new path by victim: RefundDesk runs (any repo whose folder name
contains "refunddesk") go to the first path; other victims by folder name, e.g. opsdesk=PATH.

    uv run python scripts/relocate_ledger.py evidence/ledger-snapshot.sqlite .culprit/ledger.sqlite \
        ../piedpiper-neathacks-refunddesk [opsdesk=../opsdesk clinicdesk=../clinicdesk]

Writes a new ledger (never modifies the source). Runs of a victim you don't map keep their old path.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def _check(repo: Path) -> Path:
    if not (repo / ".git").exists():
        raise SystemExit(f"{repo} is not a git checkout of a victim repo")
    return repo


def target(old: str, refunddesk: Path, others: dict[str, Path]) -> Path | None:
    name = Path(old).name
    if name in others:
        return others[name]
    return refunddesk if "refunddesk" in name else None


def relocate(source: Path, dest: Path, refunddesk: Path, others: dict[str, Path] | None = None) -> dict[str, int]:
    others = {k: _check(v) for k, v in (others or {}).items()}
    _check(refunddesk)
    if dest.exists():
        raise SystemExit(f"{dest} already exists; move it away first (it may hold your own runs)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(dest) as out:
        src.backup(out)
    conn = sqlite3.connect(dest)
    moved: dict[str, int] = {}
    for run_id, repo, config_json in conn.execute("SELECT run_id, repo, config_json FROM runs").fetchall():
        new = target(repo, refunddesk, others)
        if new is None:
            moved["unchanged"] = moved.get("unchanged", 0) + 1
            continue
        config = json.loads(config_json)
        config["repo"] = str(new)
        conn.execute("UPDATE runs SET repo = ?, config_json = ? WHERE run_id = ?",
                     (str(new), json.dumps(config, sort_keys=True), run_id))
        moved[str(new)] = moved.get(str(new), 0) + 1
    conn.commit()
    conn.close()
    return moved


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    extra = {}
    for arg in sys.argv[4:]:
        name, sep, path = arg.partition("=")
        if not sep:
            raise SystemExit(f"expected name=path, got {arg!r}\n\n{__doc__}")
        extra[name] = Path(path).resolve()
    result = relocate(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]).resolve(), extra)
    for where, n in result.items():
        print(f"{n} runs → {where}")
    print(f"written to {sys.argv[2]}")
