"""look_and_select: a BOUNDED reveal-and-choose, added 2026-09-10.

The single largest unmodeled-op-shaped gap the store had: 131 cards say "look at/reveal
the top N cards of your library, you may put a matching one into your hand, put the rest
on the bottom" (Acclaimed Contender, Astor Bearer of Blades, Augur of Bolas) — and until
this op existed, the compiler had nowhere honest to put that, so it kept mislabeling it
`search_library` (fixed separately, same day: a real search sees the ENTIRE library and
shuffles it away; this only ever sees `look` cards and never shuffles).

Offline, no store needed — `_look_and_select` is exercised directly against `_Player`/
`GameCard` fixtures, the same pattern `test_tier2_cedh.py` uses for the sibling tutor ops.
"""

from __future__ import annotations

from mythgauntlet.sim.tier2 import _Player, _look_and_select, make_game_card


def _gc(make_card, name="Bear", cost="{2}{B}", type_line="Creature — Bear",
       power=2, rank=500, produced_mana=()):
    card = make_card(name, mana_cost=cost, type_line=type_line, color_identity=("B",),
                     edhrec_rank=rank, produced_mana=produced_mana)
    if "Land" not in type_line:
        card.power, card.toughness = str(power), str(power)
    return make_game_card(card, None)


def _player(*library) -> _Player:
    return _Player(name="me", library=list(library))


# --- the dominant shape: look N, take 1 matching, rest to bottom -------------------

def test_takes_the_best_matching_card_into_hand(make_card):
    creature = _gc(make_card, "Match", type_line="Creature — Wizard", rank=200)
    other = _gc(make_card, "Other", type_line="Land", rank=900)
    library = [other, creature]  # creature is on top (library[-1])
    me = _player(*library)
    _look_and_select(me, {"look": 2, "what": {"type": "creature"}, "take": 1})
    assert [g.name for g in me.hand] == ["Match"]
    assert len(me.library) == 1  # the non-matching land went back


def test_picks_the_HIGHEST_IMPACT_match_when_several_qualify(make_card):
    weak = _gc(make_card, "Weak", type_line="Creature — Bear", rank=5000)
    strong = _gc(make_card, "Strong", type_line="Creature — Dragon", rank=1)
    library = [weak, strong]
    me = _player(*library)
    _look_and_select(me, {"look": 2, "what": {"type": "creature"}, "take": 1})
    assert [g.name for g in me.hand] == ["Strong"]


def test_no_match_takes_nothing_and_conserves_every_card(make_card):
    land1 = _gc(make_card, "L1", type_line="Land")
    land2 = _gc(make_card, "L2", type_line="Land")
    me = _player(land1, land2)
    _look_and_select(me, {"look": 2, "what": {"type": "creature"}, "take": 1})
    assert me.hand == []
    assert len(me.library) == 2  # both went back — nothing lost


def test_an_absent_what_matches_any_card(make_card):
    """Codecracker Hound: "Put one into your hand and the other into your graveyard" —
    no type filter at all."""
    a = _gc(make_card, "A", rank=100)
    b = _gc(make_card, "B", rank=900)
    me = _player(a, b)
    _look_and_select(me, {"look": 2, "take": 1})
    assert len(me.hand) == 1  # took the best of the two, no filter needed


# --- take > 1 ("up to N") ------------------------------------------------------------

def test_take_more_than_one_matching_card(make_card):
    c1 = _gc(make_card, "C1", type_line="Creature — Bear", rank=100)
    c2 = _gc(make_card, "C2", type_line="Creature — Bear", rank=200)
    land = _gc(make_card, "L", type_line="Land", rank=1)
    me = _player(land, c1, c2)
    _look_and_select(me, {"look": 3, "what": {"type": "creature"}, "take": 2})
    assert {g.name for g in me.hand} == {"C1", "C2"}
    assert len(me.library) == 1  # only the land came back


def test_take_is_capped_by_available_matches_not_by_take_alone(make_card):
    """"Up to two" with only one real match present must not fabricate a second."""
    c1 = _gc(make_card, "OnlyMatch", type_line="Creature — Bear")
    land = _gc(make_card, "L", type_line="Land")
    me = _player(land, c1)
    _look_and_select(me, {"look": 2, "what": {"type": "creature"}, "take": 2})
    assert [g.name for g in me.hand] == ["OnlyMatch"]


# --- to: battlefield, lands only -----------------------------------------------------

def test_land_to_battlefield_becomes_a_mana_source(make_card):
    land = _gc(make_card, "Forest", type_line="Land", produced_mana=("G",))
    other = _gc(make_card, "Bear", type_line="Creature — Bear")
    me = _player(other, land)
    _look_and_select(me, {"look": 2, "what": {"type": "land"}, "take": 1,
                          "to": "battlefield"})
    assert me.hand == []
    assert len(me.sources) == 1
    assert me.sources[0].colors == frozenset({"G"})
    assert len(me.library) == 1  # the non-land bear went back


def test_a_NONLAND_to_battlefield_is_declined_not_lost(make_card):
    """Collected Company / Bag of Tricks class: materializing a real creature permanent
    OUTSIDE the cast path needs infrastructure this engine doesn't have (same gap
    `reanimate` has always had). The card must not vanish -- it stays in the library."""
    creature = _gc(make_card, "Dragon", type_line="Creature — Dragon")
    me = _player(creature)
    _look_and_select(me, {"look": 1, "what": {"type": "creature"}, "take": 1,
                          "to": "battlefield"})
    assert me.hand == []
    assert len(me.library) == 1  # not lost, not materialized either
    assert me.library[0].name == "Dragon"


# --- edges -----------------------------------------------------------------------

def test_look_larger_than_the_library_is_safe(make_card):
    only = _gc(make_card, "Only", type_line="Creature — Bear")
    me = _player(only)
    _look_and_select(me, {"look": 50, "what": {"type": "creature"}, "take": 1})
    assert [g.name for g in me.hand] == ["Only"]
    assert me.library == []


def test_an_empty_library_is_a_no_op(make_card):
    me = _player()
    _look_and_select(me, {"look": 5, "take": 1})  # must not raise
    assert me.hand == [] and me.library == []


def test_look_zero_or_missing_is_a_no_op(make_card):
    card = _gc(make_card, "Card")
    me = _player(card)
    _look_and_select(me, {"take": 1})  # no "look" at all
    assert me.hand == [] and len(me.library) == 1
    _look_and_select(me, {"look": 0, "take": 1})
    assert me.hand == [] and len(me.library) == 1


def test_type_level_disjunction_ors_correctly(make_card):
    """Augur of Bolas: "reveal an instant or sorcery card" is ONE choice from ONE pool.
    Caught live 2026-09-10: the compiler's first attempt split this into TWO separate
    look_and_select effects (one for instant, one for sorcery), each independently
    re-looking at the same top-3 window -- which would let the engine take BOTH an
    instant AND a sorcery, something the real card never allows. Fixed at the prompt
    (combine into one what.type:"instant or sorcery"); this pins the simulator side,
    which already handles the disjunction correctly via _tutor_matcher."""
    instant = _gc(make_card, "Bolt", type_line="Instant", rank=200)
    sorcery = _gc(make_card, "Wrath", type_line="Sorcery", rank=900)
    me = _player(sorcery, instant)
    _look_and_select(me, {"look": 2, "what": {"type": "instant or sorcery"}, "take": 1})
    assert [g.name for g in me.hand] == ["Bolt"]  # the higher-impact of either type


def test_subtype_disjunction_ors_correctly(make_card):
    """Astor Bearer of Blades: "an Equipment or Vehicle card" -- reuses _tutor_matcher's
    existing OR-disjunction fix, not a new bug surface."""
    equip = _gc(make_card, "Sword", type_line="Artifact — Equipment", rank=100)
    other = _gc(make_card, "Rock", type_line="Artifact", rank=900)
    me = _player(other, equip)
    _look_and_select(
        me, {"look": 2, "what": {"type": "artifact", "subtype": "Equipment or Vehicle"},
             "take": 1})
    assert [g.name for g in me.hand] == ["Sword"]
