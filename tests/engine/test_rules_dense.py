"""The embedding half of rules search (data/rules_dense.py), with the model faked: no download,
no ONNX, no cache file on the dev machine."""
from __future__ import annotations

import numpy as np

from mythgauntlet.data import rules_dense, rulings

RULES = {
    "306": "Planeswalkers",
    "306.6": "Planeswalkers can be attacked.",
    "402": "Hand",
    "402.2": "Each player has a maximum hand size, which is normally seven cards.",
    "402.2a": "If an effect says a player has no maximum hand size, ignore the limit.",
}


def _cr():
    return rulings.ComprehensiveRules(effective_date=None, source_url="", rules=dict(RULES),
                                      glossary={})


def test_fuse_rewards_agreement_and_lets_either_ranking_rescue_a_doc():
    assert rules_dense.fuse([0, 1, 2], [0, 2, 1])[0] == 0
    # Only the dense ranking has doc 9 -- it still makes the fused list.
    assert 9 in rules_dense.fuse([0, 1], [9, 0])
    # Weighted towards dense: a dense #1 beats a BM25 #1 when each ranks the other last.
    assert rules_dense.fuse([1, 0], [0, 1])[0] == 0


def test_doc_texts_prefix_sub_rules_with_their_short_ancestor_headings():
    docs = [("rule", n, t) for n, t in RULES.items()] + [("glossary", "hand", "hand. A zone.")]
    texts = dict(zip([d[1] for d in docs], rules_dense.doc_texts(docs, RULES)))
    assert texts["402.2a"].startswith("Hand: ")  # 402 heading; 402.2 is a full rule, not a heading
    assert texts["306.6"] == "Planeswalkers: Planeswalkers can be attacked."
    assert texts["306"] == "Planeswalkers"
    assert texts["hand"] == "hand. A zone."


def test_corpus_key_changes_with_any_document():
    a = rules_dense.corpus_key(["x", "y"])
    assert a == rules_dense.corpus_key(["x", "y"])
    assert a != rules_dense.corpus_key(["x", "y!"])


def test_off_switch_gives_the_plain_bm25_ranking(monkeypatch):
    monkeypatch.setenv("MYTHGAUNTLET_RULES_DENSE", "off")
    index = rulings.RulesSearchIndex(_cr())
    assert not index.dense_enabled and not index.warm()
    assert [r.ref for r in index.search("maximum hand size", k=2)][0] == "402.2"


def test_fused_search_finds_a_paraphrase_bm25_cannot(monkeypatch):
    monkeypatch.setenv("MYTHGAUNTLET_RULES_DENSE", "on")
    monkeypatch.setattr(rules_dense, "enabled", lambda: True)
    index = rulings.RulesSearchIndex(_cr())
    refs = [d[1] for d in index._docs]
    vecs = np.eye(len(refs), dtype=np.float32)  # one axis per document
    monkeypatch.setattr(rules_dense, "vectors", lambda texts, wait=False, start=True: vecs)
    monkeypatch.setattr(rules_dense, "query_vector",
                        lambda q: vecs[refs.index("306.6")])  # "the model" maps it to 306.6
    question = "is a walker legal to swing at"  # no word in common with 306.6
    assert "306.6" not in [r.ref for r in rulings.RulesSearchIndex(
        _cr(), dense=False).search(question, k=3)]
    assert "306.6" in [r.ref for r in index.search(question, k=3)]


def test_vectors_unavailable_means_bm25_order(monkeypatch):
    monkeypatch.setattr(rules_dense, "enabled", lambda: True)
    index = rulings.RulesSearchIndex(_cr())
    monkeypatch.setattr(rules_dense, "vectors", lambda texts, wait=False, start=True: None)
    plain = rulings.RulesSearchIndex(_cr(), dense=False)
    q = "maximum hand size seven cards"
    assert [r.ref for r in index.search(q)] == [r.ref for r in plain.search(q)]
