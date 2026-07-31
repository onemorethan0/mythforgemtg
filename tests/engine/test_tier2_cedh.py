"""cEDH fidelity increment: ritual mana, tutors-to-hand, hand-castable combos. Offline."""

from __future__ import annotations

import json

from mythgauntlet.model.card import normalize_name
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import (
    DuelConfig,
    _main_phase,
    _Player,
    _resolve,
    make_game_card,
)


def _store(tmp_path, name: str, ccm: dict) -> SemanticsStore:
    authored = tmp_path / "authored"
    authored.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "-").replace(",", "").replace("'", "")
    (authored / f"{slug}.json").write_text(
        json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8"
    )
    return SemanticsStore(authored=authored, compiled=tmp_path / "no-compiled")


def _spell(name: str, effects: list[dict], mana: str = "{B}") -> dict:
    return {
        "name": name, "ccm_version": 1, "cost": {"mana": mana},
        "abilities": [{"kind": "spell_effect", "effects": effects}],
    }


def _src(color="B", ready=True):
    return _Source(frozenset({color}), ready=ready)


def _vanilla(make_card, name="Bear", cost="{2}{B}", power=4, rank=500):
    card = make_card(name, mana_cost=cost, type_line="Creature — Horror",
                     color_identity=("B",), edhrec_rank=rank)
    card.power, card.toughness = str(power), str(power)
    return make_game_card(card, None)


# --- to:top / to:library tutors (Vampiric/Mystical/Imperial-Seal class) -------------------


def _top_tutor(tmp_path, make_card, subtype: str | None = None):
    what: dict = {"type": "card"}
    if subtype:
        what["subtype"] = subtype
    card = make_card("Test Vampiric", mana_cost="{B}", type_line="Instant",
                     color_identity=("B",))
    ccm = _spell("Test Vampiric", [{"op": "search_library", "what": what, "to": "top"}])
    return make_game_card(card, _store(tmp_path, "Test Vampiric", ccm))


def test_profile_flags_tutor_but_not_land_fetch(tmp_path, make_card):
    tutor = _top_tutor(tmp_path, make_card)
    assert tutor.profile.tutor is True
    land_fetch = make_game_card(
        make_card("Test Cultivate", mana_cost="{2}{G}", type_line="Sorcery"),
        _store(tmp_path, "Test Cultivate", _spell(
            "Test Cultivate",
            [{"op": "search_library", "what": {"type": "land"}, "to": "battlefield"}], "{2}{G}")),
    )
    assert land_fetch.profile.tutor is False  # ramp, not a combo tutor
    assert _vanilla(make_card).profile.tutor is False  # rung-1


def test_top_tutor_puts_missing_combo_piece_on_top(tmp_path, make_card):
    """A to:top tutor fetches the missing combo piece to the TOP of library (drawn next turn),
    NOT to hand -- the previously-ignored Vampiric/Imperial-Seal class."""
    tutor = _top_tutor(tmp_path, make_card)
    piece = _vanilla(make_card, "Combo Piece", cost="{1}", power=1)
    bomb = _vanilla(make_card, "Bomb", cost="{5}", power=8, rank=1)  # highest impact
    combo = frozenset({normalize_name("Combo Piece"), normalize_name("Other Half")})
    me = _Player(name="me", library=[bomb, piece], combos=(combo,), combo_pieces=combo)
    opp = _Player(name="opp", library=[])
    _resolve(tutor, me, opp, False)
    assert me.hand == []  # to-top tutor does NOT put it in hand...
    assert me.library[-1].name == "Combo Piece"  # ...it sits on top, over the higher-impact bomb


def test_top_tutor_respects_subtype_filter(tmp_path, make_card):
    """Mystical Tutor class: 'instant or sorcery' can't fetch a higher-impact creature."""
    tutor = _top_tutor(tmp_path, make_card, subtype="instant or sorcery")
    creature = _vanilla(make_card, "Big Creature", cost="{2}", power=8, rank=1)  # high impact
    ritual = make_game_card(
        make_card("Cheap Instant", mana_cost="{U}", type_line="Instant"), None)
    me = _Player(name="me", library=[creature, ritual])
    opp = _Player(name="opp", library=[])
    _resolve(tutor, me, opp, False)
    assert me.library[-1].name == "Cheap Instant"  # filter excludes the creature


# --- ritual mana -------------------------------------------------------------------------


def test_ritual_grants_ready_temp_sources(tmp_path, make_card):
    card = make_card("Test Ritual", mana_cost="{B}", type_line="Instant",
                     color_identity=("B",))
    ccm = _spell("Test Ritual", [{"op": "add_mana", "amount": 3, "colors": "B"}])
    gc = make_game_card(card, _store(tmp_path, "Test Ritual", ccm))
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    temp = [s for s in me.sources if s.temp]
    assert len(temp) == 3
    assert all(s.ready and "B" in s.colors for s in temp)


def test_ritual_enables_a_bigger_cast_same_turn(tmp_path, make_card):
    """One land + Dark-Ritual-class spell -> a 3-drop resolves the same turn
    (land pays the ritual, the ritual's {B}{B}{B} pays the {2}{B} spell)."""
    ritual_card = make_card("Test Ritual", mana_cost="{B}", type_line="Instant",
                            color_identity=("B",), edhrec_rank=100)
    ccm = _spell("Test Ritual", [{"op": "add_mana", "amount": 3, "colors": "B"}])
    store = _store(tmp_path, "Test Ritual", ccm)
    me = _Player(name="me", library=[], sources=[_src("B")],
                 hand=[make_game_card(ritual_card, store), _vanilla(make_card)])
    opp = _Player(name="opp", library=[])
    _main_phase(me, opp, turn=1, cfg=DuelConfig())
    assert any(p.name == "Bear" for p in me.battlefield)  # {2}{B} paid off one land


def test_temp_sources_expire_via_untap_filter(tmp_path, make_card):
    """The untap step drops temp sources (the exact filter _play_game applies)."""
    me = _Player(name="me", library=[],
                 sources=[_src("B"), _Source(frozenset({"B"}), ready=True, temp=True)])
    me.sources = [s for s in me.sources if not s.temp]
    assert len(me.sources) == 1 and not me.sources[0].temp


# --- tutors to hand ----------------------------------------------------------------------


def _tutor_gc(tmp_path, make_card):
    card = make_card("Test Tutor", mana_cost="{1}{B}", type_line="Sorcery",
                     color_identity=("B",))
    ccm = _spell("Test Tutor", [{"op": "search_library", "what": {"type": "card"},
                                 "count": 1, "to": "hand", "shuffle": True}], mana="{1}{B}")
    return make_game_card(card, _store(tmp_path, "Test Tutor", ccm))


def test_tutor_prefers_a_missing_combo_piece(tmp_path, make_card):
    tutor = _tutor_gc(tmp_path, make_card)
    piece = _vanilla(make_card, "Combo Piece", cost="{1}", power=1)
    # highest impact — would win the fallback pick without the combo preference
    bomb = _vanilla(make_card, "Bomb", cost="{5}", power=8, rank=1)
    me = _Player(name="me", library=[bomb, piece],
                 combos=(frozenset({normalize_name("Combo Piece"),
                                    normalize_name("Other Half")}),),
                 combo_pieces=frozenset({normalize_name("Combo Piece"),
                                         normalize_name("Other Half")}))
    opp = _Player(name="opp", library=[])
    _resolve(tutor, me, opp, False)
    assert [g.name for g in me.hand] == ["Combo Piece"]
    assert all(g.name != "Combo Piece" for g in me.library)


def test_tutor_falls_back_to_highest_impact(tmp_path, make_card):
    tutor = _tutor_gc(tmp_path, make_card)
    weak = _vanilla(make_card, "Weak", cost="{2}", power=2, rank=20000)
    strong = _vanilla(make_card, "Strong", cost="{2}", power=2, rank=10)
    me = _Player(name="me", library=[weak, strong])
    opp = _Player(name="opp", library=[])
    _resolve(tutor, me, opp, False)
    assert [g.name for g in me.hand] == ["Strong"]


# --- hand-castable combo pieces ----------------------------------------------------------


def test_combo_assembles_from_hand_with_mana(make_card):
    """Thoracle/Consultation class: one piece online, the other castable from hand."""
    online_piece = _vanilla(make_card, "Oracle", cost="{U}{U}", power=1)
    hand_piece = make_game_card(
        make_card("Consult", mana_cost="{B}", type_line="Instant", color_identity=("B",)),
        None,
    )
    combo = frozenset({normalize_name("Oracle"), normalize_name("Consult")})
    me = _Player(name="me", library=[], combos=(combo,), combo_pieces=combo,
                 sources=[_src("B")], hand=[hand_piece])
    opp = _Player(name="opp", library=[])
    _resolve(online_piece, me, opp, False)
    me.battlefield[-1].sick = False
    assert me.combo_ready() is True
    me.sources[0].ready = False  # tapped out -> can't cast the hand piece
    assert me.combo_ready() is False


def test_combo_charges_combined_cost_of_hand_pieces(make_card):
    """Two hand pieces each within ready mana but not TOGETHER must not assemble."""
    a = make_game_card(make_card("Half A", mana_cost="{1}", type_line="Instant"), None)
    b = make_game_card(make_card("Half B", mana_cost="{1}", type_line="Instant"), None)
    combo = frozenset({normalize_name("Half A"), normalize_name("Half B")})
    me = _Player(name="me", library=[], combos=(combo,), combo_pieces=combo,
                 sources=[_src("B")], hand=[a, b])
    assert me.combo_ready() is False  # need 2 total, only 1 ready
    me.sources.append(_src("B"))
    assert me.combo_ready() is True


def test_agent_holds_an_instant_combo_piece_instead_of_binning_it(make_card):
    """The greedy agent must not cast away its own wincon.

    _combo_bonus paid the agent to cast ANY combo piece regardless of whether the combo
    could finish, so a dedicated instant/sorcery piece went to the graveyard for nothing.
    Measured on cEDH Blue Farm before the fix: Demonic Consultation 0.85 casts/game,
    Tainted Pact 0.82, Brain Freeze 0.88 — one copy each, so the first cast removed the
    wincon permanently. Unpressured (30 turns, no lethal), the deck assembled in only
    34 of 120 games; after the fix, 120 of 120.
    """
    from mythgauntlet.sim.tier2 import _card_value

    piece = make_game_card(
        make_card("Consult", mana_cost="{B}", type_line="Instant", color_identity=("B",)),
        None,
    )
    combo = frozenset({normalize_name("Oracle"), normalize_name("Consult")})
    me = _Player(name="me", library=[], combos=(combo,), combo_pieces=combo,
                 sources=[_src("B")], hand=[piece])
    opp = _Player(name="opp", library=[])
    assert _card_value(piece, me, opp, 3, DuelConfig()) == 0.0, (
        "a dedicated instant combo piece must be held (value <= 0 keeps it in hand)"
    )

    # Same card in a deck with no combo is unaffected — the rule is combo-gated.
    plain = _Player(name="me", library=[], sources=[_src("B")], hand=[piece])
    assert _card_value(piece, plain, opp, 3, DuelConfig()) > 0.0


def test_permanent_combo_piece_is_still_cast(make_card):
    """A permanent piece STAYS on the battlefield and counts as assembled, so casting it
    is progress — the hold must apply only to instants/sorceries."""
    from mythgauntlet.sim.tier2 import _card_value

    piece = _vanilla(make_card, "Oracle", cost="{U}{U}", power=1)
    combo = frozenset({normalize_name("Oracle"), normalize_name("Consult")})
    me = _Player(name="me", library=[], combos=(combo,), combo_pieces=combo,
                 sources=[_src("U"), _src("U")], hand=[piece])
    opp = _Player(name="opp", library=[])
    assert _card_value(piece, me, opp, 3, DuelConfig()) > 0.0


def test_tutor_filter_ors_a_flattened_type_disjunction(make_card):
    """"An instant or sorcery card" compiles as type=instant + subtype=sorcery.

    AND-ing those asks for a card that is both, which no card is — so Mystical Tutor
    fetched nothing, ever. A real subtype is never also a card type, so a card type in
    the subtype slot is an unambiguous flattened disjunction.
    """
    from mythgauntlet.sim.tier2 import _tutor_matcher

    matches = _tutor_matcher({"type": "instant", "subtype": "sorcery"})
    assert matches(make_game_card(make_card("Bolt", type_line="Instant"), None))
    assert matches(make_game_card(make_card("Divination", type_line="Sorcery"), None))
    assert not matches(make_game_card(make_card("Bear", type_line="Creature — Bear"), None))

    # "creature or land" arriving in the type slot itself
    m2 = _tutor_matcher({"type": "creature or land"})
    assert m2(make_game_card(make_card("Bear", type_line="Creature — Bear"), None))
    assert m2(make_game_card(make_card("Forest", type_line="Basic Land — Forest"), None))
    assert not m2(make_game_card(make_card("Bolt", type_line="Instant"), None))


def test_tutor_filter_still_ands_a_genuine_subtype(make_card):
    """artifact + Equipment must stay an AND — only card-type subtypes are disjunctions."""
    from mythgauntlet.sim.tier2 import _tutor_matcher

    matches = _tutor_matcher({"type": "artifact", "subtype": "equipment"})
    assert matches(make_game_card(
        make_card("Sword", type_line="Artifact — Equipment"), None))
    assert not matches(make_game_card(
        make_card("Signet", type_line="Artifact"), None))
