"""Regression tests for the 2026-11-07 full review (docs/REVIEW_2026-11-07_full.md).

Each test names the defect it pins. No network: Scryfall, EDHREC and the engine are faked.
"""
from __future__ import annotations

import itertools
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import commander_analysis as ca
import deck_builder
import deck_legality
import server
from api import routes_decks, routes_strength, state

client = TestClient(server.app)
JOB = "0123456789abcdef"


# ── Partner—<group> (2025+ printings) ─────────────────────────────────────────────────

def _c(name, oracle="", type_line="Legendary Creature — Human", **kw):
    return {"name": name, "oracle_text": oracle, "type_line": type_line, **kw}


KRATOS = _c("Kratos, Stoic Father", "Partner—Father & son (You can have two commanders if "
                                    "both have this ability.)")
ATREUS = _c("Atreus, Impulsive Son", "Partner—Father & son (You can have two commanders if "
                                     "both have this ability.)")
JOEL = _c("Joel, Resolute Survivor", "Partner—Survivors (You can have two commanders if both "
                                     "have this ability.)")
THRASIOS = _c("Thrasios, Triton Hero", "{4}: Scry 1.\nPartner (You can have two commanders "
                                       "if both have partner.)")
SOPHINA = _c("Sophina, Spearsage Deserter", "Partner—Friends forever (You can have two "
                                            "commanders if both have this ability.)")
KRAV = _c("Krav, the Unredeemed", "Friends forever (You can have two commanders if both have "
                                  "friends forever.)")


def test_named_partner_groups_pair_only_with_their_own_group():
    """Kratos + Thrasios used to be accepted: 'Partner—Father & son' fell through to the
    plain-Partner branch."""
    assert ca.partner_mechanic(KRATOS) == ca.PARTNER_GROUP
    assert ca.can_pair(KRATOS, ATREUS) == (True, "")
    assert not ca.can_pair(KRATOS, THRASIOS)[0]
    assert not ca.can_pair(THRASIOS, KRATOS)[0]
    assert not ca.can_pair(KRATOS, JOEL)[0]


def test_partner_friends_forever_is_still_friends_forever():
    assert ca.partner_mechanic(SOPHINA) == ca.FRIENDS_FOREVER
    assert ca.can_pair(SOPHINA, KRAV) == (True, "")


# ── Commander eligibility reads the FRONT face (CR 712.8a) ────────────────────────────

WESTVALE = {"name": "Westvale Abbey // Ormendahl, Profane Prince",
            "type_line": "Land // Legendary Creature — Demon",
            "card_faces": [{"type_line": "Land", "oracle_text": "{T}: Add {C}."},
                           {"type_line": "Legendary Creature — Demon",
                            "oracle_text": "Flying, lifelink"}]}
DELVER_LIKE_LEGEND = {"name": "Front // Back", "type_line": "Legendary Creature — Human // "
                      "Legendary Creature — Werewolf",
                      "card_faces": [{"type_line": "Legendary Creature — Human"},
                                     {"type_line": "Legendary Creature — Werewolf"}]}


@pytest.mark.parametrize("module", ["commander_analysis", "buildable", "collection_pool"])
def test_a_back_face_legend_is_not_a_commander(module):
    mod = __import__(module)
    assert not mod.is_commander_eligible(WESTVALE)
    assert mod.is_commander_eligible(DELVER_LIKE_LEGEND)


def test_import_uses_the_same_definition():
    import deck_import
    assert not deck_import._is_legendary_creature(WESTVALE)


# ── The builder never drafts a command-zone card into the library ─────────────────────

class _FakeClient:
    """Every search returns the partner first, then endless unique filler."""

    def __init__(self, partner):
        self.partner = partner
        self.n = itertools.count()

    def get_cards_collection(self, names):
        return {}

    def search_cards_paged(self, query, max_results=60):
        if "type:land" not in query and "otag:" in query and "-type:land" not in query:
            return []                                    # nonbasic land tiers: none
        filler = [{"name": f"Filler {next(self.n)}", "type_line": "Artifact", "cmc": 2,
                   "mana_cost": "{2}", "oracle_text": "", "color_identity": [],
                   "legalities": {"commander": "legal"}} for _ in range(max_results)]
        return [self.partner] + filler

    def search_cards(self, query):
        return {"data": []}


@pytest.fixture
def stub_basics():
    saved = dict(deck_builder._BASIC_LAND_CACHE)
    for name, sym in {"Plains": "W", "Island": "U", "Swamp": "B", "Forest": "G"}.items():
        deck_builder._BASIC_LAND_CACHE[name] = {
            "name": name, "type_line": f"Basic Land — {name}", "mana_cost": "", "cmc": 0,
            "oracle_text": "", "color_identity": [sym], "produced_mana": [sym]}
    yield
    deck_builder._BASIC_LAND_CACHE.clear()
    deck_builder._BASIC_LAND_CACHE.update(saved)


def test_a_partner_is_never_drafted_into_the_library(stub_basics, monkeypatch):
    """Thrasios is a top WUBG card: a Tymna + Thrasios build drafted it as a draw/ramp pick,
    then the caller appended it again as the partner, giving '2x Thrasios'."""
    monkeypatch.setattr(deck_builder.edhrec_lift, "lift_map", lambda name: {})
    tymna = {"name": "Tymna the Weaver", "type_line": "Legendary Creature — Human Cleric",
             "oracle_text": "Partner", "color_identity": ["W", "B"], "cmc": 3,
             "mana_cost": "{1}{W}{B}"}
    thrasios = {"name": "Thrasios, Triton Hero", "type_line": "Legendary Creature — Merfolk",
                "oracle_text": "Partner", "color_identity": ["G", "U"], "cmc": 2,
                "mana_cost": "{G}{U}", "legalities": {"commander": "legal"}}
    profile = ca.build_commander_profile(tymna, [thrasios])
    b = deck_builder.DeckBuilder(_FakeClient(thrasios))
    library = b.build(profile, bracket=3, partner_names=[thrasios["name"]])
    assert len(library) == 98
    assert "Thrasios, Triton Hero" not in {c["name"] for c in library}


# ── Partner decks: History count, engine payload, export, import-save ─────────────────

def _stored(name, colors=(), qty=1, tl="Artifact"):
    return {"original_name": name, "themed_name": name, "quantity": qty,
            "colors": list(colors), "type_line": tl, "original_type_line": tl,
            "render_key": name.replace(" ", "_")}


@pytest.fixture
def partner_deck(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    d = tmp_path / "renders" / JOB
    d.mkdir(parents=True)
    deck = [_stored(f"Card {i}") for i in range(61)] + [_stored("Plains", ["W"], 37,
                                                                "Basic Land — Plains")]
    deck.append(_stored("Thrasios, Triton Hero", ["G", "U"], 1, "Legendary Creature — Merfolk"))
    data = {"status": "done",
            "commander": {"original_name": "Tymna the Weaver", "themed_name": "T",
                          "colors": ["W", "B"], "type_line": "Legendary Creature — Human"},
            "partners": ["Thrasios, Triton Hero"], "deck": deck, "is_commander_deck": True}
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    with patch.dict(state._jobs, {}, clear=True):
        yield d


def test_history_counts_a_partner_deck_as_100(partner_deck):
    rows = client.get("/api/decks").json()
    assert [r["card_count"] for r in rows if r["job_id"] == JOB] == [100]


def test_engine_payload_lists_the_partner_once():
    lines = routes_strength._deck_to_lines(
        {"name": "Tymna the Weaver"},
        [{"name": "Sol Ring", "quantity": 1}, {"name": "Thrasios, Triton Hero", "quantity": 1}],
        [{"name": "Thrasios, Triton Hero"}])
    assert lines.count("Thrasios, Triton Hero") == 1
    assert lines.index("Thrasios") < lines.index("Deck:")


def test_export_keeps_the_partner_in_the_command_zone(partner_deck):
    body = client.get(f"/api/deck/{JOB}/export/decklist").text
    assert body.startswith("Commander: Tymna the Weaver\nCommander: Thrasios, Triton Hero\n")
    assert "1 Thrasios" not in body
    import deck_import
    raw = deck_import._parse_text(body)
    assert raw.commander_names == ["Tymna the Weaver", "Thrasios, Triton Hero"]
    assert sum(n for _, n in raw.card_entries) == 98


def test_import_save_persists_partners(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    tymna = {"name": "Tymna the Weaver", "type_line": "Legendary Creature", "color_identity": ["W", "B"]}
    thras = {"name": "Thrasios, Triton Hero", "type_line": "Legendary Creature",
             "color_identity": ["G", "U"]}
    import deck_import
    fake = deck_import.ImportedDeck(name="x", source="text", commander=tymna,
                                    deck=[{"name": "Sol Ring", "type_line": "Artifact"}],
                                    partners=[thras])
    monkeypatch.setattr(routes_decks.deck_import, "import_deck", lambda *a, **k: fake)
    r = client.post("/api/deck/import-save", json={"source": "x"})
    assert r.status_code == 200
    saved = json.loads((tmp_path / "renders" / r.json()["job_id"] / "deck.json").read_text("utf-8"))
    assert saved["partners"] == ["Thrasios, Triton Hero"]


# ── apply-swap enforces the rules the advisor already follows ─────────────────────────

class _Scry:
    def __init__(self, *cards):
        self.cards = {c["name"].casefold(): c for c in cards}

    def get_card_by_name(self, name, fuzzy=False):
        return self.cards.get(name.casefold())


def _card(name, ci=(), tl="Artifact", legal="legal", **kw):
    return {"name": name, "type_line": tl, "color_identity": list(ci), "mana_cost": "{1}",
            "cmc": 1, "oracle_text": "", "legalities": {"commander": legal}, **kw}


def _swap(cut, add, scry):
    with patch.object(routes_strength, "_scryfall", scry):
        return client.post(f"/api/deck/{JOB}/apply-swap", json={"cut": cut, "add": add})


def test_swap_refuses_an_off_identity_card(partner_deck):
    r = _swap("Card 1", "Lightning Bolt", _Scry(_card("Lightning Bolt", ["R"], "Instant")))
    assert r.status_code == 400 and "colour identity" in r.json()["detail"]


def test_swap_allows_a_partner_colour(partner_deck):
    r = _swap("Card 1", "Counterspell", _Scry(_card("Counterspell", ["U"], "Instant")))
    assert r.status_code == 200


def test_swap_refuses_a_banned_card(partner_deck):
    r = _swap("Card 1", "Mana Crypt", _Scry(_card("Mana Crypt", legal="banned")))
    assert r.status_code == 400 and "not legal" in r.json()["detail"]


def test_swap_refuses_cutting_a_partner(partner_deck):
    r = _swap("Thrasios, Triton Hero", "Sol Ring", _Scry(_card("Sol Ring")))
    assert r.status_code == 400 and "commander" in r.json()["detail"]


def test_swap_can_add_another_basic(partner_deck):
    r = _swap("Card 1", "Plains", _Scry(_card("Plains", ["W"], "Basic Land — Plains")))
    assert r.status_code == 200
    deck = r.json()["deck"]
    assert next(c for c in deck if c["original_name"] == "Plains")["quantity"] == 38
    assert sum(c.get("quantity", 1) for c in deck) == 99


def test_swap_recomputes_stats(partner_deck):
    r = _swap("Card 1", "Counterspell", _Scry(_card("Counterspell", ["U"], "Instant")))
    stats = r.json()["stats"]
    assert stats["total_cards"] == 100
    assert stats["type_counts"].get("Instant") == 1
    on_disk = json.loads((partner_deck / "deck.json").read_text("utf-8"))
    assert on_disk["stats"]["type_counts"].get("Instant") == 1


# ── Deck legality ──────────────────────────────────────────────────────────────────────

def _deck(n, **kw):
    return [_card(f"Card {i}", **kw) for i in range(n)]


CMDR = _card("Atraxa", ["W", "U", "B", "G"], "Legendary Creature — Phyrexian Angel")


def test_a_legal_deck_is_legal():
    rep = deck_legality.check(CMDR, _deck(99))
    assert rep["legal"] and rep["total"] == 100 and rep["unverified"] == 0


def test_size_singleton_identity_and_ban_list_are_each_reported():
    deck = _deck(97) + [_card("Card 3"), _card("Lightning Bolt", ["R"], "Instant"),
                        _card("Mana Crypt", legal="banned")]
    rep = deck_legality.check(CMDR, deck)
    kinds = {i["kind"] for i in rep["issues"]}
    assert kinds == {"size", "singleton", "identity", "legality"}
    assert rep["total"] == 101


def test_basics_and_any_number_cards_are_exempt_from_singleton():
    deck = _deck(60) + [_card("Forest", ["G"], "Basic Snow Land — Forest", quantity=20),
                        _card("Relentless Rats", ["B"], "Creature — Rat", quantity=19,
                              oracle_text="A deck can have any number of cards named "
                                          "Relentless Rats.")]
    assert deck_legality.check(CMDR, deck)["legal"]


def test_seven_dwarves_cap_is_seven():
    dwarf = dict(oracle_text="A deck can have up to seven cards named Seven Dwarves.")
    ok = _deck(92) + [_card("Seven Dwarves", ["R"], "Creature", quantity=7, **dwarf)]
    bad = _deck(91) + [_card("Seven Dwarves", ["R"], "Creature", quantity=8, **dwarf)]
    rcmdr = _card("Krenko", ["R"], "Legendary Creature — Goblin")
    assert deck_legality.check(rcmdr, ok)["legal"]
    assert {i["kind"] for i in deck_legality.check(rcmdr, bad)["issues"]} == {"singleton"}


def test_partner_in_deck_is_the_command_zone_not_a_library_card():
    thras = _card("Thrasios, Triton Hero", ["G", "U"], "Legendary Creature — Merfolk",
                  oracle_text="Partner")
    tymna = _card("Tymna the Weaver", ["W", "B"], "Legendary Creature — Human",
                  oracle_text="Partner")
    deck = _deck(97) + [_card("Counterspell", ["U"], "Instant"), thras]
    rep = deck_legality.check(tymna, deck, [{"name": thras["name"]}])
    assert rep["legal"], rep


def test_illegal_pairing_and_non_commander_face_are_reported():
    rep = deck_legality.check(KRATOS | {"color_identity": []}, _deck(98), [THRASIOS])
    assert "pairing" in {i["kind"] for i in rep["issues"]}
    rep = deck_legality.check(_card("Sol Ring"), _deck(99))
    assert "commander" in {i["kind"] for i in rep["issues"]}


def test_unknown_ban_status_is_unverified_not_legal_or_banned():
    deck = [{"name": f"C{i}", "type_line": "Artifact", "color_identity": []} for i in range(99)]
    rep = deck_legality.check(CMDR, deck)
    assert rep["legal"] and rep["unverified"] == 99


def test_compute_stats_carries_legality_and_skips_single_cards():
    assert deck_builder.compute_stats(CMDR, _deck(99))["legality"]["legal"]
    assert deck_builder.compute_stats(CMDR, [])["legality"] == {}


# ── Import never seats a token; legacy decks get a legality block on load ────────────

def test_import_skips_tokens_with_a_reason():
    import deck_import

    class _S:
        def get_cards_collection(self, names):
            return {"sol ring": {"name": "Sol Ring", "type_line": "Artifact", "layout": "normal"},
                    "dinosaur // treasure": {"name": "Dinosaur // Treasure",
                                             "type_line": "Token Creature — Dinosaur // Token Artifact — Treasure",
                                             "layout": "double_faced_token"}}

    raw = deck_import.RawDeck(name="x", source="text", commander_names=[],
                              card_entries=[("Sol Ring", 1), ("Dinosaur // Treasure", 1)])
    imp = deck_import._resolve(raw, _S())
    assert [c["name"] for c in imp.deck] == ["Sol Ring"]
    assert imp.unresolved == ["Dinosaur // Treasure (token, not a deck card)"]


def test_backfill_counts_a_missing_partner_without_guessing_identity():
    """Pre-partner_count builds stored 99 library cards + partners=[...] with the partner
    never appended: 101 cards. Size is the honest finding; identity must stand down."""
    data = {"commander": {"original_name": "Tymna the Weaver", "colors": ["W", "B"],
                          "type_line": "Legendary Creature — Human"},
            "partners": ["Thrasios, Triton Hero"],
            "deck": [_stored(f"Card {i}", ["U"]) for i in range(99)],
            "stats": {}}
    state._backfill_legality(data)
    kinds = {i["kind"] for i in data["stats"]["legality"]["issues"]}
    assert kinds == {"size"} and data["stats"]["legality"]["total"] == 101


# ── Role-query audit (2026-11-07, docs/REVIEW_2026-11-07_full.md section 8) ──────────────

def _top_level_or(q: str) -> bool:
    depth, quoted = 0, False
    for i, ch in enumerate(q):
        if ch == '"':
            quoted = not quoted
        if quoted:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and q[i:i + 4] == " OR ":
            return True
    return False


def test_every_appended_to_query_is_one_group():
    """_fetch_role / the theme step APPEND id<=... legal:commander -type:land. With an OR at
    the top level those filters bind to the last branch only: a draft of the protection
    rewrite returned Counterspell for a mono-white deck."""
    from commander_analysis import THEME_SYNERGY_QUERIES
    queries = dict(deck_builder.ROLE_QUERIES, **{k: v for k, v in THEME_SYNERGY_QUERIES.items() if v})
    assert [k for k, q in queries.items() if _top_level_or(q)] == []


def _o_terms(query):
    import re
    return re.findall(r'o:"([^"]+)"', query)


def test_ramp_query_has_no_bare_add_substring():
    """o:"add" matched "additional cost" / "in addition to" (Eldritch Evolution, Neoform)."""
    terms = _o_terms(deck_builder.ROLE_QUERIES["ramp"])
    assert "add" not in terms and "mana" not in terms
    for real in ("add {g}", "adds an additional {g}", "add three mana", "add x {r}",
                 "add six {r}", "play an additional land", "add twice that much {g}"):
        assert any(t in real for t in terms), real
    for fake in ("as an additional cost to cast this spell", "in addition to its other types",
                 "add a lore counter"):
        assert not any(t in fake for t in terms), fake


def test_protection_query_gates_self_only_creatures_and_finisher_skips_stax():
    q = deck_builder.ROLE_QUERIES["protection"]
    assert '-type:creature OR o:"you control" OR o:"target" OR o:"another"' in q
    assert 'o:"ward"' not in q
    assert '-o:"can\'t win the game"' in deck_builder.ROLE_QUERIES["finisher"]


@pytest.mark.parametrize("text,type_line,role", [
    ("Destroy target nonartifact creature.", "Instant", "removal"),              # Go for the Throat
    ("Destroy target nonblack creature. It can't be regenerated.", "Instant", "removal"),
    ("When this creature enters, destroy target nonartifact, nonblack creature.",
     "Creature — Elemental", "removal"),                                          # Shriekmaw
    ("{T}: Destroy target tapped creature.", "Creature — Human Assassin", "removal"),
    ("When this creature enters, creatures you control gain trample and get +X/+X until end "
     "of turn, where X is the number of creatures you control.", "Creature — Beast", "finisher"),
    ("Whenever enchanted land is tapped for mana, its controller adds an additional {G}.",
     "Enchantment — Aura", "ramp"),                                               # Wild Growth
])
def test_classifier_reads_qualified_removal_x_overruns_and_land_auras(text, type_line, role):
    import collection_pool
    assert role in collection_pool.classify({"oracle_text": text, "type_line": type_line})


def test_classifier_still_rejects_self_protection_and_non_removal():
    import collection_pool
    assert "protection" not in collection_pool.classify(
        {"oracle_text": "Hexproof\n{T}: Add one mana of any color.",
         "type_line": "Creature — Dryad"})                                         # Sylvan Caryatid
    assert "removal" not in collection_pool.classify(
        {"oracle_text": "Destroy all creatures. They can't be regenerated.", "type_line": "Sorcery"})
