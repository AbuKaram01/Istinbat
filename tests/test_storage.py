# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import pytest

from istinbat.core import AskResult, Source, Stage
from istinbat.storage import ConversationStore, ExportLabels


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    return ConversationStore(":memory:", clock=clock)


def test_new_conversations_are_untitled_and_listed_newest_first(store, clock):
    first = store.create_conversation()
    clock.now += 10
    second = store.create_conversation("Named")
    assert first.title == "" and first.scope is None
    assert [c.id for c in store.list_conversations()] == [second.id, first.id]


def test_first_question_titles_the_conversation_and_bumps_activity(store, clock):
    first, second = store.create_conversation(), store.create_conversation()
    clock.now += 50
    store.add_turn(first.id, "ما هي المعلومات؟", "ما هي المعلومات؟", "answer")

    assert store.get_conversation(first.id).title == "ما هي المعلومات؟"
    assert [c.id for c in store.list_conversations()] == [first.id, second.id]
    store.add_turn(first.id, "another question", "another question", "answer")
    assert store.get_conversation(first.id).title == "ما هي المعلومات؟"


def test_long_titles_are_truncated_and_rename_works(store):
    conversation = store.create_conversation()
    store.add_turn(conversation.id, "q" * 100, "q" * 100, "a")
    assert len(store.get_conversation(conversation.id).title) <= 41
    store.rename_conversation(conversation.id, "  New name  ")
    assert store.get_conversation(conversation.id).title == "New name"


def test_scope_round_trips(store):
    conversation = store.create_conversation(scope=["Book 1", "Book 2"])
    assert store.get_conversation(conversation.id).scope == ["Book 1", "Book 2"]
    store.set_scope(conversation.id, None)
    assert store.get_conversation(conversation.id).scope is None
    store.set_scope(conversation.id, [])
    assert store.get_conversation(conversation.id).scope == []


def test_turns_keep_order_sources_and_timing(store):
    conversation = store.create_conversation()
    sources = [{"book": "b", "text": "t", "score": 0.5}]
    store.add_turn(conversation.id, "q1", "q1", "a1", sources, 3.5)
    store.add_turn(conversation.id, "q2", "q2 standalone", "a2")

    turns = store.turns(conversation.id)
    assert [turn.question for turn in turns] == ["q1", "q2"]
    assert turns[0].sources == sources and turns[0].seconds == 3.5
    assert turns[1].sources == [] and turns[1].standalone == "q2 standalone"


def test_history_for_uses_standalone_questions_of_the_last_turns(store):
    conversation = store.create_conversation()
    for i in range(5):
        store.add_turn(conversation.id, f"q{i}", f"standalone{i}", f"a{i}")
    assert store.history_for(conversation.id, max_turns=2).turns == [("standalone3", "a3"), ("standalone4", "a4")]


def test_add_result_stores_an_ask_result(store):
    conversation = store.create_conversation()
    result = AskResult(
        question="q", standalone="standalone", answer="answer",
        sources=[Source("book", "text", 0.9)], timings={Stage.LLM: 2.0, Stage.RERANK: 1.0},
    )
    store.add_result(conversation.id, result)

    turn = store.turns(conversation.id)[0]
    assert (turn.question, turn.standalone, turn.answer, turn.seconds) == ("q", "standalone", "answer", 3.0)
    assert turn.sources == [{"book": "book", "text": "text", "score": 0.9}]


def test_deleting_a_conversation_cascades_to_its_turns(store):
    first, second = store.create_conversation(), store.create_conversation()
    store.add_turn(first.id, "q", "q", "a")
    store.add_turn(second.id, "q", "q", "a")
    store.delete_conversation(first.id)

    assert store.get_conversation(first.id) is None and store.turns(first.id) == []
    assert (store.stats().conversations, store.stats().turns) == (1, 1)


def test_delete_all_returns_the_count_and_clears_everything(store):
    for _ in range(3):
        store.add_turn(store.create_conversation().id, "q", "q", "a")
    assert store.delete_all() == 3
    assert (store.stats().conversations, store.stats().turns) == (0, 0)


def test_purge_uses_last_activity_and_ignores_non_positive_days(store, clock):
    old, recent = store.create_conversation(), store.create_conversation()
    clock.now += 40 * 86_400
    store.add_turn(recent.id, "q", "q", "a")

    assert store.purge_older_than(0) == 0 and store.purge_older_than(-5) == 0
    assert store.purge_older_than(30) == 1
    assert store.get_conversation(old.id) is None and store.get_conversation(recent.id) is not None


def test_export_markdown_contains_the_whole_conversation(store):
    conversation = store.create_conversation(scope=["Book 1"])
    store.add_turn(
        conversation.id, "ما هي المعلومات؟", "ما هي المعلومات؟", "نتائج معالجة البيانات.",
        [{"book": "Book 1", "text": "x", "score": 1.0}, {"book": "Book 1", "text": "y", "score": 0.5}],
    )
    markdown = store.export_markdown(conversation.id)

    assert markdown.startswith("# ما هي المعلومات؟")
    assert "**Search scope:** Book 1" in markdown
    assert "### Question" in markdown and "### Answer" in markdown and "نتائج معالجة البيانات." in markdown
    assert markdown.count("**Sources:** Book 1") == 1 and markdown.endswith("\n")


def test_export_uses_localized_labels_and_untitled_placeholder(store):
    conversation = store.create_conversation()
    labels = ExportLabels(untitled="بدون عنوان", scope="النطاق", all_books="كل الكتب")
    markdown = store.export_markdown(conversation.id, labels)
    assert markdown.startswith("# بدون عنوان") and "**النطاق:** كل الكتب" in markdown


def test_missing_conversations_raise(store):
    with pytest.raises(KeyError):
        store.add_turn(999, "q", "q", "a")
    with pytest.raises(KeyError):
        store.export_markdown(999)


def test_store_persists_on_disk(tmp_path, clock):
    path = str(tmp_path / "nested" / "conversations.db")
    first = ConversationStore(path, clock=clock)
    conversation = first.create_conversation("Persistent")
    first.close()
    assert ConversationStore(path, clock=clock).get_conversation(conversation.id).title == "Persistent"


def test_a_multi_line_question_gives_a_single_line_title(store):
    conversation = store.create_conversation()
    store.add_turn(conversation.id, "What is memory?\n\nPlease answer:\n- briefly", "x", "a")
    assert store.get_conversation(conversation.id).title == "What is memory? Please answer: - briefly"
