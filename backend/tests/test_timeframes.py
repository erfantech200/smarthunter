from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.time import parse_rfc3339
from app.data.timeframes import Timeframe, bucket_bounds, bucket_end, bucket_start


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def test_parse_rfc3339_truncates_nanoseconds_never_rounds_up() -> None:
    assert parse_rfc3339("2026-11-02T13:00:00.999999999Z") == utc(2026, 11, 2, 13, 0, 0, 999999)
    assert parse_rfc3339("2026-11-02T13:00:00Z") == utc(2026, 11, 2, 13)


def test_naive_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        bucket_start(datetime(2026, 1, 1), Timeframe.M1)  # noqa: DTZ001


@pytest.mark.parametrize(
    ("t", "tf", "start"),
    [
        (utc(2026, 11, 2, 13, 7, 30), Timeframe.M5, utc(2026, 11, 2, 13, 5)),
        (utc(2026, 11, 2, 13, 59), Timeframe.M15, utc(2026, 11, 2, 13, 45)),
        # winter (EST, UTC-5): daily boundary 17:00 NY = 22:00 UTC
        (utc(2026, 1, 14, 21, 59), Timeframe.D1, utc(2026, 1, 13, 22)),
        (utc(2026, 1, 14, 22, 0), Timeframe.D1, utc(2026, 1, 14, 22)),
        # summer (EDT, UTC-4): 17:00 NY = 21:00 UTC
        (utc(2026, 7, 15, 21, 0), Timeframe.D1, utc(2026, 7, 15, 21)),
        # H4 aligned to 17:00 NY: in winter boundaries at 22, 02, 06, 10, 14, 18 UTC
        (utc(2026, 1, 14, 13, 0), Timeframe.H4, utc(2026, 1, 14, 10)),
        (utc(2026, 1, 14, 23, 0), Timeframe.H4, utc(2026, 1, 14, 22)),
        (utc(2026, 1, 15, 1, 59), Timeframe.H4, utc(2026, 1, 14, 22)),
        # in summer: 21, 01, 05, 09, 13, 17 UTC
        (utc(2026, 7, 15, 13, 0), Timeframe.H4, utc(2026, 7, 15, 13)),
        # W1 starts Friday 17:00 NY: Wed 2026-01-14 → Fri 2026-01-09 22:00 UTC
        (utc(2026, 1, 14, 12), Timeframe.W1, utc(2026, 1, 9, 22)),
    ],
)
def test_bucket_start(t: datetime, tf: Timeframe, start: datetime) -> None:
    assert bucket_start(t, tf) == start


def test_daily_bar_across_us_dst_change_is_23_hours() -> None:
    # US DST starts Sunday 2026-03-08: the D1 bar starting Fri 06 Mar 17:00 EST ends Sat 07 Mar 17:00 EST...
    # the one starting Sat 07 Mar 22:00 UTC ends Sun 08 Mar 17:00 EDT = 21:00 UTC → 23 hours.
    s = utc(2026, 3, 7, 22)
    assert bucket_end(s, Timeframe.D1) - s == timedelta(hours=23)


@given(
    st.datetimes(min_value=datetime(2015, 1, 1), max_value=datetime(2030, 12, 31), timezones=st.just(UTC)),  # noqa: DTZ001
    st.sampled_from(list(Timeframe)),
)
def test_bucket_contains_t_and_is_stable(t: datetime, tf: Timeframe) -> None:
    s, e = bucket_bounds(t, tf)
    assert s <= t < e
    assert bucket_start(s, tf) == s
    assert bucket_start(e, tf) == e  # the next bucket starts exactly where this one ends
