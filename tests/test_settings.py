# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

from istinbat.core import Language, RewriteMode, Settings, load_settings, save_settings
from istinbat.core.paths import config_dir, data_dir


def test_round_trip_preserves_values_and_enums(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.retrieval.top_sources = 2
    settings.memory.rewrite_mode = RewriteMode.OFF
    settings.app.language = Language.AR
    settings.llm.temperature = 0.5
    save_settings(settings, path)

    loaded = load_settings(path)
    assert loaded.retrieval.top_sources == 2
    assert loaded.memory.rewrite_mode is RewriteMode.OFF
    assert loaded.app.language is Language.AR
    assert loaded.llm.temperature == 0.5


def test_saved_file_is_nested_json_with_plain_enum_values(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["app"]["language"] == "en"
    assert data["memory"]["rewrite_mode"] == "always"


def test_invalid_values_unknown_keys_and_bad_enums_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "retrieval": {"top_sources": "many", "rerank_pool": 9, "nope": 1},
        "app": {"notify_on_answer": 1, "language": "fr"},
        "memory": {"rewrite_mode": "sometimes"},
        "unknown_section": {"a": 1},
    }))
    settings = load_settings(path)
    defaults = Settings()
    assert settings.retrieval.top_sources == defaults.retrieval.top_sources
    assert settings.retrieval.rerank_pool == 9
    assert settings.app.notify_on_answer is True
    assert settings.app.language is Language.EN
    assert settings.memory.rewrite_mode is RewriteMode.ALWAYS


def test_missing_or_corrupt_files_give_defaults(tmp_path):
    assert load_settings(tmp_path / "missing.json") == Settings()
    for name, content in (("bad.json", "{not json"), ("list.json", "[1, 2]")):
        path = tmp_path / name
        path.write_text(content)
        assert load_settings(path) == Settings()


def test_defaults_are_english_and_follow_xdg_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert config_dir() == tmp_path / "config" / "istinbat"
    assert data_dir() == tmp_path / "data" / "istinbat"
    settings = Settings()
    assert settings.app.language is Language.EN
    assert settings.paths.vector_db == str(tmp_path / "data" / "istinbat" / "chroma_db")


def test_rtl_only_for_arabic():
    assert Language.AR.is_rtl and not Language.EN.is_rtl


def test_answer_language_defaults_to_following_the_question_and_round_trips(tmp_path):
    from istinbat.core import AnswerLanguage

    assert Settings().memory.answer_language is AnswerLanguage.AUTO
    settings = Settings()
    settings.memory.answer_language = AnswerLanguage.ENGLISH
    path = tmp_path / "settings.json"
    save_settings(settings, path)
    assert load_settings(path).memory.answer_language is AnswerLanguage.ENGLISH
    assert '"answer_language": "en"' in path.read_text(encoding="utf-8")
