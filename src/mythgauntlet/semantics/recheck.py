"""Re-validate ACCEPTED CCMs against the CURRENT gates.

There was no door for this, and the gap is structural rather than incidental. The compile
pipeline decides what to re-attempt from `prompt_version`: `--refresh-stale` picks up
cards accepted under an OLDER prompt, and `--retry-quarantined` / `--retry-blocked` are
narrow doors into the two failure pools. Nothing revisits a card that is **accepted at
the current prompt version and has since been invalidated by a gate change** — and
`--retry-quarantined`'s own help says the quiet part out loud: *"use after a SCHEMA or
gate change, which the prompt_version gate cannot see"*. It just cannot see accepted
cards either.

So a gate improvement only ever reached FUTURE compiles. The ~31k CCMs already in the
store kept whatever defect the new gate was written to catch, invisibly, because nothing
ever asked them the question again. Bumping `PROMPT_VERSION` is the sledgehammer that
does reach them, at the cost of marking every good CCM stale — weeks of GPU to fix a
defect that, for the duration gate this module was written alongside, affects 0.75% of
the store.

`recheck_accepted` is the missing question: run every accepted stored CCM back through
`ccm.validate` and report what NO LONGER PASSES, bucketed by `[gate] message` exactly the
way `health.analyze_failures` buckets compile failures — so the output reads the same and
the same triage habits apply. It costs no GPU and makes a gate change auditable BEFORE
deciding whether the repair is worth the compute.

Diagnosis only: this never writes to the ledger or the store. Turning its worklist into
recompiles is a separate, explicit decision (`mythgauntlet ccm-recheck --names-out`, fed
to a targeted compile), for the same reason `ccm-health` reports rather than acts.
"""

from __future__ import annotations

from collections import defaultdict

from mythgauntlet.semantics import ccm
from mythgauntlet.semantics.health import _bucket


def recheck_accepted(
    envelopes,
    card_lookup,
    top_n: int = 12,
    samples_per_class: int = 5,
) -> dict:
    """Re-run the gates over accepted CCMs; report which now fail and why.

    `envelopes` yields stored `{"card": ..., "ccm": ...}` documents and `card_lookup`
    maps a name to a `Card` (the caller owns both, so this stays pure and testable with
    no store on disk — the same contract `health.analyze_failures` has with the ledger).

    A card whose `Card` cannot be resolved is counted in `unresolved` rather than skipped
    silently: a stale card DB would otherwise look like a clean bill of health.
    """
    errors_by_name: dict[str, list[str]] = defaultdict(list)
    failing_names: list[str] = []
    checked = unresolved = 0

    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        doc = envelope.get("ccm")
        name = (envelope.get("card") or {}).get("name")
        if not isinstance(doc, dict) or not name:
            continue
        card = card_lookup(name)
        if card is None:
            unresolved += 1
            continue
        checked += 1
        try:
            gates = ccm.validate(doc, card)
        except Exception as exc:  # a malformed stored doc is itself a finding
            errors_by_name[name].append(f"[validate] raised {type(exc).__name__}")
            failing_names.append(name)
            continue
        messages = [
            f"[{gate}] {message}"
            for gate, gate_errors in gates.items()
            for message in gate_errors
        ]
        if messages:
            errors_by_name[name].extend(messages)
            failing_names.append(name)

    return {
        "checked": checked,
        "unresolved": unresolved,
        "failing": len(failing_names),
        "failing_names": sorted(failing_names),
        "classes": _bucket(errors_by_name, samples_per_class)[:top_n],
    }
