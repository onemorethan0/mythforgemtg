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


def _compile_top_args(**overrides):
    """Build `compile-top` args from the REAL parser, then apply overrides.

    These tests used to hand-build `argparse.Namespace(count=..., force=..., refresh_stale=...)`,
    so adding ANY new flag to the parser broke them with an AttributeError that had nothing to
    do with what they test (`--retry-quarantined` did exactly that). Going through the parser
    means a new flag arrives with its real default, and the tests keep exercising the defaults
    a user actually gets.
    """
    from mythgauntlet import cli          # imported locally, as every test here does

    args = cli.build_parser().parse_args(["compile-top", str(overrides.pop("count", 5))])
    vars(args).update(overrides)
    return args


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


def test_compile_overrides_a_self_declared_rung(make_card):
    """Rung 3 is the hand-authored tier — a compiled card may never claim it.

    The model does emit `"rung": 3` on its own, and `setdefault` used to keep it: 1,897
    files in the compiled store had claimed the authored tier by 2026-07-31, flipping in
    and out of the diff on every prompt refresh.
    """
    doc = json.loads(GOOD_JSON)
    doc["rung"] = 3
    result = compile_card(_card(make_card), lambda m: json.dumps(doc), exemplars=[])
    assert result.status == "accepted"
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
    store = tmp_path / "compiled"
    store.mkdir()
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(compiler, "compiled_dir", lambda: store)
    monkeypatch.setattr(cli, "_llm_client", lambda: _FakeClient(BAD_JSON))
    saved: list[str] = []
    monkeypatch.setattr(compiler, "save_compiled", lambda card, doc: saved.append(card.name))

    card = _card(make_card)
    # The prior must actually EXIST on disk — the keep now protects a stored CCM that
    # still passes the gates, not a bare ledger row (see the conditional-keep test below).
    (store / "insight-spell.json").write_text(json.dumps({
        "card": {"name": card.name, "mana_cost": "{2}{U}", "type_line": "Sorcery",
                 "oracle_text": card.oracle_text},
        "ccm": {**json.loads(GOOD_JSON), "rung": 2},
    }), encoding="utf-8")

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


def test_store_dir_override(monkeypatch, tmp_path):
    """MYTHGAUNTLET_STORE relocates the COMPILED store but never the authored exemplars.

    The engine ships open while the ~30k compiled semantics are withheld and versioned in a
    separate private repo (docs/ENGINE_DATA.md). This override lets the engine read and the
    compiler write that canonical copy in place rather than duplicating 130 MB beside the
    source. The authored exemplars are prompt SOURCE — they ship with the engine and must
    stay findable regardless.
    """
    from pathlib import Path

    monkeypatch.delenv("MYTHGAUNTLET_STORE", raising=False)
    default_authored = compiler.authored_dir()
    assert compiler.compiled_dir() == compiler.store_dir() / "compiled"
    assert compiler.ledger_path() == compiler.store_dir() / "ledger.json"

    monkeypatch.setenv("MYTHGAUNTLET_STORE", str(tmp_path))
    assert compiler.store_dir() == Path(tmp_path)
    assert compiler.compiled_dir() == Path(tmp_path) / "compiled"
    assert compiler.ledger_path() == Path(tmp_path) / "ledger.json"
    assert compiler.authored_dir() == default_authored, "exemplars must not follow the override"


def test_compile_top_tops_up_a_partial_chunk_with_refreshes(tmp_path, monkeypatch, make_card):
    """A short new-card pool must not hand the rest of the chunk's GPU time back.

    The refresh path used to be gated on `not targets` — all-or-nothing. On a night
    when the card universe has just grown, the new-card pool is far smaller than the
    overnight chunk size (140 vs 1,400 after the 2026-07-31 bulk unfreeze), so the
    chunk compiled 140 cards and stopped. New cards must still go FIRST, and the two
    halves must keep their own failure policy: a new card quarantines, a refresh keeps
    its prior CCM.
    """
    import argparse

    from mythgauntlet import cli

    fresh = make_card("Fresh Card", mana_cost="{U}", type_line="Sorcery",
                      oracle_text="Draw a card.", edhrec_rank=10)
    stale = make_card("Stale Card", mana_cost="{U}", type_line="Sorcery",
                      oracle_text="Draw a card.", edhrec_rank=20)

    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(compiler, "authored_names", lambda: set())
    led = Ledger(path=ledger_file)
    led.entries[compiler.normalize_name(stale.name)] = {
        "name": stale.name, "status": "accepted", "attempts": 1, "ops": ["draw"],
        "errors": [], "model": "old", "prompt_version": 1, "date": "2026-07-05",
    }
    led.save()

    db = type("_Db", (), {"_by_name": {"fresh card": fresh, "stale card": stale}})()
    monkeypatch.setattr(cli, "_load_db", lambda: db)

    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        cli, "_compile_cards",
        lambda cards, keep_on_failure=False: calls.append(
            ([c.name for c in cards], keep_on_failure)
        ) or 0,
    )

    cli._cmd_compile_top(_compile_top_args(refresh_stale=True))

    assert calls == [(["Fresh Card"], False), (["Stale Card"], True)], (
        "new cards compile first with quarantine-on-failure; the refresh tops up the "
        "chunk and keeps its prior CCM on failure"
    )


def test_refresh_does_not_keep_a_prior_that_fails_todays_gates(tmp_path, monkeypatch,
                                                               make_card):
    """The keep-on-failure guard must not preserve a CCM the current gates reject.

    Keeping a prior assumes the prior is correct. When a gate is newly ADDED that stops
    being true: prompt v10's trigger-event check found 1,400 stored CCMs whose trigger
    event the oracle text doesn't support. Keeping those means the engine goes on
    executing an ability the card does not have, which is worse than having no semantics
    at all — rung-1 heuristics under-count honestly.
    """
    from mythgauntlet import cli

    ledger_file = tmp_path / "ledger.json"
    store = tmp_path / "compiled"
    store.mkdir()
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(compiler, "compiled_dir", lambda: store)
    monkeypatch.setattr(cli, "_llm_client", lambda: _FakeClient(BAD_JSON))

    # A stored CCM with Smaug's exact defect: noncombat damage modelled as combat damage.
    card = make_card("Smaug", mana_cost="{5}{B}{R}", type_line="Legendary Creature — Dragon",
                     oracle_text="Whenever Smaug is dealt noncombat damage, "
                                 "create that many Treasure tokens.")
    (store / "smaug.json").write_text(json.dumps({
        "card": {"name": "Smaug", "mana_cost": "{5}{B}{R}",
                 "type_line": "Legendary Creature — Dragon",
                 "oracle_text": card.oracle_text},
        "ccm": {"name": "Smaug", "ccm_version": 1, "cost": {"mana": "{5}{B}{R}"},
                "types": ["creature"], "rung": 2,
                "abilities": [{"kind": "triggered",
                               "trigger": {"event": "combat_damage_to_player"},
                               "effects": [{"op": "create_token", "count": 1, "power": 0,
                                            "toughness": 0, "types": ["treasure"]}]}]},
    }), encoding="utf-8")

    assert compiler.stored_ccm_passes_gates(card) is False

    prior = Ledger(path=ledger_file)
    prior.entries[compiler.normalize_name(card.name)] = {
        "name": card.name, "status": "accepted", "attempts": 1, "ops": ["create_token"],
        "errors": [], "model": "old", "prompt_version": 9, "date": "2026-07-31",
    }
    prior.save()

    cli._compile_cards([card], keep_on_failure=True)
    assert Ledger(path=ledger_file).get(card.name)["status"] == "quarantined", (
        "a prior CCM that fails today's gates must not be retained"
    )


def test_refresh_still_keeps_a_prior_that_remains_valid(tmp_path, monkeypatch, make_card):
    """The original guard must survive: a VALID prior is still protected from a bad roll."""
    from mythgauntlet import cli

    ledger_file = tmp_path / "ledger.json"
    store = tmp_path / "compiled"
    store.mkdir()
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(compiler, "compiled_dir", lambda: store)
    monkeypatch.setattr(cli, "_llm_client", lambda: _FakeClient(BAD_JSON))

    card = _card(make_card)
    (store / "insight-spell.json").write_text(json.dumps({
        "card": {"name": card.name, "mana_cost": "{2}{U}", "type_line": "Sorcery",
                 "oracle_text": card.oracle_text},
        "ccm": {**json.loads(GOOD_JSON), "rung": 2},
    }), encoding="utf-8")
    assert compiler.stored_ccm_passes_gates(card) is True

    prior = Ledger(path=ledger_file)
    prior.entries[compiler.normalize_name(card.name)] = {
        "name": card.name, "status": "accepted", "attempts": 1, "ops": ["draw"],
        "errors": [], "model": "old", "prompt_version": 5, "date": "2026-07-05",
    }
    prior.save()

    cli._compile_cards([card], keep_on_failure=True)
    entry = Ledger(path=ledger_file).get(card.name)
    assert entry["status"] == "accepted" and entry["prompt_version"] == 5


def test_ledger_save_is_atomic(tmp_path, monkeypatch, make_card):
    """A reader must never see a half-written ledger.

    save() is called after EVERY card, so a ~6 MB 31k-entry file is rewritten roughly
    every three seconds for hours. Truncating the real file in place meant a concurrent
    reader could hit a fragment — observed 2026-08-01 as a JSONDecodeError while the
    nightly was mid-chunk — and a crash mid-write would destroy the index built over
    hundreds of GPU-hours. save_compiled was already atomic; the ledger was not.
    """
    ledger_file = tmp_path / "ledger.json"
    ledger = Ledger(path=ledger_file)
    result = compile_card(_card(make_card), lambda m: GOOD_JSON, exemplars=[])
    ledger.record(result, model="test-model")
    ledger.save()

    original = ledger_file.read_text(encoding="utf-8")

    # Simulate a crash PART-WAY through the next write: json.dump has emitted some bytes
    # into the temp file when the process dies.
    real_dump = json.dump

    def die_midway(obj, fh, **kwargs):
        fh.write('{"entries": {"half')
        raise KeyboardInterrupt("power cut")

    monkeypatch.setattr(json, "dump", die_midway)
    ledger.entries["another card"] = {"name": "Another Card", "status": "accepted"}
    try:
        ledger.save()
    except KeyboardInterrupt:
        pass
    monkeypatch.setattr(json, "dump", real_dump)

    # The real ledger is untouched and still parses — the damage is confined to the temp.
    assert ledger_file.read_text(encoding="utf-8") == original
    assert json.loads(ledger_file.read_text(encoding="utf-8"))["entries"]
    assert Ledger(path=ledger_file).get("insight spell")["status"] == "accepted"


def test_failed_refresh_is_not_retried_at_the_same_prompt_version(tmp_path, monkeypatch,
                                                                  make_card):
    """A refresh that fails must step aside, or it blocks the queue forever.

    The keep-on-failure guard restored the prior ledger entry VERBATIM, which left the
    card looking exactly like un-attempted work: accepted, below the current prompt
    version — the query --refresh-stale selects on. That selection sorts by
    (prompt_version, edhrec_rank) and is deterministic, so the same permanently-failing
    cards won the same top slots in every chunk of the night. On 2026-08-04 that was 384
    cards failing in all four chunks (Flusterstorm was card 1/1400 four times): 1,536 of
    5,600 refresh attempts, ~27% of the run's GPU budget, spent re-failing while the tail
    of the stale pool was never reached.

    The card stays accepted at its old version — it is still stale and still wants a
    refresh — but not at THIS prompt version again. A new prompt revision clears it.
    """
    import argparse

    from mythgauntlet import cli

    ledger_file = tmp_path / "ledger.json"
    store = tmp_path / "compiled"
    store.mkdir()
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(compiler, "compiled_dir", lambda: store)
    monkeypatch.setattr(compiler, "authored_names", lambda: set())
    monkeypatch.setattr(cli, "_llm_client", lambda: _FakeClient(BAD_JSON))
    monkeypatch.setattr(compiler, "save_compiled", lambda card, doc: None)

    # Needs a real edhrec_rank: _cmd_compile_top ranks on it and drops unranked cards
    # before any of the selection logic below runs.
    card = make_card("Insight Spell", mana_cost="{2}{U}", type_line="Sorcery",
                     oracle_text="Draw two cards.", edhrec_rank=10)
    (store / "insight-spell.json").write_text(json.dumps({
        "card": {"name": card.name, "mana_cost": "{2}{U}", "type_line": "Sorcery",
                 "oracle_text": card.oracle_text},
        "ccm": {**json.loads(GOOD_JSON), "rung": 2},
    }), encoding="utf-8")

    led = Ledger(path=ledger_file)
    led.entries[compiler.normalize_name(card.name)] = {
        "name": card.name, "status": "accepted", "attempts": 1, "ops": ["draw"],
        "errors": [], "model": "old", "prompt_version": 5, "date": "2026-07-05",
    }
    led.save()

    cli._compile_cards([card], keep_on_failure=True)

    entry = Ledger(path=ledger_file).get(card.name)
    assert entry["status"] == "accepted", "still no demotion"
    assert entry["prompt_version"] == 5, "still stale — the working CCM is v5"
    assert entry["refresh_failed_at"] == compiler.PROMPT_VERSION, (
        "the failed attempt must leave a trace scoped to the prompt version that failed"
    )
    assert entry["refresh_errors"], (
        "the trace must carry WHY it failed — a bare marker leaves the blocked pile "
        "undiagnosable without re-running the GPU"
    )
    assert entry["errors"] == [], (
        "the retained entry is still an ACCEPTED v5 compile; its own error list must not "
        "pick up the failed refresh's complaints"
    )

    # The selector now skips it, so the chunk's GPU time goes to cards further down the
    # stale pool instead of re-failing on the same head-of-line card.
    db = type("_Db", (), {"_by_name": {"insight spell": card}})()
    monkeypatch.setattr(cli, "_load_db", lambda: db)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        cli, "_compile_cards",
        lambda cards, keep_on_failure=False: calls.append([c.name for c in cards]) or 0,
    )

    cli._cmd_compile_top(_compile_top_args(refresh_stale=True))
    assert calls == [], "a card that already failed at this prompt version is not re-picked"

    # --force is the escape hatch: it re-attempts a blocked card, and exactly ONCE —
    # forcing pulls already-accepted cards into `targets`, and every one of those is
    # stale by definition, so the two pools would otherwise both claim it.
    cli._cmd_compile_top(_compile_top_args(force=True, refresh_stale=True))
    assert calls == [[card.name]], "--force retries a blocked card, and does not double it"


def test_failed_refresh_is_retried_once_the_prompt_moves(tmp_path, monkeypatch, make_card):
    """The block is scoped to one prompt version, not permanent.

    A card that can't be modelled under v10 may well compile under v11 — that is the
    whole reason the prompt keeps moving. If the marker outlived its version it would
    quietly retire cards from the corpus forever.
    """
    import argparse

    from mythgauntlet import cli

    card = make_card("Stale Card", mana_cost="{U}", type_line="Sorcery",
                     oracle_text="Draw a card.", edhrec_rank=20)
    ledger_file = tmp_path / "ledger.json"
    monkeypatch.setattr(compiler, "ledger_path", lambda: ledger_file)
    monkeypatch.setattr(compiler, "authored_names", lambda: set())
    led = Ledger(path=ledger_file)
    led.entries[compiler.normalize_name(card.name)] = {
        "name": card.name, "status": "accepted", "attempts": 1, "ops": ["draw"],
        "errors": [], "model": "old", "prompt_version": 5, "date": "2026-07-05",
        # blocked under a PAST prompt version, not the current one
        "refresh_failed_at": compiler.PROMPT_VERSION - 1,
    }
    led.save()

    db = type("_Db", (), {"_by_name": {"stale card": card}})()
    monkeypatch.setattr(cli, "_load_db", lambda: db)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        cli, "_compile_cards",
        lambda cards, keep_on_failure=False: calls.append([c.name for c in cards]) or 0,
    )

    cli._cmd_compile_top(_compile_top_args(refresh_stale=True))
    assert calls == [[card.name]], "a stale marker from an older prompt must not block"
