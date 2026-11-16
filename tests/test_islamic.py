"""Hijri calendar helpers."""

from datetime import date

from dir3 import (
    HijriDate,
    hijri_date,
    is_ayyam_al_biyd,
    is_day_of_arafah,
    is_eid_al_adha,
    is_eid_al_fitr,
    is_fasting_day,
    is_fasting_forbidden,
    is_qurban,
    is_ramadan,
    is_tashreeq,
    is_voluntary_fast,
)


def test_hijri_date_uses_umm_al_qura():
    assert hijri_date(date(2026, 10, 26)) == HijriDate(year=1448, month=5, day=15)


def test_ayyam_al_biyd_are_the_13th_to_15th():
    assert is_ayyam_al_biyd(date(2026, 10, 24))
    assert is_ayyam_al_biyd(date(2026, 10, 25))
    assert is_ayyam_al_biyd(date(2026, 10, 26))


def test_other_days_are_not_ayyam_al_biyd():
    assert not is_ayyam_al_biyd(date(2026, 10, 23))
    assert not is_ayyam_al_biyd(date(2026, 10, 27))


def test_voluntary_fast_defaults_to_monday_thursday_and_ayyam():
    assert is_voluntary_fast(date(2026, 11, 2))  # Monday
    assert is_voluntary_fast(date(2026, 11, 5))  # Thursday
    assert not is_voluntary_fast(date(2026, 11, 3))  # Tuesday
    assert is_voluntary_fast(date(2026, 10, 24))  # Saturday, Ayyam al-Biyd


def test_voluntary_fast_can_be_configured():
    assert is_voluntary_fast(date(2026, 11, 3), weekdays={1})
    assert not is_voluntary_fast(
        date(2026, 10, 24),
        weekdays={0, 3},
        ayyam_al_biyd=False,
    )


def test_ramadan_is_not_voluntary_fast():
    # 2 Ramadan 1448; Tuesday outside the default Monday/Thursday fasts.
    assert not is_voluntary_fast(date(2027, 2, 9))
    # 1 Ramadan 1448 is a Monday, but fasting is obligatory, not voluntary.
    assert not is_voluntary_fast(date(2027, 2, 8))


def test_ramadan_detection():
    assert is_ramadan(date(2027, 2, 8))
    assert is_ramadan(date(2027, 3, 8))
    assert not is_ramadan(date(2027, 3, 9))


def test_eid_and_qurban_detection():
    assert is_eid_al_fitr(date(2027, 3, 9))
    assert not is_eid_al_fitr(date(2027, 3, 10))

    assert is_day_of_arafah(date(2027, 5, 15))
    assert is_eid_al_adha(date(2027, 5, 16))
    assert is_tashreeq(date(2027, 5, 17))
    assert is_qurban(date(2027, 5, 16))
    assert is_qurban(date(2027, 5, 19))
    assert not is_qurban(date(2027, 5, 20))


def test_fasting_is_forbidden_on_eids_and_qurban_days():
    assert is_fasting_forbidden(date(2027, 3, 9))
    assert is_fasting_forbidden(date(2027, 5, 16))
    assert is_fasting_forbidden(date(2027, 5, 19))
    assert not is_fasting_forbidden(date(2027, 5, 20))
    assert not is_voluntary_fast(date(2027, 5, 17))  # Tashreeq Monday


def test_fasting_day_includes_ramadan():
    assert is_fasting_day(date(2027, 2, 9))
    assert is_fasting_day(date(2026, 11, 2))  # ordinary voluntary Monday
    assert not is_fasting_day(date(2027, 3, 10))  # Eid al-Fitr + 1
    assert not is_fasting_day(date(2027, 5, 16))  # Eid al-Adha
