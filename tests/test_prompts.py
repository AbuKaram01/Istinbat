# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import re

from istinbat.core import ContentLanguage
from istinbat.core.prompts import (
    answer_prompt,
    build_transcript,
    pack_for,
    rewrite_prompt,
    source_entry,
    system_prompt,
)
from istinbat.core.safety import PromptGuard

ARABIC_LETTER = re.compile(r"[\u0600-\u06FF]")
GUARD = PromptGuard(nonce="aaaa1111bbbb", canary="0123456789abcdef")
EN, AR = ContentLanguage.EN, ContentLanguage.AR


def test_the_english_prompts_contain_no_arabic_instructions():
    for text in (system_prompt(EN, GUARD), pack_for(EN).reminder, pack_for(EN).rewrite_instructions):
        assert not ARABIC_LETTER.search(text.replace("Arabic", ""))


def test_each_language_demands_its_own_answer_language_and_markdown():
    assert "in English" in system_prompt(EN, GUARD) and "Markdown" in system_prompt(EN, GUARD)
    assert "باللغة العربية" in system_prompt(AR, GUARD) and "Markdown" in system_prompt(AR, GUARD)


def test_the_fixed_refusal_sentence_is_in_the_answer_language_and_used_for_every_decline():
    sentences = ((EN, "The answer is not available in the sources."), (AR, "الإجابة غير متوفرة في المصادر."))
    for language, sentence in sentences:
        assert pack_for(language).refusal == sentence
        assert system_prompt(language, GUARD).count(sentence) >= 2         # Leaks and unanswerable questions.
        assert "{refusal}" in pack_for(language).reminder      # Filled in with the sentence per request.


def test_the_system_prompt_states_the_security_rules_before_the_answer_rules():
    for language, marker in ((EN, "SECURITY RULES"), (AR, "قواعد الأمان")):
        prompt = system_prompt(language, GUARD)
        assert prompt.index(marker) < prompt.index("ANSWER RULES" if language is EN else "قواعد الإجابة")


def test_the_english_rules_cover_each_attack_class():
    prompt = system_prompt(EN, GUARD).lower()
    for phrase in (
        "untrusted data", "never instructions", "ignore the previous instructions", "never reveal",
        "confidential token", "never change your role", "not a general chatbot", "links, urls or images",
        "reply exactly",
    ):
        assert phrase in prompt, phrase


def test_the_arabic_rules_cover_each_attack_class():
    prompt = system_prompt(AR, GUARD)
    for phrase in ("بيانات غير موثوقة", "تجاهل التعليمات السابقة", "لا تكشف", "الرمز السري", "لست روبوت محادثة عاماً",
                   "روابط أو صوراً", "الأمان"):
        assert phrase in prompt, phrase


def test_the_secrets_and_tag_names_are_filled_in_with_no_placeholder_left_over():
    for language in (EN, AR):
        prompt = system_prompt(language, GUARD)
        assert GUARD.canary in prompt and "<sources_aaaa1111bbbb>" in prompt and "<question_aaaa1111bbbb>" in prompt
        assert not re.search(r"\{[a-z_]+\}", prompt)


def test_the_user_message_wraps_untrusted_content_in_tags_and_ends_with_a_reminder():
    message = answer_prompt("What is X?", "CTX", EN, GUARD)[-1]["content"]
    assert message.startswith("<sources_aaaa1111bbbb>\nCTX\n</sources_aaaa1111bbbb>")
    assert "<question_aaaa1111bbbb>\nWhat is X?\n</question_aaaa1111bbbb>" in message
    reminder = message.split("\n\n")[-1]                                   # The reminder is the last paragraph.
    assert pack_for(EN).refusal in reminder and "<sources_aaaa1111bbbb>" in reminder
    arabic = answer_prompt("ما هو X؟", "CTX", AR, GUARD)[-1]["content"]
    assert pack_for(AR).refusal in arabic.split("\n\n")[-1] and "<sources_aaaa1111bbbb>" in arabic


def test_answer_prompt_places_history_between_system_and_question():
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    roles = [m["role"] for m in answer_prompt("q2", "c", EN, GUARD, history)]
    assert roles == ["system", "user", "assistant", "user"]


def test_transcript_and_rewrite_prompt_follow_the_language_and_use_tags():
    transcript = build_transcript([("What is X?", "X is Y.")], EN)
    assert transcript == "Question: What is X?\nAnswer: X is Y."
    content = rewrite_prompt("and its types?", transcript, EN, GUARD)[0]["content"]
    assert "<conversation_aaaa1111bbbb>" in content and "<new_question_aaaa1111bbbb>\nand its types?\n" in content
    assert "untrusted data" in content
    assert build_transcript([("س", "ج")], AR) == "السؤال: س\nالإجابة: ج"


def test_source_labels_follow_the_language():
    assert source_entry("Book", "text", EN) == "📘 [Source: Book]\ntext"
    assert source_entry("كتاب", "نص", AR) == "📘 [المصدر: كتاب]\nنص"
