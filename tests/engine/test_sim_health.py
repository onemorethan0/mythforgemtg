"""The simulator-fidelity gauge (`mythgauntlet sim-health`, sim/health.py).

Offline and synthetic — envelopes are built inline, so this runs with no compiled store,
which is CI's actual state.

The load-bearing test here is `test_dispatched_ops_reads_the_real_dispatch`. Everything
this module reports is derived from an AST walk of two live functions; if that walk ever
returns EMPTY (a refactor to a dict dispatch, a match statement, a renamed `op` local)
the gauge does not crash — it silently reports 100% of the store as inert and argues for
work that is already done. That is a worse failure than not having the gauge, so it is
pinned against ops the dispatch demonstrably handles rather than against a count.
"""

from __future__ import annotations

from mythgauntlet.semantics import ccm
from mythgauntlet.sim import health


def _env(name: str, abilities: list[dict]) -> dict:
    return {"card": {"name": name}, "ccm": {"name": name, "abilities": abilities}}


def _spell(*effects: dict) -> dict:
    return {"kind": "spell_effect", "effects": list(effects)}


def test_dispatched_ops_reads_the_real_dispatch():
    """An empty extraction is the silent-failure mode; assert it found real branches."""
    vocab = health.executed_ops()

    # `draw` is handled by BOTH paths and has been since the interpreter existed.
    assert "draw" in vocab["resolved"]
    assert "draw" in vocab["activated"]
    # `op in ("destroy", "exile")` — the tuple-membership branch shape, not just `==`.
    assert {"destroy", "exile"} <= vocab["resolved"]
    # The activated flattening is genuinely NARROWER than the interpreter. If these ever
    # match, one of the two paths changed and the split this module reports is stale.
    assert vocab["activated"] < vocab["resolved"]
    # Every extracted op must be a real vocabulary entry — a walk that started picking up
    # unrelated string literals would inflate "executed" and hide loss.
    assert vocab["resolved"] <= frozenset(ccm.OP_SPECS)


def test_executed_effect_counts_as_executed():
    r = health.analyze_store([_env("Divination", [_spell({"op": "draw", "count": 2})])])
    assert r["executed_effects"] == 1
    assert r["inert_effects"] == 0
    assert r["partial_effects"] == 0
    assert r["executed_share"] == 1.0
    assert r["executed_share_ceiling"] == 1.0
    assert r["cards_fully_executed"] == 1
    assert r["cards_fully_inert"] == 0
    assert r["inert_ops"] == []


def test_a_guarded_op_is_counted_as_neither_executed_nor_inert():
    """The gauge must not flatter itself — this is why the headline is a range.

    `pump`'s branch exists but acts only on a self-target with literal amounts, so a
    chosen-target pump reaches a branch that declines it. Counting that as "executed"
    is how the first version of this module reported 49.9% while the pump dispatch was
    actually firing on ~10% of pump effects.
    """
    r = health.analyze_store([_env("Giant Growth", [_spell(
        {"op": "pump", "power": 3, "toughness": 3,
         "target": {"type": "creature", "count": 1}})])])
    assert r["executed_effects"] == 0      # not claimed as done
    assert r["inert_effects"] == 0         # nor claimed as untouched
    assert r["partial_effects"] == 1
    assert r["executed_share"] == 0.0      # floor
    assert r["executed_share_ceiling"] == 1.0  # ceiling
    (row,) = r["partial_ops"]
    assert row["op"] == "pump"
    assert row["examples"] == ["Giant Growth"]
    assert r["inert_ops"] == []


def test_an_op_handled_by_another_subsystem_is_not_called_a_gap():
    """`counter_spell` has no dispatch branch and is NOT inert — the counter-war is
    resolved via profile._has_counter_spell feeding game.py's reactive window.

    The dispatch-only version of this gauge reported all 484 of its cards as a simulator
    gap, which would have sent a session to reimplement working code. "Inert" has to mean
    no consumer ANYWHERE, not absent from one if/elif chain.
    """
    r = health.analyze_store([_env("Counterspell", [_spell({"op": "counter_spell"})])])
    assert r["elsewhere_effects"] == 1
    assert r["inert_effects"] == 0
    assert r["executed_effects"] == 0
    (row,) = r["elsewhere_ops"]
    assert row["op"] == "counter_spell"
    assert "profile._has_counter_spell" in row["consumers"]
    assert r["inert_ops"] == []


def test_consumer_scan_reads_the_inline_get_op_spelling():
    """profile.py tests `effect.get("op") == ...` inline as well as via an `op` local.

    Reading only the local missed _has_counter_spell — i.e. missed precisely the consumer
    whose absence made the gauge accuse a working subsystem.
    """
    consumers = health.op_consumers()
    assert "profile._has_counter_spell" in consumers.get("counter_spell", [])
    assert "tier2._apply_resolved" in consumers.get("draw", [])


def test_the_guard_detector_finds_the_known_guarded_branches():
    """Pinned against branches whose scope is documented in tier2 itself.

    If a future session widens one of these to handle every case, this fails and wants
    the op moved to the unguarded list — which is the point: a scope change should have
    to be acknowledged, not silently re-reported.
    """
    guarded = health.analyze_store([])["guarded_ops"]["resolved"]
    # Self-target only / haste only / self-target-and-literal only.
    assert {"add_counter", "grant_ability", "pump"} <= set(guarded)
    # `draw` handles every `who` value it can receive; it must NOT read as guarded.
    assert "draw" not in guarded


# A vocabulary op the simulator still has no branch for. NOT `pump`: these tests were
# written against pump the hour before it was dispatched, and all three broke the moment
# it shipped — which is the anti-drift design working (the gauge re-read the source and
# stopped reporting a closed gap), but it means a fixture op has to be one that is still
# open. If `return_to_hand` is ever implemented, these fail loudly and want re-pointing,
# rather than silently asserting nothing.
STILL_INERT = "return_to_hand"


def test_the_fixture_op_is_actually_still_inert():
    """Guards the three tests below from quietly becoming vacuous."""
    vocab = health.executed_ops()
    assert STILL_INERT in ccm.OP_SPECS
    assert STILL_INERT not in vocab["resolved"]
    assert STILL_INERT not in vocab["activated"]


def test_inert_vocabulary_op_is_reported_against_the_simulator():
    r = health.analyze_store([_env("Boomerang", [_spell({"op": STILL_INERT})])])
    assert r["executed_effects"] == 0
    assert r["cards_fully_inert"] == 1
    (row,) = r["inert_ops"]
    assert row["op"] == STILL_INERT
    assert row["cards"] == 1
    assert row["in_vocabulary"] is True
    assert row["examples"] == ["Boomerang"]
    assert r["unknown_ops"] == []


def test_unknown_op_is_reported_separately_from_an_inert_one():
    """Two different defects: a simulator gap vs a vocabulary gap. Never one bucket."""
    r = health.analyze_store([
        _env("A", [_spell({"op": STILL_INERT})]),
        _env("B", [_spell({"op": "regenerate"})]),
    ])
    assert [row["op"] for row in r["inert_ops"]] == [STILL_INERT]
    assert [row["op"] for row in r["unknown_ops"]] == ["regenerate"]
    assert r["unknown_ops"][0]["in_vocabulary"] is False


def test_a_card_counts_once_per_op_however_many_times_it_prints_it():
    """Ranking is by CARDS AFFECTED — one card with three of an op is not three cards."""
    r = health.analyze_store([
        _env("Triple", [_spell(
            {"op": STILL_INERT}, {"op": STILL_INERT}, {"op": STILL_INERT}
        )]),
    ])
    (row,) = r["inert_ops"]
    assert row["cards"] == 1
    assert row["effects"] == 3


def test_the_same_op_is_executed_or_inert_depending_on_the_ability_kind():
    """The two paths have different vocabularies, so one printed effect has two fates.

    `add_counter` is dispatched by the interpreter and unknown to the activated
    flattening. Collapsing the two vocabularies into one would erase this, and it is a
    real source of rating error, not a reporting detail.
    """
    resolved = _env("ETB", [{"kind": "etb", "effects": [{"op": "add_counter",
                                                         "counter_type": "+1/+1"}]}])
    activated = _env("Outlet", [{"kind": "activated", "cost": {"mana": "{2}"},
                                 "effects": [{"op": "add_counter",
                                              "counter_type": "+1/+1"}]}])
    assert health.analyze_store([resolved])["inert_effects"] == 0
    assert health.analyze_store([activated])["inert_effects"] == 1


def test_activated_survival_applies_the_cost_gates():
    """A dropped ability is loss even when every one of its ops IS dispatched."""
    def one(cost: dict) -> dict:
        return _env("X", [{"kind": "activated", "cost": cost,
                           "effects": [{"op": "draw", "count": 1}]}])

    assert health.analyze_store([one({"mana": "{2}"})])["activated_kept"] == 1
    assert health.analyze_store([one({"tap": True})])["activated_kept"] == 1
    # Costs the engine cannot pay — reading past them makes a free repeatable outlet.
    assert health.analyze_store([one({"mana": "{2}", "pay_life": 3})])["activated_kept"] == 0
    assert health.analyze_store([one({"mana": "{2}", "other": "discard a card"})])["activated_kept"] == 0
    assert health.analyze_store([one({"sacrifice_self": True})])["activated_kept"] == 0
    # Nothing bounds it at all -> skipped rather than looped.
    assert health.analyze_store([one({})])["activated_kept"] == 0


def test_empty_store_reports_zero_without_dividing_by_it():
    r = health.analyze_store([])
    assert r["cards_scanned"] == 0
    assert r["total_effects"] == 0
    assert r["executed_share"] == 0.0
    assert r["activated_share"] == 0.0
    assert r["inert_ops"] == []


def test_malformed_envelopes_are_skipped_not_raised():
    """The store is 31k files of LLM output; one bad shape must not kill the gauge."""
    r = health.analyze_store([
        None,
        {"card": {"name": "No ccm"}},
        {"ccm": {"abilities": "not a list"}},
        {"ccm": {"abilities": [{"effects": [None, "nope"]}]}},
        _env("Real", [_spell({"op": "draw", "count": 1})]),
    ])
    assert r["cards_scanned"] == 3  # the two with a dict `ccm`, plus Real
    assert r["executed_effects"] == 1


def test_a_null_op_is_reported_rather_than_silently_dropped():
    """181 real stored cards carry an effect with no `op` at all; it must be visible."""
    r = health.analyze_store([_env("Nameless", [_spell({"count": 1})])])
    assert [row["op"] for row in r["unknown_ops"]] == ["None"]
