"""Re-validating ACCEPTED CCMs against today's gates (`mythgauntlet ccm-recheck`).

The gap this closes is structural. The compile pipeline decides what to re-attempt from
`prompt_version`: `--refresh-stale` reaches cards accepted under an OLDER prompt, and
`--retry-quarantined` / `--retry-blocked` reach the two failure pools. Nothing reaches a
card that is **accepted at the current prompt version and has since been invalidated by a
gate change** — so a new gate only ever protected FUTURE compiles while the ~31k CCMs
already stored kept whatever defect it was written to catch.

Run live against the real store the day it was written, it found 269 (0.85%) newly
failing across SIX classes — and only 229 were the duration gate that prompted it. The
other 40 carried defects from gates that had existed for months, invisible because
nothing ever re-asked.

Offline and synthetic: envelopes and the card lookup are supplied by the caller, the same
contract `health.analyze_failures` has with the ledger.
"""

from __future__ import annotations

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import recheck


def _card(name: str, text: str, type_line: str = "Instant", cost: str = "{1}{G}") -> Card:
    return Card(name=name, mana_cost_str=cost, type_line=type_line, oracle_text=text)


def _env(card: Card, abilities: list[dict], **doc_extra) -> dict:
    doc = {
        "ccm_version": 1,
        "name": card.name,
        "cost": {"mana": card.mana_cost_str},
        "types": [card.type_line.split()[0]],
        "abilities": abilities,
    }
    doc.update(doc_extra)
    return {"card": {"name": card.name}, "ccm": doc}


def _lookup(*cards: Card):
    index = {c.name: c for c in cards}
    return index.get


GOOD = _card("Titanic Growth", "Target creature gets +4/+4 until end of turn.")
GOOD_ABILITIES = [{"kind": "spell_effect", "effects": [
    {"op": "pump", "power": 4, "toughness": 4, "duration": "until end of turn",
     "target": {"type": "creature", "count": 1}}]}]

BAD = _card("Aberrant Manawurm", "This creature gets +2/+0 until end of turn.")
BAD_ABILITIES = [{"kind": "spell_effect", "effects": [
    {"op": "pump", "power": 2, "toughness": 0,
     "target": {"type": "creature", "count": 1}}]}]  # duration dropped


def test_a_still_valid_ccm_is_not_reported():
    result = recheck.recheck_accepted([_env(GOOD, GOOD_ABILITIES)], _lookup(GOOD))
    assert result["checked"] == 1
    assert result["failing"] == 0
    assert result["classes"] == []


def test_a_ccm_a_new_gate_invalidates_is_reported_with_its_class():
    result = recheck.recheck_accepted([_env(BAD, BAD_ABILITIES)], _lookup(BAD))
    assert result["checked"] == 1
    assert result["failing"] == 1
    assert result["failing_names"] == ["Aberrant Manawurm"]
    (cls,) = result["classes"]
    assert cls["gate"] == "cross_check"
    assert "PERMANENT" in cls["message"]
    assert cls["examples"] == ["Aberrant Manawurm"]


def test_failures_are_bucketed_by_class_not_listed_per_card():
    """Same triage habit as ccm-health: a class with 200 cards is one row, not 200."""
    other = _card("Alacrian Jaguar", "This creature gets +2/+2 until end of turn.")
    result = recheck.recheck_accepted(
        [_env(BAD, BAD_ABILITIES), _env(other, BAD_ABILITIES)], _lookup(BAD, other))
    assert result["failing"] == 2
    assert len(result["classes"]) == 1
    assert result["classes"][0]["count"] == 2


def test_a_card_missing_from_the_DB_is_counted_not_silently_skipped():
    """A stale card DB would otherwise read as a clean bill of health."""
    result = recheck.recheck_accepted([_env(BAD, BAD_ABILITIES)], _lookup())
    assert result["checked"] == 0
    assert result["unresolved"] == 1
    assert result["failing"] == 0


def test_a_malformed_stored_document_is_a_finding_not_a_crash():
    """31k files of LLM output; one bad shape must not take the diagnostic down."""
    result = recheck.recheck_accepted(
        [None, {"card": {"name": "X"}}, {"ccm": "not a dict"},
         _env(GOOD, GOOD_ABILITIES)],
        _lookup(GOOD))
    assert result["checked"] == 1
    assert result["failing"] == 0


def test_failing_names_are_sorted_so_the_worklist_is_stable():
    """The names feed `compile-names`; an unstable order makes two runs undiffable."""
    a = _card("Zebra", "This creature gets +1/+1 until end of turn.")
    b = _card("Aardvark", "This creature gets +1/+1 until end of turn.")
    result = recheck.recheck_accepted(
        [_env(a, BAD_ABILITIES), _env(b, BAD_ABILITIES)], _lookup(a, b))
    assert result["failing_names"] == ["Aardvark", "Zebra"]
