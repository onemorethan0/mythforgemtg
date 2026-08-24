"""Rulings + Comprehensive Rules corpus (docs/SPEC_deck_mentor.md Phase 0).

Two independent sources, one module, because they answer the same class of question
("what does the game actually say, not what does a language model guess it says")
and share the same doctrine as every other module in `data/`: cached under
`data_dir()`, refreshed on a staleness check, and a malformed or restructured
upstream document is a loud error here rather than a silently-empty or
silently-wrong corpus downstream (see `scryfall.py`'s SLIM_SCHEMA check and its
26-day-frozen-bulk incident — the failure mode this doctrine exists to prevent).

- **Scryfall rulings** (`fetch_rulings`): official per-card rulings, keyed by
  `oracle_id` — joins straight onto the existing `CardDb` identity, no new lookup
  problem to solve.
- **Comprehensive Rules** (`fetch_comprehensive_rules`): the numbered rules text
  from magic.wizards.com/en/rules, parsed into `{number, text}` records — the exact
  citation unit a Deck Mentor answer has to trace back to — plus the Glossary as
  `{term, text}`. Before this module, this repo had zero rules/rulings data
  anywhere (confirmed by grep while auditing SPEC_deck_mentor.md); every "does this
  actually work the way I think" question had no ground truth to check an LLM's
  answer against.

Retrieval: exact rule-number and card-name lookups are dict gets. Free-text rules
questions go through BM25 (`rank_bm25`) over rule + glossary text — deliberately
NOT an embedding index. The corpus is small (~3,500 rule records, ~1,000 glossary
terms) and CR prose is dense with the exact terminology a real question uses, which
is where lexical search outperforms semantic search; add a semantic layer only if
BM25 recall is measured on the Phase 4 gold set and found wanting.
"""

from __future__ import annotations

import gzip
import json
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import requests
from rank_bm25 import BM25Okapi

from mythgauntlet import __version__
from mythgauntlet.config import data_dir

HEADERS = {
    "User-Agent": f"MythGauntlet/{__version__} (github.com/onemorethan0/mythgauntlet)",
    "Accept": "application/json",
}

# ── Scryfall rulings ────────────────────────────────────────────────────────────

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
RULINGS_FILENAME = "rulings_slim.json"
RULINGS_SCHEMA = 1
RULINGS_MAX_AGE_DAYS = 7  # same cadence as the card bulk -- rulings ship with sets


def rulings_path() -> Path:
    return data_dir() / RULINGS_FILENAME


def rulings_age_days() -> float | None:
    out = rulings_path()
    if not out.exists():
        return None
    return (time.time() - out.stat().st_mtime) / 86400


def fetch_rulings(force: bool = False, max_age_days: float | None = RULINGS_MAX_AGE_DAYS) -> Path:
    """Download + group Scryfall's rulings bulk file by oracle_id. Returns the store path.

    Mirrors `scryfall.fetch_bulk`: JSONL-gzipped, streamed (the raw payload groups to
    ~5 MB compressed but is still read a line at a time on principle), atomic write.
    """
    out = rulings_path()
    if out.exists() and not force:
        age = rulings_age_days()
        if max_age_days is None or (age is not None and age <= max_age_days):
            return out

    resp = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    index = resp.json()
    entry = next((d for d in index.get("data", []) if d.get("type") == "rulings"), None)
    if entry is None:
        raise RuntimeError("Scryfall bulk-data index has no 'rulings' entry (API changed?).")
    uri = entry.get("jsonl_download_uri") or entry.get("download_uri")
    if not uri:
        raise RuntimeError(
            f"Scryfall's 'rulings' entry has neither jsonl_download_uri nor download_uri "
            f"(fields: {sorted(entry)}) -- the bulk API changed again."
        )

    raw_path = data_dir() / "rulings.jsonl.gz"
    part = raw_path.with_suffix(raw_path.suffix + ".part")
    with requests.get(uri, headers=HEADERS, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    part.replace(raw_path)

    by_oracle: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            oid = rec.get("oracle_id")
            if not oid:
                continue
            by_oracle[oid].append({
                "source": rec.get("source", ""),
                "published_at": rec.get("published_at", ""),
                "comment": rec.get("comment", ""),
            })
    raw_path.unlink()

    if not by_oracle:
        raise RuntimeError("Scryfall rulings download yielded 0 records -- refusing to overwrite.")

    tmp = out.with_suffix(".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"schema": RULINGS_SCHEMA, "rulings": by_oracle}, fh, ensure_ascii=False)
    tmp.replace(out)
    return out


_rulings_cache: tuple[str, float, dict[str, list[dict]]] | None = None


def load_rulings_db(path: Path | None = None) -> dict[str, list[dict]]:
    """oracle_id -> [{source, published_at, comment}, ...]. Cached by (path, mtime)."""
    global _rulings_cache
    store = path or rulings_path()
    if not store.exists():
        raise FileNotFoundError(
            f"Rulings store not found at {store}. Run `mythgauntlet fetch-rules` first."
        )
    mtime = store.stat().st_mtime
    if _rulings_cache and _rulings_cache[0] == str(store) and _rulings_cache[1] == mtime:
        return _rulings_cache[2]
    with open(store, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != RULINGS_SCHEMA or "rulings" not in payload:
        raise RuntimeError(
            f"Rulings store schema is {payload.get('schema')}, expected {RULINGS_SCHEMA}. "
            "Run `mythgauntlet fetch-rules --force` to refresh."
        )
    db = payload["rulings"]
    _rulings_cache = (str(store), mtime, db)
    return db


def rulings_for_oracle_id(oracle_id: str, db: dict[str, list[dict]] | None = None) -> list[dict]:
    return (db if db is not None else load_rulings_db()).get(oracle_id, [])


# ── Comprehensive Rules ─────────────────────────────────────────────────────────

CR_RULES_PAGE_URL = "https://magic.wizards.com/en/rules"
CR_FILENAME = "comprehensive_rules.json"
CR_SCHEMA = 1
CR_MAX_AGE_DAYS = 14  # WotC updates the CR roughly per set release, not daily

# The rules page links three formats (.docx, .pdf, .txt) with a literal space (not
# %20) before the date in the raw href -- verified 2026-08-24 against the live page.
_CR_TXT_HREF_RE = re.compile(r'href="(https?://media\.wizards\.com/[^"]+\.txt)"')
_EFFECTIVE_DATE_RE = re.compile(r"effective as of ([A-Za-z]+ \d{1,2}, \d{4})", re.IGNORECASE)

# A numbered rule or subrule: "100." (section header), "100.1." (subrule), or
# "100.1a" (lettered sub-subrule -- no period after the letter). Verified against the
# live 2026-08-19 document: every rule's full text is on ONE line (max observed 2,879
# chars, no soft-wrapping), so a line-oriented parser is sufficient.
_RULE_RE = re.compile(r"^(\d{3}(?:\.\d+[a-z]?)?)\.?\s+(\S.*)$")
# Top-level category dividers ("1. Game Concepts", "8. Multiplayer Rules") -- these
# interleave with the real rule body but are organizational, not a citable rule
# number (Magic's CR system has never used a 1-2 digit rule number).
_SECTION_HEADER_RE = re.compile(r"^\d{1,2}\.\s+\S")


def cr_path() -> Path:
    return data_dir() / CR_FILENAME


def cr_age_days() -> float | None:
    out = cr_path()
    if not out.exists():
        return None
    return (time.time() - out.stat().st_mtime) / 86400


def _discover_cr_txt_url() -> str:
    resp = requests.get(CR_RULES_PAGE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    m = _CR_TXT_HREF_RE.search(resp.text)
    if not m:
        raise RuntimeError(
            f"Could not find a Comprehensive Rules .txt link on {CR_RULES_PAGE_URL} -- "
            "the page layout changed."
        )
    return m.group(1).replace(" ", "%20")


def _split_sections(text: str) -> tuple[list[str], list[str]]:
    """Return (rule_body_lines, glossary_lines), with the TOC and Credits stripped.

    'Credits' and 'Glossary' each appear as a bare line exactly twice in the live
    document: once as a Contents entry, once at the real section start. The FIRST
    bare 'Credits' line marks the end of the table of contents (so the start of the
    real numbered-rules body); the LAST bare 'Glossary' line marks the real glossary
    start; the LAST bare 'Credits' line marks its end. A document that no longer has
    exactly two of each has changed shape enough that silently parsing it would risk
    a wrong corpus, so this raises rather than guessing.
    """
    lines = text.splitlines()
    credits_idx = [i for i, ln in enumerate(lines) if ln.strip() == "Credits"]
    glossary_idx = [i for i, ln in enumerate(lines) if ln.strip() == "Glossary"]
    if len(credits_idx) < 2 or len(glossary_idx) < 2:
        raise RuntimeError(
            "Comprehensive Rules document structure changed: expected 2 'Credits' and "
            f"2 'Glossary' markers, found {len(credits_idx)} and {len(glossary_idx)}. "
            "Refusing to parse a corpus that might be silently wrong -- update the parser."
        )
    body = lines[credits_idx[0] + 1: glossary_idx[-1]]
    glossary = lines[glossary_idx[-1] + 1: credits_idx[-1]]
    return body, glossary


def _parse_rule_body(lines: list[str]) -> list[dict]:
    """Each rule-number line starts a new record; any non-blank line that follows and
    is neither a new rule number nor a section divider (e.g. an "Example:" paragraph)
    is appended to the rule above it -- that's real, citable content about the rule."""
    rules: list[dict] = []
    number: str | None = None
    parts: list[str] = []

    def flush() -> None:
        if number is not None:
            rules.append({"number": number, "text": " ".join(parts).strip()})

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _RULE_RE.match(line)
        if m:
            flush()
            number, parts = m.group(1), [m.group(2).strip()]
            continue
        if _SECTION_HEADER_RE.match(line):
            continue
        if number is not None:
            parts.append(line)
    flush()
    return rules


def _parse_glossary(lines: list[str]) -> list[dict]:
    """Blank lines are the only entry separator; within an entry the first line is
    the term and everything else is its definition -- verified against the live
    document, no heuristic needed."""
    entries: list[dict] = []
    block: list[str] = []

    def flush() -> None:
        if block:
            term, *rest = block
            entries.append({"term": term.strip(), "text": " ".join(p.strip() for p in rest).strip()})

    for raw in lines:
        if not raw.strip():
            flush()
            block = []
            continue
        block.append(raw)
    flush()
    return entries


def parse_comprehensive_rules(text: str) -> dict:
    """Pure parse of the raw CR text -> {effective_date, rules[], glossary[]}. No I/O,
    so this is exercised directly (and offline) by tests/engine/test_rulings.py."""
    m = _EFFECTIVE_DATE_RE.search(text)
    effective_date = m.group(1) if m else None
    body_lines, glossary_lines = _split_sections(text)
    rules = _parse_rule_body(body_lines)
    glossary = _parse_glossary(glossary_lines)
    if len(rules) < 1000 or len(glossary) < 500:
        # The live document runs ~3,500 rules / ~1,000 glossary terms. A parse this far
        # under either figure means the format drifted somewhere this parser didn't
        # anticipate -- ship an honest error, not a corpus that's quietly missing most
        # of itself (the exact failure the SLIM_SCHEMA check in scryfall.py guards).
        raise RuntimeError(
            f"Comprehensive Rules parse looks incomplete ({len(rules)} rules, "
            f"{len(glossary)} glossary terms) -- refusing to write a possibly-broken "
            "corpus. Inspect the source document; the format may have changed."
        )
    return {"effective_date": effective_date, "rules": rules, "glossary": glossary}


def fetch_comprehensive_rules(
    force: bool = False, max_age_days: float | None = CR_MAX_AGE_DAYS
) -> Path:
    out = cr_path()
    if out.exists() and not force:
        age = cr_age_days()
        if max_age_days is None or (age is not None and age <= max_age_days):
            return out

    url = _discover_cr_txt_url()
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    parsed = parse_comprehensive_rules(resp.text)

    tmp = out.with_suffix(".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"schema": CR_SCHEMA, "source_url": url, **parsed}, fh, ensure_ascii=False)
    tmp.replace(out)
    return out


@dataclass(frozen=True)
class ComprehensiveRules:
    effective_date: str | None
    source_url: str
    rules: dict[str, str]  # rule number -> text
    glossary: dict[str, str]  # term (lowercased) -> text

    def get_rule(self, number: str) -> str | None:
        return self.rules.get(number)

    def get_glossary_term(self, term: str) -> str | None:
        return self.glossary.get(term.strip().lower())


_cr_cache: tuple[str, float, ComprehensiveRules] | None = None


def load_comprehensive_rules(path: Path | None = None) -> ComprehensiveRules:
    global _cr_cache
    store = path or cr_path()
    if not store.exists():
        raise FileNotFoundError(
            f"Comprehensive Rules store not found at {store}. Run `mythgauntlet fetch-rules` first."
        )
    mtime = store.stat().st_mtime
    if _cr_cache and _cr_cache[0] == str(store) and _cr_cache[1] == mtime:
        return _cr_cache[2]
    with open(store, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != CR_SCHEMA:
        raise RuntimeError(
            f"Comprehensive Rules store schema is {payload.get('schema')}, expected "
            f"{CR_SCHEMA}. Run `mythgauntlet fetch-rules --force` to refresh."
        )
    cr = ComprehensiveRules(
        effective_date=payload.get("effective_date"),
        source_url=payload.get("source_url", ""),
        rules={r["number"]: r["text"] for r in payload.get("rules", [])},
        glossary={g["term"].lower(): g["text"] for g in payload.get("glossary", [])},
    )
    _cr_cache = (str(store), mtime, cr)
    return cr


# ── BM25 search over rules + glossary ───────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9']+")
# BM25 has no stemming or synonymy -- measured live 2026-08-24: "creature toughness
# zero dies" missed rule 704.5f entirely (the actual toughness-0-or-less rule) while
# "0 toughness creature graveyard" ranked it #1, purely because "zero" and "0" are
# different tokens. CR text overwhelmingly writes small numbers as digits ("toughness
# 0 or less", "ten or more poison counters" is the exception, not the rule), so
# normalizing spelled-out small numbers to digits closes most of the gap cheaply.
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}


def _tokenize(text: str) -> list[str]:
    return [_NUMBER_WORDS.get(tok, tok) for tok in _TOKEN_RE.findall(text.lower())]


@dataclass(frozen=True)
class RuleSearchResult:
    kind: str  # "rule" | "glossary"
    ref: str   # rule number, or glossary term
    text: str
    score: float


class RulesSearchIndex:
    """BM25 over every rule + glossary entry. Built once per `ComprehensiveRules`
    instance (cheap: ~4,500 short documents) and cached by the loader below."""

    def __init__(self, cr: ComprehensiveRules) -> None:
        self._docs: list[tuple[str, str, str]] = []  # (kind, ref, text)
        for number, text in cr.rules.items():
            self._docs.append(("rule", number, text))
        for term, text in cr.glossary.items():
            self._docs.append(("glossary", term, f"{term}. {text}"))
        corpus = [_tokenize(d[2]) for d in self._docs]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, k: int = 5) -> list[RuleSearchResult]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [
            RuleSearchResult(kind=self._docs[i][0], ref=self._docs[i][1],
                              text=self._docs[i][2], score=float(scores[i]))
            for i in ranked if scores[i] > 0
        ]


_index_cache: tuple[str, float, RulesSearchIndex] | None = None


def search_rules(query: str, k: int = 5, path: Path | None = None) -> list[RuleSearchResult]:
    """Free-text search over rules + glossary. The index is built once per store
    version and cached the same way `load_comprehensive_rules` caches the parsed
    store, keyed by (path, mtime)."""
    global _index_cache
    store = path or cr_path()
    mtime = store.stat().st_mtime if store.exists() else 0.0
    if _index_cache and _index_cache[0] == str(store) and _index_cache[1] == mtime:
        index = _index_cache[2]
    else:
        cr = load_comprehensive_rules(path)
        index = RulesSearchIndex(cr)
        _index_cache = (str(store), mtime, index)
    return index.search(query, k=k)
