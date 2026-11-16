"""Trait-like event colors: policies, GCal rendering, provider wiring."""

from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace

from dir3 import cli
from dir3.color import (
    GREEN_SLOT,
    ORANGE_SLOT,
    RED_SLOT,
    YELLOW_SLOT,
    ColorPolicy,
    DictColorPolicy,
    GCalColor,
    PlainPolicy,
    PrayerColorPolicy,
    PrayerStatusColorPolicy,
    name_slot,
    normalize_event_name,
    to_gcal_color_id,
)
from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.core import day, task, week
from dir3.engine import compile_pattern
from dir3.services import Services
from dir3.services.gcal import (
    GCalSyncReport,
    GoogleCalendar,
    GoogleCalendarSyncer,
)

ISTANBUL = LocationSettings(latitude=40.7992, longitude=29.4305, timezone="Europe/Istanbul")


def _coding_day():
    @day
    def coding(ctx):
        return [
            task("Fajr", start=ctx.prayer.fajr, until=ctx.prayer.sunrise),
            task("Coding", duration=timedelta(hours=2)),
            task("Reading", duration=timedelta(hours=1)),
        ]

    return coding


def _one_day_plan():
    config = Dir3Config(location=ISTANBUL, prayer=PrayerSettings(provider="offline"))
    coding = _coding_day()
    return compile_pattern(
        week(mon=coding, tue=coding, wed=coding, thu=coding, fri=coding, sat=coding, sun=coding),
        days=1,
        start_date=date(2026, 9, 14),
        services=Services(config=config),
    )


def _syncer(**kwargs):
    settings = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")
    return GoogleCalendarSyncer(settings, **kwargs)


def test_prayers_always_yellow():
    from dir3.color import YELLOW_SLOT

    policy = PrayerColorPolicy()
    for name in ("Fajr", "FAJR", "  dhuhr  ", "Duhr", "Asr", "Maghrib", "Isha", "Sunrise"):
        assert policy.color_for(name, 0) == YELLOW_SLOT
        assert policy.color_for(name, 7) == YELLOW_SLOT
    assert to_gcal_color_id(YELLOW_SLOT) == "5"  # Banana


def test_prayer_status_policy_colors_shifted_critical_and_lecture_overlap():
    policy = PrayerStatusColorPolicy()
    assert policy.color_for("Dhuhr", 0) == GREEN_SLOT
    assert policy.color_for("Asr (verschoben: Adhan 14:14 → 15:50)", 0) == YELLOW_SLOT
    assert policy.color_for("Maghrib (kritisch, noch 22 min bis Isha-Adhan)", 0) == RED_SLOT
    assert policy.color_for("Asr (Kerahat, noch 42 min bis Maghrib-Adhan)", 0) == RED_SLOT
    assert policy.color_for("Maghrib (11 min von der Vorlesung)", 0) == ORANGE_SLOT
    assert policy.color_for("Jumuah (verschoben: Adhan 11:51 → 12:30)", 0) == YELLOW_SLOT
    assert policy.color_for("Maghrib (verschoben, 11 min von der Vorlesung)", 0) == ORANGE_SLOT
    assert (
        policy.color_for(
            "Maghrib (verschoben, kritisch, noch 20 min bis Isha-Adhan, 11 min von der Vorlesung)",
            0,
        )
        == RED_SLOT
    )
    assert to_gcal_color_id(ORANGE_SLOT) == "6"  # Tangerine
    assert to_gcal_color_id(GREEN_SLOT) == "2"  # Sage
    assert to_gcal_color_id(RED_SLOT) == "11"  # Tomato
    assert policy.color_for("Asr Analysis", 0) == name_slot("asr analysis")
    assert policy.color_for("Coding", 0) == name_slot("coding")


def test_name_hash_deterministic_per_name():
    from dir3.color import name_slot

    policy = PrayerColorPolicy()
    # sum(b"coding") = 628 -> 628 % 11 = 1, independent of position
    assert name_slot("Coding") == 1
    assert policy.color_for("Coding", 0) == 1
    assert policy.color_for("Coding", 9) == 1
    assert policy.color_for("coding", 4) == 1  # case-insensitive
    # sum(b"reading") = 730 -> 730 % 11 = 4
    assert name_slot("Reading") == 4
    assert policy.color_for("Reading", 0) == 4


def test_plain_policy_disables_colors():
    assert PlainPolicy().color_for("Fajr", 0) is None
    assert PlainPolicy().color_for("Coding", 3) is None


def test_to_gcal_color_id_palette_and_bounds():
    assert to_gcal_color_id(0) == "3"  # Fajr -> grape
    assert to_gcal_color_id(4) == "11"  # Maghrib -> tomato
    assert to_gcal_color_id(5) == "9"  # Isha -> blueberry
    assert to_gcal_color_id(11) is None
    assert to_gcal_color_id(-1) is None
    assert to_gcal_color_id("xx") is None
    assert to_gcal_color_id(True) is None


def test_gcal_color_is_public_api():
    from dir3 import GCalColor as PublicGCalColor

    assert PublicGCalColor is GCalColor


def test_gcal_color_names_are_builtin_and_match_color_ids():
    assert GCalColor.LAVENDER.value == "1"
    assert GCalColor.SAGE.value == "2"
    assert GCalColor.GRAPE.value == "3"
    assert GCalColor.FLAMINGO.value == "4"
    assert GCalColor.BANANA.value == "5"
    assert GCalColor.TANGERINE.value == "6"
    assert GCalColor.PEACOCK.value == "7"
    assert GCalColor.GRAPHITE.value == "8"
    assert GCalColor.BLUEBERRY.value == "9"
    assert GCalColor.BASIL.value == "10"
    assert GCalColor.TOMATO.value == "11"
    assert to_gcal_color_id(GCalColor.BASIL) == "10"
    assert to_gcal_color_id(GCalColor.TANGERINE) == "6"


def test_named_color_policy_works_without_numeric_slots():
    class NamedPolicy:
        def color_for(self, name, index):
            return GCalColor.PEACOCK

    assert isinstance(NamedPolicy(), ColorPolicy)
    assert to_gcal_color_id(NamedPolicy().color_for("Coding", 0)) == "7"


def test_dict_policy_accepts_gcal_colors_and_names():
    assert (
        to_gcal_color_id(DictColorPolicy({"Coding": GCalColor.BLUEBERRY}).color_for("Coding", 0))
        == "9"
    )
    assert to_gcal_color_id(DictColorPolicy({"Coding": "Basil"}).color_for("Coding", 0)) == "10"
    assert to_gcal_color_id(DictColorPolicy({"Coding": "tomato"}).color_for("Coding", 0)) == "11"


def test_normalize_event_name():
    assert normalize_event_name("  Fajr ") == "fajr"
    assert normalize_event_name(None) == ""


def test_dict_policy_overrides_and_falls_back():
    policy = DictColorPolicy({"Coding": 9, "fajr": "11"}, fallback=PrayerColorPolicy())
    assert to_gcal_color_id(policy.color_for("Coding", 0)) == "9"  # round-trip
    assert to_gcal_color_id(policy.color_for("coding", 5)) == "9"  # case-insensitive
    assert to_gcal_color_id(policy.color_for("Fajr", 0)) == "11"  # round-trip
    assert policy.color_for("Dhuhr", 0) == 2  # prayer yellow fallback
    assert policy.color_for("Reading", 4) == 4  # name-hashed fallback


def test_dict_policy_ignores_invalid_values():
    from dir3.color import name_slot

    policy = DictColorPolicy({"A": 99, "B": "xx", "C": True, "D": 0})
    # invalid overrides dropped -> name-hashed fallback (a->9, b->10, c->0, d->1)
    assert policy.color_for("A", 1) == name_slot("a") == 9
    assert policy.color_for("B", 1) == name_slot("b") == 10
    assert policy.color_for("C", 1) == name_slot("c") == 0
    assert policy.color_for("D", 1) == name_slot("d") == 1


def test_custom_trait_impl_needs_no_inheritance():
    class SleepBlue:
        def color_for(self, name, index):
            return 9 if "sleep" in name.lower() else None

    assert isinstance(SleepBlue(), ColorPolicy)
    assert SleepBlue().color_for("Sleep", 0) == 9
    assert SleepBlue().color_for("Work", 0) is None


def _by_event_name(staged):
    """Map without the leading icon marker (titles carry icons now)."""
    icons = ("🕋 ", "🏫 ", "🛣️ ")
    names = {}
    for event in staged:
        name = event.summary
        for icon in icons:
            if name.startswith(icon):
                name = name[len(icon) :]
                break
        names[name] = event
    return names


def test_stage_applies_policy_colors():
    staged = _syncer().stage(_one_day_plan(), timezone_name="Europe/Istanbul")
    by_name = _by_event_name(staged)
    assert by_name["Fajr"].body["colorId"] == "5"  # yellow
    assert by_name["Coding"].body["colorId"] == "6"  # hashed slot 1
    assert by_name["Reading"].body["colorId"] == "11"  # hashed slot 4


def test_stage_dict_override_wins():
    syncer = _syncer(color_policy=DictColorPolicy({"Coding": 11}))
    by_name = _by_event_name(syncer.stage(_one_day_plan(), timezone_name="Europe/Istanbul"))
    assert by_name["Coding"].body["colorId"] == "11"
    assert by_name["Fajr"].body["colorId"] == "5"  # yellow fallback intact


def test_stage_plain_policy_omits_color_id():
    staged = _syncer(color_policy=PlainPolicy()).stage(
        _one_day_plan(), timezone_name="Europe/Istanbul"
    )
    assert all("colorId" not in e.body for e in staged)


def test_config_overlay_merges_colors():
    config = Dir3Config()
    config.overlay(SimpleNamespace(colors={"Coding": 9}))
    config.overlay(SimpleNamespace(colors={"Reading": "5"}))
    assert config.colors == {"Coding": 9, "Reading": "5"}
    config.overlay(SimpleNamespace())
    assert config.colors == {"Coding": 9, "Reading": "5"}


def test_config_overlay_accepts_color_policy():
    policy = PrayerStatusColorPolicy()
    config = Dir3Config()
    config.overlay(SimpleNamespace(color_policy=policy))
    assert config.color_policy is policy
    config.overlay(SimpleNamespace(color_policy=object()))
    assert config.color_policy is policy


def test_cli_passes_colors_to_syncer(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "plan.py"
    planfile.write_text(
        "from datetime import time, timedelta\n"
        "from dir3 import GoogleCalendar, day, task\n"
        "from dir3.core import week\n\n"
        "location = (40.7992, 29.4305, 'Europe/Istanbul')\n"
        'gcal = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")\n'
        'colors = {"SyncTest": 9}\n\n'
        "@day\n"
        "def sample(ctx):\n"
        "    return [task('SyncTest', start=time(9, 0), duration=timedelta(minutes=30))]\n\n"
        "plan = week(mon=sample, tue=sample, wed=sample, thu=sample,\n"
        "            fri=sample, sat=sample, sun=sample)\n",
        encoding="utf-8",
    )
    recorded = {}

    def fake_syncer(settings, **kwargs):
        recorded.update(kwargs)
        return object()

    def fake_run(syncer, plan, *, timezone_name, dry_run):
        return GCalSyncReport(total=1, created=1, updated=0, dry_run=False)

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_sync", fake_run)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--sync-gcal"]) == 0
    policy = recorded.get("color_policy")
    assert isinstance(policy, DictColorPolicy)
    assert to_gcal_color_id(policy.color_for("SyncTest", 0)) == "9"
    capsys.readouterr()


def test_cli_passes_custom_color_policy(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "plan.py"
    planfile.write_text(
        "from datetime import time, timedelta\n"
        "from dir3 import GoogleCalendar, PrayerStatusColorPolicy, day, task, week\n\n"
        "location = (40.7992, 29.4305, 'Europe/Istanbul')\n"
        'gcal = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")\n'
        "color_policy = PrayerStatusColorPolicy()\n\n"
        "@day\n"
        "def sample(ctx):\n"
        "    return [task('Asr (verschoben: Adhan 14:00 → 14:15)',\n"
        "                 start=time(14, 10), duration=timedelta(minutes=8))]\n\n"
        "plan = week(mon=sample, tue=sample, wed=sample, thu=sample,\n"
        "            fri=sample, sat=sample, sun=sample)\n",
        encoding="utf-8",
    )
    recorded = {}

    def fake_syncer(settings, **kwargs):
        recorded.update(kwargs)
        return object()

    def fake_run(syncer, plan, *, timezone_name, dry_run):
        return GCalSyncReport(total=1, created=1, updated=0, dry_run=False)

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_sync", fake_run)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--sync-gcal"]) == 0
    policy = recorded.get("color_policy")
    assert isinstance(policy, PrayerStatusColorPolicy)
    assert to_gcal_color_id(policy.color_for("Asr (verschoben: Adhan 14:00 → 14:15)", 0)) == "5"
    capsys.readouterr()


def test_cli_merges_user_colors_over_custom_policy(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "plan.py"
    planfile.write_text(
        "from datetime import time, timedelta\n"
        "from dir3 import GoogleCalendar, PrayerStatusColorPolicy, day, task, week\n\n"
        "location = (40.7992, 29.4305, 'Europe/Istanbul')\n"
        'gcal = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")\n'
        "color_policy = PrayerStatusColorPolicy()\n"
        'colors = {"Coding": 9}\n\n'
        "@day\n"
        "def sample(ctx):\n"
        "    return [task('Fajr', start=time(5, 0), duration=timedelta(minutes=15)),\n"
        "            task('Coding', start=time(9, 0), duration=timedelta(minutes=30))]\n\n"
        "plan = week(mon=sample, tue=sample, wed=sample, thu=sample,\n"
        "            fri=sample, sat=sample, sun=sample)\n",
        encoding="utf-8",
    )
    recorded = {}

    def fake_syncer(settings, **kwargs):
        recorded.update(kwargs)
        return object()

    def fake_run(syncer, plan, *, timezone_name, dry_run):
        return GCalSyncReport(total=1, created=1, updated=0, dry_run=False)

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_sync", fake_run)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--sync-gcal"]) == 0
    policy = recorded.get("color_policy")
    assert isinstance(policy, DictColorPolicy)
    assert to_gcal_color_id(policy.color_for("Coding", 0)) == "9"
    assert to_gcal_color_id(policy.color_for("Fajr", 0)) == "2"
    capsys.readouterr()


def test_sync_bodies_carry_color_id():
    import asyncio

    bodies = []

    class _Status:
        status_code = 201

        def raise_for_status(self):
            pass

    class _FakeEvents:
        def insert(self, **kwargs):
            assert "body" not in kwargs, "aiogoogle takes json=, not body="
            bodies.append(kwargs["json"])
            return ("insert", kwargs)

        def update(self, **kwargs):
            return ("update", kwargs)

        def list(self, **kwargs):
            return ("list", kwargs)

    class _FakeCal:
        events = _FakeEvents()

    class _FakeAg:
        async def discover(self, *args, **kwargs):
            return _FakeCal()

        async def as_user(self, *requests, **kwargs):
            if isinstance(requests[0], tuple) and requests[0][0] == "list":
                return {"items": []}
            responses = [_Status() for _ in requests]
            return responses if len(responses) > 1 else responses[0]

    @asynccontextmanager
    async def open_client(settings, timeout):
        yield _FakeAg(), _FakeCal()

    syncer = _syncer(client_factory=open_client)
    asyncio.run(syncer.sync(_one_day_plan(), timezone_name="Europe/Istanbul"))
    assert bodies and all("colorId" in body for body in bodies)
