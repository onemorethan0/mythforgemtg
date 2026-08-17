"""Measure the DECK BUILDER end to end, so a change can be shown to help or hurt.

The test suite proves the builder does not crash. Nothing proved it produces GOOD decks,
so every ordering change (EDHREC lift, the theme package, the theme taxonomy) was argued
from a handful of hand-picked commanders. This runs a fixed roster through the real build
path and records what came out, so two commits can be compared as numbers.

    python scripts/builder_bench.py --out docs/bench/run.json
    python scripts/builder_bench.py --compare docs/bench/baseline-c6ddd79.json docs/bench/run.json

Committed reference runs live in docs/bench/ (data/ is gitignored):
  baseline-c6ddd79.json  the builder before the 2026-08-14 lift/theme work
  current-7f146f9.json   the same roster after it

The roster is FIXED and committed. Comparing runs over different commanders measures the
commanders, not the change.

A DEGRADED BUILD MUST NOT BE COUNTED. `ScryfallClient._get` returns None after its four
retries, which is indistinguishable from a legitimate empty result, so a rate-limited role
query silently contributes zero cards and the 99-card guarantee quietly pads the deck with
basics. A run that measured those would report the network, not the code. `_validate`
rejects any deck whose basic-land count or role coverage says that happened, and the
summary prints how many were dropped rather than hiding it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import collection_pool  # noqa: E402
import deck_quality  # noqa: E402
import deck_themes  # noqa: E402
import edhrec_lift  # noqa: E402
import lift_stats  # noqa: E402
import theme_match  # noqa: E402
from commander_analysis import build_commander_profile  # noqa: E402
from deck_builder import DeckBuilder  # noqa: E402
import scryfall_client  # noqa: E402
from scryfall_client import ScryfallClient  # noqa: E402

# Fixed roster, chosen to span the cases the builder handles differently:
# clear tribal, token/counter archetypes, graveyard, the three themes added 2026-08-14,
# commanders that detect NO theme (partners and value piles), and colourless/mono.
ROSTER: tuple[str, ...] = (
    # strongly themed
    "Krenko, Mob Boss",
    "Ghired, Conclave Exile",
    "Brudiclad, Telchor Engineer",
    "Meren of Clan Nel Toth",
    "Atraxa, Praetors' Voice",
    "Sythis, Harvest's Hand",
    "Edgar Markov",
    "The Ur-Dragon",
    # newly-added themes
    "Kadena, Slinking Sorcerer",     # face_down — the reproducer
    "Tom Bombadil",                  # sagas
    "Etali, Primal Storm",           # impulse
    # weakly / un-themed: goodstuff piles and partners
    "Progenitus",
    "Tymna the Weaver",
    "Jegantha, the Wellspring",
    "Karona, False God",
    "Nin, the Pain Artist",
    # shape variety
    "Kozilek, Butcher of Truth",     # colourless
    "Talrand, Sky Summoner",         # mono-blue spellslinger
    "Shelob, Child of Ungoliant",
    "Muldrotha, the Gravetide",
)

ROLE_PLAN = {"ramp": 10, "draw": 10, "removal": 7, "wipe": 4, "protection": 3, "finisher": 3}
MAX_BASICS = 30          # a healthy 37-land base is mostly nonbasic at bracket 3
MIN_ROLE_COVERAGE = 0.5  # fraction of the role plan a real build clears easily


def _is_basic(card: dict) -> bool:
    tl = (card.get("type_line") or "").lower()
    return "basic" in tl and "land" in tl


def _role_counts(deck: list[dict]) -> dict[str, int]:
    """Roles the FINISHED deck actually contains, via the local classifier.

    Post-hoc rather than instrumented: the builder does not report what each phase drafted,
    and this also catches a card filling a role it was not drafted for.
    """
    counts = dict.fromkeys(ROLE_PLAN, 0)
    for card in deck:
        if deck_quality.is_land(card):
            continue
        for role in collection_pool.classify(card):
            if role in counts:
                counts[role] += 1
    return counts


def _validate(deck: list[dict], roles: dict[str, int], padded: int,
              themes: list[str], colourless: bool = False) -> str | None:
    """Why this build must not be counted, or None if it is sound.

    `padded` is the builder's own signal and the most reliable one: any padding at
    all means a role query returned nothing. A smoke run measured Kadena at synergy
    8.7 with ONE on-theme card while padding 31 slots; the clean build of the same
    commander scored 35.5 with 21. Counting the first would have measured Scryfall.
    """
    if len(deck) != 99:
        return f"deck has {len(deck)} cards, not 99"
    if padded:
        return f"builder padded {padded} slots — role queries came back empty"
    # Skipped for colourless commanders: a Kozilek manabase is legitimately ~34 Wastes
    # plus utility lands, which tripped this gate on an otherwise clean build.
    basics = sum(int(c.get("quantity", 1) or 1) for c in deck if _is_basic(c))
    if not colourless and basics > MAX_BASICS:
        return f"{basics} basic lands — role queries returned nothing (rate limited?)"
    # Role counts are REPORTED, never a validity gate. The builder drafts roles from
    # Scryfall `otag:` queries while `collection_pool.classify` is the SEPARATE local
    # taxonomy strict mode uses, and the two disagree materially: on a clean run with
    # padded=0 (i.e. every slot filled) the classifier saw 0 wipes for Krenko and 0
    # protection for Talrand, whose protection slots are counterspells — classify only
    # tags protection GRANTED to another permanent. Gating on it dropped 8 of 20 sound
    # builds as "degraded" and would have measured the disagreement, not the change.
    return None


def _curve_deviation(deck: list[dict], commander_mv: int) -> float:
    """Total absolute distance from the reference curve — lower is better."""
    nonland = [c for c in deck if not deck_quality.is_land(c)]
    if not nonland:
        return 0.0
    target = deck_quality.curve_target(len(nonland), commander_mv)
    have: dict[int, int] = {}
    for card in nonland:
        b = deck_quality.bucket(card)
        have[b] = have.get(b, 0) + 1
    return float(sum(abs(have.get(mv, 0) - want) for mv, want in target.items()))


def run(pause: float) -> dict:
    client = ScryfallClient()
    results = []
    for i, name in enumerate(ROSTER, 1):
        print(f"[{i:2}/{len(ROSTER)}] {name}", flush=True)
        row: dict = {"commander": name}
        try:
            card = client.get_card_by_name(name)
            if card is None:
                row["invalid"] = "commander not found"
                results.append(row)
                continue
            profile = build_commander_profile(card)
            # The builder ANNOUNCES its own degradation: the 99-card guarantee logs
            # 'Padding N missing slots with goodstuff' when role queries came back
            # empty. That is the unambiguous marker, so capture it rather than trying
            # to infer rate-limiting from the finished list.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                deck = DeckBuilder(client).build(profile, bracket=3)
            log = buf.getvalue()
            padded = 0
            for line in log.splitlines():
                if "Padding" in line and "missing slots" in line:
                    padded = max(padded, int(line.split("Padding")[1].split()[0]))
            row["padded_slots"] = padded
            row["rate_limited"] = "[rate limit]" in log

            roles = _role_counts(deck)
            invalid = _validate(deck, roles, padded, profile.themes,
                                colourless=profile.is_colorless)
            row.update({
                "themes": list(profile.themes),
                "deck_size": len(deck),
                "roles": roles,
                "basics": sum(int(c.get("quantity", 1) or 1) for c in deck if _is_basic(c)),
                "curve_deviation": _curve_deviation(deck, int(profile.mana_value)),
            })
            # Record validity as a FLAG and measure anyway. Skipping the metrics for a
            # rejected build makes the JSON un-reanalysable: when the validity rule
            # itself turned out to be wrong (see _validate), rows could not simply be
            # un-dropped — they had no metrics — and re-summarising them silently
            # produced a 20-row file with 12 rows of data, which read as a colour-health
            # REGRESSION that never happened. _summary does the filtering instead.
            if invalid:
                row["invalid"] = invalid

            # assess_colors returns a ColorVerdict dataclass, not a dict. `short` is
            # recorded too: knowing WHICH colour a deck cannot cast is what makes a
            # colour regression diagnosable without rebuilding it.
            colours = deck_quality.assess_colors(deck, card)
            row["colors_ok"] = bool(colours.ok)
            row["colors_short"] = dict(colours.short or {})
            stats = lift_stats.lift_stats(deck, edhrec_lift.lift_map(name))
            if stats is not None:
                row.update({"synergy": stats.synergy, "baseline": stats.baseline,
                            "coverage": stats.coverage, "verdict": stats.verdict})
            # How much of the deck actually serves the themes it was built for.
            on_theme = sum(
                1 for c in deck
                if any(theme_match.theme_score(c, t) == theme_match.STRONG
                       for t in profile.themes)
            )
            row["on_theme_cards"] = on_theme
            row["deck_themes"] = deck_themes.detect_deck_themes(deck)
        except Exception as exc:                      # noqa: BLE001 - one bad commander
            row["invalid"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
        if pause:
            time.sleep(pause)
    return {"roster": list(ROSTER), "results": results}


def _summary(payload: dict) -> dict:
    rows = [r for r in payload["results"] if not r.get("invalid")]
    dropped = [r for r in payload["results"] if r.get("invalid")]
    syn = [r["synergy"] for r in rows if "synergy" in r]
    dev = [r["curve_deviation"] for r in rows if "curve_deviation" in r]
    on = [r["on_theme_cards"] for r in rows if "on_theme_cards" in r]
    themed = [r for r in rows if r.get("themes")]
    return {
        "valid": len(rows), "dropped": len(dropped),
        "mean_synergy": round(statistics.fmean(syn), 2) if syn else None,
        "median_synergy": round(statistics.median(syn), 2) if syn else None,
        "above_baseline": sum(1 for r in rows
                              if r.get("synergy", 0) > r.get("baseline", 0)),
        "mean_curve_deviation": round(statistics.fmean(dev), 2) if dev else None,
        "mean_on_theme_cards": round(statistics.fmean(on), 2) if on else None,
        "commanders_with_themes": len(themed),
        "colors_ok": sum(1 for r in rows if r.get("colors_ok")),
    }


def _print_summary(label: str, payload: dict) -> None:
    s = _summary(payload)
    print(f"\n=== {label}")
    for k, v in s.items():
        print(f"    {k:26} {v}")
    for r in payload["results"]:
        if r.get("invalid"):
            print(f"    DROPPED {r['commander']}: {r['invalid']}")


def _compare(before: dict, after: dict) -> None:
    b, a = _summary(before), _summary(after)
    print(f"\n{'metric':26} {'before':>10} {'after':>10} {'delta':>10}")
    for key in b:
        bv, av = b[key], a[key]
        if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
            print(f"{key:26} {bv:>10} {av:>10} {av - bv:>+10.2f}")
        else:
            print(f"{key:26} {str(bv):>10} {str(av):>10}")

    bmap = {r["commander"]: r for r in before["results"]}
    print(f"\n{'commander':30} {'synergy':>18}  {'verdict':>34}")
    for r in after["results"]:
        o = bmap.get(r["commander"], {})
        if "synergy" not in r or "synergy" not in o:
            continue
        mark = "  <-- changed" if o.get("verdict") != r.get("verdict") else ""
        print(f"{r['commander'][:30]:30} {o['synergy']:7.1f} -> {r['synergy']:6.1f}"
              f"  {str(o.get('verdict'))[:16]:>16} -> {str(r.get('verdict'))[:16]:<16}{mark}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="write results JSON here")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--pause", type=float, default=4.0,
                    help="seconds between commanders; keeps Scryfall from throttling")
    # The shipped 0.15s is fine for a single build, but a 20-commander sweep is ~200
    # searches back to back and gets throttled — and a throttled role query comes back
    # silently EMPTY, so the run would measure the network instead of the code.
    ap.add_argument("--rate-delay", type=float, default=0.35,
                    help="min seconds between Scryfall requests (default 0.35)")
    args = ap.parse_args()

    scryfall_client.RATE_LIMIT_DELAY = args.rate_delay

    if args.compare:
        before = json.loads(args.compare[0].read_text(encoding="utf-8"))
        after = json.loads(args.compare[1].read_text(encoding="utf-8"))
        _print_summary(f"BEFORE {args.compare[0].name}", before)
        _print_summary(f"AFTER  {args.compare[1].name}", after)
        _compare(before, after)
        return 0

    payload = run(args.pause)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    _print_summary("RESULTS", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
