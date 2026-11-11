"""The scouting report (B38): template-first, every line backed by a measured field. The guard
here is the spec's acceptance test -- walk the rendered text and fail on a number or a card name
that nothing in the /analyze response backs."""
from __future__ import annotations

import re

from mythgauntlet.ratings import scout

ANALYZE = {
    "insight": {
        "gameplan": "Krenko, Mob Boss: go-wide / tokens deck with 31 creatures, 11 ramp, 8 "
                    "interaction pieces. It floods the board and closes with a team-pump alpha "
                    "strike (~T6).",
        "pod_read": "Core (Bracket 2).",
        "strengths": ["Speed: fast (88/100), faster than 81% of Bracket 2 decks"],
        "weaknesses": ["Few answers to artifacts"],
    },
    "power_profile": {"bracket_estimate": 2, "bracket_label": "Core",
                      "bracket_reasons": ["0 Game Changers -> no Game Changer minimum"]},
    "kill_speed": {"games": 300, "text": "Unopposed, it kills one player in 97% of 300 games: "
                                        "median T7, middle half T6-T8."},
    "kill_methods": {"games": 300, "killing_games": 291,
                     "method_share": {"combat": 0.62, "commander": 0.30, "burn": 0.03},
                     "top_damage_cards": [{"name": "Krenko, Mob Boss token", "share": 0.41},
                                          {"name": "Goblin Chieftain", "share": 0.08}]},
    "card_verdicts": {
        "strong": [{"name": "Goblin Chieftain", "text": "Goblin Chieftain: the deck kills 0.4 "
                    "turn sooner with it in the 90 games it is drawn (paired simulation)"}],
        "weak": [{"name": "Mind Stone", "text": "Mind Stone: no measurable effect on the kill in "
                  "the 88 games it is drawn (paired simulation)"}]},
    "combos": {"checked": True, "items": [{"cards": ["Krenko, Mob Boss", "Thornbite Staff"],
                                           "produces": "infinite goblins",
                                           "needs_commander": True}]},
    "exposure": [{"key": "flyers", "text": "no creature with flying or reach: evasive attackers "
                                           "go unblocked"}],
    "dials": {"pace": {"band": "Fast", "reasons": ["ends 20% of games by T6"]}},
}
MATCHUPS = {"fidelity": "Tier-2 duels, directional.", "matchups": [
    {"label": "Control", "opponent": "Talrand", "games": 120, "winrate": 0.31, "low": 0.24,
     "high": 0.38, "verdict": "weak", "why": "loses the long game"},
    {"label": "Voltron", "opponent": "Sigarda", "games": 120, "winrate": 0.66, "low": 0.58,
     "high": 0.73, "verdict": "favoured", "why": ""}]}


def _backed_numbers(src) -> set[str]:
    """Every number a faithful line may print: the response's numbers in the forms the template
    writes them (as is, rounded, as a percentage) and any number inside an engine-written text."""
    out: set[str] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.update({str(v), str(round(v)), str(round(100 * v))})
            if isinstance(v, float):
                out.add(f"{v:g}")
        elif isinstance(v, str):
            out.update(re.findall(r"\d+(?:\.\d+)?", v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(src)
    return out


def test_every_number_in_the_report_is_measured():
    text = scout.render(scout.build(ANALYZE, MATCHUPS))
    backed = _backed_numbers([ANALYZE, MATCHUPS]) | {"90"}   # "90% interval" is the label
    for n in re.findall(r"\d+(?:\.\d+)?", text):
        assert n in backed, f"unbacked number {n!r} in:\n{text}"


def test_every_card_named_is_from_the_response():
    report = scout.build(ANALYZE, MATCHUPS)
    text = scout.render(report)
    names = {"Krenko, Mob Boss", "Krenko, Mob Boss token", "Goblin Chieftain", "Mind Stone",
             "Thornbite Staff", "Talrand", "Sigarda"}
    for n in names:
        assert n in str(ANALYZE) or n in str(MATCHUPS)
    for cap in re.findall(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)+", text):
        if cap in ("Game Changer", "Commander Spellbook", "Scout Matchups"):
            continue
        assert any(cap in n for n in names) or cap in str(ANALYZE) or cap in str(MATCHUPS), cap


def test_sections_and_caveats():
    r = scout.build(ANALYZE, MATCHUPS)
    assert r["bracket"]["bracket"] == 2
    assert any("Control decks (Talrand)" in w["text"] for w in r["weak_against"])
    assert any(s.startswith("Favoured against Voltron") for s in r["strengths"])
    assert any("creature combat 62%" in h for h in r["how_it_wins"])
    assert r["combos"] == ["Krenko, Mob Boss + Thornbite Staff: infinite goblins (needs the "
                           "commander)."]
    assert any("unopposed" in c for c in r["caveats"])
    # no matchups, combos unchecked: both are said, not implied
    bare = scout.build({**ANALYZE, "combos": {"checked": False}})
    assert any("not run" in c for c in bare["caveats"])
    assert any("not checked" in c for c in bare["caveats"])
    assert bare["combos"] == []
