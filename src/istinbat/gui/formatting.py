# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pure helpers that decide what to display (no GTK, fully testable)."""

from __future__ import annotations

import unicodedata
from datetime import datetime

_SECONDS_PER_MINUTE = 60
_MB = 1_000_000
_GB = 1_000 * _MB
_RTL_BIDI_CLASSES = {"R", "AL"}
_LTR_BIDI_CLASSES = {"L"}


def day_bucket(timestamp: float, now: float) -> str:
    """Return ``"today"``, ``"yesterday"`` or an ISO date for a conversation's last activity."""
    day = datetime.fromtimestamp(timestamp).date()
    days_ago = (datetime.fromtimestamp(now).date() - day).days
    if days_ago == 0:
        return "today"
    if days_ago == 1:
        return "yesterday"
    return day.isoformat()


def duration_parts(seconds: float) -> tuple[str, dict[str, object]]:
    """Return the translation key and parameters for a short duration such as "3.5 s" or "1 min 12 s"."""
    if seconds < _SECONDS_PER_MINUTE:
        value = f"{seconds:.1f}" if seconds < 10 else f"{seconds:.0f}"
        return "duration.seconds", {"value": value}
    minutes, remainder = divmod(round(seconds), _SECONDS_PER_MINUTE)
    return "duration.minutes_seconds", {"minutes": minutes, "seconds": remainder}


def size_label(size: int) -> str:
    """A download size the way Hugging Face writes it: decimal units, e.g. "3.2 GB" or "17 MB"."""
    if size >= _GB:
        return f"{size / _GB:.1f} GB"
    return f"{max(1, round(size / _MB))} MB"


def is_rtl_text(text: str) -> bool:
    """Tell whether ``text`` starts with a right-to-left letter (the Unicode first-strong rule)."""
    for character in text:
        bidi = unicodedata.bidirectional(character)
        if bidi in _RTL_BIDI_CLASSES:
            return True
        if bidi in _LTR_BIDI_CLASSES:
            return False
    return False
