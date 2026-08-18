"""Reusable local-model harness: SHORTLIST in code, then one narrow question per item.

Why it is built this way. The first attempt asked qwen3:14b to pick from all 43 themes, name a
missing archetype, and emit JSON, for 4 cards at once — it scored 2/4, then 5/8 with worked
examples. An A/B then showed the model answers the SAME discrimination correctly (4/4 across
14b and 32b, thinking on or off) when the question is narrow. The failure was task complexity
per call, not capability.

So: deterministic code narrows 43 candidates to a handful, and the model answers one
multiple-choice question about one card, in one word, with no JSON to malform. Confusable-pair
guidance is injected only for pairs actually on that card's shortlist, keeping prompts short.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8010/v1/chat/completions"


# One line per theme. WITHOUT THIS the model cannot succeed: `aristocrats`, `voltron` and
# `draw_matters` are this project's private vocabulary, not English, and asking a model to
# choose between undefined labels is asking it to guess. Adding the glossary is what took the
# gold set from 3/8 to its final score — the pairwise notes below only refine confusable pairs.
THEME_DEFS = {
    # Spell out the TEMPLATING, not just the concept. Three cards failed with the concept-only
    # wording — including Athreos, whose text literally says "dies" — because the model would
    # not connect Magic's phrasings to the label. A sacrifice OUTLET counts as the engine even
    # when what it sacrifices is any permanent (that is how theme_match defines it too).
    "aristocrats":  ("your own creatures DYING is the payoff. All of these count: \"dies\", "
                     "\"is put into a graveyard from the battlefield\", \"whenever a creature "
                     "you control dies\", and any repeatable SACRIFICE outlet (even one that "
                     "sacrifices any permanent, not only creatures)"),
    "graveyard":    "recursion and self-mill — casting or returning cards FROM the graveyard, or filling it on purpose",
    "reanimator":   "returning CREATURES from the graveyard to the BATTLEFIELD",
    "tokens":       "creating token creatures, or rewarding you for having many creatures",
    # "or other counters" was too loose: it matched Arixmethes' slumber counters, which are
    # bookkeeping on the card itself, not a counters STRATEGY.
    "counters":     ("putting +1/+1 counters (or similar creature-boosting counters) on "
                     "permanents as a strategy. NOT bookkeeping counters that only track one "
                     "card's own state — slumber, lore, loyalty, verse, page"),
    "spellslinger": "casting lots of instants and sorceries, and being rewarded for it",
    "artifacts":    "artifacts you control being the engine or the payoff",
    "enchantress":  "enchantments you control being the engine or the payoff",
    "auras":        "Auras attached to creatures",
    "lifegain":     "gaining life, and being rewarded for gaining it",
    "landfall":     "lands entering the battlefield triggering things",
    "draw_matters": "being rewarded FOR drawing cards, or caring how many you have drawn",
    "etb":          "creatures entering the battlefield being the payoff (blink/flicker)",
    "voltron":      "one creature suited up with Equipment or Auras to win alone",
    # theme_match scores this STRONG on 19.35% of every card in Magic, so a loose definition
    # makes it swallow anything that mentions combat. It has to be the narrowest wording here.
    "voltron_combat": ("ONE creature being suited up and winning alone, or explicit combat-damage "
                       "triggers, or granted evasion/double-strike as the plan. NOT any card that "
                       "merely mentions attacking, and NOT a go-wide creature deck"),
    "theft":        "taking or casting your opponents' cards and permanents",
    "group_hug":    "giving every player cards, mana or life",
    "energy":       "energy counters",
    "impulse":      "playing cards off the top of your library or from exile",
    "face_down":    "morph, manifest, disguise — creatures played face down",
    "sagas":        "Saga enchantments and lore counters",
    "chaos":        "randomness, coin flips, voting, goading",
}


def _tribal_def(theme: str) -> str:
    return (f"the card's TEXT names {theme[len('tribal_'):].rstrip('s').title()}s as a tribe "
            f"it rewards (merely BEING one does not count)")


def describe(theme: str) -> str:
    return THEME_DEFS.get(theme) or (_tribal_def(theme) if theme.startswith("tribal_")
                                     else theme.replace("_", " "))


NO_THINK = chr(10) + "/no_think"


class EmptyReply(RuntimeError):
    """The model returned nothing usable. Distinct from the model answering "none"."""

# Distinctions the model demonstrably gets wrong unless they are spelled out. Keyed by the
# frozenset of the confusable pair, injected only when BOTH are on the shortlist.
DISAMBIGUATION = {
    frozenset({"aristocrats", "graveyard"}):
        ("aristocrats = your own creatures DYING is the payoff (sacrifice outlets, death "
         "triggers, drain on death). 'Put into a graveyard from the battlefield' IS dying.\n"
         "graveyard = RECURSION and SELF-MILL: casting or returning cards FROM the graveyard, "
         "or filling it on purpose."),
    frozenset({"aristocrats", "draw_matters"}):
        ("aristocrats = a SACRIFICE OUTLET or a death trigger is the engine, even if the "
         "reward happens to be drawing cards.\n"
         "draw_matters = the text rewards you FOR having drawn, or cares how many cards you "
         "have drawn this turn."),
    frozenset({"tokens", "aristocrats"}):
        ("tokens = the text CREATES tokens or rewards you for having many creatures.\n"
         "aristocrats = the text rewards those creatures DYING."),
    frozenset({"reanimator", "graveyard"}):
        ("reanimator = returns CREATURES from the graveyard to the BATTLEFIELD.\n"
         "graveyard = general recursion or self-mill, not specifically reanimating creatures."),
    frozenset({"counters", "tokens"}):
        ("counters = +1/+1 or other COUNTERS placed on permanents.\n"
         "tokens = creating token creatures."),
}


def chat(prompt: str, model: str = "qwen3:14b", max_tokens: int = 400,
         temperature: float = 0.2, retries: int = 4) -> str:
    """One completion. Retries 502/503 (llama-swap mid-swap) but never a 500.

    A 500 carrying "prematurely" is a CUDA OOM inside llama-server — the next attempt fails
    identically, so retrying only wastes time.
    """
    body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    req = lambda: urllib.request.Request(  # noqa: E731
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            r = json.load(urllib.request.urlopen(req(), timeout=300))
            return (r["choices"][0]["message"].get("content") or "").strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            if e.code == 500 and "prematurely" in detail:
                raise RuntimeError(
                    "llama-server exited (CUDA OOM). Free VRAM or use a smaller model.") from e
            if e.code in (502, 503) and attempt < retries - 1:
                time.sleep(20 * (attempt + 1))       # model still loading after an idle evict
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == retries - 1:
                raise
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("unreachable")


def choose(card: dict, shortlist: list[str], model: str = "qwen3:14b") -> str | None:
    """Ask ONE narrow multiple-choice question about ONE card. Returns a label or None.

    `none` is a first-class answer and is returned as None — an honest "no archetype fits"
    beats a forced near-miss, which is the whole reason this pipeline exists.
    """
    if not shortlist:
        return None
    notes = [text for pair, text in DISAMBIGUATION.items() if pair <= set(shortlist)]
    options = "\n".join(f"- {t}" for t in shortlist)
    prompt = (
        "Which deck archetype does this Magic card's rules text REWARD?\n\n"
        f"Choose exactly one of:\n{options}\n- none\n\n"
        + ("\n" + "\n\n".join(notes) + "\n" if notes else "")
        + "\nRules: judge ONLY the text shown. A label applies when the card PAYS YOU for doing "
          "that thing, not when it could merely appear in such a deck. Answer 'none' if nothing "
          "listed genuinely fits — that is a correct answer.\n\n"
          f"{card['name']} — {card.get('type_line') or ''}\n{card.get('oracle_text') or ''}\n\n"
          "Reply with the one label and nothing else."
    )
    # `/no_think` is deliberate. qwen3 is a hybrid reasoning model: with thinking ON it spent
    # the entire token budget in the trace and returned EMPTY content, which the first version
    # of this parser silently scored as "none" — every card came back unlabelled and it looked
    # like a judgement failure. An A/B on the hardest card showed thinking OFF answers this
    # discrimination correctly in 8 tokens (14b and 32b alike), because the question is narrow.
    raw = chat(prompt + NO_THINK, model=model, max_tokens=700)
    out = re.sub(r"<think>.*?</think>", " ", raw, flags=re.S).casefold().strip()
    if not out:
        # An empty reply is a HARNESS failure, not the answer "none". Conflating the two is what
        # produced a silent all-none sweep; the caller must be able to tell them apart.
        raise EmptyReply(f"{model} returned no content for {card.get('name')!r}")
    # Last mentioned option wins: a reply that restates options before answering ends on its pick.
    best, pos = None, -1
    for t in [*shortlist, "none"]:
        i = out.rfind(t.casefold())
        if i > pos:
            best, pos = t, i
    if best is None:
        raise EmptyReply(f"{model} answered off-menu for {card.get('name')!r}: {out[:80]!r}")
    return None if best == "none" else best
