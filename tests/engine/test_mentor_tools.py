"""mentor.tools -- offline where possible (no network, uses `empty_store` per
conftest's own documented reason: a bare SemanticsStore() reads a real ~31k-file corpus
on a dev machine and tests the wrong thing). assess_card still runs a real simulation."""

from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.mentor.tools import (
    MentorContext, ToolResult, call_tool, extract_numbers,
    _numbers_in, _rule_numbers_in, _to_jsonable,
)
from mythgauntlet.sim.tier0 import SimConfig


# ── extraction helpers ──────────────────────────────────────────────────────────────

def test_numbers_in_walks_nested_structures_and_strings():
    data = {"a": 1, "b": {"c": [2.5, "costs {3} mana"]}, "flag": True}
    nums = _numbers_in(data)
    assert nums == {1.0, 2.5, 3.0}


def test_numbers_in_skips_bare_booleans():
    """A bool is an int subclass in Python (True == 1); without an explicit guard a
    True-only dict would wrongly contribute 1.0 to the budget."""
    assert _numbers_in({"flag": True, "other": False}) == set()


def test_rule_numbers_in_finds_cr_shaped_citations_in_text():
    data = {"text": "See rule 704.5f and also 100.1a for background."}
    rules = _rule_numbers_in(data)
    assert rules == {"704.5f", "100.1a"}


def test_extract_numbers_reads_a_range_as_two_positive_endpoints():
    # Found live 2026-08-25 (mentor_bench.py against a real deck): "the 2-4 mana range"
    # was parsed as {2.0, -4.0} because a bare regex reads the hyphen as a minus sign,
    # not a range separator -- a correct mana-curve explanation was gate-rejected three
    # times over for "citing -4", which never appeared as a real claim.
    assert extract_numbers("the majority fall in the 2-4 mana range") == {2.0, 4.0}


def test_extract_numbers_still_reads_a_genuine_negative_number():
    assert extract_numbers("you're now at -4 life") == {-4.0}


def test_strings_in_collects_meaningful_length_strings_recursively():
    from mythgauntlet.mentor.tools import _strings_in
    data = {"name": "Sol Ring", "oracle_text": "Exile target nonland permanent. You lose 3 life.",
            "nested": {"a": ["short-ok text here"]}}
    strings = _strings_in(data)
    assert "Exile target nonland permanent. You lose 3 life." in strings
    assert "short-ok text here" in strings


def test_strings_in_skips_trivially_short_values():
    from mythgauntlet.mentor.tools import _strings_in
    assert _strings_in({"type_line": "Instant", "color": "W"}) == set()


def test_tool_result_source_texts_property():
    tr = ToolResult(data={"oracle_text": "Exile target nonland permanent. You lose 3 life."})
    assert "Exile target nonland permanent. You lose 3 life." in tr.source_texts


def test_numbers_in_licenses_repeated_mana_symbol_counts():
    # Found live 2026-08-25: Sol Ring's real oracle_text ("{T}: Add {C}{C}.") only
    # licensed 1.0 (from its {1} cost) until this fix, so a model correctly describing
    # it as "two colorless mana" was gate-rejected for citing an uncited "2".
    data = {"oracle_text": "{T}: Add {C}{C}."}
    assert 2.0 in _numbers_in(data)


def test_numbers_in_does_not_license_a_lone_mana_symbol_as_its_count():
    data = {"oracle_text": "{T}: Add {C}."}
    assert 1.0 not in (_numbers_in(data) - {1.0})  # 1.0 is a free number regardless
    # More directly: a single {G} shouldn't manufacture a spurious "1" from symbol
    # counting on top of whatever extract_numbers already found in the string.
    from mythgauntlet.mentor.tools import _mana_symbol_counts
    assert _mana_symbol_counts("{T}: Add {G}.") == set()


def test_to_jsonable_handles_dataclasses_and_sets():
    from dataclasses import dataclass

    @dataclass
    class Inner:
        x: int

    @dataclass
    class Outer:
        inner: Inner
        tags: frozenset

    out = _to_jsonable(Outer(inner=Inner(x=1), tags=frozenset({"b", "a"})))
    assert out == {"inner": {"x": 1}, "tags": ["a", "b"]}


def test_tool_result_numbers_and_rule_numbers_properties():
    r = ToolResult(data={"number": "704.5f", "text": "toughness 0 or less"},
                    rule_numbers=frozenset({"704.5f"}))
    assert 704.5 in r.numbers
    assert 0.0 in r.numbers
    assert r.all_rule_numbers == frozenset({"704.5f"})


# ── tool functions, with a small synthetic deck ─────────────────────────────────────

def _ctx(make_card, empty_store):
    commander = make_card("Test Commander", type_line="Legendary Creature — Human",
                           mana_cost="{2}{G}", color_identity=("G",))
    ramp = make_card("Rock of Ramping", type_line="Artifact",
                      oracle_text="{T}: Add {G}.", produced_mana=("G",), mana_cost="{2}")
    forest = make_card("Forest", type_line="Basic Land — Forest",
                        produced_mana=("G",), color_identity=("G",))
    db = CardDb([commander, ramp, forest])
    resolved = ResolvedDeck(
        deck=Deck(name="test"), commanders=[commander],
        cards=[(ramp, 1), (forest, 35)], missing=[],
    )
    return MentorContext(
        card_db=db, cr=_fake_cr(), rulings_db={}, resolved=resolved,
        cfg=SimConfig(turns=5, runs=10, seed=1), store=empty_store,
    )


def _fake_cr():
    """A few distinct rules, not one -- BM25's IDF degenerates on a near-single-document
    corpus (a term in exactly half of 2 documents scores IDF=0), which is a fixture-size
    artifact, not something the real ~4,000-document corpus exhibits (verified live)."""
    from mythgauntlet.data.rulings import ComprehensiveRules
    return ComprehensiveRules(
        effective_date="August 7, 2026", source_url="https://example.invalid",
        rules={
            "704.5f": "If a creature has toughness 0 or less, it's put into its owner's graveyard.",
            "104.3a": "A player still in the game loses the game as a state-based action.",
            "702.19b": "The controller of an attacking creature with trample first assigns damage.",
            "121.1": "A player draws a card by putting the top card of their library into their hand.",
        },
        glossary={"trample": "A keyword ability. See rule 702.19, \"Trample.\""},
    )


def test_lookup_card_found(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"name": "Rock of Ramping"})
    assert result.data["found"] is True
    assert result.data["oracle_text"] == "{T}: Add {G}."
    assert result.card_names == frozenset({"Rock of Ramping"})


def test_lookup_card_includes_color_identity(make_card, empty_store):
    # Found live 2026-08-25: with no color_identity field returned, a reply describing
    # a mono-green card as "green-white" (conflating "fits the deck" with "is the
    # deck's colors") went unchecked -- this field is a prerequisite for ever fixing
    # that class of claim, even before any gate-side check exists for it.
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"name": "Test Commander"})
    assert result.data["color_identity"] == ["G"]


def test_lookup_card_not_found_grants_nothing(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"name": "Zzyzx Prism Wyrm"})
    assert result.data["found"] is False
    assert result.card_names == frozenset()


def test_search_rules_returns_rule_kind_results(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "search_rules", {"query": "toughness 0 graveyard", "k": 3})
    assert result.data["results"]
    assert "704.5f" in result.rule_numbers


def test_get_rule_found_and_not_found(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    found = call_tool(ctx, "get_rule", {"number": "704.5f"})
    assert found.data["found"] is True
    assert found.rule_numbers == frozenset({"704.5f"})

    missing = call_tool(ctx, "get_rule", {"number": "999.9z"})
    assert missing.data["found"] is False
    assert missing.rule_numbers == frozenset()


def test_get_deck_stats_reports_curve_and_roles(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "get_deck_stats", {})
    assert "curve" in result.data
    assert "manabase" in result.data
    assert "roles" in result.data
    assert result.data["curve"]["nonland_count"] == 1  # Forest is a land, excluded


def test_get_deck_stats_reports_land_count(make_card, empty_store):
    """Found live 2026-09-15 (mentor bench, real deck): asked 'how many lands am I
    running', the model had no licensed total to cite and either fabricated one by
    summing per-colour manabase sources itself (correctly gate-rejected) or refused."""
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "get_deck_stats", {})
    assert result.data["curve"]["land_count"] == 35  # the Forest x35 fixture card


def test_get_deck_stats_reports_commander_identity(make_card, empty_store):
    # Found live 2026-08-25: with no way to surface who the commander even IS, the
    # mentor answered "who are my commanders" with a flat false "I don't have access to
    # your decklist" instead of calling any tool.
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "get_deck_stats", {})
    assert result.data["commanders"] == [{"name": "Test Commander", "color_identity": ["G"]}]
    assert result.card_names == frozenset({"Test Commander"})


def _partner_ctx(make_card, empty_store):
    """A two-commander command zone (WBUG-shaped) for legality-subset tests."""
    lead = make_card("Lead Commander", type_line="Legendary Creature — Human",
                      mana_cost="{1}{W}{B}", color_identity=("W", "B"))
    partner = make_card("Partner Commander", type_line="Legendary Creature — Merfolk",
                         mana_cost="{G}{U}", color_identity=("G", "U"))
    on_color = make_card("Fine Fit", type_line="Instant", mana_cost="{U}",
                          color_identity=("U",))
    off_color = make_card("Off Color Bolt", type_line="Instant", mana_cost="{R}",
                           color_identity=("R",))
    db = CardDb([lead, partner, on_color, off_color])
    resolved = ResolvedDeck(
        deck=Deck(name="test"), commanders=[lead, partner], cards=[], missing=[],
    )
    return MentorContext(
        card_db=db, cr=_fake_cr(), rulings_db={}, resolved=resolved,
        cfg=SimConfig(turns=5, runs=10, seed=1), store=empty_store,
    )


def test_check_legality_accepts_a_card_covered_by_the_union_identity(make_card, empty_store):
    # Neither partner alone is blue+green -- only their UNION covers a blue card. A
    # per-card check against just the lead commander would wrongly reject this.
    ctx = _partner_ctx(make_card, empty_store)
    result = call_tool(ctx, "check_legality", {"name": "Fine Fit"})
    assert result.data["legal"] is True
    assert result.data["colors_not_in_deck_identity"] == []


def test_check_legality_rejects_a_color_outside_the_union_identity(make_card, empty_store):
    # Found live 2026-08-25: asked about a mono-red card against this exact WBUG shape
    # (Tymna the Weaver + Thrasios, Triton Hero), the model correctly STATED both colour
    # sets and still concluded the card was legal -- the subset check has to happen here,
    # in Python, not in the model's own reasoning.
    ctx = _partner_ctx(make_card, empty_store)
    result = call_tool(ctx, "check_legality", {"name": "Off Color Bolt"})
    assert result.data["legal"] is False
    assert result.data["colors_not_in_deck_identity"] == ["R"]
    assert result.data["deck_color_identity"] == ["B", "G", "U", "W"]


def test_check_legality_not_found(make_card, empty_store):
    ctx = _partner_ctx(make_card, empty_store)
    result = call_tool(ctx, "check_legality", {"name": "Zzyzx Prism Wyrm"})
    assert result.data["found"] is False
    assert result.card_names == frozenset()


def test_deck_card_names_includes_commander_and_nonland_cards(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    names = ctx.deck_card_names
    assert "Test Commander" in names
    assert "Rock of Ramping" in names
    assert "Forest" in names


def test_call_tool_unknown_name(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "not_a_real_tool", {})
    assert result.data["found"] is False


def test_call_tool_bad_arguments(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"wrong_kwarg": "x"})
    assert result.data["found"] is False


def test_assess_card_already_in_deck(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "assess_card", {"name": "Rock of Ramping"})
    assert result.data["found"] is True
    assert result.data["already_in_deck"] is True
    assert "Rock of Ramping" in result.card_names


# ── get_bracket_estimate (2026-09-15) ───────────────────────────────────────────────
# The mentor had curve/colour/role-supply (get_deck_stats) but no path at all to "what
# bracket is this deck" -- the headline question for this app's whole stated purpose
# (casual bracket 1-3 pod-fit gauging). This wires `ratings.analysis.analyze_deck` ->
# `ratings.bracket.estimate_bracket` in-process, the SAME pipeline `mythgauntlet analyze`
# and Forge's Analyze panel already use.

def test_get_bracket_estimate_returns_a_real_bracket(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "get_bracket_estimate", {})
    assert result.data["found"] is True
    assert 1 <= result.data["bracket"] <= 5
    assert isinstance(result.data["reasons"], list) and result.data["reasons"]
    # Documented scope: no live Spellbook lookup, no resilience pass -- disclosed via the
    # same field `estimate_bracket` already carries for exactly this purpose.
    assert result.data["combos_checked"] is False


def test_get_bracket_estimate_licenses_game_changer_names(make_card, empty_store):
    from mythgauntlet.model.card import Card

    commander = make_card("Test Commander", type_line="Legendary Creature — Human",
                           mana_cost="{2}{G}", color_identity=("G",))
    gc_card = Card(name="Bomb Effect", type_line="Sorcery", mana_cost_str="{2}{G}",
                    color_identity=("G",), game_changer=True)
    forest = make_card("Forest", type_line="Basic Land — Forest",
                        produced_mana=("G",), color_identity=("G",))
    db = CardDb([commander, gc_card, forest])
    resolved = ResolvedDeck(
        deck=Deck(name="test"), commanders=[commander],
        cards=[(gc_card, 1), (forest, 35)], missing=[],
    )
    ctx = MentorContext(card_db=db, cr=_fake_cr(), rulings_db={}, resolved=resolved,
                         cfg=SimConfig(turns=5, runs=10, seed=1), store=empty_store)
    result = call_tool(ctx, "get_bracket_estimate", {})
    assert result.data["game_changer_cards"] == ["Bomb Effect"]
    assert "Bomb Effect" in result.card_names
    # 1 Game Changer -> the official gate floors this at Bracket 3 (see estimate_bracket).
    assert result.data["bracket"] >= 3


# ── suggest_swap (2026-09-15) ───────────────────────────────────────────────────────
# Deferred out of Phase 1 on purpose (see tools.py's module docstring) until the tool
# loop was proven live across the 6-round campaign in MENTOR_HANDOFF.md. Suggests ONLY
# from the player's own Myth Suite collection -- these tests exercise the "no collection"
# and "no eligible candidates" honesty paths, which don't need a real positive swap to
# be measured (that's what mentor_bench.py / a live campaign turn is for).

def test_suggest_swap_reports_honestly_with_no_collection_file(make_card, empty_store, monkeypatch, tmp_path):
    from mythgauntlet.mentor import tools as tools_mod
    monkeypatch.setattr(tools_mod, "suite_collection_path", lambda: tmp_path / "missing.csv")
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "suggest_swap", {})
    assert result.data["found"] is False
    assert "collection" in result.data["message"].lower()
    assert result.card_names == frozenset()


def test_suggest_swap_reports_honestly_with_no_eligible_candidates(make_card, empty_store, monkeypatch, tmp_path):
    """A collection file exists, but everything in it is either already in the deck, a
    land, or outside the deck's colour identity -- `found: True` with an empty
    suggestion list, not a fabricated recommendation."""
    from mythgauntlet.mentor import tools as tools_mod
    csv_path = tmp_path / "collection.csv"
    csv_path.write_text("Count,Name\n1,Rock of Ramping\n1,Off Color Bolt\n", encoding="utf-8")
    monkeypatch.setattr(tools_mod, "suite_collection_path", lambda: csv_path)

    off_color = make_card("Off Color Bolt", type_line="Instant", mana_cost="{R}",
                           color_identity=("R",))
    ctx = _ctx(make_card, empty_store)
    # Rebuild the card_db so it also knows about the off-color card the collection
    # names -- `owned_candidates` looks each owned name up via `card_db.get`.
    db = CardDb([*[c for c, _ in ctx.resolved.cards], *ctx.resolved.commanders, off_color])
    ctx2 = MentorContext(card_db=db, cr=ctx.cr, rulings_db=ctx.rulings_db,
                          resolved=ctx.resolved, cfg=ctx.cfg, store=ctx.store)
    result = call_tool(ctx2, "suggest_swap", {})
    assert result.data["found"] is True
    assert result.data["suggestions"] == []


def test_suggest_swap_returns_a_real_measured_swap(make_card, empty_store, monkeypatch, tmp_path):
    """End-to-end positive case, reusing the exact fixture shape
    `test_advisor.py::test_advise_prefers_the_cut_that_improves_the_axis_most` documents
    as the one that reliably measures positive -- that test's own docstring records an
    earlier version of ITSELF going silently vacuous on a 'consistency + vanilla bear'
    combo (zero suggestions, assertions all vacuously true), which is exactly the mistake
    an earlier draft of THIS test made. `interaction` against a deck with zero removal
    is deterministic (seed-to-seed sd 0.00) and a real removal spell is a genuine,
    in-kind gain -- not fighting sim noise the way a same-shape creature swap does.
    """
    from mythgauntlet.mentor import tools as tools_mod

    cmdr = make_card("Test Commander", mana_cost="{2}{G}",
                      type_line="Legendary Creature — Elf", color_identity=("G",))
    forest = make_card("Forest", type_line="Basic Land — Forest",
                        produced_mana=("G",), color_identity=("G",))

    def _bear(name, rank):
        c = make_card(name, mana_cost="{1}{G}", type_line="Creature — Bear",
                      color_identity=("G",), edhrec_rank=rank)
        c.power, c.toughness = "2", "2"
        return c

    strong = _bear("Popular Bear", 500)
    weak = _bear("Obscure Bear", 90000)
    removal = make_card("Owned Removal", mana_cost="{1}{G}", type_line="Instant",
                         color_identity=("G",), edhrec_rank=4000,
                         oracle_text="Destroy target creature.")

    resolved = ResolvedDeck(
        deck=Deck(name="t"), commanders=[cmdr],
        cards=[(forest, 36), (strong, 40), (weak, 23)], missing=[],
    )
    db = CardDb([cmdr, forest, strong, weak, removal])
    ctx = MentorContext(
        card_db=db, cr=_fake_cr(), rulings_db={}, resolved=resolved,
        cfg=SimConfig(turns=5, runs=80, seed=3), store=empty_store,
    )

    csv_path = tmp_path / "collection.csv"
    csv_path.write_text("Count,Name\n1,Owned Removal\n", encoding="utf-8")
    monkeypatch.setattr(tools_mod, "suite_collection_path", lambda: csv_path)

    result = call_tool(ctx, "suggest_swap", {"axis": "interaction"})
    assert result.data["found"] is True
    assert result.data["suggestions"], "fixture is proven to produce a positive swap"
    top = result.data["suggestions"][0]
    assert top["add"] == "Owned Removal"
    assert top["after"] > result.data["baseline"]
    assert "Owned Removal" in result.card_names
    assert top["cut"] in result.card_names


def test_suggest_swap_bad_axis_returns_a_graceful_error(make_card, empty_store, monkeypatch, tmp_path):
    """advisor.advise raises ValueError for an unknown axis -- call_tool must turn that
    into a normal found:False result, not an unhandled exception from inside the tool
    loop. Needs at least one ELIGIBLE candidate (owned, in-colour, not already in the
    deck) or `tool_suggest_swap` never reaches `advise()` at all -- "Rock of Ramping"
    alone is already in the deck and wouldn't exercise this path."""
    from mythgauntlet.mentor import tools as tools_mod
    csv_path = tmp_path / "collection.csv"
    csv_path.write_text("Count,Name\n1,Rock of Ramping\n1,Second Green Card\n", encoding="utf-8")
    monkeypatch.setattr(tools_mod, "suite_collection_path", lambda: csv_path)

    second_green = make_card("Second Green Card", type_line="Creature — Bear",
                              mana_cost="{1}{G}", color_identity=("G",))
    ctx = _ctx(make_card, empty_store)
    db = CardDb([*[c for c, _ in ctx.resolved.cards], *ctx.resolved.commanders, second_green])
    ctx2 = MentorContext(card_db=db, cr=ctx.cr, rulings_db=ctx.rulings_db,
                          resolved=ctx.resolved, cfg=ctx.cfg, store=ctx.store)
    result = call_tool(ctx2, "suggest_swap", {"axis": "not_a_real_axis"})
    assert result.data["found"] is False
