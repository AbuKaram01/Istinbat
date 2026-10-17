# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Interface translations with runtime language switching.

Catalogs are JSON files in ``locales/`` (one flat ``key -> text`` map per
language). Keys use ``{name}`` placeholders. A key missing from the active
language falls back to English, and a key missing everywhere returns the key
itself, so a gap is visible rather than fatal.
"""

from __future__ import annotations

import json
from importlib import resources

from ..core.settings import Language

FALLBACK_LANGUAGE = Language.EN


def load_catalog(language: Language) -> dict[str, str]:
    """Read the catalog of ``language`` from the package data."""
    path = resources.files(__package__) / "locales" / f"{language.value}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class Translator:
    """Translates keys into the active language."""

    def __init__(self, language: Language = FALLBACK_LANGUAGE) -> None:
        self._catalogs = {lang: load_catalog(lang) for lang in Language}
        self._language = language

    @property
    def language(self) -> Language:
        return self._language

    @property
    def is_rtl(self) -> bool:
        return self._language.is_rtl

    def set_language(self, language: Language) -> None:
        self._language = language

    def __call__(self, key: str, **params: object) -> str:
        text = self._catalogs[self._language].get(key)
        if text is None:
            text = self._catalogs[FALLBACK_LANGUAGE].get(key, key)
        return text.format(**params) if params else text
