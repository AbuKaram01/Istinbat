# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import datetime

from istinbat.gui.formatting import day_bucket, duration_parts, is_rtl_text


def stamp(year, month, day, hour=12):
    return datetime(year, month, day, hour).timestamp()


def test_day_bucket_names_today_and_yesterday_then_falls_back_to_the_date():
    now = stamp(2026, 10, 4)
    assert day_bucket(stamp(2026, 10, 4, 1), now) == "today"
    assert day_bucket(stamp(2026, 10, 3, 23), now) == "yesterday"
    assert day_bucket(stamp(2026, 9, 20), now) == "2026-09-20"


def test_short_durations_use_seconds_with_one_decimal_below_ten():
    assert duration_parts(3.46) == ("duration.seconds", {"value": "3.5"})
    assert duration_parts(42.4) == ("duration.seconds", {"value": "42"})


def test_long_durations_use_minutes_and_seconds():
    assert duration_parts(72) == ("duration.minutes_seconds", {"minutes": 1, "seconds": 12})
    assert duration_parts(60) == ("duration.minutes_seconds", {"minutes": 1, "seconds": 0})


def test_text_direction_follows_the_first_strong_letter():
    assert is_rtl_text("المعلومات هي النتائج")
    assert not is_rtl_text("What is information?")
    assert is_rtl_text("123 ... المعلومات")        # Neutral characters are skipped.
    assert not is_rtl_text("Information ما هي")
    assert not is_rtl_text("")
