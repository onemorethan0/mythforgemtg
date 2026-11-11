"""The deck scouting report (B38, docs/SPEC_deck_scouting_report.md).

Assembles what B30-B37 already measure -- the `/analyze` response with card stats -- into one
report: what the deck is, its bracket, how fast and how it kills, what it is good at and weak
against, its strong and weak cards (the shared cut ranking), its combos, and the caveats.

TEMPLATE FIRST. Every line is either an engine-written sentence copied verbatim (insight, kill
speed, exposure, verdicts: each already built from that deck's own measurements) or a template
filled ONLY from fields of the response. `tests/engine/test_scout.py` walks the rendered text and
fails on a number or card name no field backs. There is deliberately no model-written prose here;
an optional gated paragraph can come later (the spec's swap_narrative-style gate), never instead.
Pure: no simulation, no network -- `build(analyze_json)`.
"""

from __future__ import annotations

_METHOD_WORD = {
    "combat": "creature combat", "commander": "its commander's damage",
    "commander_damage": "21 commander damage", "burn": "direct damage and drain",
    "poison": "poison", "overrun": "an overrun alpha strike", "storm": "a storm turn",
    "combo": "a combo", "alt_win": "an alternate win",
}


def _pct(x) -> str:
    return f"{round(100 * float(x))}%"


def build(a: dict, matchups: dict | None = None) -> dict:
    """The structured report from an `/analyze` response (card_stats on). `matchups` is the
    engine `/matchups` response when the caller has one cached; None leaves that section out."""
    ins = a.get("insight") or {}
    pp = a.get("power_profile") or {}
    ks = a.get("kill_speed") or {}
    km = a.get("kill_methods") or {}
    cv = a.get("card_verdicts") or {}
    combos = a.get("combos") or {}
    caveats: list[str] = []

    gameplan = ins.get("gameplan") or ""
    bracket = {
        "bracket": pp.get("bracket_estimate"), "label": pp.get("bracket_label"),
        "reasons": list(pp.get("bracket_reasons") or []), "pod_read": ins.get("pod_read") or "",
    }

    clock: list[str] = []
    if ks.get("text"):
        clock.append(ks["text"])
    ts = a.get("table_speed") or {}
    if isinstance(ts, dict) and ts.get("text"):
        clock.append(ts["text"])
    cc = a.get("combo_clock") or {}
    if isinstance(cc, dict) and cc.get("text"):
        clock.append(cc["text"])

    how: list[str] = []
    share = km.get("method_share") or {}
    if share:
        parts = [f"{_METHOD_WORD.get(m, m)} {_pct(v)}"
                 for m, v in sorted(share.items(), key=lambda kv: -kv[1]) if v >= 0.05]
        if parts:
            how.append(f"Its kills come from {', '.join(parts)} of the games it wins "
                       f"({km.get('killing_games')} of {km.get('games')} unopposed games).")
    top = km.get("top_damage_cards") or []
    if top:
        how.append("Most of the damage: " + ", ".join(
            f"{t['name']} {_pct(t['share'])}" for t in top[:5]) + ".")

    strengths = list(ins.get("strengths") or [])
    weak_against = [{"text": w, "source": "profile"} for w in ins.get("weaknesses") or []]
    weak_against += [{"text": e["text"], "source": "exposure"} for e in a.get("exposure") or []
                     if e.get("text")]
    if matchups and isinstance(matchups.get("matchups"), list):
        for m in matchups["matchups"]:
            line = (f"{m.get('label')} decks ({m.get('opponent')}): wins {_pct(m['winrate'])} of "
                    f"{m.get('games')} duels (90% interval {_pct(m['low'])}-{_pct(m['high'])})"
                    + (f"; {m['why']}" if m.get("why") else ""))
            if m.get("verdict") == "weak":
                weak_against.append({"text": line, "source": "matchup"})
            elif m.get("verdict") == "favoured":
                strengths.append(f"Favoured against {line}")
        if matchups.get("fidelity"):
            caveats.append(f"Matchups: {matchups['fidelity']}")
    else:
        caveats.append("Matchups against the reference field were not run (Scout matchups "
                       "on the deck page runs them).")

    strong_cards = [v["text"] for v in cv.get("strong") or []]
    weak_cards = [v["text"] for v in cv.get("weak") or []]
    if not cv:
        caveats.append("Strong and weak cards were not measured (needs the per-card pass).")

    combo_lines: list[str] = []
    if combos.get("checked"):
        for c in combos.get("items") or []:
            cards = " + ".join(c.get("cards") or [])
            what = c.get("produces") or "a combo"
            note = " (needs the commander)" if c.get("needs_commander") else ""
            combo_lines.append(f"{cards}: {what}{note}.")
        if not combo_lines:
            combo_lines.append("No game-ending combo found in the list.")
    else:
        caveats.append("Combos were not checked (Commander Spellbook was not consulted), so "
                       "none are listed -- that is not the same as none existing.")

    dials = []
    for key, d in (a.get("dials") or {}).items():
        if isinstance(d, dict) and d.get("band"):
            why = "; ".join(d.get("reasons") or [])
            dials.append(f"{key.capitalize()}: {d['band']}" + (f" ({why})" if why else ""))

    caveats.append("Speed and card value come from unopposed (goldfish) games: removal, "
                   "counterspells and protection are judged by what they answer, not by speed.")
    return {
        "gameplan": gameplan, "bracket": bracket, "clock": clock, "how_it_wins": how,
        "strengths": strengths, "weak_against": weak_against, "strong_cards": strong_cards,
        "weak_cards": weak_cards, "combos": combo_lines, "dials": dials, "caveats": caveats,
    }


def render(r: dict) -> str:
    """Markdown text of the report, section by section; empty sections are left out."""
    out: list[str] = []
    if r.get("gameplan"):
        out += [r["gameplan"], ""]
    b = r.get("bracket") or {}
    if b.get("bracket"):
        out.append(f"**Bracket {b['bracket']} ({b.get('label') or ''})**"
                   + (f" -- {b['pod_read']}" if b.get("pod_read") else ""))
        out += [f"- {x}" for x in b.get("reasons") or []]
        out.append("")

    def section(title: str, lines: list) -> None:
        if lines:
            out.append(f"**{title}**")
            out.extend(f"- {x['text'] if isinstance(x, dict) else x}" for x in lines)
            out.append("")

    section("How fast", r.get("clock") or [])
    section("How it wins", r.get("how_it_wins") or [])
    section("Good at", r.get("strengths") or [])
    section("Weak against", r.get("weak_against") or [])
    section("Strongest cards", r.get("strong_cards") or [])
    section("Weakest cards (best cuts first)", r.get("weak_cards") or [])
    section("Combos", r.get("combos") or [])
    section("Table feel", r.get("dials") or [])
    section("Caveats", r.get("caveats") or [])
    return "\n".join(out).strip()
