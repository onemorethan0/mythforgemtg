"""Analyse a pod of real decks end to end: bracket, axes, off-meta read, and upgrades you OWN.

Everything the app computes, for a list of decks, in one run — so a pod can be checked without
clicking through the wizard once per deck.

    python scripts/pod_report.py --decks docs/data/pod.json
    python scripts/pod_report.py --decks docs/data/pod.json --json out.json

Candidate upgrades come from the Myth Suite collection (`collection.suite_collection_path()`),
so every suggestion is a card the pilot already has. The advisor is MULTI-SEED by default here:
a single seed's suggestion list is not stable (measured ~60% relative spread on the totals), so
this reports how often each swap survives across seeds rather than one seed's opinion.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("MYTHFORGE_EDHREC_LIFT", "on")

import collection                                              # noqa: E402
import deck_builder                                            # noqa: E402
import deck_import                                             # noqa: E402
from scryfall_client import ScryfallClient                     # noqa: E402

from mythgauntlet.data.scryfall import load_card_db            # noqa: E402
from mythgauntlet.model.deck import Deck, resolve              # noqa: E402
from mythgauntlet.ratings import advisor                       # noqa: E402
from mythgauntlet.ratings.analysis import analyze_deck         # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore        # noqa: E402
from mythgauntlet.sim.tier0 import SimConfig                   # noqa: E402

SEEDS = [7, 21, 99, 123]
AXES = ("speed", "consistency", "resilience", "interaction", "ceiling")


def _owned_candidates(db, limit: int | None = None):
    """Cards the pilot actually owns, resolved against the engine's card db.

    NO ALPHABETICAL TRUNCATION. The first version took `sorted(names)[:600]`, which on a
    972-card collection cut the pool off at "orzhov signet" — every card from P to Z was
    invisible to the advisor, and the surviving A–O bias combined with a name-based tiebreak
    in `advise` to produce advice led by Arcane Signet and Arid Mesa. If a cap is ever needed
    it must be by relevance, never by spelling.
    """
    out = [c for c in (db.get(n) for n in sorted(collection.load_owned_names())) if c is not None]
    return out[:limit] if limit else out


def _as_decklist(imported) -> str:
    """The engine parses decklist TEXT, so render the import back to one."""
    lines = []
    if imported.commander:
        lines += ["Commander:", f"1 {imported.commander['name']}"]
    for p in imported.partners:
        lines.append(f"1 {p['name']}")
    lines.append("Deck:")
    for c in imported.deck:
        lines.append(f"{int(c.get('quantity', 1) or 1)} {c['name']}")
    return "\n".join(lines)


def analyse(source: str, db, store, candidates, runs: int):
    sc = ScryfallClient()
    imported = deck_import.import_deck(source, sc)
    deck_cards = list(imported.deck) + [dict(p, quantity=1) for p in imported.partners]
    stats = deck_builder.compute_stats(imported.commander, deck_cards,
                                       partners=imported.partners)
    resolved = resolve(Deck.parse_text(_as_decklist(imported)), db)

    # One analysis per seed. Bracket and the axes are simulation outputs, so a single seed is
    # a sample, not a measurement — the same caveat advisor_bench carries.
    brackets, axis_runs, suggestions = [], collections.defaultdict(list), collections.Counter()
    reasons: dict[str, None] = {}
    gc = 0
    detail: dict[str, dict] = {}
    for seed in SEEDS:
        cfg = SimConfig(turns=8, runs=runs, seed=seed)
        a = analyze_deck(resolved, cfg, store, run_resilience=True)
        # `bracket` is a BracketEstimate dataclass, not an int, and it is not hashable.
        brackets.append((a.bracket.bracket, a.bracket.label))
        # a dict as an ordered set — reasons repeat across seeds and order carries meaning
        reasons.update(dict.fromkeys(a.bracket.reasons))
        gc = a.bracket.game_changers
        for ax in AXES:
            axis_runs[ax].append(advisor.axis_score(a, ax))
        rep = advisor.advise(resolved, cfg, store, candidates, top=5, max_eval=12, cut_pool=3)
        for s in rep.suggestions:
            suggestions[(s.add, s.cut)] += 1
            detail[f"{s.add}|{s.cut}"] = {"delta": round(s.delta, 2), "reason": s.reason,
                                          "axis": rep.axis}
    return {
        "name": imported.name,
        "commander": (imported.commander or {}).get("name"),
        "cards": stats.get("total_cards"),
        "bracket": collections.Counter(brackets).most_common(1)[0][0][0],
        "bracket_label": collections.Counter(brackets).most_common(1)[0][0][1],
        "bracket_spread": sorted({b for b, _ in brackets}),
        "game_changers": gc,
        "bracket_reasons": list(reasons),
        "axes": {ax: round(sum(v) / len(v), 1) for ax, v in axis_runs.items()},
        "quality": stats.get("quality"),
        "offmeta": stats.get("offmeta"),
        "archetypes": stats.get("archetypes"),
        "suggestions": [
            {"add": add, "cut": cut, "seeds": n, "of": len(SEEDS), **detail[f"{add}|{cut}"]}
            for (add, cut), n in suggestions.most_common()
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", type=Path, required=True,
                    help='JSON list of {"source": "<url or decklist>"} entries')
    # 240, not 120. The Ceiling estimator averages the FASTEST DECILE of kill turns, so its
    # resolution scales with how many kills the sim actually observes. Casual decks rarely
    # kill inside 8 goldfish turns, and at runs=60 the decile collapsed to a single game —
    # every suggestion tied at one whole-turn step. Measured on a real pod: runs=60 gave 5
    # distinct suggestion deltas, runs=240 gave 12.
    ap.add_argument("--runs", type=int, default=240,
                    help="sim runs per analysis; below ~240 the Ceiling axis loses resolution "
                         "on slow decks (see compute_ceiling)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    db = load_card_db()
    store = SemanticsStore()
    candidates = _owned_candidates(db)
    sources = json.loads(args.decks.read_text(encoding="utf-8"))
    print(f"semantics {len(store)} · owned candidates {len(candidates)} · "
          f"seeds {SEEDS} · runs {args.runs}\n", flush=True)

    out = []
    for entry in sources:
        rec = analyse(entry["source"], db, store, candidates, args.runs)
        out.append(rec)
        q = rec["quality"] or {}
        mana, colors = q.get("mana") or {}, q.get("colors") or {}
        om = rec["offmeta"] or {}
        print(f"=== {rec['name']}  ({rec['commander']})", flush=True)
        print(f"    bracket {rec['bracket']} ({rec['bracket_label']}) · "
              f"{rec['game_changers']} game changers   seeds saw {rec['bracket_spread']}")
        for r in rec["bracket_reasons"][:2]:
            print(f"      - {r}")
        print("    " + " · ".join(f"{k} {v}" for k, v in rec["axes"].items()))
        print(f"    mana {mana.get('sources','?')} sources "
              f"({mana.get('lands','?')} lands + {mana.get('ramp','?')} ramp, "
              f"{mana.get('verdict','?')})"
              f"{'' if colors.get('ok', True) else '  COLOURS SHORT ' + str(colors.get('short'))}")
        if om:
            print(f"    off-meta {om.get('verdict')} · synergy {om.get('synergy')} "
                  f"(typical {om.get('baseline')}) · {om.get('confidence')} confidence")
        print(f"    archetypes {(rec['archetypes'] or {}).get('merged')}")
        if rec["suggestions"]:
            print("    upgrades from your collection:")
            for s in rec["suggestions"][:5]:
                print(f"      +{s['add']}  -{s['cut']}   "
                      f"(+{s['delta']} {s['axis']}, held on {s['seeds']}/{s['of']} seeds)")
        else:
            print("    upgrades: none cleared the noise floor")
        print(flush=True)

    if args.json:
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
