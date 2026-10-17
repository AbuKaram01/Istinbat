# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from istinbat.core.sentences import split_sentences


def test_arabic_sentences_split_on_arabic_and_latin_punctuation():
    text = "جملة طويلة بما يكفي هنا. وجملة أخرى طويلة أيضا؟ وثالثة طويلة كذلك؛ ورابعة"
    assert split_sentences(text, 10) == [
        "جملة طويلة بما يكفي هنا.",
        "وجملة أخرى طويلة أيضا؟",
        "وثالثة طويلة كذلك؛ ورابعة",
    ]


def test_english_sentences_split_after_terminal_punctuation():
    text = "Neural networks learn from data. They are used widely! Is that clear? Yes it is."
    assert split_sentences(text, 10) == [
        "Neural networks learn from data.",
        "They are used widely!",
        "Is that clear?",
        "Yes it is.",
    ]


def test_dots_inside_numbers_and_names_are_not_boundaries():
    text = "Pi is about 3.14159 in value. The file node.js runs the server."
    assert split_sentences(text, 10) == ["Pi is about 3.14159 in value.", "The file node.js runs the server."]


def test_short_fragments_are_merged_instead_of_dropped():
    assert split_sentences("Yes. That works well for us.", 10) == ["Yes. That works well for us."]
    assert split_sentences("This is a long enough sentence. OK.", 10) == ["This is a long enough sentence. OK."]


def test_text_without_punctuation_stays_one_sentence():
    assert split_sentences("نص بلا علامات ترقيم على الإطلاق", 10) == ["نص بلا علامات ترقيم على الإطلاق"]


def test_closing_quotes_stay_with_their_sentence():
    assert split_sentences('He said "stop now." Then he left the room.', 10) == [
        'He said "stop now."',
        "Then he left the room.",
    ]


def test_blank_text_yields_nothing():
    assert split_sentences("", 10) == [] and split_sentences("   ", 10) == []
