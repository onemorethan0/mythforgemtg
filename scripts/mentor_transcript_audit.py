"""Mine REAL Deck Mentor conversations for what the synthetic bench can't see.

    python scripts/mentor_transcript_audit.py

`scripts/mentor_bench.py` grades synthetic questions the developer thought to ask.
`mentor_transcripts.jsonl` (`mythgauntlet.mentor.transcript`) already logs every REAL
question a real user asked, the gate's verdict, and the thumbs up/down that followed --
Phase 3 of the mentor build wrote that log and nothing has read it back since. This is
that missing read: it does no grading of its own and invents no new "correct" answers,
it just surfaces the two signals a synthetic bench structurally cannot produce, because
they require a real person to have actually used the feature:

    FALSE NEGATIVE  -- gate said `gated: True` (no fabrication caught) but the human
                       rated the reply down anyway. The gate's checks (card names, rule
                       citations, numbers) are necessary, not sufficient -- a reply can
                       clear every one of them and still be wrong or unhelpful. These are
                       the turns that matter most, because a passing synthetic bench case
                       cannot expose this failure mode by construction.
    CAUGHT ATTEMPT  -- turns where the gate actually rejected one or more drafts before
                       settling on a final answer (`gate_rejections` non-empty). This is
                       the model's real fabrication behaviour on real questions, which is
                       exactly what a hand-picked heuristic vocabulary (gate.py's
                       rules-paraphrase check) should be tuned against instead of guessed.

Per this repo's "no silent caps" convention, every flagged turn is printed in full.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mythgauntlet.mentor import transcript  # noqa: E402

HIGH_TOOL_CALL_THRESHOLD = 4  # MAX_TOOL_TURNS in chat.py is 6; flag turns approaching it


def analyze(records: list[dict]) -> dict:
    """Pure analysis over transcript records -- no I/O, so this is the unit-testable
    core. Returns the raw groupings; `main()` owns all printing."""
    turns = {r["turn_id"]: r for r in records if r.get("event") == "turn"}
    # A turn can receive more than one feedback event (a person changing their mind, or a
    # UI double-fire) -- keep the LAST rating per turn_id, since that's what the user's
    # final judgment actually was.
    feedback: dict[str, dict] = {}
    for r in records:
        if r.get("event") == "feedback":
            feedback[r["turn_id"]] = r

    rating_counts = Counter(f["rating"] for f in feedback.values())
    unrated = [tid for tid in turns if tid not in feedback]
    false_negatives = [
        turns[tid] for tid, f in feedback.items()
        if f["rating"] == "down" and turns.get(tid, {}).get("gated")
    ]
    caught_attempts = [t for t in turns.values() if t.get("gate_rejections")]
    high_tool_use = [
        t for t in turns.values()
        if len(t.get("tool_trace") or []) >= HIGH_TOOL_CALL_THRESHOLD
    ]
    return {
        "turns": turns,
        "feedback": feedback,
        "rating_counts": rating_counts,
        "unrated": unrated,
        "false_negatives": false_negatives,
        "caught_attempts": caught_attempts,
        "high_tool_use": high_tool_use,
    }


def _print_turn(turn: dict, label: str) -> None:
    print(f"\n[{label}] turn_id={turn['turn_id']}")
    print(f"  deck: {turn.get('deck_commander')} ({turn.get('deck_card_count')} cards)")
    print(f"  question: {turn.get('question')!r}")
    print(f"  reply: {turn.get('reply')!r}")
    print(f"  gated: {turn.get('gated')}  tool_calls: {len(turn.get('tool_trace') or [])}")
    for draft, reasons in [(r["draft"], r["reasons"]) for r in turn.get("gate_rejections") or []]:
        print(f"  REJECTED DRAFT: {draft!r}\n    reasons: {reasons}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--path", type=Path, default=None, help="override transcript path (testing)")
    args = p.parse_args()

    records = transcript.load_transcript(args.path)
    result = analyze(records)
    turns, feedback = result["turns"], result["feedback"]

    if not turns:
        print("No real mentor conversations logged yet -- nothing to audit.")
        print(f"(checked {args.path or transcript.transcript_path()})")
        return 0

    rating_counts, unrated = result["rating_counts"], result["unrated"]
    false_negatives = result["false_negatives"]
    caught_attempts = result["caught_attempts"]
    high_tool_use = result["high_tool_use"]

    print(f"{len(turns)} real turn(s), {len(feedback)} rated "
          f"({rating_counts.get('up', 0)} up / {rating_counts.get('down', 0)} down), "
          f"{len(unrated)} unrated.\n")

    if false_negatives:
        print(f"=== {len(false_negatives)} FALSE NEGATIVE(S) -- gated=True but rated down ===")
        print("These are gold-set candidates: the gate missed something a human caught.")
        for t in false_negatives:
            _print_turn(t, "FALSE NEGATIVE")
    else:
        print("No false negatives found (no down-rated turn that the gate marked verified).")

    if caught_attempts:
        print(f"\n=== {len(caught_attempts)} CAUGHT ATTEMPT(S) -- gate rejected a draft ===")
        print("Real fabrication patterns to tune gate.py's heuristics against.")
        for t in caught_attempts:
            _print_turn(t, "CAUGHT")
    else:
        print("\nNo caught-attempt turns found (gate never had to reject a draft yet).")

    if high_tool_use:
        print(f"\n=== {len(high_tool_use)} HIGH TOOL-CALL turn(s) (>= {HIGH_TOOL_CALL_THRESHOLD}) ===")
        for t in high_tool_use:
            _print_turn(t, "HIGH TOOL USE")

    if unrated:
        print(f"\n{len(unrated)} turn(s) have no feedback yet -- rating more real answers "
              "(thumbs up/down in the Forge chat panel) directly grows this audit's power.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
