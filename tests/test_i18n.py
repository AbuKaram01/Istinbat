# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import re

import pytest

from istinbat.core import AskStatus, Language, ProgressKey, Stage
from istinbat.i18n import Translator, load_catalog

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text))


def test_catalogs_define_the_same_keys():
    english, arabic = load_catalog(Language.EN), load_catalog(Language.AR)
    assert set(english) == set(arabic)


def test_translations_use_the_same_placeholders_as_english():
    english, arabic = load_catalog(Language.EN), load_catalog(Language.AR)
    mismatched = [key for key in english if placeholders(english[key]) != placeholders(arabic[key])]
    assert mismatched == []


def test_every_core_enum_value_has_a_translation():
    catalog = load_catalog(Language.EN)
    keys = (
        [f"progress.{key.value}" for key in ProgressKey]
        + [f"stage.{stage.value}" for stage in Stage]
        + [f"status.{status.value}" for status in AskStatus if status is not AskStatus.OK]
    )
    assert [key for key in keys if key not in catalog] == []


def test_english_is_the_default_language():
    assert Translator().language is Language.EN and not Translator().is_rtl


def test_language_can_be_switched_at_runtime():
    translate = Translator()
    assert translate("progress.load.ready") == "Ready"
    translate.set_language(Language.AR)
    assert translate("progress.load.ready") == "جاهز" and translate.is_rtl


def test_placeholders_are_filled():
    translate = Translator()
    assert translate("progress.index.encoding", book="Book", done=3, total=9) == "Encoding “Book” (3/9)"


def test_unknown_keys_fall_back_to_the_key_itself():
    assert Translator()("no.such.key") == "no.such.key"


@pytest.mark.parametrize("language", list(Language))
def test_no_catalog_entry_is_empty(language):
    assert all(text.strip() for text in load_catalog(language).values())


def test_every_key_the_interface_uses_exists_in_both_catalogs():
    import pathlib

    english, arabic = load_catalog(Language.EN), load_catalog(Language.AR)
    pattern = re.compile(
        r'"((?:chat|sidebar|library|prefs|scope|menu|language|loading|error|notify|close|about|dialog|time|duration|welcome)'
        r'\.[a-z0-9_.]+)"'
    )
    used = set()
    for path in pathlib.Path("src/istinbat/gui").glob("*.py"):
        used |= set(pattern.findall(path.read_text(encoding="utf-8")))
    used |= {f"prefs.data.{name}.subtitle" for name in ("export", "rebuild", "delete")}
    assert sorted(key for key in used if key not in english) == []
    assert sorted(key for key in used if key not in arabic) == []
