# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from conftest import FakeLLM

from istinbat.core.generation import generate_answer

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


def test_blocking_generation_reports_token_usage():
    generation = generate_answer(FakeLLM(), MESSAGES, max_tokens=10, temperature=0)
    assert generation.text == "a test answer"
    assert (generation.prompt_tokens, generation.completion_tokens) == (10, 3)


def test_streaming_delivers_fragments_and_first_token_time():
    fragments = []
    generation = generate_answer(
        FakeLLM(answer="one two three"), MESSAGES, max_tokens=10, temperature=0, on_token=fragments.append,
    )
    assert "".join(fragments).strip() == generation.text == "one two three"
    assert generation.first_token_seconds is not None and not generation.cancelled


def test_streaming_can_be_cancelled_between_fragments():
    fragments = []
    generation = generate_answer(
        FakeLLM(answer="one two three"), MESSAGES, max_tokens=10, temperature=0,
        on_token=fragments.append, cancel=lambda: len(fragments) >= 1,
    )
    assert generation.cancelled and len(fragments) == 1
