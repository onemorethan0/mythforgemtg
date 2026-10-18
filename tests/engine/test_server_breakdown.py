"""`/breakdown` -- the Deck Mentor's measurements as one block for charts and the deck view's
group-by-role. Offline via injected synthetic stores. The property that matters: the block
is the mentor's OWN tool output, so a chart can never disagree with a mentor answer."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mythgauntlet import server as server_mod  # noqa: E402
from mythgauntlet.data.scryfall import CardDb  # noqa: E402
from mythgauntlet.mentor import tools as mentor_tools  # noqa: E402
from mythgauntlet.mentor.tools import MentorContext  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402
from mythgauntlet.sim.tier0 import SimConfig  # noqa: E402

DECK = """
Commander:
1 Test Commander

Deck:
30 Forest
20 Grizzly Bears
4 Mana Ring
3 Snuff Out Test
"""


@pytest.fixture
def setup(tmp_path, make_card, forest, bear, sol_ring_like, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path / "suite"))
    commander = make_card(
        "Test Commander", mana_cost="{2}{G}", type_line="Legendary Creature — Beast",
        color_identity=("G",),
    )
    kill = make_card(
        "Snuff Out Test", mana_cost="{1}{G}", type_line="Instant",
        oracle_text="Destroy target creature.", colors=("G",), color_identity=("G",),
    )
    db = CardDb([forest, bear, sol_ring_like, commander, kill])
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    app = server_mod.create_app(db=db, store=store, mentor_cr=None, mentor_rulings_db=None)
    return TestClient(app), db, store


def test_breakdown_works_without_the_rules_corpus(setup):
    client, _, _ = setup
    resp = client.post("/breakdown", json={"deck": DECK, "runs": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"roles", "removal", "curve", "manabase", "cards", "commanders"}


def test_breakdown_roles_are_the_mentor_role_summary(setup):
    client, db, store = setup
    body = client.post("/breakdown", json={"deck": DECK, "runs": 5}).json()
    resolved = resolve(Deck.parse_text(DECK, name="deck"), db)
    ctx = MentorContext(card_db=db, cr=None, rulings_db={}, resolved=resolved,
                        cfg=SimConfig(runs=5, seed=42), store=store)
    mentor = mentor_tools.tool_get_deck_stats(ctx).data["role_summary"]
    assert body["roles"] == mentor
    removal = next(r for r in body["roles"]["rows"] if r["role"] == "removal")
    assert removal["cards"] == 3


def test_breakdown_cards_carry_roles_and_quantities(setup):
    client, _, _ = setup
    cards = {c["name"]: c for c in client.post("/breakdown", json={"deck": DECK, "runs": 5}).json()["cards"]}
    assert cards["Test Commander"]["commander"] is True
    assert cards["Forest"] == {"name": "Forest", "qty": 30, "roles": ["land"], "commander": False}
    assert "removal" in cards["Snuff Out Test"]["roles"]
    assert "ramp" in cards["Mana Ring"]["roles"]


def test_breakdown_removal_counts_by_type(setup):
    client, _, _ = setup
    removal = client.post("/breakdown", json={"deck": DECK, "runs": 5}).json()["removal"]
    assert removal["counts_by_type"]["creature"]["answers"] >= 1
    assert "Snuff Out Test" in removal["answers_by_type"]["creature"]


def test_breakdown_400_on_unresolvable_deck(setup):
    client, _, _ = setup
    resp = client.post("/breakdown", json={"deck": "Commander:\n1 Nothing Resolves Here\n"})
    assert resp.status_code == 400
