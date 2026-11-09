"""B35: matchups against the reference field -- verdicts need the interval to clear 50%."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

from mythgauntlet.ratings import matchups as mu


def test_verdicts_need_the_interval_to_clear_50():
    assert mu.verdict(0.30, 0.22, 0.39) == "weak"
    assert mu.verdict(0.38, 0.30, 0.52) == "even"      # below 40% but the interval reaches 50%
    assert mu.verdict(0.70, 0.62, 0.78) == "favoured"
    assert mu.verdict(0.62, 0.48, 0.70) == "even"      # the interval reaches below 50%
    assert mu.verdict(0.50, 0.42, 0.58) == "even"


def test_why_names_how_the_losses_came():
    res = NS(games=120, avg_turns=9.4, win_methods_b={"combat": 50, "combo": 10})
    assert mu.why_lost(res, "go-wide tokens") == ("50 of its 60 losses to go-wide tokens came "
                                                  "by combat; games ran about 9 turns")
    clean = NS(games=120, avg_turns=8.0, win_methods_b={})
    assert mu.why_lost(clean, "control / stax-light") == ("never lost to control / stax-light "
                                                          "in 120 games")


def test_run_plays_every_field_deck_and_sorts_the_verdicts(tmp_path, make_card, forest):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (corpus / name).write_text("Commander:\n1 Forest\n\nDeck:\n1 Forest\n", encoding="utf-8")
    field = tmp_path / "field.json"
    field.write_text(json.dumps({"brackets": {"2": {
        "go_wide": {"deck": "a.txt", "commander": "Tokens Guy"},
        "control": {"deck": "b.txt", "commander": "Control Gal"},
        "midrange": {"deck": "c.txt", "commander": "Beef"},
        "voltron": {"deck": "missing.txt", "commander": "Gone"},     # skipped, not a crash
    }}}), encoding="utf-8")
    wins = iter([20, 100, 60])

    def fake_duel(cards_a, cmd_a, cards_b, cmd_b, cfg, store=None, combos_a=(), combos_b=()):
        w = next(wins)
        return NS(games=cfg.games, wins_a=w, avg_turns=10.0,
                  win_methods_b={"combat": cfg.games - w})

    class DB:
        def get(self, name):
            return forest if name == "Forest" else None

    report = mu.run([(forest, 99)], None, 2, db=DB(), store=None, games=120,
                    corpus=corpus, field_path=field, duel_fn=fake_duel,
                    combos_fn=lambda resolved: ())
    by = {m.archetype: m for m in report.matchups}
    assert set(by) == {"go_wide", "control", "midrange"}
    assert by["go_wide"].verdict == "weak" and by["control"].verdict == "favoured"
    assert by["midrange"].verdict == "even"
    assert report.weak_against == ["go-wide tokens"]
    assert report.favoured_against == ["control / stax-light"]
    assert "directional" in report.fidelity


def test_no_field_file_means_no_matchups(tmp_path):
    assert mu.load_field(2, tmp_path / "none.json") == {}


def test_reference_field_archetype_rule_order():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "build_reference_field",
        Path(__file__).resolve().parents[2] / "scripts" / "build_reference_field.py")
    brf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brf)
    a = brf.archetype_of
    assert a("Midrange goodstuff", [], 0.6) == "voltron"          # commander kills first
    assert a("Combo", ["reanimator", "tokens"], 0.0) == "graveyard"
    assert a("Control", ["tokens", "graveyard"], 0.0) == "graveyard"   # top two themes count
    assert a("Midrange goodstuff", ["spellslinger"], 0.0) == "spellslinger"
    assert a("Combo", [], 0.0) == "artifact_combo"
    assert a("Go-wide / tokens", [], 0.0) == "go_wide"
    assert a("Control", [], 0.0) == "control"
    assert a("Creature aggro", ["lifegain"], 0.0) == "midrange"
