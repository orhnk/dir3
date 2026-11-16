"""dir3 - das Leben zeitlich programmieren, weich und anker-basiert.

Public API::

    from dir3 import anchor, task, day, week, month, compile, prayer, sun,
                      midnight, next_day_start

Declare *your own* time anchors with ``@anchor``, build days as functions
receiving a per-day context, bundle weeks/months and compile softly.
"""

from __future__ import annotations

from .alarm import (
    Alarm,
    AlarmError,
    AlarmSettings,
    WakeAlarmPolicy,
    alarm,
    coerce_alarm,
    parse_offset,
)
from .anchor import (
    Anchor,
    DerivedAnchor,
    FixedAnchor,
    FunctionAnchor,
    NamedAnchor,
    all_anchors,
    anchor,
    midnight,
    named_anchor,
    next_event,
    register,
)
from .color import (
    AVOCADO_SLOT,
    BASIL_SLOT,
    FLAMINGO_SLOT,
    LEMON_SLOT,
    MANDARIN_SLOT,
    MANGO_SLOT,
    PISTACHIO_SLOT,
    TOMATO_SLOT,
    BasilPistazienColorPolicy,
    ColorPolicy,
    DefaultIconPolicy,
    DictColorPolicy,
    GCalColor,
    IconPolicy,
    PlainPolicy,
    PrayerColorPolicy,
    PrayerStatusColorPolicy,
    event_summary,
    icon_policy_chain,
    shorten_event_name,
    to_gcal_color_id,
)
from .config import (
    Dir3Config,
    GoogleCalendar,
    LocationSettings,
    PrayerSettings,
    SyncSettings,
    TransitSettings,
)
from .context import DayContext, PrayerGate, SunGate, TransitGate
from .core import (
    CalendarPattern,
    Day,
    DayFactory,
    Month,
    PlanError,
    Task,
    Todo,
    Week,
    calendar,
    day,
    going,
    month,
    next_day_start,
    task,
    week,
)
from .diet import (
    ACTIVITY_LEVELS,
    DietProfile,
    MealPlan,
    MealPlanEntry,
    MealPlanSettings,
    NutritionTarget,
    ShoppingItem,
    ShoppingList,
    ShoppingRun,
    ShoppingSettings,
    avoid_terms,
    basal_metabolic_rate,
    build_shopping_list,
    daily_calorie_target,
    max_carbs_per_meal,
    nutrition_targets,
    plan_meals,
    recipe_allowed,
    shopping_task,
)
from .engine import Plan, PlanDay, PlannedEvent
from .engine import compile_pattern as compile
from .family import (
    Relative,
    SilaRahimSettings,
    Whom,
    select_relatives,
    sila_rahim,
    sila_rahim_events,
    under,
)
from .home import (
    HomeSettings,
    cleanup_after_dinner,
    dinner_after_homecoming,
    shower_after_homecoming,
    shower_before,
)
from .islamic import (
    DEFAULT_VOLUNTARY_FAST_WEEKDAYS,
    HijriDate,
    SunnahFastSettings,
    hijri_date,
    is_ashura,
    is_ayyam_al_biyd,
    is_day_of_arafah,
    is_eid_al_adha,
    is_eid_al_fitr,
    is_fasting_day,
    is_fasting_forbidden,
    is_first_nine_dhul_hijjah,
    is_last_ten_nights,
    is_laylat_al_qadr_candidate,
    is_muharram,
    is_qurban,
    is_ramadan,
    is_shaban,
    is_shawwal,
    is_sunnah_fast,
    is_tashreeq,
    is_tasu_a,
    is_voluntary_fast,
    sunnah_fast_name,
)
from .meals import MealSettings, breakfast
from .night import NightSettings, night_events
from .prayerplan import FixedPrayer, PrayerPlanner, PrayerPlanSettings
from .qurban import (
    QurbanSettings,
    eid_prayer,
    qurban_distribution,
    qurban_events,
    qurban_sacrifice,
)
from .ramadan import RamadanSettings, iftar, ramadan_events, suhoor, tarawih
from .recipe_enrich import (
    EnrichmentStats,
    NutritionEstimate,
    enrich_database,
    estimate_recipe,
    lookup_food,
)
from .recipes import (
    DEFAULT_RECIPE_DB,
    PROJECT_RECIPE_DB,
    TARGET_REGIONS,
    HaramIngredientError,
    ImportStats,
    Ingredient,
    Recipe,
    RecipeBook,
    find_haram,
    normalize_region,
    parse_amount,
    parse_ingredient_line,
    parse_kcal,
    parse_minutes,
    parse_servings,
    region_for_cuisines,
)
from .render import render_plan
from .services import (
    Services,
    TransitJourney,
    TransitLeg,
    TransitService,
    TransitStop,
)
from .services.weather import rains
from .sleepplan import (
    AFTER_TAHAJJUD,
    BALANCED,
    BEFORE_SLEEP,
    LONG,
    SHORT,
    SeasonSettings,
    SleepPlanSettings,
    classify_night,
    sleep_plan,
)
from .sunnah import (
    AdhkarSettings,
    AwwabinSettings,
    DuhaSettings,
    EidFitrSettings,
    ItikafSettings,
    QiyamSettings,
    QuranSettings,
    RawatibSettings,
    WitrSettings,
    adhkar_events,
    awwabin,
    duha,
    eid_fitr_events,
    eid_fitr_prayer,
    evening_adhkar,
    itikaf,
    itikaf_events,
    laylat_al_qadr_qiyam,
    morning_adhkar,
    qiyam,
    quran,
    rawatib_events,
    witr,
)
from .timeutils import (
    add_time,
    format_duration,
    format_minutes,
    format_time,
    parse_duration,
    parse_hhmm,
    subtract_time,
    time_from_minutes,
    to_minutes,
)
from .travel import Route, TravelSettings, route_end, route_way
from .whereabouts import Trip, Whereabouts, where_am_i


class _PrayerProviderProxy:
    """Module-level prayer anchors usable inside day definitions.

    ``prayer.dhuhr`` is an :class:`Anchor`; ``ctx.prayer.dhuhr`` inside a day
    function is a fresh anchor too. Both resolve through the day context, so
    they are per-day and cached.
    """

    def __getattr__(self, name: str) -> Anchor:
        allowed = {"fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"}
        if name not in allowed:
            raise AttributeError(f"Unknown prayer anchor '{name}'")
        from .anchor import NamedAnchor

        return NamedAnchor(f"prayer.{name}", _prayer_resolver(name))


class _SunProviderProxy:
    def __getattr__(self, name: str) -> Anchor:
        allowed = {"sunrise", "sunset"}
        if name not in allowed:
            raise AttributeError(f"Unknown sun anchor '{name}'")
        from .anchor import NamedAnchor

        return NamedAnchor(f"sun.{name}", _sun_resolver(name))


def _prayer_resolver(name: str):
    def resolve(ctx: DayContext):
        schedule = ctx.prayer.schedule(ctx)
        return getattr(schedule, name)

    return resolve


def _sun_resolver(name: str):
    def resolve(ctx: DayContext):
        times = ctx.sun._times(ctx)  # noqa: SLF001 - internal reuse in same package
        return getattr(times, name)

    return resolve


#: The module-level prayer anchor group (``prayer.fajr``, ``prayer.dhuhr``, ...).
prayer = _PrayerProviderProxy()
#: The module-level sun anchor group (``sun.sunrise``, ``sun.sunset``).
sun = _SunProviderProxy()

__all__ = [
    "Anchor",
    "DerivedAnchor",
    "FixedAnchor",
    "FunctionAnchor",
    "NamedAnchor",
    "DayContext",
    "PrayerGate",
    "SunGate",
    "PlanError",
    "Task",
    "Todo",
    "Alarm",
    "AlarmError",
    "AlarmSettings",
    "WakeAlarmPolicy",
    "alarm",
    "coerce_alarm",
    "parse_offset",
    "Trip",
    "Whereabouts",
    "Day",
    "DayFactory",
    "Week",
    "Month",
    "CalendarPattern",
    "Plan",
    "PlanDay",
    "PlannedEvent",
    "Services",
    "Dir3Config",
    "HijriDate",
    "HomeSettings",
    "SilaRahimSettings",
    "Relative",
    "ACTIVITY_LEVELS",
    "DietProfile",
    "NutritionTarget",
    "MealPlan",
    "MealPlanEntry",
    "MealPlanSettings",
    "ShoppingItem",
    "ShoppingList",
    "ShoppingRun",
    "ShoppingSettings",
    "avoid_terms",
    "basal_metabolic_rate",
    "build_shopping_list",
    "daily_calorie_target",
    "max_carbs_per_meal",
    "nutrition_targets",
    "plan_meals",
    "recipe_allowed",
    "shopping_task",
    "Whom",
    "select_relatives",
    "sila_rahim",
    "sila_rahim_events",
    "under",
    "MealSettings",
    "Ingredient",
    "Recipe",
    "RecipeBook",
    "ImportStats",
    "HaramIngredientError",
    "DEFAULT_RECIPE_DB",
    "PROJECT_RECIPE_DB",
    "EnrichmentStats",
    "NutritionEstimate",
    "enrich_database",
    "estimate_recipe",
    "lookup_food",
    "TARGET_REGIONS",
    "find_haram",
    "normalize_region",
    "region_for_cuisines",
    "parse_amount",
    "parse_ingredient_line",
    "parse_servings",
    "parse_kcal",
    "parse_minutes",
    "NightSettings",
    "FixedPrayer",
    "PrayerPlanSettings",
    "PrayerPlanner",
    "hijri_date",
    "is_ayyam_al_biyd",
    "is_ramadan",
    "is_eid_al_fitr",
    "is_eid_al_adha",
    "is_day_of_arafah",
    "is_qurban",
    "is_tashreeq",
    "is_fasting_forbidden",
    "is_fasting_day",
    "is_voluntary_fast",
    "is_sunnah_fast",
    "is_ashura",
    "is_tasu_a",
    "is_muharram",
    "is_shaban",
    "is_shawwal",
    "is_first_nine_dhul_hijjah",
    "is_last_ten_nights",
    "is_laylat_al_qadr_candidate",
    "sunnah_fast_name",
    "SunnahFastSettings",
    "DEFAULT_VOLUNTARY_FAST_WEEKDAYS",
    "RamadanSettings",
    "suhoor",
    "iftar",
    "tarawih",
    "ramadan_events",
    "QurbanSettings",
    "eid_prayer",
    "qurban_sacrifice",
    "qurban_distribution",
    "qurban_events",
    "RawatibSettings",
    "WitrSettings",
    "AwwabinSettings",
    "DuhaSettings",
    "AdhkarSettings",
    "QuranSettings",
    "EidFitrSettings",
    "ItikafSettings",
    "QiyamSettings",
    "rawatib_events",
    "witr",
    "awwabin",
    "duha",
    "morning_adhkar",
    "evening_adhkar",
    "adhkar_events",
    "quran",
    "eid_fitr_prayer",
    "eid_fitr_events",
    "itikaf",
    "itikaf_events",
    "qiyam",
    "laylat_al_qadr_qiyam",
    "breakfast",
    "night_events",
    "AFTER_TAHAJJUD",
    "BALANCED",
    "BEFORE_SLEEP",
    "LONG",
    "SHORT",
    "SeasonSettings",
    "SleepPlanSettings",
    "classify_night",
    "sleep_plan",
    "dinner_after_homecoming",
    "shower_after_homecoming",
    "shower_before",
    "cleanup_after_dinner",
    "where_am_i",
    "Route",
    "TravelSettings",
    "route_way",
    "route_end",
    "LocationSettings",
    "PrayerSettings",
    "TransitSettings",
    "SyncSettings",
    "GoogleCalendar",
    "ColorPolicy",
    "IconPolicy",
    "AVOCADO_SLOT",
    "BASIL_SLOT",
    "FLAMINGO_SLOT",
    "LEMON_SLOT",
    "MANDARIN_SLOT",
    "MANGO_SLOT",
    "PISTACHIO_SLOT",
    "TOMATO_SLOT",
    "DefaultIconPolicy",
    "DictColorPolicy",
    "GCalColor",
    "PlainPolicy",
    "PrayerColorPolicy",
    "PrayerStatusColorPolicy",
    "BasilPistazienColorPolicy",
    "icon_policy_chain",
    "event_summary",
    "shorten_event_name",
    "to_gcal_color_id",
    "TransitGate",
    "TransitJourney",
    "TransitLeg",
    "TransitService",
    "TransitStop",
    "rains",
    "anchor",
    "register",
    "all_anchors",
    "named_anchor",
    "next_event",
    "task",
    "day",
    "going",
    "week",
    "month",
    "calendar",
    "compile",
    "prayer",
    "sun",
    "midnight",
    "next_day_start",
    "render_plan",
    "parse_hhmm",
    "parse_duration",
    "format_time",
    "format_minutes",
    "format_duration",
    "to_minutes",
    "time_from_minutes",
    "add_time",
    "subtract_time",
]
