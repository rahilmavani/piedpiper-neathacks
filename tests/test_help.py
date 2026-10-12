"""`culprit help` and bare `culprit`: the commands in the order you use them."""

import re

from typer.testing import CliRunner

from culprit.cli import GUIDE, app


def plain(text: str) -> str:
    """Help is colored when the environment asks for it (GitHub Actions does); compare the text only."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_help_and_bare_culprit_print_the_guide():
    for args in (["help"], []):
        out = CliRunner().invoke(app, args)
        assert out.exit_code == 0
        assert out.output == GUIDE
    assert GUIDE.index("culprit init") < GUIDE.index("1. culprit run") < GUIDE.index("2. culprit localise") \
        < GUIDE.index("3. culprit fix") < GUIDE.index("4. culprit report")


def test_help_for_one_command_shows_its_options():
    out = CliRunner().invoke(app, ["help", "run"])
    assert out.exit_code == 0
    assert "--good" in plain(out.output) and "--budget-usd" in plain(out.output)


def test_help_for_an_unknown_or_hidden_command_lists_the_real_ones():
    for name in ("nope", "bench"):
        out = CliRunner().invoke(app, ["help", name])
        assert out.exit_code == 2
        assert "Commands:" in out.output and "localise" in out.output and "bench" not in out.output.split("Commands:")[1]


def test_every_listed_command_exists():
    out = plain(CliRunner().invoke(app, ["--help"]).output)
    for line in GUIDE.splitlines():
        if "culprit " in line and "help <command>" not in line:
            command = line.split("culprit ", 1)[1].split()[0]
            assert command in out, command
