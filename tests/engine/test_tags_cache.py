"""`tags.analyze` is memoized on the card fields it reads.

The sim's finisher/go-off checks call `analyze` once per card per simulated game, so a
300-run analysis re-derived every card's regex tags ~150k times. That made one
`analyze_deck` cost ~25 s and pushed the upgrade advisor (97 analyses) far past its 900 s
HTTP timeout - "Suggest upgrades" never finished (2026-10-23).
"""
from dataclasses import replace

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags


def _card(**kw):
    base = dict(name="Llanowar Elves", mana_cost_str="{G}", type_line="Creature — Elf Druid",
                oracle_text="{T}: Add {G}.", power="1", toughness="1", edhrec_rank=100)
    base.update(kw)
    return Card(**base)


def test_repeat_analysis_does_the_work_once(monkeypatch):
    calls = []
    real = tags._analyze_uncached
    monkeypatch.setattr(tags, "_analyze_uncached", lambda c: calls.append(c.name) or real(c))
    tags.analyze_cache_clear()
    card = _card()
    first = tags.analyze(card)
    for _ in range(50):
        assert tags.analyze(card) == first
    # An equal but distinct Card object (the db and a test fixture both build these) hits too.
    assert tags.analyze(_card()) == first
    assert calls == ["Llanowar Elves"]


def test_any_field_analyze_reads_is_part_of_the_key():
    tags.analyze_cache_clear()
    card = _card()
    ramp = tags.analyze(card)
    assert ramp.ramp_sources == 1
    # Each field analyze reads must produce a fresh result, never a stale cached one.
    assert tags.analyze(replace(card, oracle_text="Draw a card.")).ramp_sources == 0
    assert tags.analyze(replace(card, type_line="Land — Forest")).ramp_sources == 0
    assert tags.analyze(replace(card, edhrec_rank=None)).impact != ramp.impact
    assert tags.analyze(replace(card, mana_cost_str="{5}{G}")) == tags._analyze_uncached(
        replace(card, mana_cost_str="{5}{G}"))
