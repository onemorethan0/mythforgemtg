"""Keep game-ending combos out of Bracket 1-2 builds (docs/DECKBUILD_REVIEW.md, P1a).

Measured 2026-11-06 (docs/bench/brackets-2026-11-06.json): the builder never looks for combos, and
four of six commanders' Bracket 1-2 builds held an in-deck game-ending combo, which the official gate
treats as "at least Bracket 3". Game Changers were already 0 there; combos were what leaked.

The combo table lives in the strength engine (Commander Spellbook, graded), a separate process, so
this asks it rather than duplicating it. The loop is: analyse the finished library, pick the cards
that break the most combos (greedy hitting set, never the commander), have the builder swap them out
and refill, and re-check. Bounded, and it degrades to today's behaviour: if the engine is down the
build ships unchanged and the report says why.

Bracket 3 is NOT repaired: P0 measured it 6/6 on target, and combos are allowed there.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Callable, Optional

import requests

ENGINE_URL = os.getenv("MYTHGAUNTLET_URL", "http://127.0.0.1:8020").rstrip("/")
REPAIRED_BRACKETS = (1, 2)
MAX_PASSES = 3
MAX_CUTS_PER_PASS = 6
MAX_CUTS_TOTAL = 12


def decklist_text(commander_name: str, partners: list[dict], deck: list[dict]) -> str:
    counts: Counter = Counter()
    order: list[str] = []
    for c in deck:
        n = c.get("name")
        if not n:
            continue
        if n not in counts:
            order.append(n)
        counts[n] += int(c.get("quantity", 1) or 1)
    lines = ["Commander:", f"1 {commander_name}"]
    lines += [f"1 {p['name']}" for p in partners or [] if p.get("name")]
    lines += ["", "Deck:"] + [f"{counts[n]} {n}" for n in order]
    return "\n".join(lines)


def engine_combos(text: str, name: str, timeout: int = 180) -> Optional[dict]:
    """The engine's graded combo report for a decklist, or None when it is unreachable."""
    try:
        r = requests.post(f"{ENGINE_URL}/analyze", timeout=timeout,
                          json={"deck": text, "name": name, "runs": 20, "resilience": False, "combos": True})
        if r.status_code != 200:
            return None
        combos = r.json().get("combos")
        return combos if isinstance(combos, dict) and combos.get("checked") else None
    except Exception:                                   # noqa: BLE001 - engine down is a normal state
        return None


def pick_cuts(items: list[dict], protected: set[str], deck_order: list[str], limit: int) -> list[str]:
    """Cards whose removal breaks the most combos: a greedy hitting set.

    A combo made only of protected cards (the commander and partners) cannot be broken here and is
    left. Ties go to the card drafted LATER, which is flexible filler rather than a role pick.
    """
    live = [set(i.get("cards") or []) - protected for i in items if i.get("cards")]
    live = [c for c in live if c]
    position = {n: k for k, n in enumerate(deck_order)}
    cuts: list[str] = []
    while live and len(cuts) < limit:
        tally = Counter(n for combo in live for n in combo)
        best = max(tally, key=lambda n: (tally[n], position.get(n, -1)))
        cuts.append(best)
        live = [c for c in live if best not in c]
    return cuts


def repair_combos(builder, profile, commander: dict, partners: list[dict], bracket: int,
                  analyze: Callable[[str, str], Optional[dict]] = engine_combos) -> dict:
    """Run the loop on `builder`'s finished library. Mutates builder; returns a report.

    `builder.build()` must already have run. The caller reads the repaired library from
    `builder._deck`.
    """
    report: dict = {"applicable": bracket in REPAIRED_BRACKETS, "bracket": bracket, "passes": 0,
                    "removed": [], "added": [], "combos_before": None, "combos_after": None,
                    "skipped": None}
    if not report["applicable"]:
        report["skipped"] = f"bracket {bracket} allows combos"
        return report
    protected = {commander["name"]} | {p["name"] for p in partners or [] if p.get("name")}
    name = commander["name"]
    for _ in range(MAX_PASSES + 1):
        combos = analyze(decklist_text(name, partners, builder._deck), name)
        if combos is None:
            report["skipped"] = "strength engine unreachable" if report["passes"] == 0 \
                else "strength engine stopped answering mid-repair"
            return report
        total = int(combos.get("total") or 0)
        if report["combos_before"] is None:
            report["combos_before"] = total
        report["combos_after"] = total
        if total == 0 or report["passes"] >= MAX_PASSES or len(report["removed"]) >= MAX_CUTS_TOTAL:
            return report
        room = min(MAX_CUTS_PER_PASS, MAX_CUTS_TOTAL - len(report["removed"]))
        cuts = pick_cuts(combos.get("items") or [], protected,
                         [c.get("name") for c in builder._deck], room)
        if not cuts:
            report["skipped"] = "remaining combos are made only of the commander(s)"
            return report
        added = builder.swap_out(set(cuts), profile)
        report["passes"] += 1
        report["removed"] += cuts
        report["added"] += added
    return report
