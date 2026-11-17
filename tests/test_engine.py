# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

from conftest import BOOK_A, FakeCollection, FakeEmbedder, FakeLLM, FakeReranker

from istinbat.core import AnswerLanguage, AskStatus, ChatHistory, ContentLanguage, Engine, Stage, StageEvent
from istinbat.core.retrieval import Retriever


def test_first_question_uses_one_llm_call_and_returns_sources(indexed_engine):
    result = indexed_engine.ask("ما هو الحاسوب؟", ChatHistory())

    assert len(indexed_engine.llm.calls) == 1
    assert result.status is AskStatus.OK and result.answer == "a test answer"
    assert result.standalone == result.question
    assert result.sources and all(source.book and source.text for source in result.sources)
    assert set(result.timings) == {Stage.VECTOR, Stage.BM25, Stage.RERANK, Stage.LLM}
    assert (result.prompt_tokens, result.completion_tokens) == (10, 3)
    assert result.total_seconds == sum(result.timings.values())


def test_follow_up_is_rewritten_and_history_is_sent_to_the_model(indexed_engine):
    history = ChatHistory()
    indexed_engine.ask("ما هو الحاسوب؟", history)
    result = indexed_engine.ask("وإيه أنواعه؟", history)

    assert result.standalone == "standalone question" and Stage.REWRITE in result.timings
    roles = [message["role"] for message in indexed_engine.llm.calls[-1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert history.turns[-1][0] == "standalone question"


def test_without_history_there_is_no_rewrite(indexed_engine):
    result = indexed_engine.ask("ما هو الحاسوب؟")
    assert Stage.REWRITE not in result.timings and len(indexed_engine.llm.calls) == 1


def test_stage_events_arrive_in_order_as_start_then_done(indexed_engine):
    events = []
    history = ChatHistory()
    history.add("old question", "old answer")
    indexed_engine.ask("وإيه بعده؟", history, on_stage=lambda stage, event, seconds: events.append((stage, event)))

    expected = [Stage.REWRITE, Stage.VECTOR, Stage.BM25, Stage.RERANK, Stage.LLM]
    assert [stage for stage, event in events if event is StageEvent.START] == expected
    assert [stage for stage, event in events if event is StageEvent.DONE] == expected


def test_streaming_delivers_tokens_that_match_the_final_answer(indexed_engine):
    tokens = []
    result = indexed_engine.ask("ما هو الحاسوب؟", on_token=tokens.append)
    assert "".join(tokens).strip() == result.answer
    assert result.first_token_seconds is not None


def test_cancelling_before_start_skips_the_model(indexed_engine):
    result = indexed_engine.ask("ما هو الحاسوب؟", cancel=lambda: True)
    assert result.status is AskStatus.CANCELLED and result.cancelled
    assert result.answer == "" and indexed_engine.llm.calls == []


def test_cancelling_mid_stream_keeps_the_partial_answer_and_skips_history(indexed_engine):
    history, tokens = ChatHistory(), []
    result = indexed_engine.ask("ما هو الحاسوب؟", history, on_token=tokens.append, cancel=lambda: len(tokens) >= 1)
    assert result.cancelled and result.answer and history.turns == []


def test_empty_index_reports_no_books_without_calling_the_model(settings):
    retriever = Retriever(FakeCollection(), FakeEmbedder(), FakeReranker())
    retriever.refresh()
    engine = Engine(settings, retriever, FakeLLM())

    result = engine.ask("any question?")
    assert result.status is AskStatus.NO_BOOKS and result.answer == "" and engine.llm.calls == []


def test_scope_restricts_the_sources(indexed_engine):
    result = indexed_engine.ask("ما هي المعلومات؟", books=["information-book"])
    assert result.sources and {source.book for source in result.sources} == {"information-book"}


def test_scope_without_matching_books_skips_the_model(indexed_engine):
    result = indexed_engine.ask("ما هي المعلومات؟", books=["missing-book"])
    assert result.status is AskStatus.NO_RESULTS and result.sources == []
    assert indexed_engine.llm.calls == []


def test_books_lists_the_indexed_books(indexed_engine):
    assert indexed_engine.books() == ["computer-book", "information-book"]


def test_index_library_refreshes_the_search_index(settings, write_book):
    retriever = Retriever(FakeCollection(), FakeEmbedder(), FakeReranker())
    retriever.refresh()
    engine = Engine(settings, retriever, FakeLLM())
    assert retriever.is_empty

    write_book("a", BOOK_A)
    report = engine.index_library()
    assert report.new_books == 1 and not retriever.is_empty
    assert engine.ask("ما هو الحاسوب؟").sources


def test_rebuild_index_reindexes_and_refreshes(settings, write_book):
    collection = FakeCollection()
    retriever = Retriever(collection, FakeEmbedder(), FakeReranker())
    engine = Engine(settings, retriever, FakeLLM())
    write_book("a", BOOK_A)
    engine.index_library()
    chunk_count = len(collection.rows)

    report = engine.rebuild_index()
    assert report.new_books == 1 and len(collection.rows) == chunk_count and not retriever.is_empty


def test_removing_a_book_refreshes_the_search_index(indexed_engine, settings):
    path = os.path.join(settings.paths.books_dir, "computer-book.txt")

    assert indexed_engine.remove_book(path) is True

    assert indexed_engine.books() == ["information-book"]
    result = indexed_engine.ask("ما هو الحاسوب؟")
    assert {source.book for source in result.sources} == {"information-book"}


def test_removing_the_last_book_leaves_an_empty_index_that_says_so(indexed_engine, settings):
    for name in ("computer-book", "information-book"):
        indexed_engine.remove_book(os.path.join(settings.paths.books_dir, f"{name}.txt"))

    assert indexed_engine.books() == [] and indexed_engine.ask("سؤال").status is AskStatus.NO_BOOKS


def test_removing_a_book_that_is_not_indexed_leaves_the_search_index_alone(indexed_engine, settings):
    assert indexed_engine.remove_book(os.path.join(settings.paths.books_dir, "other.txt")) is False
    assert indexed_engine.books() == ["computer-book", "information-book"]


# -- Answer language ----------------------------------------------------------

def _answer_system_prompt(engine):
    answer_call = [call for call in engine.llm.calls if call["messages"][0]["role"] == "system"][-1]
    return answer_call["messages"][0]["content"], answer_call["messages"][-1]["content"]


def test_an_english_question_gets_the_english_prompt_automatically(indexed_engine):
    result = indexed_engine.ask("What is a computer?")
    system, user_message = _answer_system_prompt(indexed_engine)
    assert result.answer_language is ContentLanguage.EN
    assert "in English" in system and user_message.startswith("<sources_")


def test_an_arabic_question_gets_the_arabic_prompt_automatically(indexed_engine):
    result = indexed_engine.ask("ما هو الحاسوب؟")
    system, user_message = _answer_system_prompt(indexed_engine)
    assert result.answer_language is ContentLanguage.AR
    assert "باللغة العربية" in system and user_message.startswith("<sources_")


def test_a_forced_answer_language_overrides_the_question_language(indexed_engine):
    indexed_engine.settings.memory.answer_language = AnswerLanguage.ENGLISH
    result = indexed_engine.ask("ما هو الحاسوب؟")
    system, _ = _answer_system_prompt(indexed_engine)
    assert result.answer_language is ContentLanguage.EN and "in English" in system

    indexed_engine.settings.memory.answer_language = AnswerLanguage.ARABIC
    assert indexed_engine.ask("What is a computer?").answer_language is ContentLanguage.AR


def test_an_english_follow_up_is_rewritten_with_the_english_rewrite_prompt(indexed_engine):
    history = ChatHistory()
    history.add("What is a computer?", "A machine.")
    indexed_engine.ask("and its types?", history)
    rewrite_call = indexed_engine.llm.calls[0]["messages"][0]["content"]
    assert rewrite_call.startswith("Your only task: rewrite the new question")
    assert "Question: What is a computer?" in rewrite_call
