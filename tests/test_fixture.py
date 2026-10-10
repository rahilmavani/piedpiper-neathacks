"""The fixture victim must stay installable after the pin revert, whatever else lands on that commit."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402


def show(repo: Path, rev: str, path: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{rev}:{path}"], text=True)


def nth(repo: Path, n: int) -> str:
    """The n-th commit after good-v1.0 (1-based)."""
    revs = subprocess.check_output(
        ["git", "-C", str(repo), "rev-list", "--reverse", "good-v1.0..main"], text=True
    ).split()
    return revs[n - 1]


def locked_install_ok(repo: Path, rev: str, tmp_path: Path) -> bool:
    wt = tmp_path / f"wt-{rev[:8]}"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt), rev], check=True)
    return subprocess.run(["uv", "sync", "--locked"], cwd=wt, capture_output=True).returncode == 0


@pytest.mark.parametrize(
    "kwargs, agent_at_8",
    [
        ({"breaks_at": 10, "noisy_from": 8}, "RETRY_PASS = 0.75"),  # the docstring example
        ({"breaks_at": 8, "noisy_from": None}, "RETRY_PASS = 0.05"),
    ],
)
def test_change_on_the_revert_commit_keeps_the_revert(tmp_path: Path, kwargs, agent_at_8):
    repo = build(tmp_path / "victim", commits=14, unbuildable_at=7, **kwargs)

    assert "requests==99.99.99" in show(repo, nth(repo, 7), "pyproject.toml")
    assert "requests" not in show(repo, nth(repo, 8), "pyproject.toml")
    assert "requests" not in show(repo, "main", "pyproject.toml")
    assert agent_at_8 in show(repo, nth(repo, 8), "refunddesk/agent.py")

    assert not locked_install_ok(repo, nth(repo, 7), tmp_path)
    assert locked_install_ok(repo, nth(repo, 8), tmp_path)
    assert locked_install_ok(repo, "main", tmp_path)
