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
from dataclasses import dataclass, field

import requests

from mythgauntlet.mentor import gate as gate_mod
from mythgauntlet.mentor.tools import MentorContext, ToolResult, TOOL_SCHEMAS, call_tool

LLM_BASE = os.getenv("MYTHGAUNTLET_LLM_BASE", "http://127.0.0.1:8010").rstrip("/")
DEFAULT_MODEL = "qwen3:14b"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 700

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
question OR any question about who the commander(s) are or the deck's colour identity, \
lookup_card before describing any specific card, search_rules or get_rule \
before citing any rule, assess_card before saying whether a specific card would be \
good to add, and check_legality before saying whether a card CAN be added at all.

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
    label -- same tidy-up `swap_narrative._strip` does for the narrower case."""
    body = _THINK_TAG_RE.sub("", text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    body = re.sub(r"^\s*(answer|reply|response)\s*[:\-]\s*", "", body, flags=re.I)
    return " ".join(body.split()).strip()


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

    for _ in range(MAX_TOOL_TURNS):
        msg = _post_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            draft = _strip(msg.get("content") or "")
            break
        messages.append(msg)
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = call_tool(ctx, fn_name, args)
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
        msg = _post_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        draft = _strip(msg.get("content") or "")

    budget = gate_mod.ClaimBudget.from_tool_results(all_results, known_names)
    gate_rejections: list[tuple[str, list[str]]] = []

    for attempt in range(MAX_GATE_ATTEMPTS):
        reasons = gate_mod.check(draft, budget, question=question)
        if not reasons:
            return MentorReply(text=draft, gated=True, tool_trace=tool_trace,
                               gate_rejections=gate_rejections)
        gate_rejections.append((draft, reasons))
        if attempt == MAX_GATE_ATTEMPTS - 1:
            break
        retry_messages = messages + [
            {"role": "assistant", "content": draft},
            {"role": "user", "content": (
                "That answer is not acceptable: " + "; ".join(reasons) + ". "
                "Rewrite it using ONLY facts from the tool results above. If you cannot "
                "answer precisely with what you have, say so honestly instead of guessing."
            )},
        ]
        msg = _post_chat(retry_messages, model=model, temperature=temperature + 0.1,
                          max_tokens=max_tokens)
        draft = _strip(msg.get("content") or "")

    fallback = (
        "I looked into that, but I couldn't put together an answer I'm confident is "
        "fully accurate -- I don't want to guess on this one. Try asking a narrower "
        "version of the question, or ask me to look up a specific card or rule directly."
    )
    return MentorReply(text=fallback, gated=False, tool_trace=tool_trace,
                       gate_rejections=gate_rejections)
