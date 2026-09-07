from datetime import time, timedelta

import pytest

from dir3.timeutils import (
    add_time,
    format_duration,
    format_time,
    parse_duration,
    parse_hhmm,
    span_between,
    subtract_time,
)


def test_parse_hhmm_variants():
    assert parse_hhmm("05:00") == time(5, 0)
    assert parse_hhmm("5.30") == time(5, 30)
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


def test_parse_duration():
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("90m") == timedelta(minutes=90)
    assert parse_duration("1:30") == timedelta(hours=1, minutes=30)
    assert parse_duration("1.05") == timedelta(hours=1, minutes=5)
    assert parse_duration("45") == timedelta(minutes=45)
    assert parse_duration("1h30m") == timedelta(hours=1, minutes=30)
    assert parse_duration("1h 30m") == timedelta(hours=1, minutes=30)


def test_format_duration():
    assert format_duration(timedelta()) == "0 min"
    assert format_duration(timedelta(minutes=30)) == "30 min"
    assert format_duration(timedelta(hours=1, minutes=30)) == "1:30 h"
    assert format_duration(-timedelta(minutes=15)) == "-15 min"


def test_add_time_wraps_midnight():
    assert add_time(time(23, 0), timedelta(hours=2)) == time(1, 0)
    assert subtract_time(time(1, 0), timedelta(hours=2)) == time(23, 0)


def test_format_time():
    assert format_time(time(7, 5)) == "07:05"


def test_span_between_wraps():
    assert span_between(time(23, 0), time(1, 0)) == timedelta(hours=2)
    assert span_between(time(6, 0), time(18, 0)) == timedelta(hours=12)
