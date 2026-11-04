"""parse_anthem: the closed, unconditional anthem template and nothing else (B3 phase 1)."""
from __future__ import annotations

import pytest

from mythgauntlet.semantics.compiler import parse_anthem


def test_flat_pt_anthem():
    assert parse_anthem("Creatures you control get +1/+1") == {
        "affects": "you", "others": False, "nontoken": False,
        "power": 1, "toughness": 1, "keywords": []}


def test_trailing_period_and_case_are_tolerated():
    assert parse_anthem("  Creatures you control get +2/+0.  ")["power"] == 2


def test_other_and_nontoken_flags():
    a = parse_anthem("Other nontoken creatures you control get +1/+1 and have vigilance")
    assert a["others"] is True and a["nontoken"] is True
    assert a["keywords"] == ["vigilance"]
    assert parse_anthem("Other creatures you control get +1/+1")["others"] is True
    assert parse_anthem("Nontoken creatures you control get +1/+1")["nontoken"] is True


def test_pt_with_keyword_list():
    a = parse_anthem("Creatures you control get +1/+1 and have first strike and lifelink")
    assert a["keywords"] == ["first strike", "lifelink"]


def test_negative_numbers_and_opponents():
    a = parse_anthem("Creatures your opponents control get -1/-1")
    assert a["affects"] == "opponents" and (a["power"], a["toughness"]) == (-1, -1)


def test_keyword_only_anthem():
    a = parse_anthem("Other creatures you control have vigilance")
    assert (a["power"], a["toughness"], a["keywords"]) == (0, 0, ["vigilance"])
    assert a["others"] is True


@pytest.mark.parametrize("note", [
    "",                                                                     # nothing
    "Creatures you control get +1/+1 as long as you control an artifact",    # conditional
    "Creatures you control get +1/+1 for each land you control",             # scaling
    "During your turn, creatures you control get +1/+1",                     # timing prefix
    "Goblin creatures you control get +1/+1",                               # subtype filter
    "Red creatures you control get +1/+1",                                  # colour filter
    "Attacking creatures you control get +1/+0",                            # state filter
    "Creatures you control get +X/+X",                                      # variable amount
    "Creatures you control get +1/+1 and have 'T: add one mana'",           # granted ability prose
    "Creatures you control have vigilance and lifelink typo",               # unknown keyword token
    "Creatures you control have vigilance and lifellink",                   # the Batterbone typo: reject ALL
    "Equipped creature gets +2/+2",                                          # that is parse_attach_grant
    "Enchanted creature has flying",
    "Artifact creatures you control get +1/+1",                             # type filter
    "Creatures you control",                                                 # no effect
    "All creatures get -1/-1",                                               # no controller: both sides
])
def test_out_of_scope_notes_decline_whole(note):
    assert parse_anthem(note) is None


def test_ward_and_protection_are_not_plain_keywords():
    # they need a parameter this shape cannot carry (same exclusion as attach grants)
    assert parse_anthem("Creatures you control have ward") is None
    assert parse_anthem("Creatures you control have protection from red") is None


# -- anthem_for_card: the note must be a whole printed line ----------------------------

from mythgauntlet.semantics.compiler import anthem_for_card  # noqa: E402


def test_whole_line_anthem_is_accepted():
    text = "Flash\nCreatures you control get +2/+2."
    assert anthem_for_card("Creatures you control get +2/+2", text)["power"] == 2


def test_modal_bullet_is_rejected():
    # Frostcliff Siege: only active if the Temur mode was chosen
    text = "As this enchantment enters, choose Jeskai or Temur.\n- Temur: Creatures you control get +1/+0 and have trample and haste."
    assert anthem_for_card("Creatures you control get +1/+0 and have trample and haste", text) is None


def test_ability_word_prefix_is_rejected_as_an_honest_undercount():
    text = "Trample\nDevastating Charge: Other creatures you control have trample."
    assert anthem_for_card("Other creatures you control have trample", text) is None


def test_reminder_text_is_ignored_when_matching_a_line():
    text = "Creatures you control get +1/+1. (They get bigger.)"
    assert anthem_for_card("Creatures you control get +1/+1", text) is not None


def test_empty_oracle_text_declines():
    assert anthem_for_card("Creatures you control get +1/+1", "") is None
