# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from conftest import FakeCollection, FakeEmbedder, FakeReranker

from istinbat.core.retrieval import Candidate, Retriever, build_context, reciprocal_rank_fusion

DOCS = [
    ("a", "الحاسوب جهاز يعالج البيانات"),
    ("b", "الحاسوب الشخصي يستخدم في المكاتب"),
    ("c", "الطبخ فن تحضير الطعام"),
]


def make_retriever(docs=DOCS):
    collection = FakeCollection()
    for index, (source, text) in enumerate(docs):
        collection.upsert([str(index)], [[0]], [text], [{"source": source, "norm_text": text}])
    retriever = Retriever(collection=collection, embedder=FakeEmbedder(), reranker=FakeReranker())
    retriever.refresh()
    return retriever


def test_empty_store_yields_empty_retriever():
    retriever = Retriever(FakeCollection(), FakeEmbedder(), FakeReranker())
    assert retriever.refresh() == 0 and retriever.is_empty
    assert retriever.bm25_search("حاسوب", 3) == [] and retriever.vector_search([[0]], 3) == []
    assert retriever.books() == []


def test_bm25_ranks_the_matching_chunk_first_and_drops_non_matches():
    hits = make_retriever().bm25_search("الحاسوب", 3)
    assert hits[0] == DOCS[0][1] and DOCS[2][1] not in hits
    assert make_retriever().bm25_search("؟!", 3) == []


def test_vector_search_clamps_the_limit_to_the_store_size():
    assert len(make_retriever().vector_search([[0]], 50)) == 3


def test_rerank_orders_by_score_and_attaches_it():
    retriever = make_retriever()
    top = retriever.rerank("question", retriever.to_candidates([text for _, text in DOCS]), 2)
    assert len(top) == 2 and top[0].score >= top[1].score
    assert top[0].text == max((text for _, text in DOCS), key=len)
    assert retriever.rerank("question", [], 2) == []


def test_to_candidates_tolerates_texts_missing_from_the_index():
    candidate = make_retriever().to_candidates(["unindexed passage text"])[0]
    assert candidate.source == "unknown" and candidate.normalized_text


def test_rank_fusion_rewards_agreement():
    assert reciprocal_rank_fusion([["a", "b"], ["b", "c"]], 60)[0] == "b"


def test_build_context_truncates_the_overflowing_chunk_with_an_ellipsis():
    candidates = [Candidate("x" * 500, "s", ""), Candidate("y" * 500, "s", "")]
    context = build_context(candidates, 700)
    assert context.endswith("…") and len(context) <= 705
    assert build_context(candidates, 5000).count("📘") == 2


# -- Search scope -------------------------------------------------------------

def test_books_lists_unique_sorted_names():
    assert make_retriever().books() == ["a", "b", "c"]


def test_bm25_scope_limits_results_to_the_selected_books():
    retriever = make_retriever()
    assert len(retriever.bm25_search("الحاسوب", 5)) == 2
    assert retriever.bm25_search("الحاسوب", 5, books=["b"]) == [DOCS[1][1]]
    assert retriever.bm25_search("الحاسوب", 5, books=["c"]) == []
    assert retriever.bm25_search("الحاسوب", 5, books=[]) == []


def test_vector_scope_limits_results_to_the_selected_books():
    retriever = make_retriever()
    assert len(retriever.vector_search([[0]], 5)) == 3
    assert retriever.vector_search([[0]], 5, books=["a", "c"]) == [DOCS[0][1], DOCS[2][1]]
    assert retriever.vector_search([[0]], 5, books=["ghost"]) == []
    assert retriever.vector_search([[0]], 5, books=[]) == []


# -- Bilingual retrieval --------------------------------------------------------

ENGLISH_DOCS = [
    ("en-book", "Neural networks learn patterns from large datasets"),
    ("en-book", "Cooking pasta requires boiling water and salt"),
    ("ar-book", "الحاسوب جهاز يعالج البيانات"),
]


def test_keyword_search_finds_english_passages_regardless_of_case_and_word_form():
    retriever = make_retriever(ENGLISH_DOCS)
    assert retriever.bm25_search("NEURAL NETWORK", 3) == [ENGLISH_DOCS[0][1]]
    assert retriever.bm25_search("dataset", 3) == [ENGLISH_DOCS[0][1]]


def test_keyword_search_still_finds_arabic_passages_in_a_mixed_library():
    retriever = make_retriever(ENGLISH_DOCS)
    assert retriever.bm25_search("الحاسوب", 3) == [ENGLISH_DOCS[2][1]]


def test_build_context_labels_sources_in_the_answer_language():
    from istinbat.core import ContentLanguage

    candidates = [Candidate("some text", "Book", "")]
    assert build_context(candidates, 500, ContentLanguage.EN).startswith("📘 [Source: Book]")
    assert build_context(candidates, 500, ContentLanguage.AR).startswith("📘 [المصدر: Book]")
