"""Strength engine routes: proxies to the MythGauntlet engine on :8020 (measure,
advise, card impact, mentor, breakdown, duel) and the helpers that feed it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import traceback
import uuid
from datetime import datetime as _dt
from typing import Optional

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

import edhrec_lift
from api import state
from api.cards import _safe_name
from api.state import (
    _CHAT_RATE_LIMIT_KEY,
    _RATE_LIMIT_CHAT_REQUESTS,
    _RATE_LIMIT_WINDOW,
    _check_rate_limit,
    _jobs,
    _load_deck_from_disk,
    _require_job_id,
    _scryfall,
    _serializable_job,
)
from collection import suite_collection_path

router = APIRouter()


# --- MythGauntlet strength API (Myth Suite contract C3) ---------------------------------
# Simulation-grounded deck strength: MythGauntlet plays thousands of games and returns a
# measured Power Profile. It is the SOLE bracket authority — Forge used to carry its own
# heuristic estimator (deck_analysis.py) as a fallback and the import preview rendered
# both, which let the copies drift: Forge's still applied the tutor restrictions the
# October 2025 bracket update removed. The duplicate is deleted; when :8020 is down the
# UI says so rather than substituting a second, worse opinion.
MYTHGAUNTLET_URL = os.getenv("MYTHGAUNTLET_URL", "http://127.0.0.1:8020").rstrip("/")


def _job_partners(job: dict) -> list[dict]:
    """The rest of the command zone for a stored job, in `_deck_to_lines`'s shape.

    `job["partners"]` is persisted as plain names (see `_run_build`'s checkpoint) — this
    is the one place that turns them back into the `{"name": ...}` dicts every
    `_gauntlet_*` helper expects."""
    return [{"name": n} for n in (job.get("partners") or [])]


def _deck_to_lines(commander, deck, partners=None) -> str:
    """Render an imported deck as MythGauntlet's decklist text format.

    `partners` is the rest of the command zone. `Deck.commanders` (mythgauntlet's own
    parser, model/deck.py) reads every line under the "Commander:" header, so a second
    line here is enough for the engine to resolve BOTH cards and union their colour
    identity in `manabase.analyze` — mirroring `deck_quality.assess_colors`'s own
    partners= fix. Omitting it (as this function always did) makes the strength engine
    and the mentor measure a partner deck's manabase against the LEAD commander's colours
    alone: a real WBUG manabase (duals/fetches that fix all four colours) reads back as
    "0 U sources, 0 G sources" because those colours sit outside the half-identity.
    Found live 2026-08-25 on Tymna the Weaver + Thrasios, Triton Hero.
    """
    lines = []
    if commander and commander.get("name"):
        lines += ["Commander:", f"1 {commander['name']}"]
        for p in (partners or []):
            if p.get("name"):
                lines.append(f"1 {p['name']}")
        lines.append("")
    lines.append("Deck:")
    for c in deck:
        name = c.get("name", "")
        if name:
            lines.append(f"{c.get('quantity', 1)} {name}")
    return "\n".join(lines)


_ENGINE_FP_CACHE = {"at": 0.0, "fp": None}


def _engine_fingerprint() -> str | None:
    """The running engine's `model_fingerprint` (60 s cache), None when unknown.

    A cached `last_measure` from different scoring code is stale: the deck page used to
    show a Sep 4 Resilience 88 as current beside a fresh 41 for the same list, because
    `engine_version` never moved through the axis re-models. Unknown (engine down) is not
    stale - there is nothing better to show."""
    now = time.time()
    if _ENGINE_FP_CACHE["fp"] is not None and now - _ENGINE_FP_CACHE["at"] < 60:
        return _ENGINE_FP_CACHE["fp"]
    try:
        fp = requests.get(f"{MYTHGAUNTLET_URL}/health", timeout=1.5).json().get("model_fingerprint")
    except Exception:
        return None
    _ENGINE_FP_CACHE.update(at=now, fp=fp)
    return fp


def _gauntlet_analyze(commander, deck, partners=None):
    """Simulation-grounded strength from MythGauntlet; None if the service is unavailable."""
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/analyze",
            json={
                "deck": _deck_to_lines(commander, deck, partners),
                "name": (commander or {}).get("name") or "deck",
                "runs": 300,
                "resilience": True,
                "combos": True,  # graded combo gate: real wincons vs durdles (Spellbook, cached)
            },
            # Measured 2026-10-06: a real 89-card deck takes ~38s through /analyze
            # (runs=300 + resilience + combos), so the old 25s read timeout reported
            # a healthy engine as "unreachable". 120s leaves margin for a loaded box.
            timeout=120,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "engine_version": data.get("engine_version"),
            "model_fingerprint": data.get("model_fingerprint"),
            "power_profile": data.get("power_profile"),
            "combos": data.get("combos"),  # graded in-deck combos for the strength panel
            # Deck-specific narrative (archetype/gameplan/pod placement/key cards/strengths
            # & weaknesses) -- fully computed by the engine's own insight.py, deterministic
            # and free (no extra simulation), but previously dropped here: this function
            # reshapes the /analyze response and only ever forwarded the three keys above.
            "insight": data.get("insight"),
            "unresolved": (data.get("deck") or {}).get("unresolved", []),
        }
    except Exception as e:
        print(f"  [import-preview] MythGauntlet strength API unavailable: {e}")
        return None


def _deck_archetypes(job: dict) -> list[str]:
    """The deck's OWN detected archetypes, for the engine's redundancy targets.

    The engine judges "what does this deck have too much of" against ONE population
    baseline unless it is told what the deck is trying to DO, and that reads a deck's plan
    as oversupply: a spellslinger deck is scored against a population whose median deck
    plays ZERO counterspells, so its interaction becomes the cut pool. The detector lives
    here (`deck_themes`), not in the engine on :8020, so this is the handoff.

    PREFER THE PERSISTED BLOCK. `stats.archetypes` was computed by `compute_stats` from the
    deck's REAL cards, before theming touched them. Re-deriving it from the stored entries
    is second best on purpose, because theming MUTATES the text those rules read: a tribe
    reskin rewrites rules text ("equip Knight" -> "equip Cowboy") and the self-reference
    pass swaps the card's own name in. `original_type_line` is the un-reskinned line and is
    what the fallback reads; the oracle text has no such rewind, so on a tribe-reskinned
    deck built before `stats.archetypes` existed this can under-detect.

    Under-detection is the safe failure: no archetype means the population baseline, which
    is what the engine did before this existed. Never raises - advice must not fail because
    a descriptive figure could not be derived.
    """
    try:
        stored = ((job.get("stats") or {}).get("archetypes") or {}).get("deck")
        if stored:
            return list(stored)
        import deck_themes
        return deck_themes.detect_deck_themes([
            {
                "name": c.get("original_name", ""),
                "type_line": c.get("original_type_line") or c.get("type_line", ""),
                "oracle_text": c.get("oracle_text", ""),
            }
            for c in (job.get("deck") or [])
        ])
    except Exception:      # noqa: BLE001 - a missing archetype only costs precision
        return []


def _gauntlet_advise(commander, deck, axis=None, themes=None, partners=None):
    """Owned-card upgrade suggestions from MythGauntlet's ablation advisor.

    Returns the advise JSON, {"error": detail} for a meaningful 400 (no collection
    exported / bad axis), or None when the service is unreachable.

    `themes` are the deck's own archetypes (see `_deck_archetypes`); without them the
    engine judges every role against one population baseline and offers the deck its own
    plan as the cut pool.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck, partners),
            "name": (commander or {}).get("name") or "deck",
            "runs": 300,
            # The advisor ranks owned candidates by TARGET-AXIS relevance + commander fit
            # before spending the eval budget, then returns a NON-OVERLAPPING package
            # (distinct cuts). cut_pool=6 gives up to 6 replaceable slots so the package
            # can be more than 3 swaps; max_eval=16 relevant adds compete for them.
            # NOT "~60s warm" — that estimate was swept at max_eval=10, runs=60.
            # MEASURED 2026-08-26 at this exact config against a real 99-card deck with
            # ComfyUI + llama-swap warm-but-idle: 583s (96 analyses, ~6s/analysis at
            # runs=300). `_gauntlet_advise` now runs off the request thread (see
            # `advise_deck`'s docstring), so 900s just needs real margin over that
            # measurement, not to double as a UI-responsiveness budget.
            "max_eval": 16,
            "cut_pool": 6,
        }
        if themes:
            payload["themes"] = list(themes)
        if axis:
            payload["axis"] = axis
        lift = edhrec_lift.lift_map((commander or {}).get("name") or "")
        if lift:
            payload["lift"] = lift
        resp = requests.post(f"{MYTHGAUNTLET_URL}/advise", json=payload, timeout=900)
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "advise failed")}
            except Exception:
                return {"error": "advise failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.Timeout:
        # Reachable but slower than the budget — saying "unreachable" here sent the
        # 2026-10-23 investigation after the wrong process (the cause was sim cost).
        print("  [advise] MythGauntlet /advise timed out after 900s")
        return {"error": "The upgrade search took longer than 15 minutes and was stopped. "
                         "The strength engine is running but overloaded — try again, or pick "
                         "a single target axis."}
    except Exception as e:
        print(f"  [advise] MythGauntlet strength API unavailable: {e}")
        return None


def _gauntlet_card_impact(commander, deck, card_name, themes=None, partners=None):
    """Would ONE named card help or hurt this deck (MythGauntlet /card-impact).

    Same shape as _gauntlet_advise: the JSON on success, {"error": detail} for a
    meaningful 400/404 (unknown card name is the common one, and the user needs to see
    that rather than a generic failure), None when the service is unreachable.

    runs is lower than /advise's because this re-simulates the whole Power Profile per
    candidate cut and the user is waiting on it interactively; cut_pool=3 keeps it to
    three analyses.

    `themes` are the deck's own archetypes (see `_deck_archetypes`) - same handoff /advise
    uses, and needed here for the same reason: without them the slot this card is tested
    against can be part of the deck's own plan.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck, partners),
            "name": (commander or {}).get("name") or "deck",
            "card": card_name,
            "runs": 200,
            "cut_pool": 3,
            "themes": list(themes or []),
        }
        lift = edhrec_lift.lift_map((commander or {}).get("name") or "")
        if lift:
            payload["lift"] = lift
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/card-impact",
            json=payload,
            timeout=120,
        )
        if resp.status_code in (400, 404):
            try:
                return {"error": resp.json().get("detail", "card lookup failed")}
            except Exception:
                return {"error": "card lookup failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [card-impact] MythGauntlet strength API unavailable: {e}")
        return None


def _gauntlet_mentor_chat(commander, deck, question, history=None, model=None, themes=None,
                           partners=None, offmeta=None, advice=None):
    """Deck Mentor chat turn from MythGauntlet's tool-calling loop + claim-budget gate
    (docs/SPEC_deck_mentor.md Phase 2). Same shape as `_gauntlet_advise`/
    `_gauntlet_card_impact`: JSON on success, {"error": detail} for a meaningful 400/503
    the caller should show verbatim, None when the service process itself is unreachable.

    Unlike the other two, a 503 from :8020 here can mean "the engine is down" (None,
    same as always) OR "the engine is up but hasn't run fetch-rules yet" (a real detail
    message worth showing) -- both are surfaced as {"error": ...} rather than being
    collapsed into the generic "unreachable" case, since only the latter is actionable
    with "start the server"; the former needs "run fetch-rules" instead.

    `offmeta` is this deck's own persisted `lift_stats.stats_block` reading (see
    `mentor_chat_deck`) -- the engine has no EDHREC cache of its own, so this is a
    pass-through of what Forge already computed, exactly like `themes` already is.

    `advice` is `_valid_advice(job)`: the deck's still-current cached full swap searches
    (D2), `{axis key: {"result", "computed_at"}}`, for the engine's `get_measured_swaps`.
    """
    try:
        payload = {
            "deck": _deck_to_lines(commander, deck, partners),
            "name": (commander or {}).get("name") or "deck",
            "question": question,
            "history": history or [],
        }
        if model:
            payload["model"] = model
        if themes:
            payload["themes"] = list(themes)
        if offmeta:
            payload["offmeta"] = offmeta
        if advice:
            payload["advice"] = advice
        resp = requests.post(f"{MYTHGAUNTLET_URL}/mentor/chat", json=payload, timeout=120)
        if resp.status_code in (400, 503):
            try:
                return {"error": resp.json().get("detail", "mentor chat failed")}
            except Exception:
                return {"error": "mentor chat failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [mentor] MythGauntlet strength API unavailable: {e}")
        return None


class MentorChatDeckRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)
    model: Optional[str] = None  # None -> the engine's own default (qwen3:14b)


@router.post("/api/deck/{job_id}/mentor")
def mentor_chat_deck(job_id: str, req: MentorChatDeckRequest, request: Request):
    """Ask the Deck Mentor a question about this finished deck (docs/SPEC_deck_mentor.md
    Phase 2). Every reply is checked against that turn's own tool calls before it comes
    back — `gated: false` in the response means the answer is an honest "I'm not sure"
    rather than a claim that failed verification, never a silently-stripped one.
    """
    _require_job_id(job_id)
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip + _CHAT_RATE_LIMIT_KEY, _RATE_LIMIT_CHAT_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_CHAT_REQUESTS} requests per {_RATE_LIMIT_WINDOW}s")
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck for the mentor to read.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    result = _gauntlet_mentor_chat(
        commander, deck, req.question.strip(), history=req.history, model=req.model,
        themes=_deck_archetypes(job), partners=_job_partners(job),
        offmeta=(job.get("stats") or {}).get("offmeta") or None,
        advice=_valid_advice(job) or None,
    )
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


def _gauntlet_breakdown(commander, deck, themes=None, partners=None):
    """The engine's /breakdown block (the mentor's own role table, interaction coverage,
    curve, colour sources and per-card roles); {"error": detail} on a 400, None when the
    service is unreachable."""
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/breakdown",
            json={"deck": _deck_to_lines(commander, deck, partners),
                  "name": (commander or {}).get("name") or "deck",
                  "themes": list(themes or [])},
            timeout=120,
        )
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "breakdown failed")}
            except ValueError:
                return {"error": "breakdown failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [breakdown] MythGauntlet strength API unavailable: {e}")
        return None


# Bump when the engine's /breakdown payload gains fields, so cached breakdowns re-measure once.
# 2: per-card `commander_synergy`.
BREAKDOWN_SCHEMA = 2


@router.post("/api/deck/{job_id}/breakdown")
def deck_breakdown(job_id: str, refresh: bool = False):
    """The Deck Mentor's measurements for charts and the deck view's group-by-role.

    Persisted in deck.json under `breakdown` with the hash of the decklist text and the
    themes it was measured with, so the panel opens instantly on a revisit and a swap,
    rebuild or edit recomputes it rather than charting the old list. `refresh=true`
    re-measures anyway (a tagger change in the engine moves roles without moving the hash).
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    if not (job.get("deck") or []):
        raise HTTPException(400, "A single-card build has no deck to break down.")
    commander, deck = _job_deck_inputs(job)
    partners = _job_partners(job)
    themes = _deck_archetypes(job)
    key = hashlib.sha1(json.dumps(
        [BREAKDOWN_SCHEMA, _deck_to_lines(commander, deck, partners), sorted(themes)]
    ).encode("utf-8")).hexdigest()
    cached = job.get("breakdown") or {}
    if not refresh and cached.get("key") == key and cached.get("data"):
        return {**cached["data"], "computed_at": cached.get("computed_at"), "cached": True}
    data = _gauntlet_breakdown(commander, deck, themes=themes, partners=partners)
    if data is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in data:
        raise HTTPException(400, data["error"])
    stamp = {"key": key, "data": data, "computed_at": _dt.now().isoformat(timespec="seconds")}
    try:
        p = state.RENDER_DIR / job_id / "deck.json"
        if p.exists():
            disk_data = json.loads(p.read_text(encoding="utf-8"))
            disk_data["breakdown"] = stamp
            p.write_text(json.dumps(disk_data), encoding="utf-8")
        if job_id in _jobs:
            _jobs[job_id]["breakdown"] = stamp
    except Exception as e:
        print(f"  [breakdown] could not persist: {e}")
    return {**data, "computed_at": stamp["computed_at"], "cached": False}


class MentorFeedbackDeckRequest(BaseModel):
    turn_id: str = Field(min_length=1)
    rating: str = Field(description="'up' or 'down'")
    note: Optional[str] = Field(default=None, max_length=1000)


@router.post("/api/deck/{job_id}/mentor/feedback")
def mentor_feedback_deck(job_id: str, req: MentorFeedbackDeckRequest, request: Request):
    """Thumbs up/down on a logged mentor turn (docs/SPEC_deck_mentor.md, Phase 3
    prerequisite). `job_id` isn't sent to the engine -- `turn_id` alone identifies the
    logged record on :8020's side -- but the route is scoped under the deck anyway so a
    stray or spoofed turn_id from a different session can't be submitted from a page that
    was never shown that turn_id in the first place.
    """
    _require_job_id(job_id)
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip + _CHAT_RATE_LIMIT_KEY, _RATE_LIMIT_CHAT_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_CHAT_REQUESTS} requests per {_RATE_LIMIT_WINDOW}s")
    try:
        resp = requests.post(
            f"{MYTHGAUNTLET_URL}/mentor/feedback",
            json={"turn_id": req.turn_id, "rating": req.rating, "note": req.note},
            timeout=15,
        )
    except Exception as e:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        ) from e
    if resp.status_code == 400:
        detail = "invalid feedback"
        try:
            detail = resp.json().get("detail", detail)
        except ValueError:
            pass
        raise HTTPException(400, detail)
    if resp.status_code != 200:
        raise HTTPException(502, "Feedback was not recorded.")
    return resp.json()


class CardImpactDeckRequest(BaseModel):
    card: str = Field(min_length=1, max_length=200)


def _narrate_suggestions(result: dict, job: dict) -> dict:
    """Rewrite each swap's `reason` as prose, keeping the template as the fallback.

    The engine ships a `brief` per suggestion — the facts the swap is entitled to claim — and
    `swap_narrative` turns one into two or three sentences, then GATES the result against that
    brief. A draft that names a card outside the swap, cites a number nobody measured, calls a
    card something its vector does not show, or claims redundancy on a deck that over-supplies
    nothing is thrown away and the deterministic sentence stands.

    That fallback is what makes the gate affordable: refusing a draft costs polish, while
    shipping an invented claim costs the one thing an MTG-facing tool cannot afford. Every
    failure path here — no brief, LLM down, every attempt rejected — lands on the template.

    The original is preserved as `reason_template` rather than discarded, so the UI and any
    debugging can see both.
    """
    suggestions = result.get("suggestions") or []
    if not suggestions:
        return result
    try:
        import swap_narrative
    except Exception:                       # noqa: BLE001 - advice must never fail on this
        return result

    # Every card the deck actually plays, so the gate can catch an invented one. Read from the
    # stored deck rather than the engine payload: this is the only place that knows the list.
    deck_names = {c.get("original_name", "") for c in (job.get("deck") or [])}
    deck_names.discard("")
    commander = (job.get("commander") or {}).get("original_name")
    if commander:
        deck_names.add(commander)

    kept = 0
    for suggestion in suggestions:
        brief = suggestion.get("brief")
        if not brief:
            continue
        try:
            text = swap_narrative.narrate(brief, deck_card_names=deck_names)
        except Exception:                   # noqa: BLE001 - never fail the route
            text = None
        if text:
            suggestion["reason_template"] = suggestion.get("reason", "")
            suggestion["reason"] = text
            kept += 1
    if suggestions:
        print(f"  [advise] narrated {kept}/{len(suggestions)} suggestions "
              f"({len(suggestions) - kept} kept the measured template)")
    return result


class AdviseDeckRequest(BaseModel):
    axis: Optional[str] = None  # None -> the deck's weakest axis
    narrate: bool = True        # rewrite each reason as prose (gated; falls back silently)


@router.post("/api/deck/{job_id}/card-impact")
def card_impact_deck(job_id: str, req: CardImpactDeckRequest):
    """Ask whether ONE named card would help or hurt this finished deck, and why.

    Legality is judged before anything is simulated, so an off-colour or banned card comes
    back as a refusal with the reason rather than a power score for a card you cannot play.
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to measure against.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    result = _gauntlet_card_impact(commander, deck, req.card.strip(),
                                   themes=_deck_archetypes(job), partners=_job_partners(job))
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


def _suite_collection_mtime() -> float | None:
    """mtime of the Myth Suite collection.csv the advisor suggests from, None when absent.
    A cached swap search is only valid while the collection it searched is unchanged."""
    try:
        return suite_collection_path().stat().st_mtime
    except OSError:
        return None


def _advice_deck_hash(commander, deck, partners=None) -> str:
    """Identity of the deck a swap search ran on: sha1 of the exact decklist text the engine
    is sent. A swap, rebuild or edit changes it, so stale advice is never shown."""
    return hashlib.sha1(_deck_to_lines(commander, deck, partners).encode("utf-8")).hexdigest()


def _job_deck_inputs(job: dict) -> tuple[dict, list[dict]]:
    """(commander, deck) in the `{"name": ...}` shape every `_gauntlet_*` helper takes."""
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in (job.get("deck") or [])
    ]
    return commander, deck


def _valid_advice(job: dict) -> dict:
    """The deck's `advice_cache` entries that still describe THIS deck and THIS collection
    (deck hash and collection mtime both match), as `{axis key: {"result", "computed_at"}}`.
    Anything else is dropped -- the mentor then says no full search has been run."""
    cache = job.get("advice_cache") or {}
    if not cache:
        return {}
    commander, deck = _job_deck_inputs(job)
    deck_hash = _advice_deck_hash(commander, deck, _job_partners(job))
    mtime = _suite_collection_mtime()
    return {
        key: {"result": e["result"], "computed_at": e.get("computed_at")}
        for key, e in cache.items()
        if isinstance(e, dict) and isinstance(e.get("result"), dict)
        and e.get("deck_hash") == deck_hash and mtime is not None
        and e.get("collection_mtime") == mtime
    }


def _persist_advice(deck_job_id: str, axis_key: str, entry: dict) -> None:
    """Write `advice_cache[axis_key] = entry` into the deck's deck.json (and the in-memory job),
    the same read-modify-write `/measure` uses for `last_measure`. Deliberately NOT in
    `_PROVENANCE_KEYS`: a rebuilt/rethemed deck is a different deck and must not inherit it."""
    try:
        p = state.RENDER_DIR / deck_job_id / "deck.json"
        if p.exists():
            disk = json.loads(p.read_text(encoding="utf-8"))
            disk.setdefault("advice_cache", {})[axis_key] = entry
            p.write_text(json.dumps(disk), encoding="utf-8")
        mem = _jobs.get(deck_job_id)
        if mem is not None:
            mem.setdefault("advice_cache", {})[axis_key] = entry
    except Exception as e:
        print(f"  [advise] could not persist advice_cache: {e}")


def _run_advise_job(advise_job_id: str, commander, deck, axis, themes, partners, narrate, deck_job,
                    deck_job_id: str | None = None):
    """Background body of `advise_deck` — see that route for why this is async.

    Mirrors `_run_style_sample`: write status/result/error into `_jobs[advise_job_id]`
    rather than returning, since this runs via `BackgroundTasks` after the POST has
    already responded.

    On success the result is also cached in the DECK's deck.json (`advice_cache`, keyed by the
    requested axis or "auto") so the Deck Mentor's `get_measured_swaps` can cite it (D2). The
    collection mtime is read BEFORE the search: a collection edited mid-run invalidates the
    entry rather than blessing a search that ran on the old file.
    """
    job = _jobs[advise_job_id]
    mtime = _suite_collection_mtime()
    try:
        result = _gauntlet_advise(commander, deck, axis=axis, themes=themes, partners=partners)
        if result is not None and "error" not in result and narrate:
            result = _narrate_suggestions(result, deck_job)
        if result is None:
            job.update(status="error", error=(
                "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
                "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'."
            ))
        elif "error" in result:
            job.update(status="error", error=result["error"])
        else:
            job.update(status="done", result=result)
            if deck_job_id:
                _persist_advice(deck_job_id, axis or "auto", {
                    "result": result,
                    "deck_hash": _advice_deck_hash(commander, deck, partners),
                    "collection_mtime": mtime,
                    "computed_at": _dt.now().isoformat(timespec="seconds"),
                })
    except Exception as e:
        traceback.print_exc()
        job.update(status="error", error=str(e))


@router.post("/api/deck/{job_id}/advise")
async def advise_deck(job_id: str, req: AdviseDeckRequest, background_tasks: BackgroundTasks, request: Request):
    """Start upgrade-advice from the user's collection for a FINISHED deck (suite C4).

    Every suggestion is a measured axis delta from MythGauntlet's ablation re-simulation,
    never popularity. Needs the strength API (:8020) and a Myth Suite collection export.

    **Runs in the background (2026-08-26) — this used to block on the whole simulation
    inside the POST.** The advisor's own default (`max_eval=16, cut_pool=6, runs=300`)
    was measured end to end at **583s** against a real 99-card deck with Myth Forge's own
    GPU services warm-but-idle (the ordinary state right after a build) — ~10x the "~60s
    warm" estimate in `advisor.advise`'s docstring, which was swept at a smaller
    `max_eval=10` and a 5x-lower `runs=60`. That is far past any synchronous HTTP timeout
    worth setting: covering it would mean holding a live browser connection AND a FastAPI
    worker thread for ten-plus minutes, and a busier machine or bigger deck can only make
    it longer. So the fix is not a bigger timeout number or a smaller `max_eval`/`cut_pool`
    (that would just trade advice quality for a still-dishonest wait) — it's the same
    start-a-job/poll-for-it shape `style_sample` already uses for its own long ComfyUI
    renders. The POST returns a job id immediately; poll
    `GET /api/deck/advise/{advise_job_id}` for the result.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip + _CHAT_RATE_LIMIT_KEY, _RATE_LIMIT_CHAT_REQUESTS):
        raise HTTPException(429, f"Rate limited — max {_RATE_LIMIT_CHAT_REQUESTS} requests per {_RATE_LIMIT_WINDOW}s")
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to advise on.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    advise_job_id = uuid.uuid4().hex[:16]
    _jobs[advise_job_id] = {"status": "running", "kind": "advise", "result": None,
                            "error": None, "created_at": time.time()}
    background_tasks.add_task(
        _run_advise_job, advise_job_id, commander, deck, req.axis,
        _deck_archetypes(job), _job_partners(job), req.narrate, job, job_id,
    )
    return {"job_id": advise_job_id}


@router.get("/api/deck/advise/{advise_job_id}")
async def advise_status(advise_job_id: str):
    j = _jobs.get(advise_job_id)
    if not j or j.get("kind") != "advise":
        raise HTTPException(404, "Advise job not found")
    if j.get("status") == "done":
        return {"status": "done", "result": j.get("result")}
    if j.get("status") == "error":
        return {"status": "error", "detail": j.get("error")}
    return {"status": "running"}


@router.post("/api/deck/{job_id}/measure")
def measure_deck(job_id: str):
    """Simulation-grounded strength for a FINISHED deck (suite C3, result screen).

    Converts the stored deck.json back into a decklist and reuses the same
    MythGauntlet call as import-preview, so imported and generated decks measure
    identically. 503 when the strength API is down (the UI says how to start it);
    400 for a single-card build (nothing to measure).
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to measure.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    sim = _gauntlet_analyze(commander, deck, partners=_job_partners(job))
    if sim is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    # Persist the measurement so History/Recent tiles can badge the measured
    # bracket and the result screen shows the cached profile without re-simulating.
    stamp = {"simulation": sim, "date": _dt.now().isoformat(timespec="seconds")}
    try:
        p = state.RENDER_DIR / job_id / "deck.json"
        if p.exists():
            disk_data = json.loads(p.read_text(encoding="utf-8"))
            disk_data["last_measure"] = stamp
            p.write_text(json.dumps(disk_data), encoding="utf-8")
        if job_id in _jobs:
            _jobs[job_id]["last_measure"] = stamp
    except Exception as e:
        print(f"  [measure] could not persist last_measure: {e}")
    return sim


class ApplySwapRequest(BaseModel):
    add: str
    cut: str


@router.post("/api/deck/{job_id}/apply-swap")
def apply_swap(job_id: str, req: ApplySwapRequest):
    """Apply an advisor suggestion to a FINISHED deck: cut one card, add another.

    Closes the build -> test -> improve loop (suite C4): the AdvisePanel's measured
    suggestions become one-click edits instead of a manual re-import. The added card
    is stored UNTHEMED (real name, Scryfall art fallback, swapped_in flag) — theming
    art for it is a later regen, not a blocker for testing. The cached measurement is
    invalidated because the deck changed; the swap is recorded in applied_swaps.
    """
    _require_job_id(job_id)
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        _jobs[job_id] = disk
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has no deck to modify.")

    cut_norm = req.cut.strip().casefold()
    idx = next(
        (i for i, c in enumerate(cards)
         if (c.get("original_name") or "").casefold() == cut_norm),
        None,
    )
    if idx is None:
        raise HTTPException(400, f"'{req.cut}' is not in this deck (already swapped out?)")
    add_norm = req.add.strip().casefold()
    if any((c.get("original_name") or "").casefold() == add_norm for c in cards):
        raise HTTPException(400, f"'{req.add}' is already in this deck.")

    card = _scryfall.get_card_by_name(req.add, fuzzy=True)
    if not card:
        raise HTTPException(400, f"Card not found on Scryfall: {req.add}")

    # cut: decrement a stack (imported duplicate basics), else remove the entry
    if (cards[idx].get("quantity") or 1) > 1:
        cards[idx]["quantity"] = cards[idx]["quantity"] - 1
    else:
        cards.pop(idx)

    swap_no = int(job.get("swap_count") or 0) + 1
    job["swap_count"] = swap_no
    name = card.get("_front_name") or card.get("name") or req.add
    new_entry = {
        "original_name": name,
        "themed_name":   name,               # unthemed — shows the real card
        "art_prompt":    "",
        "custom_prompt": "",
        "use_custom":    False,
        "flavor_text":   "",
        "mana_cost":     card.get("mana_cost", ""),
        "type_line":          card.get("type_line", ""),
        "original_type_line": card.get("type_line", ""),
        "oracle_text":   card.get("oracle_text", ""),
        "cmc":           card.get("cmc", 0),
        "colors":        card.get("color_identity", []),
        "power":         card.get("power"),
        "toughness":     card.get("toughness"),
        "rarity":        card.get("rarity", ""),
        "quantity":      1,
        "scryfall_img":  (card.get("image_uris") or {}).get("normal", ""),
        "has_render":    False,              # tile falls back to scryfall_img
        "has_video":     False,
        "render_key":    f"{_safe_name(name)}_swap{swap_no:02d}",
        "swapped_in":    True,               # UI badge: an applied upgrade
    }
    cards.insert(min(idx, len(cards)), new_entry)

    swap_record = {"add": name, "cut": req.cut,
                   "date": _dt.now().isoformat(timespec="seconds")}
    job.setdefault("applied_swaps", []).append(swap_record)
    job.pop("last_measure", None)            # the measurement no longer matches the list

    try:
        p = state.RENDER_DIR / job_id / "deck.json"
        if p.exists():
            disk_data = json.loads(p.read_text(encoding="utf-8"))
            disk_data["deck"] = cards
            disk_data["swap_count"] = swap_no
            disk_data.setdefault("applied_swaps", []).append(swap_record)
            disk_data.pop("last_measure", None)
            p.write_text(json.dumps(disk_data), encoding="utf-8")
    except Exception as e:
        print(f"  [apply-swap] could not persist swap: {e}")

    return _serializable_job(job)


class DuelRequest(BaseModel):
    opponent: str                 # opponent decklist text (pasted, Moxfield/plain)
    opponent_name: str = "Opponent"
    games: int = 120


def _gauntlet_duel(commander, deck, opponent_text, name_a, name_b, games, partners=None):
    """Head-to-head win rate from MythGauntlet's Tier-2 adversarial engine.

    Returns the duel JSON, {"error": detail} for a meaningful 400 (unparseable
    opponent list), or None when the service is unreachable.
    """
    try:
        payload = {
            "deck_a": _deck_to_lines(commander, deck, partners),
            "deck_b": opponent_text,
            "name_a": name_a or "Your deck",
            "name_b": name_b or "Opponent",
            "games": max(20, min(400, int(games))),
            "seed": 42,
        }
        resp = requests.post(f"{MYTHGAUNTLET_URL}/duel", json=payload, timeout=180)
        if resp.status_code == 400:
            try:
                return {"error": resp.json().get("detail", "duel failed")}
            except Exception:
                return {"error": "duel failed"}
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  [duel] MythGauntlet strength API unavailable: {e}")
        return None


@router.post("/api/deck/{job_id}/duel")
def duel_deck(job_id: str, req: DuelRequest):
    """Test THIS finished deck head-to-head against a pasted opponent decklist (Tier-2).

    Battlecruiser-fidelity 1v1 win rate — an honest "how does my deck play against
    my friend's?" read, not a bracket verdict. Needs the strength API (:8020).
    """
    _require_job_id(job_id)
    if not (req.opponent or "").strip():
        raise HTTPException(400, "Paste an opponent decklist to test against.")
    job = _jobs.get(job_id)
    if not job or "commander" not in job:
        disk = _load_deck_from_disk(job_id)
        if not disk:
            raise HTTPException(404, "Deck not found")
        job = disk
    cards = job.get("deck") or []
    if not cards:
        raise HTTPException(400, "A single-card build has nothing to duel with.")
    commander = {"name": (job.get("commander") or {}).get("original_name") or ""}
    deck = [
        {"name": c.get("original_name", ""), "quantity": c.get("quantity", 1)}
        for c in cards
    ]
    name_a = (job.get("commander") or {}).get("themed_name") \
        or (job.get("commander") or {}).get("original_name") or "Your deck"
    result = _gauntlet_duel(
        commander, deck, req.opponent, name_a, req.opponent_name, req.games,
        partners=_job_partners(job),
    )
    if result is None:
        raise HTTPException(
            503,
            "MythGauntlet strength API isn't reachable on :8020 — start Myth Forge "
            "via manage.bat (it auto-starts it) or run 'mythgauntlet serve'.",
        )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
