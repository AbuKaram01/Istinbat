# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-user locations on Linux and on Windows (the Windows branch is exercised from any system)."""

from pathlib import Path

import pytest

from istinbat.core import paths
from istinbat.core.settings import Settings


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    return tmp_path / "home"


def as_windows(monkeypatch):
    monkeypatch.setattr(paths, "is_windows", lambda: True)


def test_linux_uses_the_dot_directories_under_home(monkeypatch, clean_env):
    monkeypatch.setattr(paths, "is_windows", lambda: False)
    assert paths.config_dir() == clean_env / ".config" / "istinbat"
    assert paths.data_dir() == clean_env / ".local" / "share" / "istinbat"
    assert paths.documents_dir() == clean_env / "Documents"


def test_windows_keeps_settings_in_roaming_and_data_in_local_appdata(monkeypatch, clean_env, tmp_path):
    as_windows(monkeypatch)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.config_dir() == tmp_path / "Roaming" / "istinbat"
    assert paths.data_dir() == tmp_path / "Local" / "istinbat"
    assert paths.default_settings_path() == tmp_path / "Roaming" / "istinbat" / "settings.json"
    assert paths.default_models_dir() == tmp_path / "Local" / "istinbat" / "models"
    assert paths.log_file() == tmp_path / "Local" / "istinbat" / "istinbat.log"


def test_windows_falls_back_to_the_profile_when_the_variables_are_missing(monkeypatch, clean_env):
    as_windows(monkeypatch)
    assert paths.config_dir() == clean_env / "AppData" / "Roaming" / "istinbat"
    assert paths.data_dir() == clean_env / "AppData" / "Local" / "istinbat"


def test_an_explicit_xdg_variable_wins_on_windows_too(monkeypatch, clean_env, tmp_path):
    as_windows(monkeypatch)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "portable"))
    assert paths.config_dir() == tmp_path / "portable" / "istinbat"


def test_windows_asks_the_shell_for_the_documents_folder(monkeypatch, clean_env, tmp_path):
    as_windows(monkeypatch)
    redirected = tmp_path / "OneDrive" / "Documents"
    monkeypatch.setattr(paths, "_windows_known_documents", lambda: redirected)
    assert paths.documents_dir() == redirected
    assert Path(Settings().paths.books_dir) == redirected / "Books"


def test_a_failed_shell_lookup_falls_back_to_documents_under_home(monkeypatch, clean_env):
    as_windows(monkeypatch)
    monkeypatch.setattr(paths, "_windows_known_documents", lambda: None)
    assert paths.documents_dir() == clean_env / "Documents"


def test_the_shell_lookup_never_raises_where_there_is_no_windows_api():
    # On Linux ``ctypes.windll`` does not exist; on Windows the call really works. Either way: no exception.
    result = paths._windows_known_documents()
    assert result is None or isinstance(result, Path)
