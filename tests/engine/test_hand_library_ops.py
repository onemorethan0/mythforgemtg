"""discard / scry / surveil / mill — the hand-and-library ops.

Ranked by their IMPLEMENTABLE subset rather than raw card count (`mythgauntlet
sim-health`): discard 949 cards, scry 448, mill 399, surveil 202. All four are dominated
by shapes with NO target to choose — a player-level or global effect — which is exactly
why they were reachable at all; the bigger ops by raw count (`return_to_hand` 2,286) are
mostly a chosen target the engine has no way to pick without fabricating.

The engine has NO GRAVEYARD ZONE, and that shapes all four: a discarded or milled card
simply leaves the game, and surveil degrades to scry. Everything a graveyard deck is
really buying — recursion, delirium, threshold, madness — is unmodelled, so every one of
these under-counts rather than over-counts.
"""

from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.semantics.interpreter import ResolvedEffect
from mythgauntlet.sim.tier2 import _apply_resolved, _Player, _Source


def _gc(name: str, impact: float = 1.0, is_land: bool = False):
    """Minimal GameCard stand-in: only .name/.profile.impact/.card.is_land are read."""
    return SimpleNamespace(
        name=name,
        card=SimpleNamespace(name=name, is_land=is_land),
        profile=SimpleNamespace(impact=impact),
    )


def _player(hand=(), library=(), sources=0) -> _Player:
    p = _Player(name="P", library=list(library))
    p.hand = list(hand)
    p.sources = [_Source(colors=frozenset("G"), ready=True) for _ in range(sources)]
    return p


def _eff(op: str, **params) -> ResolvedEffect:
    return ResolvedEffect(op=op, params=params)


# --- discard ------------------------------------------------------------------------

def test_discard_who_you_empties_my_hand_not_the_opponents():
    me = _player(hand=[_gc("a", 1.0), _gc("b", 2.0)])
    opp = _player(hand=[_gc("x", 1.0)])
    _apply_resolved(_eff("discard", who="you", count=1), me, opp, None)
    assert len(me.hand) == 1 and len(opp.hand) == 1


def test_discard_takes_the_least_useful_card():
    """Both players discard their OWN worst — normal play, not an advantageous choice."""
    me = _player(hand=[_gc("bomb", 9.0), _gc("chaff", 0.1), _gc("mid", 3.0)])
    _apply_resolved(_eff("discard", who="you", count=1), me, _player(), None)
    assert [g.name for g in me.hand] == ["bomb", "mid"]


def test_discard_who_opponent_hits_the_opponent():
    me = _player(hand=[_gc("a")])
    opp = _player(hand=[_gc("x"), _gc("y")])
    _apply_resolved(_eff("discard", who="opponent", count=2), me, opp, None)
    assert len(me.hand) == 1 and opp.hand == []


def test_discard_each_hits_everyone():
    me, opp = _player(hand=[_gc("a")]), _player(hand=[_gc("x")])
    _apply_resolved(_eff("discard", who="each", count=1), me, opp, None)
    assert me.hand == [] and opp.hand == []


def test_discard_with_no_who_at_all_is_DECLINED():
    """Emptying the wrong player's hand is a fabrication whichever way it lands, so an
    unattributed discard does nothing rather than guessing."""
    me, opp = _player(hand=[_gc("a")]), _player(hand=[_gc("x")])
    _apply_resolved(_eff("discard", count=1), me, opp, None)
    assert len(me.hand) == 1 and len(opp.hand) == 1


def test_discard_falls_back_to_the_target_controller():
    me, opp = _player(hand=[_gc("a")]), _player(hand=[_gc("x")])
    _apply_resolved(_eff("discard", count=1, target={"controller": "opponent"}),
                    me, opp, None)
    assert len(me.hand) == 1 and opp.hand == []


def test_discarding_more_than_the_hand_holds_is_safe():
    me = _player(hand=[_gc("a")])
    _apply_resolved(_eff("discard", who="you", count=7), me, _player(), None)
    assert me.hand == []


# --- scry / surveil -----------------------------------------------------------------

def test_scry_puts_the_best_card_on_top_when_mana_is_developed():
    """Library is drawn from the END, so "top" is the tail."""
    me = _player(library=[_gc("deep"), _gc("chaff", 0.1), _gc("bomb", 9.0)], sources=6)
    _apply_resolved(_eff("scry", count=2), me, _player(), None)
    assert me.library[-1].name == "bomb"  # drawn next


def test_scry_prefers_a_LAND_while_still_developing_mana():
    """Ranking purely by impact would bury the land a mana-light draw needs under a
    seven-drop bomb — actively worse than not modelling scry at all."""
    me = _player(library=[_gc("deep"), _gc("bomb", 9.0), _gc("Forest", 0.1, is_land=True)],
                 sources=2)
    _apply_resolved(_eff("scry", count=2), me, _player(), None)
    assert me.library[-1].name == "Forest"


def test_scry_never_removes_a_card_from_the_library():
    """Only the reorder is modelled; real scry also bottoms, which DIGS. Under-count."""
    me = _player(library=[_gc("a"), _gc("b", 5.0), _gc("c", 0.1)], sources=6)
    _apply_resolved(_eff("scry", count=3), me, _player(), None)
    assert sorted(g.name for g in me.library) == ["a", "b", "c"]


def test_surveil_behaves_as_scry_because_there_is_no_graveyard():
    me = _player(library=[_gc("chaff", 0.1), _gc("bomb", 9.0)], sources=6)
    _apply_resolved(_eff("surveil", count=2), me, _player(), None)
    assert me.library[-1].name == "bomb"
    assert len(me.library) == 2


def test_scry_on_a_nearly_empty_library_is_safe():
    for lib in ([], [_gc("only")]):
        me = _player(library=list(lib), sources=6)
        _apply_resolved(_eff("scry", count=3), me, _player(), None)
        assert len(me.library) == len(lib)


# --- mill ---------------------------------------------------------------------------

def test_mill_removes_from_the_top_of_the_named_players_library():
    me = _player(library=[_gc("bottom"), _gc("mid"), _gc("top")])
    _apply_resolved(_eff("mill", who="you", count=2), me, _player(), None)
    assert [g.name for g in me.library] == ["bottom"]


def test_mill_can_deck_a_player():
    """No graveyard, so depletion is the ONLY thing mill models — but it is real:
    _Player.draw sets `decked` on an empty library."""
    opp = _player(library=[_gc("a"), _gc("b")])
    _apply_resolved(_eff("mill", who="opponent", count=5), _player(), opp, None)
    assert opp.library == []
    opp.draw(1)
    assert opp.decked is True


def test_mill_with_no_who_is_declined_like_discard():
    me, opp = _player(library=[_gc("a")]), _player(library=[_gc("x")])
    _apply_resolved(_eff("mill", count=1), me, opp, None)
    assert len(me.library) == 1 and len(opp.library) == 1
