"""LLM-assisted CCM compilation (docs/CARD_SEMANTICS.md).

Oracle text -> few-shot prompt -> local llama-swap gateway -> JSON CCM -> validation
gates -> accepted store or quarantine. The LLM runs at COMPILE time only — simulation
never calls it (invariant: determinism). One retry with gate-error feedback, then
quarantine; quarantined cards stay at rung 1 and form the hand-authoring worklist.

Artifacts (committed):
  ccm/authored/*.json    hand-written rung-3 exemplars ({"card": {...}, "ccm": {...}})
  ccm/compiled/*.json    gate-passing rung-2 output, same envelope
  ccm/ledger.json        per-card status: accepted | quarantined (+ errors, model, date)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import json_repair
import requests

from mythgauntlet.config import PROJECT_ROOT, USER_AGENT
from mythgauntlet.model.card import Card, normalize_name
from mythgauntlet.semantics import ccm
from mythgauntlet.semantics.ccm_grammar import CCM_GRAMMAR

# v9 targets the three schema classes that account for 939 of the 2,276 quarantine
# first-errors (41%): the closed activated-cost key set (428), empty effects lists on
# non-static abilities (281), and riders smuggled into mana abilities (230). All three
# were SHAPE errors the v8 prompt never stated outright — it showed the activated cost
# by example without saying the key set was closed, and never mentioned "other" at all,
# so the model invented keys like "discard". Bumping the version also re-arms the
# quarantine retry gate in compile-top for all 2,276 entries.
# v11 targets the failure shapes measured across the 1,114 cards still stuck on v10
# after 6-7 refresh nights (each blocked entry's ledger `refresh_errors` gives the
# actual gate that rejected its last retry — read, not guessed): 156 of the 330
# recorded reasons (47%) were still trigger-event cross_check failures, dominated by
# ONE unstated confusion — "{T}: <effect>" (a plain tap-COST activated ability) being
# read as a tap_for_mana TRIGGER (Glasses of Urza, Cinder Pyromancer, Burning Anger,
# Gideon's Avenger's "becomes tapped" reading the same way). Also: Target.controller
# is a closed 4-value enum but got invented free text ("target_player", "defending",
# "owner", 15 cards); "dies" got read as leaves_battlefield instead of death (Ashcloud
# Phoenix); Ward's reminder text got promoted into a phantom becomes_target ability
# (Archive Dragon); Cycling — a real activated ability printed ON an instant/sorcery —
# was rejected by v10's absolute "instant/sorcery is always spell_effect" rule
# (Rebuild, Lay Waste, Whiteout, 26 cards); and every sampled planeswalker (Jace
# Unraveler of Secrets, Liliana Death Wielder, Nicol Bolas, Jaya Ballard) failed
# "needs a non-empty effects list" because v10 gave no guidance at all for
# representing a +N/-N loyalty cost. All six are addressed above with an explicit
# rule plus a worked example, not just a restated generality.
PROMPT_VERSION = 11  # v11: tap-cost vs tap_for_mana, controller enum, death vs leaves_battlefield, keyword reminder text, cycling-on-spells, planeswalker loyalty costs
DEFAULT_LLM_URL = os.environ.get("MYTHGAUNTLET_LLM_URL", "http://127.0.0.1:8010")
DEFAULT_LLM_MODEL = os.environ.get("MYTHGAUNTLET_LLM_MODEL", "qwen3:14b")

SYSTEM_PROMPT = """You are a compiler that converts Magic: The Gathering Oracle text into a JSON Card Capability Model (CCM). Output ONLY one JSON object. No prose, no markdown fences.

CCM shape:
{"name": str, "ccm_version": 1, "cost": {"mana": "{2}{G}"}, "types": ["sorcery"], "abilities": [Ability, ...]}
Add "enters_tapped": true only for a permanent that enters the battlefield tapped.

Ability kinds:
- {"kind":"spell_effect","effects":[...]} — what an instant/sorcery does when it resolves
- {"kind":"mana_ability","cost":{"tap":true},"effects":[{"op":"add_mana",...}]} — effects may contain add_mana and NOTHING else
- {"kind":"activated","cost":{"mana":"{2}","tap":true,"sacrifice_self":false,"pay_life":0},"effects":[...]} — include only the cost keys the card actually uses
- {"kind":"triggered","trigger":{"event":E},"effects":[...]} where E is one of: etb, death, creature_dies, upkeep, draw_step, end_step, end_of_combat, attack, blocks, becomes_blocked, self_cast, cast_creature, cast_spell, opponent_casts_spell, landfall, combat_damage_to_player, dealt_damage, saga_chapter, leaves_battlefield, becomes_target, tap_for_mana, gain_life, lose_life, counter_added, activate_ability, other
- {"kind":"static","note":"<short description>"} — continuous effects that fit no op

Effect ops (params; amounts may be "X" — when a numeric param is "X", also put "x_basis" on that effect saying what X counts: one of mana_paid (X in the mana cost), chosen, creatures_you_control, lands_you_control, artifacts_you_control, permanents_you_control, cards_in_hand, life_paid, counters_on_this, target_power, other):
add_mana(amount, colors: concatenated letters like "G", "C", "GU" — for "one mana of any color" use "any"; never write "G or U") ; draw(count) ; discard(count, who) ; mill(count, who) ; scry(count) ; surveil(count) ; search_library(what: Target, count, to: "battlefield"|"hand"|"graveyard", tapped, shuffle) ; shuffle() ; destroy(target) ; exile(target) ; return_to_hand(target) ; gain_control(target) ; attach(target) — for Equip/attach abilities ; counter_spell(unless_pays) ; deal_damage(amount, target) ; gain_life(amount, who) ; lose_life(amount, who) ; create_token(count, power, toughness, types) ; pump(power, toughness, target, duration) ; add_counter(count, counter_type, target) — for +1/+1 and other counters ; tap(target) ; untap(target) ; sacrifice(target, who) ; reanimate(target) ; extra_turn() ; cost_reduction(amount, applies_to) ; win_game(condition)
Target: {"type": "creature"|"permanent"|"land"|"artifact"|"card"|"player"|"any"|..., "subtype": opt, "controller": "you"|"opponent"|"any"|"each", "count": int|"all", "zone": opt}
"controller" is a CLOSED enum of exactly those four words — NEVER invent a value like "target_player", "attacking_player", "defending", or "owner". This applies to type:"player" targets too: "target player" is {"type":"player","controller":"any"}; "target opponent" is {"type":"player","controller":"opponent"}; "each opponent" is {"type":"player","controller":"opponent","count":"all"}.
Any effect may carry "optional": true (player may decline) and "condition": "<short text>" (restrictions the ops cannot express).

Rules:
- cost.mana must EXACTLY equal the printed mana cost. types must be words from the type line, lowercase.
- An activated/mana ability's "cost" object may use ONLY these five keys: "mana" (string), "tap" (bool), "sacrifice_self" (bool), "pay_life" (int), "other" (string). This list is CLOSED. Any other cost component — discarding, exiling, removing a counter, sacrificing another permanent, revealing, tapping other creatures, a PLANESWALKER LOYALTY COST — goes in "other" as plain text, e.g. {"mana":"{1}","other":"discard a card"} or {"other":"+1 loyalty"} / {"other":"-2 loyalty"} / {"other":"0 loyalty"}. NEVER invent a cost key like "discard" or "sacrifice" or "exile" or "loyalty".
- A planeswalker's "+N:"/"-N:"/"0:" line is an "activated" ability (cost per the loyalty rule above). If its effect is a big multi-clause payoff that doesn't fit the ops below (an emblem, a multi-step chain like "deals 7 damage... discards seven... sacrifices seven permanents"), use {"kind":"static","note":"<what it does>"} for that ability rather than leaving effects empty — see the next rule.
- Every ability EXCEPT "static" must have a non-empty "effects" list. If the ability's effect cannot be expressed with the ops below, do not emit an empty list and do not omit the key — emit {"kind":"static","note":"<what it does>"} instead. A cost with nothing to pay for is never valid.
- A "mana_ability" contains ONLY add_mana effects. If the card also does something else when that ability is used (scry, damage, a counter, a drawback), put THAT in a separate "triggered" or "static" ability — never inside the mana ability's effects.
- Model ONLY what the text says. If a clause cannot be expressed with these ops, represent it as {"kind":"static","note":...} rather than inventing ops or forcing a bad fit.
- "static" is an ability KIND, never an effect op. Every effect's "op" must come from the op list above. Any effect may carry a "note" string for details the params cannot express.
- An instant or sorcery's RESOLUTION effect (what the card does when it resolves off the stack) must be spell_effect — never mana_ability, activated, or triggered. But the same card CAN separately carry a genuine activated or triggered ability alongside that: Cycling, Flashback-with-a-rider, or a graveyard-recursion clause ("Sacrifice a snow land: return this card from your graveyard to your hand") are real abilities usable outside resolution — model those as their own "activated" (Cycling: cost {"mana":"{2}","other":"discard this card"}, effects [draw(1)]) or "triggered" (a "When you cycle this card, ..." rider) entry. Only the spell's OWN resolution must be spell_effect; do not force Cycling into it.
- "{T}: <effect>" (or any cost paid to use an ability) is an ACTIVATED ability whose cost includes "tap": true — it is NEVER a "triggered" ability with event tap_for_mana. tap_for_mana is reserved for the rare genuine trigger "Whenever this/a permanent is tapped for mana" — a card simply having a tap-cost ability, even one that adds mana, does not trigger anything by itself (that ability IS the mana_ability or activated ability; there is no separate trigger to record).
- THE TRIGGER EVENT MUST MATCH THE TEXT EXACTLY. A trigger on the wrong event is a different card, not a close-enough one. If no event in the list fits, use "other" — that is always correct and always better than a near miss. Specifically:
  * "is dealt damage" / "is dealt noncombat damage" is dealt_damage. It is NOT combat_damage_to_player — noncombat damage is the opposite of combat damage.
  * "deals combat damage to a player" (or planeswalker) is combat_damage_to_player. "deals combat damage" with NO "to a player" (e.g. combat damage to a blocking creature, or the target unspecified) is NOT combat_damage_to_player — use other.
  * "Whenever this creature deals damage" (this permanent's own damage OUTPUT, combat or not) has no matching event — it is the opposite of dealt_damage (which is damage received). Use other. dealt_damage is ONLY for "is dealt damage" / "deals damage to it/this".
  * "When you cast this spell" is self_cast — it happens ONCE. "Whenever you cast a creature spell" is cast_creature and happens every time. Never use cast_creature for a card's own cast.
  * "blocks" is blocks and "becomes blocked" is becomes_blocked. Neither is attack — blocking is the opposite side of combat from attacking.
  * landfall is a land ENTERING the battlefield. A land being destroyed, sacrificed, or put into a graveyard is not landfall; a land being tapped for mana is tap_for_mana (the genuine trigger, not an ordinary tap-cost ability — see above).
  * A Saga's chapter abilities (I, II, III) are saga_chapter, never upkeep or draw_step.
  * "Whenever another creature dies" is creature_dies. "When this creature dies" is death — and so is the spelled-out version some cards use instead of the keyword, "is put into a graveyard from the battlefield" (that IS the rules definition of dying, CR 700.4). Dying (going to the graveyard FROM the battlefield, however worded) is NEVER leaves_battlefield — leaves_battlefield is for other zone changes (exile, bounce, put on top/bottom of library) that are not specifically dying. This holds even when the EFFECT also returns the card to the battlefield (a phoenix-style "When this creature dies, return it to the battlefield" ability): the trigger is still death (the cause), not leaves_battlefield (a description of the result) — and the effect for "return it to the battlefield" is reanimate, never return_to_hand.
  * "becomes tapped" (generic — NOT "is tapped for mana") has no matching event; use other. A creature "becomes the target" is becomes_target ONLY when that is real card text, never when it is reminder text for a keyword (see the next rule).
- Parenthetical REMINDER TEXT that explains a keyword (Ward, Flying, Trample, Deathtouch, Flash, Hexproof, Menace, ...) is not separate card text — do not turn it into its own ability. "Ward {2} (Whenever this creature becomes the target of a spell or ability an opponent controls, counter it unless that player pays {2}.)" is ONE keyword; represent it as {"kind":"static","note":"Ward {2}"} (or fold into an existing static note), never as a second "becomes_target" triggered ability duplicating the reminder text.
- A card with no triggered ability must not have one. Prevention effects, activated abilities, and static keywords are not triggers — do not invent an "etb" for a card that never mentions entering. Example: "{T}: Draw a card, then discard a card." is ONLY an activated ability — it has no ETB, no trigger of any kind, even though drawing/discarding sounds like it could be one.
- search_library's "count" is REQUIRED even when the text says "a card" (count:1) or "up to N cards" (count:N, and mark the effect "optional":true) — never omit it.
- Output must be strictly valid JSON: double-quoted keys, no trailing commas, no | alternatives inside values.
/no_think"""


def store_dir() -> Path:
    """Directory holding the COMPILED store (`compiled/` + `ledger.json`).

    Override: ``MYTHGAUNTLET_STORE``. This exists because the engine ships open while the
    compiled semantics do not (see docs/ENGINE_DATA.md) — the store is ~30k documents
    produced by many hundreds of GPU-hours and is versioned in a separate private repo.
    Pointing this at that repo lets the engine READ and the compiler WRITE the canonical
    copy in place, instead of keeping a duplicate 130 MB tree beside the source.

    Unset, it falls back to this repo's own `ccm/` — so a fresh clone works with whatever
    the user has compiled themselves, and an empty store degrades to rung-1 heuristics
    rather than failing.
    """
    override = os.environ.get("MYTHGAUNTLET_STORE")
    return Path(override) if override else PROJECT_ROOT / "ccm"


def authored_dir() -> Path:
    """Hand-written rung-3 exemplars. NOT store_dir() — these are prompt source, they ship
    with the engine, and they must stay findable even when the compiled store is elsewhere."""
    return PROJECT_ROOT / "ccm" / "authored"


def compiled_dir() -> Path:
    """Path to the compiled-CCM store. Pure getter — does NOT create the dir, so building
    a SemanticsStore to READ semantics never fails on a read-only checkout."""
    return store_dir() / "compiled"


def ledger_path() -> Path:
    return store_dir() / "ledger.json"


def card_block(card: Card) -> str:
    lines = [f"NAME: {card.name}", f"COST: {card.mana_cost_str or '(none)'}"]
    lines.append(f"TYPE: {card.type_line}")
    if card.power is not None or card.toughness is not None:
        lines.append(f"P/T: {card.power}/{card.toughness}")
    lines.append(f"ORACLE: {card.oracle_text or '(vanilla, no text)'}")
    return "\n".join(lines)


def read_envelope(path: Path) -> dict:
    """Read a {card, ccm} envelope, failing with the offending file named.

    CCM artifacts are committed JSON that humans hand-author and hand-edit; a raw
    KeyError/JSONDecodeError without the path is undebuggable.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            envelope = json.load(fh)
        if not isinstance(envelope.get("card"), dict) or "name" not in envelope["card"]:
            raise ValueError("missing card.name")
        if not isinstance(envelope.get("ccm"), dict):
            raise ValueError("missing ccm object")
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"malformed CCM envelope {path}: {exc}") from exc
    return envelope


def authored_names() -> set[str]:
    """Normalized names of hand-authored (rung 3) cards — compile-top skips these."""
    names = set()
    for path in authored_dir().glob("*.json"):
        names.add(normalize_name(read_envelope(path)["card"]["name"]))
    return names


def load_exemplars() -> list[tuple[str, str]]:
    """(card_block, ccm_json) pairs from ccm/authored/, in filename order."""
    pairs: list[tuple[str, str]] = []
    for path in sorted(authored_dir().glob("*.json")):
        doc = read_envelope(path)
        c = doc["card"]
        card = Card(
            name=c["name"],
            mana_cost_str=c.get("mana_cost", ""),
            type_line=c.get("type_line", ""),
            oracle_text=c.get("oracle_text", ""),
            power=c.get("power"),
            toughness=c.get("toughness"),
        )
        pairs.append((card_block(card), json.dumps(doc["ccm"], ensure_ascii=False)))
    return pairs


def build_messages(
    card: Card, exemplars: list[tuple[str, str]], feedback: str | None = None
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for block, ccm_json in exemplars:
        messages.append({"role": "user", "content": block})
        messages.append({"role": "assistant", "content": ccm_json})
    target = card_block(card)
    if feedback:
        target += (
            "\n\nYour previous attempt failed validation with these errors — "
            f"fix them:\n{feedback}"
        )
    messages.append({"role": "user", "content": target})
    return messages


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _repair_json(snippet: str) -> str:
    """Best-effort fixes for the LLM's common JSON slips (safe, reversible transforms)."""
    # drop trailing commas before a closing } or ] (the #1 parse failure)
    repaired = re.sub(r",(\s*[}\]])", r"\1", snippet)
    # normalize Python-ish literals that occasionally leak through
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    return repaired


def _deep_repair(snippet: str) -> dict:
    """Last-resort structural repair (missing commas/quotes) via json-repair (v8).

    ~276 quarantines were pure parse failures the regex fixes can't touch. This is safe
    because repair NEVER auto-accepts a card: the repaired document still faces all three
    validation gates, and provenance records that repair happened (`json_repaired`) so
    audits can stratify repaired vs clean acceptances.
    """
    doc = json_repair.loads(snippet)
    if not isinstance(doc, dict) or not doc:
        raise ValueError("JSON repair did not yield an object")
    doc["_json_repaired"] = True  # popped by compile_card into provenance
    return doc


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response (tolerates fences/think tags).

    Escalating parse: strict -> cheap regex repairs (trailing commas, Python literals) ->
    deep structural repair (marks the doc, see _deep_repair).
    """
    cleaned = _THINK_RE.sub("", text)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object in response")
    snippet = cleaned[start:]
    try:
        doc, _ = json.JSONDecoder().raw_decode(snippet)
    except json.JSONDecodeError:
        try:
            doc, _ = json.JSONDecoder().raw_decode(_repair_json(snippet))
        except json.JSONDecodeError:
            doc = _deep_repair(snippet)
    if not isinstance(doc, dict):
        raise ValueError("response JSON is not an object")
    return doc


class LlamaSwapClient:
    """OpenAI-compatible chat client for the local llama-swap gateway."""

    def __init__(
        self,
        base_url: str = DEFAULT_LLM_URL,
        model: str = DEFAULT_LLM_MODEL,
        timeout: int = 300,
        grammar: str | None = CCM_GRAMMAR,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # llama-server constrains sampling to this GBNF, so a token that would break
        # gate 1 is never emitted (see ccm_grammar). Pass grammar=None to sample freely —
        # that is how the A/B in docs/engine/CARD_SEMANTICS.md was measured, and the
        # escape hatch if a future backend does not implement the field.
        self.grammar = grammar

    def available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=5)
            return resp.ok
        except requests.RequestException:
            return False

    def complete(self, messages: list[dict]) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1600,
        }
        if self.grammar:
            # `grammar` is a llama.cpp extension to the OpenAI schema; llama-server reads
            # it off /v1/chat/completions and ignores unknown fields, so this stays a
            # no-op against any other OpenAI-compatible backend rather than erroring.
            payload["grammar"] = self.grammar
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers={"User-Agent": USER_AGENT},
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


@dataclass
class CompileResult:
    name: str
    status: str  # accepted | quarantined | error
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    ops: list[str] = field(default_factory=list)
    doc: dict | None = None


def _ops_used(doc: dict) -> list[str]:
    ops = set()
    for ability in doc.get("abilities") or []:
        for effect in ability.get("effects") or []:
            if isinstance(effect, dict) and "op" in effect:
                ops.add(effect["op"])
    return sorted(ops)


def compile_card(
    card: Card,
    complete,
    exemplars: list[tuple[str, str]],
    max_attempts: int = 2,
) -> CompileResult:
    """Compile one card. `complete` is messages -> response text (injectable for tests)."""
    feedback: str | None = None
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            raw = complete(build_messages(card, exemplars, feedback))
            doc = extract_json(raw)
        except (ValueError, KeyError, requests.RequestException) as exc:
            errors = [f"response error: {exc}"]
            feedback = errors[0]
            continue
        was_repaired = bool(doc.pop("_json_repaired", False))
        gates = ccm.validate(doc, card)
        errors = [f"[{gate}] {msg}" for gate, msgs in gates.items() for msg in msgs]
        if not errors:
            # The COMPILER owns the tier, not the model. setdefault let the LLM keep a
            # self-declared "rung": 3 — the tier reserved for hand-authored exemplars —
            # and 1,897 compiled cards had claimed it by 2026-07-31, churning in and out
            # on every prompt refresh. Rung 2 is what this path produces, always.
            doc["rung"] = 2
            unsupported = ccm.unsupported_ops(doc)
            if unsupported:
                doc["unsupported_ops"] = unsupported
            doc["provenance"] = {
                "source": "llm_compiled",
                "prompt_version": PROMPT_VERSION,
                "date": date.today().isoformat(),
            }
            if was_repaired:
                doc["provenance"]["json_repaired"] = True
            return CompileResult(
                name=card.name, status="accepted", attempts=attempt,
                ops=_ops_used(doc), doc=doc,
            )
        feedback = "\n".join(errors[:12])
    return CompileResult(
        name=card.name, status="quarantined", attempts=max_attempts, errors=errors
    )


def stored_ccm_passes_gates(card: Card) -> bool:
    """Does the CCM already on disk still satisfy today's gates?

    The refresh path keeps a prior CCM when a recompile fails, so a good card can't be
    demoted by a bad roll. But that guard assumed the prior was CORRECT — when a gate is
    newly ADDED, the prior may be exactly what the gate now rejects, and keeping it means
    the engine goes on executing something the card cannot do. Prompt v10's trigger-event
    check found 1,400 such cards. So the keep is conditional: retain the prior only if it
    would pass today, otherwise let the failure stand and drop the card to rung-1
    heuristics, which under-count honestly instead of fabricating.
    """
    path = compiled_dir() / f"{_slug(card.name)}.json"
    if not path.exists():
        return False
    try:
        envelope = read_envelope(path)
    except ValueError:
        return False
    return not any(ccm.validate(envelope["ccm"], card).values())


class Ledger:
    """Per-card compilation record, committed at ccm/ledger.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ledger_path()
        self.entries: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                self.entries = json.load(fh).get("entries", {})

    def get(self, card_name: str) -> dict | None:
        return self.entries.get(normalize_name(card_name))

    def record(self, result: CompileResult, model: str) -> None:
        self.entries[normalize_name(result.name)] = {
            "name": result.name,
            "status": result.status,
            "attempts": result.attempts,
            "ops": result.ops,
            "errors": result.errors[:8],
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "date": date.today().isoformat(),
        }

    def save(self) -> None:
        """Write the ledger ATOMICALLY (temp file + replace), like save_compiled does.

        This is called after EVERY card, so a ~6 MB, 31k-entry file is rewritten roughly
        every three seconds for hours. Truncating the real file in place meant:

          * any concurrent reader — the strength API on :8020, `ccm-status`, a morning
            script — could read a half-written file and raise JSONDecodeError (observed
            2026-08-01 while the nightly was mid-chunk);
          * a crash or power cut during a write would destroy the whole ledger, which is
            the index over many hundreds of GPU-hours of compilation.

        Writing to a sibling temp and replacing makes the swap atomic on Windows and
        POSIX alike, so a reader sees either the old ledger or the new one, never a
        fragment.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.part")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"entries": self.entries}, fh, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.replace(self.path)

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for entry in self.entries.values():
            out[entry["status"]] = out.get(entry["status"], 0) + 1
        return out


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def save_compiled(card: Card, doc: dict) -> Path:
    out_dir = compiled_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "card": {
            "name": card.name,
            "mana_cost": card.mana_cost_str,
            "type_line": card.type_line,
            "oracle_text": card.oracle_text,
            "power": card.power,
            "toughness": card.toughness,
            "oracle_id": card.oracle_id,
        },
        "ccm": doc,
    }
    # _slug is lossy (drops punctuation), so two distinct names can collide on one file
    # while the store keys by normalize_name — the loser would silently drop to rung 1.
    # Reuse the same file for the same card; disambiguate a genuine cross-name collision.
    path = out_dir / f"{_slug(card.name)}.json"
    if path.exists():
        try:
            existing = normalize_name(read_envelope(path)["card"]["name"])
        except ValueError:
            existing = normalize_name(card.name)  # unreadable -> treat as ours, overwrite
        if existing != normalize_name(card.name):
            suffix = re.sub(r"[^a-z0-9]+", "", (card.oracle_id or card.name).casefold())[:8]
            path = out_dir / f"{_slug(card.name)}-{suffix}.json"
    tmp = path.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, ensure_ascii=False)
    tmp.replace(path)  # atomic
    return path
