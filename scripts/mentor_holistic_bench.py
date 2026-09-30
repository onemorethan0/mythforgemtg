"""Acceptance bench for the Deck Mentor's OPEN-ENDED questions (docs/PLAN_MENTOR_ADHOC.md).

    python scripts/mentor_holistic_bench.py [--decks a,b] [--questions x,y]
        [--json out.json] [--model qwen3:14b] [--runs 150] [--turns N] [--list]
        [--regrade saved.json]

`scripts/mentor_bench.py` grades non-trap questions on `gated` alone, so a reply can be
fully grounded and still wrong about the deck ("somewhat vulnerable to wipes" for a deck the
engine measures at 93/100 resilience). This bench computes the engine's own ground truth once
per deck (`analyze_deck(..., run_resilience=True)`, `tool_get_deck_stats`, colour identity),
asks eight holistic questions through `mentor_chat.ask`, and grades each reply with the
MECHANICAL rubrics in `mentor_holistic_rubrics.py` (phrase maps live in
`mythgauntlet.mentor.verdicts`). Never an LLM judge (docs/MENTOR_HANDOFF.md, round 7).

The exit code is 0 whenever the script finishes: this is a measurement, not a gate.

Scaffold drafted by qwen3:14b from docs/specs/mentor_adhoc/A0.md and reviewed/fixed by hand;
the rubrics are hand-written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mythgauntlet.data import rulings  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.mentor import chat as mentor_chat  # noqa: E402
from mythgauntlet.mentor.tools import MentorContext, tool_get_deck_stats  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings.analysis import analyze_deck  # noqa: E402
from mythgauntlet.semantics.store import load_store  # noqa: E402
from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig  # noqa: E402
import mentor_holistic_rubrics as rubrics  # noqa: E402

DECKS: list[tuple[str, str, str]] = [
    ("shelob",   "archidekt-1010839.txt", "Shelob, Child of Ungoliant - B1 midrange spiders (the plan's reference deck)"),
    ("tymna",    "archidekt-23961193.txt", "Tymna the Weaver + Sidar Kondo - B1 partner deck"),
    ("kess",     "archidekt-24597563.txt", "Kess, Dissident Mage - B3 spellslinger"),
    ("ghired",   "archidekt-10310070.txt", "Ghired, Conclave Exile - B2 tokens / go-wide"),
    ("isshin",   "archidekt-25728474.txt", "Isshin, Two Heavens as One - B2 attack-trigger aggro"),
    ("najeela",  "archidekt-25769482.txt", "Najeela, the Blade-Blossom - B4 combo-ish warriors"),
    ("arahbo",   "archidekt-15559859.txt", "Arahbo, Roar of the World - B1 cat tribal"),
    ("kaalia",   "archidekt-24748428.txt", "Kaalia of the Vast - B1 cheat creatures into play"),
    ("meren",    "archidekt-24777697.txt", "Meren of Clan Nel Toth - B2 recursion / aristocrats"),
]

QUESTIONS: list[tuple[str, str, str | None]] = [
    ("overview",   "What does this deck do well and poorly?", None),
    ("cards",      "Which cards are doing the most work in this deck?", "overview"),
    ("faster",     "How could I make this deck faster?", None),
    ("resilience", "How resilient is this deck to a board wipe, and how could I improve that?", None),
    ("wincon",     "How does this deck win?", None),
    ("weakest",    "What are the weakest cards in this deck?", None),
    ("vs_b3",      "What is this deck's biggest weakness against a bracket 3 pod?", None),
    ("removal",    "Is my removal good enough, and what can it not answer?", None),
]

def load_world() -> tuple:
    db = load_card_db()
    cr = rulings.load_comprehensive_rules()
    rdb = rulings.load_rulings_db()
    print("Loading semantics store...", file=sys.stderr)
    store = load_store()
    return (db, cr, rdb, store)

def build_truth(key: str, path: Path, world: tuple, runs: int, turns: int) -> dict | None:
    db, cr, rdb, store = world
    deck_text = path.read_text(encoding="utf-8")
    deck = Deck.parse_text(deck_text, name=path.stem)
    resolved = resolve(deck, db)
    if not resolved.cards:
        print(f"Deck {key} has no cards; skipping.", file=sys.stderr)
        return None
    cfg = SimConfig(turns=turns, runs=runs, seed=42)
    ctx = MentorContext(card_db=db, cr=cr, rulings_db=rdb, resolved=resolved, cfg=cfg, store=store)
    analysis = analyze_deck(resolved, cfg, store, run_resilience=True)
    stats = tool_get_deck_stats(ctx).data
    identity = frozenset(ch for c in resolved.commanders for ch in c.color_identity)
    deck_names = frozenset([c.name for c, _qty in resolved.cards]
                           + [c.name for c in resolved.commanders])
    truth = {
        "key": key,
        "ctx": ctx,
        "analysis": analysis,
        "stats": stats,
        "identity": identity,
        "deck_names": deck_names,
    }
    return truth

def run_deck(key, truth, questions, model) -> list[dict]:
    rows = []
    replies = []
    for qid, question, follow_up_of in questions:
        history = None
        if follow_up_of:
            for prev_qid, prev_question, _ in questions:
                if prev_qid == follow_up_of:
                    for row in rows:
                        if row["qid"] == prev_qid:
                            history = [
                                {"role": "user", "content": prev_question},
                                {"role": "assistant", "content": row["reply"]}
                            ]
                            break
                    break
        # llama-swap answers 502/503 while it swaps a model in (the previous one was evicted
        # on its idle TTL); that is transient, so retry before giving up on a long run.
        for attempt in range(4):
            try:
                start = time.time()
                reply = mentor_chat.ask(truth["ctx"], question, history, model=model)
                break
            except mentor_chat.LLMUnavailable as exc:
                print(f"LLM unavailable for {key} {qid} (attempt {attempt + 1}/4): {exc}",
                      file=sys.stderr)
                if attempt == 3:
                    sys.exit(2)
                time.sleep(20 * (attempt + 1))
        dt = time.time() - start
        passed, reason = rubrics.grade(qid, reply, truth)
        row = {
            "deck": key,
            "qid": qid,
            "question": question,
            "passed": passed,
            "reason": reason,
            "gated": reply.gated,
            "seconds": round(dt, 1),
            "reply": reply.text,
            "tools": [t.name for t in reply.tool_trace],
            "tool_trace": [{"name": t.name, "args": t.args, "result": t.result_data} for t in reply.tool_trace],
            "rejections": [{"draft": d, "reasons": r} for d, r in reply.gate_rejections]
        }
        rows.append(row)
        replies.append(reply)
        print(f"[{key}] {qid} {fmt(passed)} ({dt:.1f}s)", file=sys.stderr)
    colour_passed, colour_reason = rubrics.grade_colour(replies, truth)
    rows.append({
        "deck": key,
        "qid": "colour",
        "question": "(all replies)",
        "passed": colour_passed,
        "reason": colour_reason,
        "gated": True,
        "seconds": 0.0,
        "reply": "",
        "tools": [],
        "tool_trace": [],
        "rejections": []
    })
    return rows

def fmt(passed):
    if passed is True:
        return "PASS"
    elif passed is False:
        return "FAIL"
    else:
        return "n/a"

def print_table(rows, deck_keys, qids):
    deck_to_rows = {}
    for row in rows:
        deck_key = row["deck"]
        if deck_key not in deck_to_rows:
            deck_to_rows[deck_key] = {}
        qid = row["qid"]
        deck_to_rows[deck_key][qid] = row

    headers = ["deck"] + list(qids)
    table = [headers]
    for deck_key in deck_keys:
        cells = deck_to_rows.get(deck_key, {})
        table.append([deck_key] + [fmt(cells[q]["passed"]) if q in cells else "--" for q in qids])

    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    for row in table:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))

    fail_rows = []
    for row in rows:
        if row["passed"] is False:
            fail_rows.append((row["deck"], row["qid"], row["reason"]))
    for deck_key, qid, reason in fail_rows:
        print(f"  {deck_key} {qid}: {reason}")

    qid_summary = {}
    for row in rows:
        qid = row["qid"]
        if qid not in qid_summary:
            qid_summary[qid] = {"pass": 0, "total": 0}
        if row["passed"] is not None:
            qid_summary[qid]["total"] += 1
            if row["passed"] is True:
                qid_summary[qid]["pass"] += 1

    for qid in qid_summary:
        total = qid_summary[qid]["total"]
        pass_count = qid_summary[qid]["pass"]
        if total > 0:
            percent = f"{(pass_count / total) * 100:.0f}"
            print(f"{qid}: {pass_count}/{total} ({percent}%)")
        else:
            print(f"{qid}: n/a")

    overall_pass = 0
    overall_total = 0
    for qid in qid_summary:
        total = qid_summary[qid]["total"]
        pass_count = qid_summary[qid]["pass"]
        if total > 0:
            overall_total += total
            overall_pass += pass_count
    if overall_total > 0:
        percent = f"{(overall_pass / overall_total) * 100:.0f}"
        print(f"OVERALL: {overall_pass}/{overall_total} ({percent}%)")

    gated_count = 0
    total_gated = 0
    for row in rows:
        if row["qid"] != "colour":
            total_gated += 1
            if row["gated"] and not row["rejections"]:
                gated_count += 1
    print(f"gated on first attempt: {gated_count}/{total_gated}")

def _stand_in_reply(row: dict):
    """A MentorReply look-alike rebuilt from a saved JSON row (for --regrade)."""
    from types import SimpleNamespace
    return SimpleNamespace(
        text=row["reply"], gated=row["gated"],
        gate_rejections=[(r["draft"], r["reasons"]) for r in row["rejections"]],
        tool_trace=[SimpleNamespace(name=t["name"], args=t["args"], result_data=t["result"])
                    for t in row["tool_trace"]],
    )


def regrade(data: dict, world: tuple, runs: int, turns: int) -> list[dict]:
    """Re-grade a saved --json run with the CURRENT rubrics -- no model calls. Ground truth
    is recomputed (analyze_deck is deterministic for a given deck and SimConfig). Used to
    compare a baseline and a later run under ONE rubric version after the rubrics were
    refined from reading replies."""
    out: list[dict] = []
    by_deck: dict[str, list[dict]] = {}
    for row in data["rows"]:
        by_deck.setdefault(row["deck"], []).append(row)
    for key, filename, _note in DECKS:
        rows = by_deck.get(key)
        if not rows:
            continue
        truth = build_truth(key, ROOT / "corpus" / "decks" / filename, world, runs, turns)
        if truth is None:
            continue
        replies = []
        for row in rows:
            if row["qid"] == "colour":
                continue
            reply = _stand_in_reply(row)
            replies.append(reply)
            passed, reason = rubrics.grade(row["qid"], reply, truth)
            out.append({**row, "passed": passed, "reason": reason})
        passed, reason = rubrics.grade_colour(replies, truth)
        colour = next((r for r in rows if r["qid"] == "colour"), {"deck": key, "qid": "colour"})
        out.append({**colour, "passed": passed, "reason": reason})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Mentor holistic bench")
    parser.add_argument("--regrade", type=Path,
                        help="re-grade a saved --json run with the current rubrics (no model calls)")
    parser.add_argument("--decks", type=str, default="shelob,tymna,kess,ghired,isshin,najeela,arahbo,kaalia,meren")
    parser.add_argument("--questions", type=str, default="overview,cards,faster,resilience,wincon,weakest,vs_b3,removal")
    parser.add_argument("--json", type=Path, help="Output JSON file")
    parser.add_argument("--model", type=str, default="qwen3:14b")
    parser.add_argument("--runs", type=int, default=150)
    parser.add_argument("--turns", type=int, default=DEFAULT_ANALYZE_TURNS)
    parser.add_argument("--list", action="store_true", help="List available decks and exit")
    args = parser.parse_args()

    if args.list:
        print("Available decks:")
        for key, filename, note in DECKS:
            print(f"- {key}: {filename} - {note}")
        return 0

    if args.regrade:
        data = json.loads(args.regrade.read_text(encoding="utf-8"))
        rows = regrade(data, load_world(), data.get("runs", args.runs), data.get("turns", args.turns))
        deck_keys = [k for k, _f, _n in DECKS if any(r["deck"] == k for r in rows)]
        qids = [q[0] for q in QUESTIONS] + ["colour"]
        print_table(rows, deck_keys, qids)
        return 0

    decks = []
    for deck_key in [d.strip() for d in args.decks.split(",") if d.strip()]:
        found = False
        for key, filename, note in DECKS:
            if deck_key == key or deck_key == filename:
                decks.append((key, filename, note))
                found = True
                break
        if not found:
            parser.error(f"Unknown deck: {deck_key}")

    wanted = [q.strip() for q in args.questions.split(",") if q.strip()]
    known = {q[0] for q in QUESTIONS}
    for qid in wanted:
        if qid not in known:
            parser.error(f"Unknown question: {qid}")
    # QUESTIONS order, not CLI order: a follow-up must come after its parent.
    questions = [q for q in QUESTIONS if q[0] in wanted]

    world = load_world()
    rows = []
    for key, filename, note in decks:
        path = ROOT / "corpus" / "decks" / filename
        truth = build_truth(key, path, world, args.runs, args.turns)
        if truth is None:
            continue
        deck_rows = run_deck(key, truth, questions, args.model)
        rows.extend(deck_rows)

    if args.json:
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data = {
            "model": args.model,
            "runs": args.runs,
            "turns": args.turns,
            "rows": rows,
            "started": started
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    deck_keys = [key for key, _, _ in decks]
    qids = [qid for qid, _, _ in questions] + ["colour"]
    print_table(rows, deck_keys, qids)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
