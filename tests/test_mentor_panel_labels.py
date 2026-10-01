"""MentorChatPanel.jsx stays in step with the engine's tool list (Mentor adhoc G1).

The panel's "Checked N sources" list falls back to a raw `tool(args-json)` string for any tool
without a `TOOL_LABELS` entry; this pins that every tool in `TOOL_SCHEMAS` has one. Read out of
the JSX source (same approach as test_lift_stats.py's StepDeck.jsx check) so it tests the
labels that ship."""
import re
from pathlib import Path

from mythgauntlet.mentor.tools import TOOL_SCHEMAS

_SRC = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components"
        / "MentorChatPanel.jsx").read_text(encoding="utf-8")


def _label_keys() -> set[str]:
    block = re.search(r"const TOOL_LABELS = \{(.*?)\n\}", _SRC, re.S)
    assert block, "MentorChatPanel.jsx no longer defines a TOOL_LABELS map"
    return set(re.findall(r"^\s{2}([a-z_]+):", block.group(1), re.M))


def test_every_engine_tool_has_a_label():
    tools = {t["function"]["name"] for t in TOOL_SCHEMAS}
    missing = sorted(tools - _label_keys())
    assert not missing, f"MentorChatPanel.jsx TOOL_LABELS has no entry for: {missing}"


def test_no_label_for_a_tool_that_no_longer_exists():
    tools = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert _label_keys() <= tools


def test_the_holistic_starter_prompts_are_offered():
    block = re.search(r"const STARTER_PROMPTS = \[(.*?)\n\]", _SRC, re.S).group(1)
    assert "What does this deck do well and poorly?" in block
    assert "How could I make it faster or more resilient?" in block
