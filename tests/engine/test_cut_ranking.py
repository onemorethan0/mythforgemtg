"""The shared cut ranking (ratings/cut_ranking, 2026-11-10): protect the plan and the role floors,
then cut what measurably does nothing or drags, then trim the most over-full role."""
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings.cut_ranking import DRAG, IDLE, SURPLUS, rank_cuts
from mythgauntlet.sim.tier0 import SimConfig

CFG = SimConfig(turns=12, runs=150, seed=5)


def _deck(make_card, extra, bears=30):
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature — Bear")
    bear.power, bear.toughness = "2", "2"
    cards = [(forest, 40), (bear, bears)] + [(c, 1) for c in extra]
    return ResolvedDeck(deck=Deck(commanders=[], entries=[]), commanders=[], cards=cards,
                        missing=[])


def test_a_threat_is_kept_a_do_nothing_body_is_cut(make_card):
    giant = make_card("Giant", mana_cost="{3}{G}", type_line="Creature — Giant")
    giant.power, giant.toughness = "9", "9"
    wall = make_card("Wall", mana_cost="{3}{G}", type_line="Creature — Wall")
    wall.power, wall.toughness = "0", "4"
    rk = rank_cuts(_deck(make_card, [giant, wall]), CFG)
    assert "Giant" in rk.protected and "sooner" in rk.protected["Giant"]
    wall_cut = next(c for c in rk.cuts if c.name == "Wall")
    assert wall_cut.kind in (IDLE, DRAG) and "games it is drawn" in wall_cut.why
    assert "Giant" not in rk.names()


def test_interaction_is_only_ever_cut_by_role_count(make_card):
    """No opponent, so a removal spell's measured value means nothing: it is offered only when
    removal is over its card target, and never as 'idle' or 'drag'."""
    kills = [make_card(f"Kill {i}", mana_cost="{1}{G}", type_line="Instant",
                       oracle_text="Destroy target creature.") for i in range(12)]
    rk = rank_cuts(_deck(make_card, kills, bears=18), CFG)
    offered = [c for c in rk.cuts if c.name.startswith("Kill")]
    assert offered and all(c.kind == SURPLUS and c.role == "removal" for c in offered)
    one = rank_cuts(_deck(make_card, kills[:1], bears=29), CFG)
    assert "Kill 0" not in one.names()           # at/under its floor: kept, with the reason
    assert "opens a gap" in one.protected["Kill 0"]
