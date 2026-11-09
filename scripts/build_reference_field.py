"""Build the B35 reference field: per bracket 1-4, one corpus deck per archetype a casual pod
actually meets, committed as data so matchup numbers stay comparable over time.

    python scripts/build_reference_field.py            # sweep (resumable) + write the field
    python scripts/build_reference_field.py --report   # field from the cache, printed only

Each labelled (audited) corpus deck of Brackets 1-4 is analyzed once (`analyze_deck`, 120 runs,
real Spellbook combos, cached) and given ONE archetype, first match wins:

  voltron       half or more of its goldfish kills come from the commander: its own combat
                damage as the biggest share of a life kill, or 21 commander damage (B34)
  graveyard     Forge's theme detector puts reanimator or graveyard in its top two themes
  spellslinger  the engine's archetype is Spellslinger / storm, or the spellslinger theme
  artifact_combo the engine's archetype is Combo, or the artifacts theme
  go_wide       the engine's archetype is Go-wide / tokens, or the tokens / aristocrats theme
  control       the engine's archetype is Control
  midrange      everything else that wins with creatures (Creature aggro, Ramp / midrange,
                Midrange goodstuff)

For each (bracket, archetype) cell with at least MIN_CELL decks, the pick is the deck whose
measured strength score (`BracketEstimate.strength_score`) is closest to the cell's median --
a typical member, not the best one. Ties go to the file name, so a re-run is reproducible.

NOT CI-SAFE: needs the card store, the compiled semantics store and (first run) Spellbook.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "scripts"):
    sys.path.insert(0, str(p))

CACHE = ROOT / ".cache" / "reference_field_rows.jsonl"
OUT = ROOT / "src" / "mythgauntlet" / "data" / "reference_field.json"   # tracked (data/ is not)
ARCHETYPES = ("go_wide", "voltron", "midrange", "spellslinger", "graveyard", "artifact_combo",
              "control")
MIN_CELL = 3
RUNS = 120


def archetype_of(insight_archetype: str, themes: list[str], commander_kill_share: float) -> str:
    top = themes[:2]
    if commander_kill_share >= 0.5:
        return "voltron"
    if "reanimator" in top or "graveyard" in top:
        return "graveyard"
    if insight_archetype == "Spellslinger / storm" or "spellslinger" in themes:
        return "spellslinger"
    if insight_archetype == "Combo" or "artifacts" in top:
        return "artifact_combo"
    if insight_archetype == "Go-wide / tokens" or "tokens" in top or "aristocrats" in top:
        return "go_wide"
    if insight_archetype == "Control":
        return "control"
    return "midrange"


def _row(path, label, db, store, cfg):
    from bracket_accuracy import real_combo_lookup

    import deck_themes
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings.analysis import analyze_deck

    r = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
    if r.card_count < 90 or not r.commanders:
        return None
    report, failed = real_combo_lookup(r, path.name)
    a = analyze_deck(r, cfg, store, combo_report=report, combos_checked=not failed,
                     run_resilience=False)
    themes = deck_themes.detect_deck_themes([
        {"name": c.name, "type_line": c.type_line or "", "oracle_text": c.oracle_text or "",
         "quantity": n} for c, n in r.cards])
    km = a.kill_methods
    # Voltron = kills the commander delivered: its combat damage was the biggest share of a life
    # kill ("commander") OR 21 commander damage ("commander_damage") -- B34 splits the two
    cmd_share = ((km.method_share.get("commander", 0.0) + km.method_share.get("commander_damage", 0.0))
                 if km and km.killing_games else 0.0)
    return {"deck": path.name, "label": label, "commander": r.commanders[0].name,
            "insight": a.insight.archetype if a.insight else "", "themes": themes,
            "commander_kill_share": round(cmd_share, 3),
            "strength_score": a.bracket.strength_score,
            "archetype": archetype_of(a.insight.archetype if a.insight else "", themes, cmd_share)}


def sweep() -> list[dict]:
    from bracket_accuracy import labelled_decks

    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.semantics.store import load_store
    from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig

    done = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["deck"]] = row
    db, store = load_card_db(), load_store()
    cfg = SimConfig(turns=DEFAULT_ANALYZE_TURNS, runs=RUNS, seed=42)
    todo = [(p, b) for p, b in labelled_decks() if b <= 4 and p.name not in done]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with CACHE.open("a", encoding="utf-8") as fh:
        for i, (path, label) in enumerate(todo, 1):
            try:
                row = _row(path, label, db, store, cfg)
            except Exception as exc:   # noqa: BLE001 - one bad deck must not stop the sweep
                print(f"  {path.name}: FAILED {exc}", flush=True)
                continue
            if row is None:
                continue
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            done[row["deck"]] = row
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
    return list(done.values())


def build(rows: list[dict]) -> dict:
    from bracket_accuracy import labelled_decks
    labelled = {p.name: b for p, b in labelled_decks()}
    rows = [r for r in rows if labelled.get(r["deck"]) == r["label"]
            and r.get("strength_score") is not None]
    field: dict[str, dict] = {}
    for bracket in range(1, 5):
        field[str(bracket)] = {}
        for arch in ARCHETYPES:
            cell = [r for r in rows if r["label"] == bracket and r["archetype"] == arch]
            if len(cell) < MIN_CELL:
                continue
            median = statistics.median(r["strength_score"] for r in cell)
            pick = min(cell, key=lambda r: (abs(r["strength_score"] - median), r["deck"]))
            field[str(bracket)][arch] = {
                "deck": pick["deck"], "commander": pick["commander"],
                "strength_score": round(pick["strength_score"], 3),
                "cell_median": round(median, 3), "cell_n": len(cell),
            }
    return {"generated": time.strftime("%Y-%m-%d"), "runs": RUNS, "min_cell": MIN_CELL,
            "note": "B35 reference field: per bracket, the corpus deck nearest its archetype's "
                    "median strength (scripts/build_reference_field.py)",
            "brackets": field}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="build from the cache, print only")
    args = ap.parse_args()
    rows = sweep() if not args.report else [json.loads(x) for x in
                                            CACHE.read_text(encoding="utf-8").splitlines() if x]
    field = build(rows)
    for b, cells in field["brackets"].items():
        print(f"Bracket {b}: " + "; ".join(f"{a} {c['commander']} (n={c['cell_n']})"
                                           for a, c in cells.items()))
    if not args.report:
        OUT.write_text(json.dumps(field, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
