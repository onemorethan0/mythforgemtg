"""Shared test fixtures. Tests are offline (invariant #5): cards are synthetic."""

import pytest

from mythgauntlet.model.card import Card


def _make_card(
    name: str,
    mana_cost: str = "",
    type_line: str = "Creature — Bear",
    oracle_text: str = "",
    produced_mana: tuple[str, ...] = (),
    color_identity: tuple[str, ...] = (),
    colors: tuple[str, ...] = (),
    edhrec_rank: int | None = None,
) -> Card:
    return Card(
        name=name,
        mana_cost_str=mana_cost,
        type_line=type_line,
        oracle_text=oracle_text,
        produced_mana=produced_mana,
        color_identity=color_identity,
        colors=colors,
        edhrec_rank=edhrec_rank,
    )


@pytest.fixture
def make_card():
    return _make_card


@pytest.fixture
def forest():
    return _make_card(
        "Forest", type_line="Basic Land — Forest", produced_mana=("G",), color_identity=("G",)
    )


@pytest.fixture
def bear():
    return _make_card("Grizzly Bears", mana_cost="{1}{G}", colors=("G",), color_identity=("G",))


@pytest.fixture
def sol_ring_like():
    return _make_card(
        "Mana Ring",
        mana_cost="{1}",
        type_line="Artifact",
        oracle_text="{T}: Add {C}{C}.",
        produced_mana=("C",),
    )
