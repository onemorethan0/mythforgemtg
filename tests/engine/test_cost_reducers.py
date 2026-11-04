"""Static cost reducers: the strict, deterministic parser (B3). Wiring it into tier0 was tried and
REVERTED by the bracket guard (docs/BACKLOG.md B3), so only the parser ships."""
from __future__ import annotations

import pytest

from mythgauntlet.semantics.compiler import parse_cost_reducer


def test_parser_reads_the_closed_generic_shape():
    assert parse_cost_reducer("Instant and sorcery spells you cast cost {1} less to cast.") == {
        "subject": "instant and sorcery spells", "amount": 1}
    assert parse_cost_reducer("Creature spells you cast cost {2} less to cast") == {
        "subject": "creature spells", "amount": 2}
    assert parse_cost_reducer("Spells you cast cost {1} less to cast.")["subject"] == "spells"
    assert parse_cost_reducer("White spells you cast cost {1} less to cast.")["subject"] == "white spells"


@pytest.mark.parametrize("line", [
    "",
    "Spells cost {1} less to cast.",                                       # all players (Helm of Awakening)
    "Spells you cast cost {W} less to cast.",                              # coloured symbol
    "Spells you cast cost {X} less to cast.",                              # X
    "Spells you cast cost {1} more to cast.",                              # an increase
    "Goblin spells you cast cost {1} less to cast.",                       # subtype filter
    "Legendary spells you cast cost {1} less to cast.",                    # filter not in vocabulary
    "Spells you cast cost {1} less to cast as long as you control a Forest.",
    "This spell costs {1} less to cast for each creature you control.",    # self reduction
    "Creature spells you cast cost {1} less to cast for each Elf you control.",
    "Spells your opponents cast cost {1} less to cast.",
])
def test_parser_declines_everything_else(line):
    assert parse_cost_reducer(line) is None
