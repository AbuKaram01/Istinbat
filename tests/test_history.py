# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from istinbat.core import ChatHistory


def test_keeps_only_the_most_recent_turns():
    history = ChatHistory(max_turns=2)
    for i in range(4):
        history.add(f"q{i}", f"a{i}")
    assert [question for question, _ in history.turns] == ["q2", "q3"]


def test_zero_turns_keeps_nothing():
    history = ChatHistory(max_turns=0)
    history.add("q", "a")
    assert history.turns == []


def test_messages_alternate_roles_and_truncate_answers():
    history = ChatHistory(answer_chars=5)
    history.add("question", "x" * 20)
    messages = history.as_messages()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "xxxxx…"


def test_from_turns_keeps_recent_and_clear_empties():
    history = ChatHistory.from_turns([("a", "1"), ("b", "2"), ("c", "3")], max_turns=2)
    assert [question for question, _ in history.turns] == ["b", "c"]
    history.clear()
    assert history.turns == [] and history.as_messages() == []
