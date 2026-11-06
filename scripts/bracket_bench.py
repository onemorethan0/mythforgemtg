"""P0 of docs/DECKBUILD_REVIEW.md: does the REQUESTED bracket produce that bracket?

builder_bench.py builds at bracket 3 only, so it cannot see whether the bracket knob does anything.
This builds each commander at brackets 1-5, records what the build holds (Game Changers, fast mana,
tutors) and, with the strength engine running on :8020, the ENGINE's bracket estimate and key axes.
It decides nothing and changes nothing; the output (docs/bench/brackets-*.json) is the evidence that
sizes P1 (make bracket a target) and P2 (close the loop).

    python scripts/bracket_bench.py --out docs/bench/brackets-2026-11-06.json
    python scripts/bracket_bench.py --commanders "Krenko, Mob Boss" "Tymna the Weaver" --brackets 1 3 5
    python scripts/bracket_bench.py --no-engine            # structure only, no :8020 needed

Also builds one commander twice per run (--determinism) to answer F8: is a build reproducible?

Fast mana and tutors are heuristics (a named list; oracle text), good for comparing brackets with each
other, not an audit of any one deck.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import requests  # noqa: E402

from commander_analysis import build_commander_profile  # noqa: E402
import bracket_repair  # noqa: E402
from deck_builder import DeckBuilder  # noqa: E402
from scryfall_client import ScryfallClient  # noqa: E402

ENGINE = "http://127.0.0.1:8020"
DEFAULT_COMMANDERS = ("Krenko, Mob Boss", "Meren of Clan Nel Toth", "Atraxa, Praetors' Voice",
                      "Talrand, Sky Summoner", "Edgar Markov", "Tymna the Weaver")

FAST_MANA = frozenset({
    "Sol Ring", "Mana Crypt", "Mana Vault", "Grim Monolith", "Chrome Mox", "Mox Diamond", "Mox Amber",
    "Mox Opal", "Mox Tantalite", "Lotus Petal", "Jeweled Lotus", "Lion's Eye Diamond", "Ancient Tomb",
    "Simian Spirit Guide", "Elvish Spirit Guide", "Dark Ritual", "Cabal Ritual", "Culling the Weak",
    "Mana Drain", "Basalt Monolith", "Everflowing Chalice", "Worn Powerstone", "Thran Dynamo",
})

_BASIC_TYPES = ("plains", "island", "swamp", "mountain", "forest")


def _qty(card: dict) -> int:
    return int(card.get("quantity", 1) or 1)


def is_tutor(card: dict) -> bool:
    """Library search for a NON-land card (a heuristic: land fetch text names a land/basic type)."""
    if "land" in (card.get("type_line") or "").lower():
        return False
    t = (card.get("oracle_text") or "").lower()
    i = t.find("search your library for")
    if i < 0:
        return False
    clause = t[i:i + 90]
    return not ("land card" in clause or "basic land" in clause or any(b in clause for b in _BASIC_TYPES))


def structure(deck: list[dict]) -> dict:
    nonbasic = [c for c in deck if "basic" not in (c.get("type_line") or "").lower()]
    return {
        "game_changers": sum(1 for c in nonbasic if c.get("game_changer")),
        "fast_mana": sorted(c["name"] for c in nonbasic if c.get("name") in FAST_MANA),
        "tutors": sorted(c["name"] for c in nonbasic if is_tutor(c)),
        "nonbasic_names": sorted(c["name"] for c in nonbasic),
        "lands": sum(_qty(c) for c in deck if "land" in (c.get("type_line") or "").lower()),
    }


def decklist_text(commander: dict, deck: list[dict]) -> str:
    lines = ["Commander:", f"1 {commander['name']}", "", "Deck:"]
    lines += [f"{_qty(c)} {c['name']}" for c in deck if c.get("name")]
    return "\n".join(lines)


def analyze(text: str, name: str, runs: int, timeout: int = 240) -> dict | None:
    try:
        r = requests.post(f"{ENGINE}/analyze", timeout=timeout,
                          json={"deck": text, "name": name, "runs": runs, "resilience": False, "combos": True})
        return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as exc:                                  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def build(client: ScryfallClient, card: dict, bracket: int, repair: bool = False) -> tuple[list[dict], int]:
    buf = io.StringIO()
    profile = build_commander_profile(card)
    with contextlib.redirect_stdout(buf):
        builder = DeckBuilder(client)
        deck = builder.build(profile, bracket=bracket)
        if repair:
            rep = bracket_repair.repair_combos(builder, profile, card, [], bracket)
            build.last_repair = rep
            deck = list(builder._deck)
    padded = 0
    for line in buf.getvalue().splitlines():
        if "Padding" in line and "missing slots" in line:
            padded = max(padded, int(line.split("Padding")[1].split()[0]))
    return deck, padded


def run(commanders, brackets, use_engine: bool, runs: int, determinism: bool, repair: bool = False) -> dict:
    client = ScryfallClient()
    rows = []
    for ci, name in enumerate(commanders, 1):
        card = client.get_card_by_name(name, fuzzy=True)
        if card is None:
            rows.append({"commander": name, "invalid": "commander not found"})
            continue
        built: dict[int, list[str]] = {}
        for b in brackets:
            t0 = time.time()
            row: dict = {"commander": name, "bracket": b}
            try:
                build.last_repair = None
                deck, padded = build(client, card, b, repair)
                row['repair'] = build.last_repair
                row["padded_slots"] = padded
                row["deck_size"] = len(deck)
                row.update(structure(deck))
                built[b] = row["nonbasic_names"]
                row["build_s"] = round(time.time() - t0, 1)
                if use_engine:
                    a = analyze(decklist_text(card, deck), name, runs)
                    if a and "error" not in a:
                        pp = a.get("power_profile") or {}
                        row["engine_bracket"] = pp.get("bracket_estimate")
                        row["engine_label"] = pp.get("bracket_label")
                        row["engine_confidence"] = pp.get("bracket_confidence")
                        row["engine_plays_up"] = pp.get("bracket_plays_up")
                        row["engine_reasons"] = pp.get("bracket_reasons")
                        row["power"] = {k: pp.get(k) for k in (
                            "consistency", "speed_kill_rate", "speed_avg_kill_turn",
                            "interaction", "ceiling", "pod")}
                        cb = a.get("combos") or {}
                        row["combos"] = {k: cb.get(k) for k in (
                            "total", "two_card", "terminal", "fast_terminal_two_card")} if isinstance(cb, dict) else None
                    else:
                        row["engine_error"] = (a or {}).get("error", "no response")
            except Exception as exc:                          # noqa: BLE001
                row["invalid"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            print(f"[{ci}/{len(commanders)}] {name[:22]:22} B{b} gc={row.get('game_changers')} "
                  f"fast={len(row.get('fast_mana', []))} tutors={len(row.get('tutors', []))} "
                  f"est={row.get('engine_bracket')} {row.get('invalid', '')}", flush=True)
    out: dict = {"commanders": list(commanders), "brackets": list(brackets), "rows": rows}
    if determinism:
        name = commanders[0]
        card = client.get_card_by_name(name, fuzzy=True)
        d1, _ = build(client, card, 3)
        d2, _ = build(client, card, 3)
        n1, n2 = sorted(c["name"] for c in d1), sorted(c["name"] for c in d2)
        out["determinism"] = {"commander": name, "bracket": 3, "identical": n1 == n2,
                              "only_in_first": sorted(set(n1) - set(n2)), "only_in_second": sorted(set(n2) - set(n1))}
        print("determinism:", out["determinism"], flush=True)
    return out


def summarize(result: dict) -> None:
    rows = [r for r in result["rows"] if "bracket" in r and "invalid" not in r]
    print(f"\n{'requested':>9} {'builds':>6} {'mean est':>9} {'est==req':>9} {'within1':>8} "
          f"{'GC':>5} {'fastmana':>9} {'tutors':>7}")
    for b in result["brackets"]:
        rs = [r for r in rows if r["bracket"] == b]
        es = [r["engine_bracket"] for r in rs if isinstance(r.get("engine_bracket"), (int, float))]
        if not rs:
            continue
        mean = f"{sum(es) / len(es):.2f}" if es else "-"
        exact = f"{sum(1 for e in es if round(e) == b)}/{len(es)}" if es else "-"
        w1 = f"{sum(1 for e in es if abs(round(e) - b) <= 1)}/{len(es)}" if es else "-"
        print(f"{b:>9} {len(rs):>6} {mean:>9} {exact:>9} {w1:>8} "
              f"{sum(r['game_changers'] for r in rs) / len(rs):>5.1f} "
              f"{sum(len(r['fast_mana']) for r in rs) / len(rs):>9.1f} "
              f"{sum(len(r['tutors']) for r in rs) / len(rs):>7.1f}")
    print("\nnon-basic cards shared with the next bracket up (mean share):")
    by: dict[str, dict[int, set]] = {}
    for r in rows:
        by.setdefault(r["commander"], {})[r["bracket"]] = set(r["nonbasic_names"])
    for lo, hi in zip(result["brackets"], result["brackets"][1:]):
        sh = [len(v[lo] & v[hi]) / max(1, len(v[lo])) for v in by.values() if lo in v and hi in v]
        if sh:
            print(f"  B{lo}->B{hi}: {sum(sh) / len(sh):.0%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commanders", nargs="+", default=list(DEFAULT_COMMANDERS))
    ap.add_argument("--brackets", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument("--no-engine", action="store_true")
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--determinism", action="store_true")
    ap.add_argument("--repair", action="store_true", help="apply bracket_repair (P1a) before analysing")
    ap.add_argument("--out")
    ap.add_argument("--summarize", help="re-summarize a saved result file and exit")
    args = ap.parse_args()
    if args.summarize:
        summarize(json.loads(Path(args.summarize).read_text(encoding="utf-8")))
        return 0
    result = run(args.commanders, args.brackets, not args.no_engine, args.runs, args.determinism, args.repair)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    summarize(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
