# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-user filesystem locations.

Linux follows the XDG Base Directory specification. Windows uses ``%APPDATA%`` for settings
and ``%LOCALAPPDATA%`` for the (large, machine-specific) data. On either system an explicit
``XDG_CONFIG_HOME`` / ``XDG_DATA_HOME`` wins, which also makes a portable setup possible.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "istinbat"


def is_windows() -> bool:
    return sys.platform == "win32"


def _windows_base(variable: str, fallback: tuple[str, ...]) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value else Path.home().joinpath(*fallback)


def config_dir() -> Path:
    """Return the per-user configuration directory."""
    explicit = os.environ.get("XDG_CONFIG_HOME")
    if explicit:
        return Path(explicit) / APP_NAME
    if is_windows():
        return _windows_base("APPDATA", ("AppData", "Roaming")) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def data_dir() -> Path:
    """Return the per-user data directory (vector store, manifest, conversations, models)."""
    explicit = os.environ.get("XDG_DATA_HOME")
    if explicit:
        return Path(explicit) / APP_NAME
    if is_windows():
        return _windows_base("LOCALAPPDATA", ("AppData", "Local")) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def default_settings_path() -> Path:
    """Return the location of ``settings.json``."""
    return config_dir() / "settings.json"


def default_models_dir() -> Path:
    """Return where downloaded models are stored unless the user chooses another folder."""
    return data_dir() / "models"


def log_file() -> Path:
    """Return the log file used when the process has no console (a Windows GUI launch)."""
    return data_dir() / "istinbat.log"


def documents_dir() -> Path:
    """Return the user's Documents folder.

    On Windows the folder can be redirected (OneDrive, a policy), so it is asked from the
    shell instead of being assumed to be ``~/Documents``.
    """
    if is_windows():
        known = _windows_known_documents()
        if known is not None:
            return known
    return Path.home() / "Documents"


def _windows_known_documents() -> Path | None:
    try:
        import ctypes
        from ctypes import wintypes

        class _Guid(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        tail = (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7)
        folder_id = _Guid(0xFDD39AD0, 0x238F, 0x46AF, tail)
        buffer = ctypes.c_wchar_p()
        shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32      # type: ignore[attr-defined]
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_Guid), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p),
        ]
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(buffer)) != 0:
            return None
        try:
            return Path(buffer.value) if buffer.value else None
        finally:
            ole32.CoTaskMemFree(buffer)
    except Exception:    # Never let a lookup of a default location stop the application.
        return None
