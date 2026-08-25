"""Combo determinism (Layer 2): rules/errata classification of guaranteed-win vs chance-based."""

from mythgauntlet.data.spellbook import assess_combos, classify_combo, parse_response
from mythgauntlet.ratings.analysis import make_determinism_fn
from mythgauntlet.semantics.combo_rules import classify_determinism


def _variant(cards, produces, **extra):
    v = {
        "id": extra.pop("id", "x"),
        "uses": [{"card": {"name": c}} for c in cards],
        "produces": [{"feature": {"name": p}} for p in produces],
    }
    v.update(extra)
    return v


def _combo(cards, produces, **extra):
    payload = {"results": {"included": [_variant(cards, produces, **extra)]}}
    return parse_response(payload).included[0]


# --- the pure text classifier -----------------------------------------------------------

def test_clean_text_is_deterministic():
    v = classify_determinism(["Add {C}{C}.", "Untap target artifact."])
    assert v.deterministic and v.markers == ()
    assert "CR 732" in v.rule


def test_you_choose_is_still_deterministic():
    # The combo's controller making a choice / a 'may' is a deterministic stop point, not chance.
    v = classify_determinism(["You may untap it.", "You choose a creature."])
    assert v.deterministic


def test_at_random_is_non_deterministic():
    v = classify_determinism(["Discard a card at random."])
    assert not v.deterministic and "at random" in v.markers


def test_coin_flip_is_non_deterministic():
    v = classify_determinism(["Flip a coin. If you win the flip, repeat this process."])
    assert not v.deterministic and "coin flip" in v.markers


def test_opponent_choice_is_non_deterministic():
    v = classify_determinism(["An opponent chooses one of them."])
    assert not v.deterministic and "opponent's choice" in v.markers


def test_dice_roll_is_non_deterministic():
    v = classify_determinism(["Roll a six-sided die."])
    assert not v.deterministic and "dice roll" in v.markers


def test_opponent_separates_is_non_deterministic():
    """Found live 2026-08-25 spot-checking real cards: Fact or Fiction ("An opponent
    SEPARATES those cards into two piles") was missed outright because the marker only
    matched the verb "chooses"/"choose". MTG templates this whole family of split-and-pick
    effects (Fact or Fiction, Sphinx of Uthuun, Brilliant Ultimatum, ...) with several
    verbs -- widened to separates/picks/selects, verified against all 8 real cards using
    any of those verbs near "opponent" in the live card store, zero false positives."""
    v = classify_determinism(["An opponent separates those cards into two piles."])
    assert not v.deterministic and "opponent's choice" in v.markers


def test_benign_random_order_of_unchosen_cards_is_not_flagged():
    """A candidate widening (matching "in a random order" to catch Possibility Storm) was
    tried and REVERTED: it also flagged Thassa's Oracle -- one of the most iconic, fully
    DETERMINISTIC cEDH win conditions -- because "put the rest on the bottom in a random
    order" is common, benign anti-stacking templating for cards you did NOT keep, unrelated
    to whether the effect's actual outcome is deterministic. This pins the non-regression."""
    v = classify_determinism([
        "Put up to one of them on top of your library and the rest on the bottom of your "
        "library in a random order. If X is greater than or equal to the number of cards "
        "in your library, you win the game."
    ])
    assert v.deterministic


def test_description_is_searched_too():
    v = classify_determinism(["Vanilla text."], description="Flip a coin until you lose.")
    assert not v.deterministic


# --- grading integration ----------------------------------------------------------------

def test_non_deterministic_caps_reliability_and_notes_it():
    combo = _combo(["A", "B"], ["Win the game"], manaValueNeeded=1)
    assert classify_combo(combo).reliability == "fast-win"  # clean shape
    nd = classify_determinism(["Flip a coin."])
    g = classify_combo(combo, determinism=nd)
    assert g.reliability == "slow"  # a chance-based win is never fast/strong
    assert "NON-DETERMINISTIC" in g.note and "coin flip" in g.note


def test_assessment_counts_non_deterministic_and_reasons(make_card):
    report = parse_response({"results": {"included": [
        _variant(["Krark", "Thumb"], ["Win the game"], manaValueNeeded=1),
    ]}})
    krark = make_card("Krark", oracle_text="Whenever you cast a spell, flip a coin.")
    thumb = make_card("Thumb", oracle_text="If you would flip a coin, flip two instead.")
    det_fn = make_determinism_fn([(krark, 1), (thumb, 1)], [])
    a = assess_combos(report, determinism_fn=det_fn)
    assert a.nondeterministic_count == 1
    assert "non-deterministic" in a.gate_reason()
    assert not a.fast_terminal_two_card  # demoted -> no cEDH escalation


def test_determinism_fn_uses_commander_text(make_card):
    report = parse_response({"results": {"included": [
        _variant(["Cmdr", "Piece"], ["Win the game"], manaValueNeeded=1),
    ]}})
    cmd = make_card("Cmdr", oracle_text="Each opponent chooses a card.")
    piece = make_card("Piece", oracle_text="Draw a card.")
    det_fn = make_determinism_fn([(piece, 1)], [cmd])  # cmd only in the commanders list
    a = assess_combos(report, frozenset({"Cmdr"}), determinism_fn=det_fn)
    assert a.nondeterministic_count == 1


def test_omitting_determinism_fn_leaves_it_unjudged():
    report = parse_response({"results": {"included": [
        _variant(["A", "B"], ["Win the game"], manaValueNeeded=1),
    ]}})
    a = assess_combos(report)  # Layer 1 only
    assert a.nondeterministic_count == 0
    assert a.grades[0].determinism is None
