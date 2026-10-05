"""Dense (embedding) half of the Comprehensive Rules search.

BM25 matches WORDS, and a player rarely uses the rulebook's: "can I attack a planeswalker?" never
reaches 306.6 ("Planeswalkers can be attacked"), "more than seven cards at end of turn" never
reaches 402.2 ("maximum hand size"). Measured 2026-10-05 on 450 player-style questions
(`scripts/rules_retrieval_bench.py`), BM25 put the right rule family in the top 5 for 83.1% and the
exact rule first for 56.9%; reciprocal-rank fusion with a small CPU embedding model raised that to
90.0% / 69.1%.

Optional by construction -- `RulesSearchIndex` falls back to BM25 alone whenever this is off
(`MYTHGAUNTLET_RULES_DENSE=off`, which `tests/conftest.py` sets), `fastembed` is not installed, the
model cannot be fetched, or the document vectors are still being built. Building them is ~2.5 min
of CPU for ~4,000 documents, so it NEVER happens inline in a search: a missing cache starts a
background thread and the search answers from BM25 until it lands. `fetch-rules` and engine
startup start that build so a player rarely meets the fallback. Vectors are cached beside the
rules store, keyed by a hash of the model and every document's text, so a rules update rebuilds
them and a stale file can never be read against a new corpus.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
# bge models are trained with this instruction on the QUERY side only.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# Fusion weights, swept on the qwen3:14b question set and checked on the muse-glimmer held-out
# set: the dense ranking is the better one alone, BM25 still rescues exact-term questions.
DENSE_WEIGHT = 1.5
BM25_WEIGHT = 1.0
RRF_K = 60
DEPTH = 200

_LOCK = threading.Lock()
_model = None
_disabled_reason: str | None = None
_vectors: dict[str, object] = {}  # corpus key -> np.ndarray (unit rows)
_building: set[str] = set()


def enabled() -> bool:
    if os.environ.get("MYTHGAUNTLET_RULES_DENSE", "").strip().lower() == "off":
        return False
    if _disabled_reason is not None:
        return False
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _cache_dir() -> Path:
    from mythgauntlet.data.rulings import cr_path
    return cr_path().parent


def _disable(reason: str) -> None:
    global _disabled_reason
    if _disabled_reason is None:
        _disabled_reason = reason
        print(f"  [rules-search] embedding search off, BM25 only: {reason}")


def _get_model():
    """Loaded once per process (~3 s, ~130 MB RAM). Model files live beside the rules store,
    not in fastembed's default temp folder, which the OS may clean."""
    global _model
    with _LOCK:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(MODEL, cache_dir=str(_cache_dir() / "fastembed"))
        return _model


def is_heading(text: str) -> bool:
    """A section/rule TITLE ("Trample", "Handling Triggered Abilities") rather than a rule: the
    CR ends every rule sentence with punctuation and no title (417 titles, 0 exceptions, 2026-10).
    Length is not the test -- 402.2 is a 68-character rule."""
    return bool(text) and not text.rstrip().endswith((".", ")", "”", ":"))


def doc_texts(docs: list[tuple[str, str, str]], rules: dict[str, str]) -> list[str]:
    """What gets embedded: a sub-rule is prefixed with its short ancestor headings ("Keyword
    Abilities / Trample: ..."), because 702.19c's own text never says what section it is in."""
    out = []
    for kind, ref, text in docs:
        if kind != "rule":
            out.append(text)
            continue
        heads = []
        for anc in (ref[:3], ref[:-1] if ref[-1:].isalpha() else None):
            if anc and anc != ref and is_heading(rules.get(anc, "")):
                heads.append(rules[anc])
        out.append(f"{' / '.join(heads)}: {text}" if heads else text)
    return out


def corpus_key(texts: list[str]) -> str:
    h = hashlib.sha1(MODEL.encode())
    for t in texts:
        h.update(b"\0" + t.encode("utf-8"))
    return h.hexdigest()


def _cache_file(key: str) -> Path:
    slug = MODEL.split("/")[-1]
    return _cache_dir() / f"rules_dense_{slug}_{key[:16]}.npy"


def _build(key: str, texts: list[str]) -> None:
    import numpy as np
    try:
        vecs = np.array(list(_get_model().embed(texts, batch_size=64)), dtype=np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        path = _cache_file(key)
        tmp = path.with_suffix(".part.npy")
        np.save(tmp, vecs)
        tmp.replace(path)
        with _LOCK:
            _vectors[key] = vecs
    except Exception as exc:  # model download / ONNX failure: degrade, never break search
        _disable(f"{type(exc).__name__}: {exc}")
    finally:
        with _LOCK:
            _building.discard(key)


def vectors(texts: list[str], wait: bool = False, start: bool = True):
    """The unit document vectors for `texts`, or None while they are not available (and a
    background build has been started, unless `start=False`). `wait=True` builds inline -- CLI
    use only."""
    if not enabled():
        return None
    key = corpus_key(texts)
    with _LOCK:
        if key in _vectors:
            return _vectors[key]
    path = _cache_file(key)
    if path.exists():
        import numpy as np
        try:
            vecs = np.load(path)
            if vecs.shape[0] == len(texts):
                with _LOCK:
                    _vectors[key] = vecs
                return vecs
        except (OSError, ValueError):
            pass
    if wait:
        with _LOCK:
            _building.add(key)
        _build(key, texts)
        with _LOCK:
            return _vectors.get(key)
    with _LOCK:
        if key in _building or not start:
            return None
        _building.add(key)
    threading.Thread(target=_build, args=(key, texts), daemon=True,
                     name="rules-dense-build").start()
    return None


def query_vector(query: str):
    import numpy as np
    try:
        v = np.array(next(iter(_get_model().embed([QUERY_PREFIX + query]))), dtype=np.float32)
    except Exception as exc:
        _disable(f"{type(exc).__name__}: {exc}")
        return None
    return v / np.linalg.norm(v)


def fuse(bm25_order: list[int], dense_order: list[int]) -> list[int]:
    """Reciprocal-rank fusion of two rankings of document indices."""
    score: dict[int, float] = {}
    for weight, order in ((BM25_WEIGHT, bm25_order), (DENSE_WEIGHT, dense_order)):
        for rank, doc in enumerate(order[:DEPTH]):
            score[doc] = score.get(doc, 0.0) + weight / (RRF_K + rank + 1)
    return sorted(score, key=score.__getitem__, reverse=True)
