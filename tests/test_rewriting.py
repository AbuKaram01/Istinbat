# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from conftest import OneShotLLM

from istinbat.core import ChatHistory, MemoryConfig, RewriteMode
from istinbat.core.rewriting import needs_rewrite, rewrite_question
from istinbat.core.safety import PromptGuard

GUARD = PromptGuard.new()
SHORT = "وإيه أنواعها؟"
LONG = "ما هي أنواع الأشعة المستخدمة في تشخيص الأمراض الباطنية؟"


def history():
    chat = ChatHistory()
    chat.add("ما هو اسم الكتاب؟", "أساسيات الحاسوب")
    return chat


def config(mode=RewriteMode.ALWAYS):
    return MemoryConfig(rewrite_mode=mode)


def test_needs_rewrite_by_mode_and_history():
    assert not needs_rewrite(SHORT, None, config())
    assert not needs_rewrite(SHORT, ChatHistory(), config())
    assert needs_rewrite(LONG, history(), config(RewriteMode.ALWAYS))
    assert not needs_rewrite(LONG, history(), config(RewriteMode.AUTO))
    assert needs_rewrite(SHORT, history(), config(RewriteMode.AUTO))
    assert not needs_rewrite(SHORT, history(), config(RewriteMode.OFF))


def test_rewrite_strips_the_label_and_keeps_the_first_line():
    llm = OneShotLLM("السؤال: ما هي أنواع الأشعة؟\nشرح زائد")
    assert rewrite_question(SHORT, history(), config(), llm, GUARD) == "ما هي أنواع الأشعة؟"


def test_rewrite_restores_english_terms_the_model_dropped():
    llm = OneShotLLM("ما هي المعلومات؟")
    rewritten = rewrite_question("ما هي المعلومات Information؟", history(), config(), llm, GUARD)
    assert "Information" in rewritten and "المعلومات" in rewritten


def test_rewrite_does_not_duplicate_english_terms_it_kept():
    llm = OneShotLLM("ما هي أنواع Information؟")
    rewritten = rewrite_question("وإيه أنواعها؟ Information", history(), config(), llm, GUARD)
    assert rewritten.count("Information") == 1


def test_an_english_follow_up_keeps_the_rewrite_without_the_words_it_replaced():
    llm = OneShotLLM("How does a hash table resolve collisions?")
    rewritten = rewrite_question("How does it resolve collisions?", history(), config(), llm, GUARD)
    assert rewritten == "How does a hash table resolve collisions?"          # No stray "it" appended.


def test_rewrite_falls_back_to_the_original_on_rambling_or_empty_output():
    assert rewrite_question("وبعدين؟", history(), config(), OneShotLLM("x" * 500), GUARD) == "وبعدين؟"
    assert rewrite_question("وبعدين؟", history(), config(), OneShotLLM(""), GUARD) == "وبعدين؟"
