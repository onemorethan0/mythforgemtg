"""Shell completion script generation (dependency-free).

`mythgauntlet completion <shell>` prints a script the user sources from their shell
profile. Command names are passed in from the live parser (see cli._cmd_completion) so the
completions can never go stale relative to the actual commands. Output is ASCII-only.

Supported shells: powershell (primary on this Windows machine), bash, zsh, fish.
"""

from __future__ import annotations

SHELLS = ("powershell", "bash", "zsh", "fish")

# Global options accepted before the subcommand; offered when the current word starts "-".
GLOBAL_FLAGS = ("--plain", "--no-color", "--version", "--help")


def _clean_desc(text: str) -> str:
    """Neutralize characters that would break a shell completion description."""
    return text.replace("'", "").replace(":", " -").replace('"', "")


def render(shell: str, commands: list[tuple[str, str]]) -> str:
    """Return a completion script for `shell`. `commands` is [(name, description)]."""
    if shell == "powershell":
        return _powershell(commands)
    if shell == "bash":
        return _bash(commands)
    if shell == "zsh":
        return _zsh(commands)
    if shell == "fish":
        return _fish(commands)
    raise ValueError(f"unsupported shell '{shell}'; choose one of: {', '.join(SHELLS)}")


def _powershell(commands: list[tuple[str, str]]) -> str:
    names = ", ".join(f"'{name}'" for name, _ in commands)
    flags = ", ".join(f"'{f}'" for f in GLOBAL_FLAGS)
    return f"""\
# mythgauntlet PowerShell completion.
# Add to your profile (find it with $PROFILE):
#   mythgauntlet completion powershell | Out-String | Invoke-Expression
Register-ArgumentCompleter -Native -CommandName @('mythgauntlet','mythgauntlet.exe') -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $cmds = @({names})
    $flags = @({flags})
    if ($wordToComplete -like '-*') {{
        $flags | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
        return
    }}
    $elems = @($commandAst.CommandElements | Select-Object -Skip 1 | ForEach-Object {{ "$_" }})
    $hasCmd = $false
    foreach ($e in $elems) {{ if ($cmds -contains $e) {{ $hasCmd = $true; break }} }}
    if (-not $hasCmd) {{
        $cmds | Where-Object {{ $_ -like "$wordToComplete*" }} | Sort-Object | ForEach-Object {{
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }}
    }}
}}
"""


def _bash(commands: list[tuple[str, str]]) -> str:
    names = " ".join(name for name, _ in commands)
    flags = " ".join(GLOBAL_FLAGS)
    return f"""\
# mythgauntlet bash completion.
# Add to ~/.bashrc:  eval "$(mythgauntlet completion bash)"
_mythgauntlet_complete() {{
    local cur cmds flags i has
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    cmds="{names}"
    flags="{flags}"
    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return
    fi
    has=0
    for ((i=1; i<COMP_CWORD; i++)); do
        case " $cmds " in *" ${{COMP_WORDS[i]}} "*) has=1;; esac
    done
    if [ $has -eq 0 ]; then
        COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
    else
        COMPREPLY=( $(compgen -f -- "$cur") )
    fi
}}
complete -F _mythgauntlet_complete mythgauntlet
"""


def _zsh(commands: list[tuple[str, str]]) -> str:
    entries = "\n".join(f"        '{name}:{_clean_desc(desc)}'" for name, desc in commands)
    return f"""\
#compdef mythgauntlet
# mythgauntlet zsh completion.
# Add to ~/.zshrc:  eval "$(mythgauntlet completion zsh)"
_mythgauntlet() {{
    local -a cmds
    cmds=(
{entries}
    )
    _arguments '1: :->cmd' '*: :_files'
    case $state in
        cmd) _describe 'mythgauntlet command' cmds;;
    esac
}}
compdef _mythgauntlet mythgauntlet
"""


def _fish(commands: list[tuple[str, str]]) -> str:
    lines = [
        "# mythgauntlet fish completion.",
        "# Save to ~/.config/fish/completions/mythgauntlet.fish, or:",
        "#   mythgauntlet completion fish | source",
        "complete -c mythgauntlet -f",
    ]
    for name, desc in commands:
        lines.append(
            f"complete -c mythgauntlet -n '__fish_use_subcommand' "
            f"-a '{name}' -d '{_clean_desc(desc)}'"
        )
    for flag in GLOBAL_FLAGS:
        if flag.startswith("--"):
            lines.append(f"complete -c mythgauntlet -l {flag[2:]}")
    return "\n".join(lines) + "\n"
