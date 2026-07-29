"""Compiler pipeline with a fake LLM (offline)."""

import json

from mythgauntlet.semantics import compiler
from mythgauntlet.semantics.compiler import (
    Ledger,
    build_messages,
    compile_card,
    extract_json,
)

GOOD_JSON = json.dumps({
    "name": "Insight Spell",
    "ccm_version": 1,
    "cost": {"mana": "{2}{U}"},
    "types": ["sorcery"],
    "abilities": [{"kind": "spell_effect", "effects": [{"op": "draw", "count": 2}]}],
})

# Fails gate 3 (oracle says "Draw two cards" but the CCM has no draw effect — the
# tolerated unknown op does not satisfy it), forcing a feedback-driven retry.
BAD_JSON = json.dumps({
    "name": "Insight Spell",
    "ccm_version": 1,
    "cost": {"mana": "{2}{U}"},
    "types": ["sorcery"],
    "abilities": [{"kind": "spell_effect", "effects": [{"op": "hallucinate"}]}],
})


def _card(make_card):
    return make_card(
        "Insight Spell", mana_cost="{2}{U}", type_line="Sorcery", oracle_text="Draw two cards."
    )


def test_extract_json_tolerates_think_tags_and_fences():
    raw = "<think>\nreasoning...\n</think>\n```json\n" + GOOD_JSON + "\n```\ntrailing"
    doc = extract_json(raw)
    assert doc["name"] == "Insight Spell"


def test_extract_json_repairs_trailing_commas():
    """The #1 remaining LLM JSON slip — a trailing comma before a close brace."""
    broken = (
        '{"name": "Bear", "ccm_version": 1, "cost": {"mana": "{G}",}, '
        '"types": ["creature",], "abilities": [{"kind": "spell_effect", '
        '"effects": [{"op": "draw", "count": 1,},],},]}'
    )
    doc = extract_json(broken)
    assert doc["name"] == "Bear"
    assert doc["abilities"][0]["effects"][0]["op"] == "draw"


def test_extract_json_deep_repairs_missing_commas():
    """v8: the ~276 quarantines that were pure parse failures (missing delimiters)."""
    broken = (
        '{"name": "Insight Spell"\n "ccm_version": 1,\n "cost": {"mana": "{2}{U}"},\n'
        ' "types": ["sorcery"]\n "abilities": [{"kind": "spell_effect", '
        '"effects": [{"op": "draw" "count": 2}]}]}'
    )  # missing commas after "name", "types", and between op/count
    doc = extract_json(broken)
    assert doc.pop("_json_repaired") is True  # marked so provenance can record it
    assert doc["name"] == "Insight Spell"
    assert doc["abilities"][0]["effects"][0] == {"op": "draw", "count": 2}


def test_compile_stamps_repaired_provenance(make_card):
    """A deep-repaired doc still faces the gates; acceptance records the repair."""
    broken = GOOD_JSON.replace('"ccm_version": 1,', '"ccm_version": 1')  # kill one comma
    result = compile_card(_card(make_card), lambda m: broken, exemplars=[])
    assert result.status == "accepted"
    assert result.doc["provenance"]["json_repaired"] is True
    assert "_json_repaired" not in result.doc  # internal marker never persists


def test_clean_parse_has_no_repair_stamp(make_card):
    result = compile_card(_card(make_card), lambda m: GOOD_JSON, exemplars=[])
    assert result.status == "accepted"
    assert "json_repaired" not in result.doc["provenance"]


def test_compile_accepts_valid_response(make_card):
    result = compile_card(_card(make_card), lambda messages: GOOD_JSON, exemplars=[])
    assert result.status == "accepted"
    assert result.attempts == 1
    assert result.ops == ["draw"]
    assert result.doc["provenance"]["source"] == "llm_compiled"
    assert result.doc["rung"] == 2


def test_compile_retries_with_feedback_then_accepts(make_card):
    calls = []

    def fake(messages):
        calls.append(messages)
        return BAD_JSON if len(calls) == 1 else GOOD_JSON

    result = compile_card(_card(make_card), fake, exemplars=[])
    assert result.status == "accepted"
    assert result.attempts == 2
    # retry prompt must carry the gate errors back to the model
    assert "draw" in calls[1][-1]["content"] and "fix them" in calls[1][-1]["content"]


def test_compile_quarantines_after_max_attempts(make_card):
    result = compile_card(_card(make_card), lambda m: BAD_JSON, exemplars=[])
    assert result.status == "quarantined"
    assert result.errors


def test_compile_handles_non_json_response(make_card):
    result = compile_card(_card(make_card), lambda m: "I cannot help with that.", exemplars=[])
    assert result.status == "quarantined"
    assert any("response error" in e for e in result.errors)


def test_build_messages_fewshot_structure(make_card):
    messages = build_messages(_card(make_card), [("CARD BLOCK", "{}")], feedback=None)
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "CARD BLOCK"}
    assert messages[2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"
    assert "Insight Spell" in messages[-1]["content"]


def test_ledger_roundtrip(tmp_path, make_card):
    ledger = Ledger(path=tmp_path / "ledger.json")
    result = compile_card(_card(make_card), lambda m: GOOD_JSON, exemplars=[])
    ledger.record(result, model="test-model")
    ledger.save()
    reloaded = Ledger(path=tmp_path / "ledger.json")
    entry = reloaded.get("insight spell")
    assert entry is not None
    assert entry["status"] == "accepted"
    assert reloaded.stats() == {"accepted": 1}


def test_refresh_keeps_prior_ccm_when_recompile_fails(tmp_path, monkeypatch, make_card):
    """A stale-CCM refresh must never be a downgrade.

    compile-top --refresh-stale recompiles cards that are ALREADY accepted, just at an
    older prompt version. _compile_cards records every result unconditionally, so
    without the keep_on_failure guard a bad roll would flip a working card to
    quarantined while save_compiled was skipped — leaving the ledger and the on-disk
    CCM store disagreeing about the same card.
    """
    from mythgauntlet import cli

    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(cli, "_llm_client", lambda: _FakeClient(BAD_JSON))
    saved: list[str] = []
    monkeypatch.setattr(compiler, "save_compiled", lambda card, doc: saved.append(card.name))

    card = _card(make_card)
    prior = Ledger(path=ledger_file)
    prior.entries[compiler.normalize_name(card.name)] = {
        "name": card.name, "status": "accepted", "attempts": 1, "ops": ["draw"],
        "errors": [], "model": "old-model", "prompt_version": 5, "date": "2026-07-05",
    }
    prior.save()

    cli._compile_cards([card], keep_on_failure=True)

    entry = Ledger(path=ledger_file).get(card.name)
    assert entry["status"] == "accepted", "a failed refresh must not demote the card"
    assert entry["prompt_version"] == 5, "the prior entry is kept verbatim, not restamped"
    assert saved == [], "no CCM should be written when the refresh fails its gates"

    # Same failure WITHOUT the guard is a demotion — that's the behaviour being fenced off.
    cli._compile_cards([card], keep_on_failure=False)
    assert Ledger(path=ledger_file).get(card.name)["status"] == "quarantined"


class _FakeClient:
    """Stands in for LlamaSwapClient: always returns the same canned completion."""

    model = "fake-model"

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, messages) -> str:  # noqa: ARG002 - signature parity
        return self._response


def test_load_exemplars_produces_pairs():
    pairs = compiler.load_exemplars()
    assert len(pairs) >= 10
    block, ccm_json = pairs[0]
    assert "NAME:" in block and "ORACLE:" in block
    assert json.loads(ccm_json)["ccm_version"] == 1
