# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Defences against prompt injection.

Two kinds of text reach the model that nobody on the project controls: the books
(an indexed file may contain instructions written for the model) and the user's
questions. Both are untrusted. No prompt can make a language model obey rules with
certainty, so the protection is layered:

1. ``neutralize`` strips what could forge structure: chat-template control tokens,
   look-alikes of our own delimiters, invisible characters and control characters.
2. ``PromptGuard`` gives every request unguessable delimiters and a secret canary.
3. ``check_answer`` inspects what the model produced before the user sees it: it
   withholds an answer that leaks the instructions (whole lines, or any run of six
   words) or the canary, and removes links that the sources never contained.

The model's behaviour itself is measured with ``scripts/injection_check.py``.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass

_NONCE_BYTES = 6
_CANARY_BYTES = 8
_MIN_PROTECTED_LINE = 24
_COPIED_PHRASE_WORDS = 6   # This many consecutive words of the instructions in an answer count as a leak.

# Invisible or direction-changing characters that can hide or spoof text:
# Unicode "tag" characters (invisible ASCII smuggling), bidirectional overrides and isolates,
# zero-width space, word joiner and the byte-order mark. ZWNJ and ZWJ are kept: scripts need them.
_INVISIBLE = re.compile("[\u200b\u2060\ufeff\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Control tokens of common chat templates (<start_of_turn>, <|im_start|>, <bos>, ...), role
# tags, and the names of our own delimiters, including the per-request suffix.
_ANGLE_TOKEN = re.compile(
    r"<\s*/?\s*(?:"
    r"\|[^<>\n]{1,40}\|"
    r"|(?:start|end)_of_[a-z_]+"
    r"|(?:bos|eos|pad|unk|mask|s)"
    r"|unused\d+"
    r"|(?:system|user|assistant|model|developer|tool|context|sources?|question|conversation|history"
    r"|instructions?|new_question)[\w\-]*"
    r")\s*>",
    re.IGNORECASE,
)
_BRACKET_TOKEN = re.compile(r"\[\s*/?\s*(?:INST|SYS)\s*\]|<<\s*/?\s*SYS\s*>>", re.IGNORECASE)
_BRACKET_SWAPS = str.maketrans({"<": "‹", ">": "›", "[": "⟦", "]": "⟧"})

_WORD = re.compile(r"\w+")
_URL = re.compile(r"(?:https?://|mailto:)[^\s<>()\[\]\"'`]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?،؛"
_CODE_FENCE = re.compile(r"(```.*?```)", re.DOTALL)
_INLINE_LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>", re.IGNORECASE)


def strip_invisible(text: str) -> str:
    """Remove invisible and direction-spoofing characters (used on the model's output too)."""
    return _INVISIBLE.sub("", text)


def neutralize(text: str) -> str:
    """Make untrusted text safe to place inside a prompt without changing what a person reads.

    Control tokens and delimiter look-alikes keep their words but lose their angle or
    square brackets, so they can no longer be mistaken for structure by the model or
    by the tokenizer. Ordinary text, code and Arabic are left untouched.
    """
    text = _CONTROL.sub("", strip_invisible(text))

    def defang(match: re.Match[str]) -> str:
        return match.group().translate(_BRACKET_SWAPS)

    return _BRACKET_TOKEN.sub(defang, _ANGLE_TOKEN.sub(defang, text))


@dataclass(frozen=True)
class PromptGuard:
    """Secrets that live for a single request.

    ``nonce`` is part of every delimiter tag, so text inside a book cannot close a
    block early: it would have to guess the random suffix. ``canary`` is a confidential
    token placed only in the system prompt; if it ever shows up in an answer, the
    instructions leaked.
    """

    nonce: str
    canary: str

    @classmethod
    def new(cls) -> PromptGuard:
        return cls(secrets.token_hex(_NONCE_BYTES), secrets.token_hex(_CANARY_BYTES))

    def tag(self, name: str) -> str:
        """The delimiter tag name for ``name`` in this request, e.g. ``sources_3f9a1c02b7d4``."""
        return f"{name}_{self.nonce}"


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def protected_lines(*prompts: str, exempt: Iterable[str] = ()) -> list[str]:
    """Lines of the instructions that must never appear in an answer.

    ``exempt`` lists sentences the model is *supposed* to say (the fixed refusal): they are
    cut out first, so using one is never mistaken for a leak.
    """
    lines = []
    for prompt in prompts:
        for sentence in exempt:
            prompt = prompt.replace(sentence, " ")
        for line in prompt.splitlines():
            squashed = _squash(line.lstrip("0123456789.-• "))
            if len(squashed) >= _MIN_PROTECTED_LINE:
                lines.append(squashed)
    return lines


def _copies_a_phrase(answer: str, protected: list[str]) -> bool:
    """Whether the answer repeats ``_COPIED_PHRASE_WORDS`` consecutive words of any protected line.

    Catches partial copies that a whole-line comparison misses, such as the first half of a rule.
    """
    spoken = f" {' '.join(_WORD.findall(answer.casefold()))} "
    size = _COPIED_PHRASE_WORDS
    for line in protected:
        words = _WORD.findall(line)
        for start in range(len(words) - size + 1):
            if f" {' '.join(words[start:start + size])} " in spoken:
                return True
    return False


def leaks_instructions(answer: str, guard: PromptGuard, protected: list[str]) -> bool:
    """Whether ``answer`` exposes the canary, a delimiter name or any part of the instructions."""
    squashed = _squash(answer)
    if guard.canary in squashed or guard.nonce in squashed:
        return True
    return any(line in squashed for line in protected) or _copies_a_phrase(answer, protected)


def allowed_urls(*texts: str) -> frozenset[str]:
    """Every URL written in the given texts (the sources and the question)."""
    return frozenset(_normalize_url(url) for text in texts for url in _URL.findall(text))


def _normalize_url(url: str) -> str:
    return url.rstrip(_TRAILING_PUNCTUATION).casefold()


def restrict_links(answer: str, allowed: frozenset[str]) -> str:
    """Remove links and images that point somewhere the sources never mentioned.

    A model steered by an injected instruction could add a phishing link. A link survives
    only if its URL is written in the sources or in the question; otherwise just its text
    is kept. Fenced code blocks are left alone.
    """

    def inline(match: re.Match[str]) -> str:
        _bang, text, url = match.groups()
        if _normalize_url(url) in allowed:
            return match.group()
        return text if text else ""  # An image or link with no label disappears.

    def autolink(match: re.Match[str]) -> str:
        return match.group() if _normalize_url(match.group(1)) in allowed else ""

    parts = _CODE_FENCE.split(answer)
    for index in range(0, len(parts), 2):  # Even parts are outside code fences.
        parts[index] = _AUTOLINK.sub(autolink, _INLINE_LINK.sub(inline, parts[index]))
    return "".join(parts)


@dataclass(frozen=True)
class CheckedAnswer:
    text: str
    blocked: bool


def check_answer(
    answer: str,
    guard: PromptGuard,
    protected: list[str],
    allowed: frozenset[str],
) -> CheckedAnswer:
    """Inspect the model's answer before it is shown or stored.

    Invisible characters are removed. An answer that leaks the instructions is blocked
    outright (its text is dropped); otherwise unapproved links are removed.
    """
    cleaned = strip_invisible(answer)
    if leaks_instructions(cleaned, guard, protected):
        return CheckedAnswer("", blocked=True)
    return CheckedAnswer(restrict_links(cleaned, allowed), blocked=False)
