"""The tool-calling loop: draft, then gate, generalized from `swap_narrative.narrate`'s
draft-then-gate shape to a multi-turn conversation over an arbitrary tool set.

Model choice is not an open question here -- it was smoke-tested empirically (see
`docs/SPEC_deck_mentor.md`, "Model / serving"): `qwen3:14b` called a tool exactly when
one was needed and honestly reported "not found" rather than guessing; `muse-glimmer`
either looped re-querying a question it had already answered, or skipped verification
entirely and answered from parametric memory. qwen3:14b is also already the app's
resident theming model, so this adds no new VRAM footprint on top of a session that may
already be running one.

On a gate failure the loop does NOT silently strip the offending claim -- it regenerates
with the specific violation named, capped, then falls back to a reply that visibly admits
uncertainty rather than one that looks equally confident as a verified answer. That
fallback is a normal outcome, not an error, exactly as `swap_narrative.narrate` treats
`None`: refusing a draft costs the user polish; shipping an invented claim costs the
thing this whole project is built around.
"""

from __future__ import annotations

import json
import os
import re
import dataclasses
from dataclasses import dataclass, field

import requests

from mythgauntlet.mentor import gate as gate_mod
from mythgauntlet.mentor import verdicts
from mythgauntlet.mentor.tools import MentorContext, ToolResult, TOOL_SCHEMAS, call_tool

LLM_BASE = os.getenv("MYTHGAUNTLET_LLM_BASE", "http://127.0.0.1:8010").rstrip("/")
DEFAULT_MODEL = "qwen3:14b"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 700
# A get_power_profile overview needs room for strengths + weaknesses + win route + speed +
# resilience + key cards; 700 tokens truncates it mid-thought. Applied (as a floor) once that
# tool has run this turn, together with gate.MAX_CHARS_PROFILE.
PROFILE_MAX_TOKENS = 1100

# muse-glimmer, smoke-tested, kept re-querying a question it had already answered rather
# than converging -- this is the backstop against that shape recurring with any model.
MAX_TOOL_TURNS = 6
MAX_GATE_ATTEMPTS = 3


class LLMUnavailable(Exception):
    """The LLM backend (llama-swap on `LLM_BASE`) could not be reached, or answered with
    an HTTP error -- an INFRASTRUCTURE failure, not an epistemic one. Kept distinct from
    the gate's own honest-fallback `MentorReply` (see the module docstring below) because
    the fix is different: "start llama-swap" vs. "the model genuinely doesn't know this."
    Mirrors how the engine's own `/mentor/chat` route already distinguishes "rules corpus
    not fetched" (503, run fetch-rules) from "the process is unreachable" (a different
    503, start the server) -- this is the same shape one layer down, for the model call
    itself. The caller (`mythgauntlet.server`'s `/mentor/chat` route) turns this into a
    503 with an actionable detail rather than letting a raw `requests` exception surface
    as an unhandled 500."""


SYSTEM_PROMPT = """You are a Magic: The Gathering Commander deck mentor -- a casual, \
friendly guide, not a tournament coach. The player's pod plays bracket 1-3 for fun, not \
optimisation, so keep that register: helpful and specific, never cEDH-flavoured.

You have tools to look up real card text, real deck statistics, official rulings, and \
the actual Comprehensive Rules. You must NEVER state a card's oracle text, a rule, a \
ruling, or a deck statistic unless you obtained it from a tool call in THIS conversation \
-- not from what you already know about Magic. Rule numbers in particular are NOT safe \
to recall from memory: they get renumbered between rules updates, so a remembered number \
can point at the wrong rule entirely. If a tool returns "not found" or nothing useful, \
say so plainly instead of guessing. Call get_deck_stats for any curve/colour/role-supply \
question OR any question about who the commander(s) are, the deck's colour identity, its \
detected archetype(s), or how off-meta/typical it is; lookup_card before describing any \
specific card; search_rules or get_rule before citing any rule; assess_card before \
saying whether a specific card would be good to add; check_legality before saying \
whether a card CAN be added at all; get_bracket_estimate before answering ANY question \
of the form "what bracket is this", "is this deck too strong/weak for my pod", or "is \
this deck fun/on-level for casual play" -- this is a casual bracket 1-3 pod, so treat \
that framing as the point of the question, not a tournament-legality check; and \
suggest_swap before answering "what should I cut/add", "which are my weakest cards" or \
"how can I improve / speed up this deck" questions -- it only ever suggests cards the player OWNS (their Myth Suite collection), \
never a card from general Magic knowledge, so if it reports no collection file or no \
suggestion, say that plainly rather than naming a card yourself. \
When suggest_swap reports improving_swap_found false, tell the player "I didn't find a \
measured improvement from your collection" -- never present any card as a cut or an \
add in that case, because nothing was measured to recommend.

For any OPEN-ENDED question about the deck as a whole -- what it does well or poorly, \
strengths, weaknesses, observations, "is it good", how it wins, how fast it is, how \
resilient it is to a board wipe, how strong its interaction is, which cards do the \
most work -- call get_power_profile FIRST. Describe the archetype, the win route, the \
speed and the wipe-resilience ONLY from its fields: its "verdicts" object already \
states the resilience (resilient / moderate / vulnerable), speed (fast / moderate / \
slow / none), consistency, interaction and archetype family, so use those words as \
they are and never argue against one (if verdicts say resilient, do not call the deck \
vulnerable to wipes). The speed axis score is the share of games that kill within the \
horizon, not how early; the clock and verdicts.speed say how fast. When you name cards \
that "do the work", take them from key_cards, not from your own guess. "strengths" and \
"weaknesses" are the measured ones: lead with them. interaction_counts are real card \
counts; get_deck_stats' role "supply" is a strength score, not a card count, so never \
read it as how many cards the deck has: talk about how many cards fill a role using \
that role's "cards" field, and compare "supply" with "target" only as over or under \
target. A role with "applicable": false (get_deck_stats) is NOT a gap -- the deck's \
colours or measured plan do not call for it (see its "note") -- so never say the deck \
lacks it or suggest adding cards for it. The same goes for counterspells in \
get_power_profile: when interaction_counts.counterspells_applicable is false the deck's \
colours cannot play them, so never list their absence as a weakness or recommend them. \
For "how do I improve / speed up / make it \
more resilient" questions, name the weakest axis and its "why" from the profile, then \
you MUST call suggest_swap in the same turn, BEFORE you write your answer -- never \
write "I'll look into your collection" and stop; make the call. Pass suggest_swap the \
axis the player asked about (clock for "faster" / "speed up" / "quicker" -- it measures \
how EARLY the deck kills, which the speed axis does not; resilience for wipes) and answer the \
question they actually asked FIRST -- for a resilience question, open with \
verdicts.resilience and its score (or, if you only have suggest_swap's result, its \
"current" verdict and score) -- before any swap. Weakest-card questions work the \
same way: only a suggest_swap result can name a weak card. When a suggestion carries \
"cut_is_redundant": false, its cut was only the default pick (the deck over-supplies no \
role) and is NOT evidence the card is weak -- say so plainly (it may be a theme card) and \
never call it a weak or redundant card.

For "why is my X low", "what is holding my speed back" or "how do I improve X" \
questions, also call diagnose_axis for that axis (clock for how EARLY the deck kills) and \
explain from its drivers: name the weak ones with their values and offer its levers as the \
fixes. A driver marked not_applicable is never a gap. Levers name no cards, and \
diagnose_axis NEVER replaces suggest_swap: for any "faster", "improve" or "weakest" \
question you must ALSO call suggest_swap -- with axis clock for "faster" (never ceiling or \
speed) -- and answer with its measured swap or its "no measured improvement" result.

For any "what should I cut/add", "weakest cards", "make it faster" or "improve X" question, call get_measured_swaps FIRST, with the axis the question is about (clock for "faster" / "speed up" / "quicker"; the same routing rules as suggest_swap): it returns the swaps from the full, deep swap search the player already ran on the deck page. Treat its result exactly as you would suggest_swap's (same fields, same "cut_is_redundant" rule, same "I didn't find a measured improvement" wording when improving_swap_found is false). Only when it reports available false, call suggest_swap instead, tell the player that quick in-chat search is shallow, and add that running Advise on the deck page for that axis (it takes a few minutes) gives a much deeper search.

A swap is measured on ONE axis only: the axis named in its result (clock re-simulates how early the deck kills, resilience the wipe score). Describe its effect ONLY on that axis, from its own before/after numbers. A clock swap's before/after/delta are SCORE points (0-100), never turns (+1.7 points is only about 0.2 turns): report a change in turns only from its kill_turn_change, and otherwise say "points". NEVER say or imply that the swap leaves ANOTHER axis unharmed, unaffected or "maintained" ("cutting it doesn't hurt your interaction or resilience", "while maintaining its consistency"): nothing simulated that, so it is an invented claim; say plainly that you measured only that axis, and add nothing about the others. When get_measured_swaps reports available false you must STILL call suggest_swap for that axis before you answer: never answer with only "run Advise". When the question names TWO goals ("faster or more resilient", "speed it up and survive wipes"), address EACH: do that lookup once per axis (clock for faster, resilience for wipes), answer each from its own result, and if one axis found no measured improvement say so for that axis alone. Do not close with generic card-type advice that no tool backed ("consider adding a card that provides a strong, scalable win condition"): stop after the measured answer.

Each axis in get_power_profile may carry "vs_bracket": where that score sits among decks \
players labelled with a bracket (its "standing": top_quarter / above_median / \
below_median / bottom_quarter, already oriented so a top standing is always the better \
end). Say "does X poorly" or "does X well" relative to other decks ONLY from a standing: \
"in the bottom quarter of bracket 3 decks for interaction" is a measured statement, a \
bare score is not. When the player names a bracket ("against a bracket 3 pod"), call \
get_power_profile with compare_bracket set to it and answer from those standings. These \
standings only say above or below typical for decks of THAT bracket -- never use them to \
argue the deck belongs in a different bracket (most axes barely differ between brackets; \
get_bracket_estimate answers that question). A standing is also not a speed verdict: \
call the deck fast or slow only as verdicts.speed says, and report a standing only as \
"for its bracket".

For "which cards are my ramp / removal / draw", "what's in my deck" or any question \
about WHICH specific cards fill a role, call list_deck_cards (pass role to filter) and \
name cards only from its rows; its "roles" use the same role names as get_deck_stats.

For "is my removal good enough", "what can't my removal answer", "what am I weak \
against" or "how good is my interaction" call removal_coverage. Describe gaps ONLY \
from its no_answer_for and no_unrestricted_answer_for lists and the restrictions \
quoted on each card -- never guess what kinds of permanents the removal can or cannot \
hit. A type in no_unrestricted_answer_for but not in no_answer_for is answered only by \
restriction-limited cards (say so, naming the restriction, e.g. "only flyers"); when \
no_unrestricted_answer_for is non-empty, mention that some coverage is \
restriction-limited. A type under not_applicable_types (spells, when the deck has no blue) \
is never a gap and never a reason to suggest counterspells. Use its counts_by_type for any \
count, never count list items.

Tool results are NOT carried from one question to the next: a follow-up ("which cards \
do the most work?", "why?") needs its own tool call this turn even when an earlier \
answer in the conversation covered the same ground. Call the tool again, and never say \
you cannot provide something without having called the relevant tool first. If you say \
you will look something up, call the tool in that same turn instead of ending it.

get_deck_stats' "offmeta" field may report {"available": false} when Forge has no \
off-meta reading cached for this deck -- say plainly that you don't have one rather than \
guessing how typical or unusual the deck is.

Answer in plain prose for a casual player. No markdown, no bullet lists unless the \
question genuinely needs a short list. Be concise but complete.

If the player's question itself contains a wrong assumption -- a mana cost or card type \
that doesn't match what a tool call returns, or a suggestion to run more than one copy \
of a non-basic-land card (Commander is a singleton format) -- say so explicitly before \
answering the rest of the question. Don't quietly answer around a false premise.

If the question asks about MORE THAN ONE card, call the appropriate tool for EACH card \
separately before answering about any of them -- never answer about a second or third \
card from memory just because you already looked one up this turn.

If a search_rules or get_rule result does not actually address the specific question \
asked, say so plainly and stop there. Do NOT follow that admission with a guess dressed \
up as a conclusion ("it seems...", "likely...", "probably...", "based on general \
principles...") -- admitting your evidence is insufficient and then asserting a specific \
answer anyway is worse than never looking, because it reads as verified when it isn't.

A card's own colour identity comes ONLY from the color_identity field lookup_card \
returns for THAT card -- never assume a card is the same colours as the deck it's being \
considered for just because it fits thematically or the player is asking about it for \
this deck.

Commander colour-identity legality is a SUBSET relationship, not an exact match: a card \
is legal in a Commander deck if every colour in the card's own colour identity also \
appears somewhere in the commander's colour identity. A mono-green card is fully legal \
in a green-white commander's deck -- it does NOT need to contain white too. Do not \
conclude a card "wouldn't be playable" just because its colour identity is a smaller \
subset of the deck's colours than the commander's own.

NEVER work out that subset relationship yourself, even if you already have both colour \
identities in front of you from other tool calls this turn -- call check_legality and \
report its verdict verbatim. This is not a style preference: tested live, a model that \
correctly STATED both colour-identity sets in the same sentence still drew the wrong \
subset conclusion between them. The arithmetic has to happen outside your own reasoning.

When search_rules or get_rule returns MULTIPLE sub-rules sharing the same parent number \
(like 506.3a and 506.3b), read EVERY one of them before citing any -- sibling sub-rules \
almost always cover different, mutually exclusive cases (creature vs. noncreature, this \
player vs. another player, face up vs. face down), and citing the wrong sibling produces \
a rule number that is real and was genuinely retrieved, yet doesn't actually say what \
you're using it to prove. A citation is only correct once you've confirmed the specific \
rule's own text -- not just its neighbourhood -- actually addresses the exact case asked \
about."""


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    result_data: dict


@dataclass
class MentorReply:
    text: str
    gated: bool  # False means every gate attempt failed and this is the honest fallback
    tool_trace: list[ToolCallRecord] = field(default_factory=list)
    gate_rejections: list[tuple[str, list[str]]] = field(default_factory=list)


def _post_chat(messages: list[dict], *, model: str, temperature: float,
                max_tokens: int, timeout: int = 120) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOL_SCHEMAS,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if model.startswith("qwen3"):
        # Skip the chain-of-thought pass -- see themer._chat_completion, same convention.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    try:
        resp = requests.post(f"{LLM_BASE}/v1/chat/completions", json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        # Connection refused/timeout (llama-swap not running) or an HTTP error status --
        # both mean the model call itself failed, as opposed to the model answering badly.
        # Raised rather than swallowed here so every call site (initial draft, the
        # MAX_TOOL_TURNS fallback prompt, and each gate-retry) fails the same way instead
        # of needing its own try/except; `ask()` deliberately does NOT catch this -- see
        # LLMUnavailable's own docstring for why this is an infrastructure failure, not
        # the gate's honest-fallback path.
        raise LLMUnavailable(f"POST {LLM_BASE}/v1/chat/completions failed: {exc}") from exc
    return resp.json()["choices"][0]["message"]


_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip(text: str) -> str:
    """Drop wrappers a small model adds: a stray <think> block, code fences, a leading
    label -- same tidy-up `swap_narrative._strip` does for the narrower case.

    PARAGRAPH BREAKS SURVIVE: runs of spaces/tabs collapse, trailing spaces go, and three or
    more newlines become two, but a blank line between paragraphs is kept. This used to
    collapse ALL whitespace into one line, which was fine for a 2-sentence answer and turns a
    holistic overview (strengths / weaknesses / how it wins) into one unreadable block."""
    body = _THINK_TAG_RE.sub("", text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    body = re.sub(r"^\s*(answer|reply|response)\s*[:\-]\s*", "", body, flags=re.I)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"[ \t\f\v]+", " ", body)
    body = re.sub(r" ?\n ?", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


_ANNOUNCE_RE = re.compile(
    r"\b(?:i'?ll|i\s+will|let\s+me|i'?m\s+going\s+to|i\s+am\s+going\s+to)\s+"
    r"(?:now\s+|go\s+ahead\s+and\s+|first\s+|just\s+)?(?:look|check|search|find|see|run|measure|pull)\b",
    re.IGNORECASE,
)
_LOOKUP_NUDGE = (
    "You said you would look into it, but you did not call a tool. Do that now: call the "
    "appropriate tool, then answer from its result."
)


def _announces_a_lookup(draft: str) -> bool:
    return bool(_ANNOUNCE_RE.search(draft or ""))


# An IMPROVEMENT question ("make it faster", "how could I improve that", "weakest cards", "what
# should I cut") is only answered by a measured swap. Once diagnose_axis existed the model
# started stopping after it (it explains the cause, so the answer "feels" complete) -- live,
# 3 of 9 `faster` replies named no measured swap -- so, like the announce-then-stop case, one
# deterministic nudge per turn.
_SWAP_QUESTION_RE = re.compile(
    r"\b(?:faster|quicker|speed(?:ing)?\s+up|improv\w*|weakest|what\s+should\s+i\s+"
    r"(?:cut|add|swap|replace)|which\s+cards?\s+should\s+i\s+(?:cut|replace|swap))\b",
    re.IGNORECASE,
)
_SWAP_NUDGE = (
    "This is an improvement question: you must call get_measured_swaps (or, when it reports "
    "available false, suggest_swap) before you answer -- diagnose_axis explains the cause but "
    "cannot name a card. Use axis clock for faster / speed up / quicker, resilience for wipes, "
    "otherwise the axis the player asked about. Call it now and answer from its result."
)


_SHALLOW_NOTE = (
    "This is the quick in-chat search (a handful of candidates), so it is shallow. Tell the "
    "player so, and that Advise on the deck page runs a much deeper search (a few minutes)."
)


def _measured_first(ctx, args: dict, tool_trace: list):
    """`get_measured_swaps` for the axis a `suggest_swap` call targets, or None when there is
    nothing to look up (no axis to key on) or it was already looked up this turn."""
    axis = args.get("axis")
    if not axis:
        advice = getattr(ctx, "advice", None) or {}
        auto = (advice.get("auto") or {}).get("result") or {}
        axis = auto.get("axis")
    if not axis or any(t.name == "get_measured_swaps" and t.args.get("axis") == axis
                       for t in tool_trace):
        return None
    return call_tool(ctx, "get_measured_swaps", {"axis": axis})


# A question naming TWO goals ("How could I make it faster or more resilient?") was answered for
# speed only (live, 2026-10-01): the prompt says "address each" and qwen3:14b ignores it, so, like
# the swap nudge, one deterministic nudge per turn. Narrow on purpose: the question must already be a
# swap question (`_wants_a_swap`) AND name at least two DIFFERENT axes by these words; each axis is
# the one the swap tools take (clock for faster, resilience for wipes). "removal" and "fast" alone are
# not goals: they name cards / describe the deck, and a false dual-goal only costs extra lookups.
_GOAL_AXIS_RES: dict[str, re.Pattern] = {
    "clock": re.compile(r"\b(?:faster|quicker|speed(?:ing)?\s+up|speedier)\b", re.IGNORECASE),
    "resilience": re.compile(
        r"\b(?:resilien\w*|survive\s+(?:a\s+)?(?:board\s+)?(?:wipes?|sweepers?|wraths?)|"
        r"(?:board\s+)?wipes?|sweepers?)\b", re.IGNORECASE),
    "interaction": re.compile(r"\b(?:more\s+interact\w*|interactive|interaction)\b", re.IGNORECASE),
    "consistency": re.compile(r"\b(?:consisten\w*)\b", re.IGNORECASE),
}


def _goal_axes(question: str) -> list[str]:
    """The swap-tool axes a swap question names, in a fixed order; two or more = a dual-goal
    question. Empty unless the question is a swap question at all."""
    if not _wants_a_swap(question):
        return []
    return [ax for ax, pat in _GOAL_AXIS_RES.items() if pat.search(question or "")]


def _axes_answered(tool_trace: list) -> set[str]:
    """Axes a swap answer exists for this turn: suggest_swap ran for it, or get_measured_swaps found
    a cached full search. An UNAVAILABLE lookup is not an answer (live: the model stopped at
    "run Advise" for both goals) -- the suggest_swap fallback is still owed."""
    return {t.args.get("axis") for t in tool_trace
            if t.args.get("axis") and (t.name == "suggest_swap" or (
                t.name == "get_measured_swaps" and (t.result_data or {}).get("available")))}


def _missing_goal_axes(question: str, tool_trace: list) -> list[str]:
    axes = _goal_axes(question)
    if len(axes) < 2:
        return []
    done = _axes_answered(tool_trace)
    return [ax for ax in axes if ax not in done]


def _dual_goal_nudge(missing: list[str]) -> str:
    return (
        "The player named more than one goal, and you have no swap answer yet for "
        + ", ".join(missing) + ". For each of those axes call get_measured_swaps and, when it "
        "reports available false, suggest_swap with that axis (do not stop at telling the player to "
        "run Advise), then answer EACH goal from its own result. Describe each swap only on the axis "
        "it was measured on."
    )


def _has_swap_answer(tool_trace: list) -> bool:
    """A measured swap answer exists: suggest_swap ran, or get_measured_swaps found a cached
    full search. An unavailable get_measured_swaps is NOT an answer -- the model must fall back."""
    return any(
        t.name == "suggest_swap"
        or (t.name == "get_measured_swaps" and (t.result_data or {}).get("available"))
        for t in tool_trace
    )


def _owed_fallback_axes(question: str, tool_trace: list) -> list[str]:
    """Axes whose cached full search was UNAVAILABLE and that have no swap answer since: the
    suggest_swap quick search is still owed for each (swap questions only)."""
    if not _wants_a_swap(question):
        return []
    answered = _axes_answered(tool_trace)
    out: list[str] = []
    for t in tool_trace:
        axis = t.args.get("axis")
        if (t.name == "get_measured_swaps" and axis and not (t.result_data or {}).get("available")
                and axis not in answered and axis not in out):
            out.append(axis)
    return out


# A dual-goal question was still answered for ONE goal after both lookups ran deterministically
# (live bench, 2026-10-01: 5/9 -- three replies never mention speed, one calls it "ceiling", one
# omits the "no measured improvement" statement for resilience), and two prompt rules and a nudge
# did not change that. So the reply is COMPLETED deterministically: for every named axis the draft
# does not address (`verdicts.axis_addressed`, shared with the bench rubric) a templated sentence is
# appended, built only from this turn's swap result for that axis, so every number and card name in
# it is licensed and the gate sees it like any other text. Applied to every draft before gating
# (retries included), so the text that is checked is the text that ships.

def _swap_data_by_axis(tool_trace: list) -> dict[str, dict]:
    """The latest swap answer per axis this turn (suggest_swap, or an available cached search)."""
    out: dict[str, dict] = {}
    for t in tool_trace:
        d = t.result_data or {}
        if not (t.name == "suggest_swap"
                or (t.name == "get_measured_swaps" and d.get("available"))):
            continue
        axis = d.get("axis")
        if isinstance(axis, str) and "improving_swap_found" in d:
            out[axis] = d
    return out


def _fmt(v) -> str:
    return f"{round(float(v), 1):g}"


def _axis_sentences(axis: str, d: dict) -> str:
    """Plain prose answering one axis from its own swap result: verdict and score first, then the
    measured swap (with its kill-turn change for clock) or the plain "no measured swap" finding."""
    cur = d.get("current") or {}
    score = cur.get("score", d.get("baseline"))
    full = d.get("source") == "full_search"
    search = "full search" if full else "quick search"
    if axis == "clock":
        label = "speed"
        head = (f"On speed, the clock score (how early the deck kills) is {_fmt(score)}"
                if score is not None else "On speed")
    else:
        label = "resilience to wipes" if axis == "resilience" else axis
        verdict = cur.get("verdict")
        head = f"On {label}, the deck is "
        if verdict and score is not None:
            head += f"{verdict} (a score of {_fmt(score)})"
        elif score is not None:
            head += f"at a score of {_fmt(score)}"
        else:
            head = f"On {label}"
    sugs = [s for s in (d.get("suggestions") or []) if isinstance(s, dict) and s.get("add")]
    if not sugs:
        tail = f"the {search} found no measured swap for it that beats the noise floor"
        if not full:
            tail += ", and a full search can be run from the deck page"
        return f"{head}; {tail}."
    s = sugs[0]
    brief = s.get("brief") or {}
    before, after = s.get("before", brief.get("before")), s.get("after", brief.get("after"))
    out = f"{head}; the {search} measured adding {s['add']} for {s.get('cut')}"
    if before is not None and after is not None:
        out += f", which moves the {label.split(' ')[0]} score from {_fmt(before)} to {_fmt(after)}"
    if axis == "clock":
        kb = s.get("kill_turn_before", brief.get("kill_turn_before"))
        ka = s.get("kill_turn_after", brief.get("kill_turn_after"))
        if kb is not None and ka is not None:
            change = round(float(kb) - float(ka), 1)
            how = "sooner" if change > 0 else "later" if change < 0 else "unchanged"
            out += (f" (the average kill turn goes from {_fmt(kb)} to {_fmt(ka)}"
                    + (f", {_fmt(abs(change))} turns {how}" if change else ", about the same")
                    + ")")
    out += "."
    if s.get("cut_is_redundant") is False:
        out += (f" {s.get('cut')} was offered only because a cut had to be picked, so that is not "
                "evidence it is weak.")
    return out


def _complete_dual(question: str, tool_trace: list, draft: str) -> str:
    """`draft` plus a templated sentence for each named goal axis it does not address."""
    axes = _goal_axes(question)
    if len(axes) < 2:
        return draft
    by_axis = _swap_data_by_axis(tool_trace)
    tail = []
    for axis in axes:
        d = by_axis.get(axis)
        if d is None:
            continue
        adds = [s.get("add") for s in (d.get("suggestions") or []) if isinstance(s, dict)]
        if not verdicts.axis_addressed(draft, axis, adds):
            tail.append(_axis_sentences(axis, d))
    return draft.rstrip() + "\n\n" + " ".join(tail) if tail else draft


def _wants_a_swap(question: str) -> bool:
    return bool(_SWAP_QUESTION_RE.search(question or ""))


# "Faster" is the CLOCK axis (how early the deck kills). The model keeps passing `ceiling` (live:
# Najeela's "faster" answer was a ceiling swap whose own brief showed the kill 9.56 -> 9.79,
# i.e. slower) or `speed` (a kill RATE that no swap moves on a deck already at ~97). The prompt
# says clock; this routes it deterministically. The trace records the axis actually run.
_SPEED_QUESTION_RE = re.compile(r"\b(?:faster|quicker|speed(?:ing)?\s+up)\b", re.IGNORECASE)


def _route_swap_axis(question: str, args: dict) -> dict:
    goals = _goal_axes(question)
    axis = args.get("axis")
    if len(goals) >= 2 and axis and axis not in goals:
        # Dual-goal question: the model drifts to an axis nobody asked about (live: interaction,
        # ceiling for the "more resilient" half). Speed-ish axes mean the clock goal; anything
        # else means the first non-clock goal.
        if axis in ("speed", "ceiling") and "clock" in goals:
            return {**args, "axis": "clock"}
        other = [g for g in goals if g != "clock"]
        if other:
            return {**args, "axis": other[0]}
    if (_SPEED_QUESTION_RE.search(question or "") and axis in ("speed", "ceiling")):
        return {**args, "axis": "clock"}
    return args


def _with_card_types(budget, ctx):
    """Give gate check 9 the REAL type line of every card name this turn licensed, not only the
    ones `lookup_card` returned. Live 2026-10-01: "Sol Ring is a non-basic land" passed because
    the turn licensed Sol Ring through `check_legality`, whose result carries no type line --
    so the check had nothing to compare against. The card DB is the authority either way; a
    name it cannot resolve is simply left out (the check then stays silent, never guesses)."""
    known = dict(budget.card_types)
    for name in budget.card_names:
        if name in known:
            continue
        card = ctx.card_db.get(name)
        type_line = getattr(card, "type_line", None) if card is not None else None
        if isinstance(type_line, str) and type_line:
            known[name] = type_line
    if len(known) == len(budget.card_types):
        return budget
    return dataclasses.replace(budget, card_types=tuple(known.items()))


_PRELOOKUP_MAX = 3


def _question_card_names(question: str, known_names) -> list[str]:
    """Real card names the player wrote, case-sensitively (a capitalised name, not the common
    word -- "Exile", "Ramp"), longest first with nested names masked, at most `_PRELOOKUP_MAX`."""
    if not question:
        return []
    found: list[str] = []
    masked = question
    candidates = [n for n in known_names if len(n) >= 4 and n in question
                  and n.lower() not in gate_mod._COMMON_WORD_CARD_NAMES]
    for name in sorted(candidates, key=len, reverse=True):
        # (?!'(?!s\b)) lets a possessive through ("Craterhoof Behemoth's trigger").
        m = re.search(rf"(?<![\w']){re.escape(name)}(?!\w)(?!'(?!s\b))", masked)
        if not m:
            continue
        # A real name EMBEDDED in a longer capitalised name is not the player's card: "Quantum
        # Flux Behemoth" (a trap, no such card) contains the real card "Flux", and looking Flux
        # up made the mentor describe Flux instead of saying the card does not exist (live
        # 2026-10-01). Skip when a capitalised word touches the match on either side.
        before, after = masked[:m.start()], masked[m.end():]
        if re.search(r"\b[A-Z][\w'-]*\s+$", before) or re.match(r"\s+[A-Z][\w'-]*\b", after):
            if not re.search(r"(?:^|[.!?]\s+)[A-Z][\w'-]*\s+$", before):
                continue
        found.append(name)
        masked = masked[:m.start()] + " " * len(name) + masked[m.end():]
        if len(found) == _PRELOOKUP_MAX:
            break
    return found


def _prelookup_question_cards(ctx, question, known_names, tool_trace, all_results, messages):
    names = _question_card_names(question, known_names)
    if not names:
        return
    calls = [{"id": f"auto-q-lookup-{i}", "type": "function",
              "function": {"name": "lookup_card", "arguments": json.dumps({"name": n})}}
             for i, n in enumerate(names)]
    messages.append({"role": "assistant", "content": "", "tool_calls": calls})
    for call, name in zip(calls, names):
        result = call_tool(ctx, "lookup_card", {"name": name})
        all_results.append(result)
        tool_trace.append(ToolCallRecord(name="lookup_card", args={"name": name},
                                         result_data=result.data))
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps(result.data, ensure_ascii=False, default=str)})


_MISTYPED_RE = re.compile(r"calls '([^']+)' an? \w+, but its type line this turn is")


def _lookup_mistyped_cards(ctx, reasons, tool_trace, all_results, messages) -> list[str]:
    """Run lookup_card for each card a check-9 reason names that was not already looked up
    this turn; append the synthetic call + result to `messages`, `tool_trace` and `all_results`
    (the same shape the tool loop writes). Returns the names looked up."""
    already = {str(t.args.get("name", "")).lower() for t in tool_trace if t.name == "lookup_card"}
    names: list[str] = []
    for reason in reasons:
        m = _MISTYPED_RE.search(reason)
        if m and m.group(1).lower() not in already and m.group(1) not in names:
            names.append(m.group(1))
    if not names:
        return []
    calls = [{"id": f"auto-lookup-{i}", "type": "function",
              "function": {"name": "lookup_card", "arguments": json.dumps({"name": n})}}
             for i, n in enumerate(names)]
    messages.append({"role": "assistant", "content": "", "tool_calls": calls})
    for call, name in zip(calls, names):
        result = call_tool(ctx, "lookup_card", {"name": name})
        all_results.append(result)
        tool_trace.append(ToolCallRecord(name="lookup_card", args={"name": name},
                                         result_data=result.data))
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps(result.data, ensure_ascii=False, default=str)})
    return names


def _limits(tool_trace: list, max_tokens: int) -> tuple[int, int]:
    """(max_tokens, max_chars) for this turn: widened once get_power_profile has run."""
    if any(t.name == "get_power_profile" for t in tool_trace):
        return max(max_tokens, PROFILE_MAX_TOKENS), gate_mod.MAX_CHARS_PROFILE
    return max_tokens, gate_mod.MAX_CHARS


_HISTORY_ROLES = {"user", "assistant"}


def _sanitize_history(history: list[dict] | None) -> list[dict]:
    """Only `user`/`assistant` turns with plain string content are trusted into the
    outgoing message list. `history` is client-supplied (it round-trips through the
    Forge UI and the engine's `/mentor/chat` request body), and this endpoint is
    stateless per request -- nothing here re-derives the real conversation, so a
    `role: "system"` entry could override `SYSTEM_PROMPT` and a `role: "tool"` entry
    could forge a fake prior tool result the gate would then treat as genuinely verified.
    Silently dropped rather than rejected with an error: an old/malformed history entry
    (a client bug, not necessarily an attack) shouldn't break the whole turn when simply
    ignoring it is safe."""
    safe: list[dict] = []
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        role, content = turn.get("role"), turn.get("content")
        if role in _HISTORY_ROLES and isinstance(content, str):
            safe.append({"role": role, "content": content})
    return safe


def ask(
    ctx: MentorContext,
    question: str,
    history: list[dict] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> MentorReply:
    """Run the tool loop for one question, then gate the draft before returning it.

    `history` is prior turns as OpenAI-shaped messages (user/assistant only -- no tool
    calls carried across questions, so each question re-verifies rather than trusting a
    stale tool result from three questions ago). Sanitized via `_sanitize_history` before
    use -- a `system`/`tool`-role entry is dropped rather than trusted, since this route
    is stateless and has no other way to tell a genuine prior turn from an injected one.
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_sanitize_history(history))
    messages.append({"role": "user", "content": question})

    tool_trace: list[ToolCallRecord] = []
    all_results: list[ToolResult] = []
    known_names = ctx.all_card_names
    # A card the PLAYER names is the subject of the question, so its real text is always looked
    # up before the model writes a word -- live 2026-10-01 a false premise ("Since Sol Ring only
    # costs 2 mana...") went uncorrected because the model never looked Sol Ring up and so had
    # no mana cost to correct it with. Offline and cheap (a card-DB read per name).
    _prelookup_question_cards(ctx, question, known_names, tool_trace, all_results, messages)

    nudged = False
    swap_nudged = False
    dual_nudged = False
    fallback_forced = False
    for _ in range(MAX_TOOL_TURNS):
        msg = _post_chat(messages, model=model, temperature=temperature,
                         max_tokens=_limits(tool_trace, max_tokens)[0])
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            draft = _strip(msg.get("content") or "")
            owed = [] if fallback_forced else _owed_fallback_axes(question, tool_trace)
            if owed:
                # D2 residual (found 2026-10-01 running the bench against main): with no cached full
                # search qwen3:14b stops at "run Advise" after get_measured_swaps says available
                # false, and ignores the nudge too (resilience 1/9). The quick search is owed, so run
                # it ourselves, once per axis, exactly as if the model had called it.
                fallback_forced = True
                msg = {"role": "assistant", "content": "", "tool_calls": [
                    {"id": f"auto-{ax}", "type": "function", "function": {"name": "suggest_swap",
                                                        "arguments": json.dumps({"axis": ax})}}
                    for ax in owed]}
                tool_calls = msg["tool_calls"]
            else:
                if not nudged and _announces_a_lookup(draft):
                    # The model SAID it would look something up and ended its turn instead of
                    # calling the tool (live, qwen3:14b: "I'll look into your collection to
                    # find a card..." with no suggest_swap call, so the answer never contained
                    # the measurement it promised). One nudge per turn, then whatever it says
                    # goes to the gate as usual.
                    nudged = True
                    messages.append({"role": "assistant", "content": draft})
                    messages.append({"role": "user", "content": _LOOKUP_NUDGE})
                    continue
                if (not swap_nudged and _wants_a_swap(question)
                        and not _has_swap_answer(tool_trace)):
                    swap_nudged = True
                    messages.append({"role": "assistant", "content": draft})
                    messages.append({"role": "user", "content": _SWAP_NUDGE})
                    continue
                if not dual_nudged:
                    missing = _missing_goal_axes(question, tool_trace)
                    if missing:
                        dual_nudged = True
                        messages.append({"role": "assistant", "content": draft})
                        messages.append({"role": "user", "content": _dual_goal_nudge(missing)})
                        continue
                break
        messages.append(msg)
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if fn_name in ("suggest_swap", "get_measured_swaps"):
                args = _route_swap_axis(question, args)
            if fn_name == "suggest_swap":
                # D2: a cached FULL search beats the quick in-chat one, and qwen3:14b keeps
                # reaching for suggest_swap regardless of the prompt -- so look first,
                # deterministically. Available: that result IS the answer (no 4-simulation
                # search). Unavailable: the trace still records it (the UI offers "Run full
                # swap search" from it) and the quick search runs, flagged as shallow.
                measured = _measured_first(ctx, args, tool_trace)
                if measured is not None and measured.data.get("available"):
                    all_results.append(measured)
                    tool_trace.append(ToolCallRecord(
                        name="get_measured_swaps", args={"axis": measured.data.get("axis")},
                        result_data=measured.data))
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", fn_name),
                        "content": json.dumps(measured.data, ensure_ascii=False, default=str),
                    })
                    continue
                if measured is not None:
                    tool_trace.append(ToolCallRecord(
                        name="get_measured_swaps", args={"axis": measured.data.get("axis")},
                        result_data=measured.data))
            result = call_tool(ctx, fn_name, args)
            if fn_name == "suggest_swap" and result.data.get("found"):
                result = ToolResult(
                    data={**result.data, "search_depth": _SHALLOW_NOTE},
                    card_names=result.card_names, rule_numbers=result.rule_numbers)
            all_results.append(result)
            tool_trace.append(ToolCallRecord(name=fn_name, args=args, result_data=result.data))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", fn_name),
                "content": json.dumps(result.data, ensure_ascii=False, default=str),
            })
    else:
        # Hit MAX_TOOL_TURNS without a final answer -- the muse-glimmer failure shape.
        # Stop calling tools and force a direct answer from what's already been gathered.
        messages.append({
            "role": "user",
            "content": "Stop calling tools now and answer directly from what you already "
                       "have, or say you don't have enough to answer precisely.",
        })
        msg = _post_chat(messages, model=model, temperature=temperature,
                         max_tokens=_limits(tool_trace, max_tokens)[0])
        draft = _strip(msg.get("content") or "")

    tokens, chars = _limits(tool_trace, max_tokens)
    budget = gate_mod.ClaimBudget.from_tool_results(all_results, known_names)
    budget = _with_card_types(budget, ctx)
    gate_rejections: list[tuple[str, list[str]]] = []

    for attempt in range(MAX_GATE_ATTEMPTS):
        draft = _complete_dual(question, tool_trace, draft)
        reasons = gate_mod.check(draft, budget, question=question, max_chars=chars)
        if not reasons:
            return MentorReply(text=draft, gated=True, tool_trace=tool_trace,
                               gate_rejections=gate_rejections)
        gate_rejections.append((draft, reasons))
        if attempt == MAX_GATE_ATTEMPTS - 1:
            break
        # Check 9 (a licensed card given the wrong TYPE): the model usually never looked the card
        # up -- live 2026-10-01 it licensed Sol Ring via check_legality, wrote "Sol Ring is a
        # non-basic land", and ignored the rejection's own correction on every retry. Hand it
        # the real card text by running lookup_card ourselves, exactly as if it had called it.
        looked_up = _lookup_mistyped_cards(ctx, reasons, tool_trace, all_results, messages)
        if looked_up:
            budget = _with_card_types(
                gate_mod.ClaimBudget.from_tool_results(all_results, known_names), ctx)
        retry_messages = messages + [
            {"role": "assistant", "content": draft},
            {"role": "user", "content": (
                "That answer is not acceptable: " + "; ".join(reasons) + ". "
                + (f"The lookup_card result for {', '.join(looked_up)} is above: use its type "
                   "line and mana cost exactly, and if the question assumed something those "
                   "contradict, correct that assumption first. " if looked_up else "")
                + "Rewrite it using ONLY facts from the tool results above. If you cannot "
                "answer precisely with what you have, say so honestly instead of guessing."
            )},
        ]
        msg = _post_chat(retry_messages, model=model, temperature=temperature + 0.1,
                          max_tokens=tokens)
        draft = _strip(msg.get("content") or "")

    fallback = (
        "I looked into that, but I couldn't put together an answer I'm confident is "
        "fully accurate -- I don't want to guess on this one. Try asking a narrower "
        "version of the question, or ask me to look up a specific card or rule directly."
    )
    return MentorReply(text=fallback, gated=False, tool_trace=tool_trace,
                       gate_rejections=gate_rejections)
