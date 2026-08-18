"""Shared test fixtures. Tests are offline (invariant #5): cards are synthetic."""

import pytest

from mythgauntlet.model.card import Card
from mythgauntlet.semantics.store import SemanticsStore


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


@pytest.fixture(scope="session")
def empty_store(tmp_path_factory):
    """A SemanticsStore that is ACTUALLY empty, so rung-1 tests test rung 1.

    `SemanticsStore()` with no arguments resolves `compiler.compiled_dir()`, which reads
    `MYTHGAUNTLET_STORE`. On a developer machine that variable is set, so a bare
    `SemanticsStore()` loaded **31,042 compiled CCMs in 7.5 seconds** while the fixture
    using it was commented "empty -> everything resolves at rung 1 (offline)". Three
    consequences, all real:

    * the tests did not test what they claimed — they asserted rung-1 behaviour while
      running at rung 2/3;
    * CI (no store) and a dev machine (store present) exercised DIFFERENT code paths, so
      the suite meant something different depending on where it ran;
    * every instantiation re-read 31k files, which is where the intermittent OSError in
      `tests/engine/test_advisor.py` came from — it only appeared when the suite ran
      alongside another job also walking the store.

    Session-scoped: the directories are empty, so there is nothing to isolate between tests.
    """
    empty = tmp_path_factory.mktemp("empty_ccm_store")
    return SemanticsStore(authored=empty, compiled=empty)
