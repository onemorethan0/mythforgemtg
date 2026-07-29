"""Shell-completion script generation. Pure/offline."""

from __future__ import annotations

import pytest

from mythgauntlet import completion, nav
from mythgauntlet.cli import build_parser

COMMANDS = [(n, h) for _, cmds in nav.COMMAND_GROUPS for n, h in cmds]

ANCHORS = {
    "powershell": "Register-ArgumentCompleter",
    "bash": "complete -F _mythgauntlet_complete",
    "zsh": "compdef _mythgauntlet",
    "fish": "complete -c mythgauntlet",
}


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_render_has_anchor_and_all_commands(shell):
    script = completion.render(shell, COMMANDS)
    assert ANCHORS[shell] in script
    for name, _ in COMMANDS:
        assert name in script, f"{name} missing from {shell} completion"


def test_powershell_array_is_comma_separated():
    # regression: PowerShell array literals need commas -- @('a' 'b') is a syntax error
    script = completion.render("powershell", COMMANDS)
    assert "'analyze', 'advise'" in script


def test_unknown_shell_raises():
    with pytest.raises(ValueError, match="unsupported shell"):
        completion.render("tcsh", COMMANDS)


def test_zsh_descriptions_have_no_raw_colons():
    # a raw ':' in a zsh 'name:desc' entry would split the description
    script = completion.render("zsh", [("x", "before: after")])
    assert "'x:before - after'" in script


def test_completion_command_parses():
    args = build_parser().parse_args(["completion", "bash"])
    assert args.shell == "bash"


def test_completion_rejects_bad_shell_via_argparse():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["completion", "klingon"])
