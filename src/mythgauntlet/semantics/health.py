"""Standing diagnostic over the CCM ledger's FAILURE patterns.

compile-top's own retry/refresh gating already answers the scoreboard question (how
many accepted/quarantined/blocked — see cli.py's `ccm-status`). It does not answer WHY
cards are failing, and answering that by hand meant re-deriving the same investigation
every time a prompt-version rollout stalled: read every blocked/quarantined entry's
stored error strings, bucket them by `[gate] message`, and go look at a few example
cards' oracle text to find the actual root cause. Done manually for prompt v11
(2026-09-02): 156 of 330 sampled failures turned out to share ONE unstated confusion
("{T}: <effect>" read as a tap_for_mana trigger) that a few targeted prompt rules fixed
outright.

`analyze_failures` is that investigation, made repeatable: given the ledger's `entries`
dict, it buckets every recorded compile failure into two pools —

  * QUARANTINED — never accepted at all. `entry["errors"]` holds its last attempt's
    gate messages (compiler.compile_card returns the final attempt's errors on
    quarantine; see `compiler.Ledger.record`).
  * BLOCKED-REFRESH — accepted at an OLDER prompt version, but its most recent refresh
    attempt failed the CURRENT prompt's gates. `entry["refresh_errors"]` holds that
    attempt's messages (compiler._compile_cards' "keep" branch). compile-top will not
    spend GPU on it again until the prompt version moves (cli.py's
    `_ledger_entry_blocks` / the `refresh_failed_at == PROMPT_VERSION` check) — this is
    exactly the pool that silently absorbed 1,114 cards under v10 with nobody looking
    at WHY until this module existed.

`refresh_errors` can be absent even on a blocked entry (an artifact of history — see
compiler.py's v9/v10 comments on that field's rollout) — `blocked_total` counts every
blocked entry, `blocked_with_data` counts how many actually carry a diagnosable reason,
so the report is honest about its own coverage rather than silently under-counting.

Each returned class is `[gate] normalized_message` (quoted values collapsed to 'X',
digits to N, so "trigger event 'etb' has no support..." and "...'dealt_damage' has no
support..." land in the same bucket instead of one-per-value) with a card-name sample.
The point is to run this BEFORE committing a night's compile budget to a prompt-version
bump — see `mythgauntlet ccm-health` — not just to explain one after the fact.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

_QUOTED = re.compile(r"'[^']*'")
_DIGITS = re.compile(r"\d+")
_GATE_MSG = re.compile(r"^\[(\w+)\]\s*(.*)$")


def _normalize_message(msg: str) -> str:
    """Collapse a gate error to its SHAPE, not its specific value."""
    msg = _QUOTED.sub("'X'", msg)
    msg = _DIGITS.sub("N", msg)
    return msg.strip()


def _bucket(errors_by_name: dict[str, list[str]], samples_per_class: int) -> list[dict]:
    """Group name -> [error strings] into [gate, message] classes, ranked by size.

    A card contributes AT MOST ONCE per class even if the same shape of error recurs
    across several of its abilities (e.g. three separate "needs a non-empty effects
    list" hits on one planeswalker) — the class size counts CARDS affected, not raw
    error lines, which is the number that actually matters for prioritizing a fix.
    """
    counts: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    seen_per_name: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for name, errors in errors_by_name.items():
        for err in errors:
            m = _GATE_MSG.match(err)
            if not m:
                continue
            key = (m.group(1), _normalize_message(m.group(2)))
            if key in seen_per_name[name]:
                continue
            seen_per_name[name].add(key)
            counts[key] += 1
            if len(examples[key]) < samples_per_class:
                examples[key].append(name)
    return [
        {"gate": gate, "message": msg, "count": n, "examples": examples[(gate, msg)]}
        for (gate, msg), n in counts.most_common()
    ]


def analyze_failures(
    entries: dict[str, dict], top_n: int = 12, samples_per_class: int = 5
) -> dict:
    """Bucket every recorded compile failure into ranked classes.

    `entries` is a ledger's raw `{name: entry}` dict (compiler.Ledger().entries or the
    JSON's "entries" key read directly, as overnight.py's ledger_stats() does).
    """
    versions = [e.get("prompt_version") or 0 for e in entries.values()]
    latest = max(versions, default=0)

    quarantined_errors = {
        e["name"]: e.get("errors") or []
        for e in entries.values()
        if e.get("status") == "quarantined"
    }
    blocked_entries = [
        e for e in entries.values()
        if e.get("status") == "accepted"
        and (e.get("prompt_version") or 0) < latest
        and e.get("refresh_failed_at") == latest
    ]
    blocked_errors = {e["name"]: e.get("refresh_errors") or [] for e in blocked_entries}

    return {
        "prompt_version": latest,
        "quarantined_total": len(quarantined_errors),
        "quarantined_classes": _bucket(quarantined_errors, samples_per_class)[:top_n],
        "blocked_total": len(blocked_entries),
        "blocked_with_data": sum(1 for e in blocked_entries if e.get("refresh_errors")),
        "blocked_classes": _bucket(blocked_errors, samples_per_class)[:top_n],
    }
