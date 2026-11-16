"""Icon-Policy und Namensverkürzung."""

import sys
from pathlib import Path

# Füge das src-Verzeichnis hinzu, damit dir3 importierbar ist
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dir3.color import (  # noqa: E402
    BASIL_SLOT,
    FLAMINGO_SLOT,
    PISTACHIO_SLOT,
    TOMATO_SLOT,
    BasilPistazienColorPolicy,
    DefaultIconPolicy,
    IconPolicy,
    event_summary,
    icon_policy_chain,
    name_slot,
    shorten_event_name,
    to_gcal_color_id,
)

ICONS = DefaultIconPolicy()
COLORS = BasilPistazienColorPolicy()


class TestIconPolicy:
    """Icon-Zuordnung nach Event-Art."""

    def test_prayer_icons(self):
        """Gebete bekommen 🕋, in der Moschee 🕌 und allein 🧍‍♂️."""
        prayer_names = [
            "Fajr",
            "Sunrise",
            "Dhuhr",
            "Asr",
            "Maghrib",
            "Isha",
            "Tahajjud",
            "Tarawih",
            "Duhr",
            "Asr (verschoben: Adhan 14:14 → 15:48)",
        ]
        for name in prayer_names:
            assert ICONS.icon_for(name, 0) == "🕋", f"{name} should get 🕋"

        assert ICONS.icon_for("Fajr (Moschee)", 0) == "🕌"
        assert ICONS.icon_for("Asr (Moschee, Farz)", 0) == "🕌"
        assert ICONS.icon_for("Jumuah", 0) == "🕌"
        assert ICONS.icon_for("Jumuah (verschoben: Adhan 11:55 → 12:30)", 0) == "🕌"
        assert ICONS.icon_for("Isha (allein)", 0) == "🧍‍♂️"
        assert ICONS.icon_for("Isha (allein, Farz)", 0) == "🧍‍♂️"

    def test_lecture_icons(self):
        """Vorlesungen/Übungen bekommen 🏫 - per Keyword oder Kursnummer."""
        lecture_names = [
            "EN 732 ROBS (Uebung, Marvin)",
            "A053 ROBS (Uebung)",
            "Vorlesung: Mathematik",
            "Übung Analysis",
            "Seminar: Thema XY",
            "Lab 3",
            "Bib Spandau GldP (Selbstlernen)",
            "HE101 AnalinA (Winkert)",  # Kursnummer ohne Keyword
        ]
        for name in lecture_names:
            assert ICONS.icon_for(name, 0) == "🏫", f"{name} should get 🏫"

    def test_meal_icons(self):
        """Suhoor, Frühstück und Abendessen bekommen 🍽️."""
        for name in ("Suhoor", "Suhoor 🌕️", "Iftar", "Frühstück", "Abendessen", "Abendsessen"):
            assert ICONS.icon_for(name, 0) == "🍽️", f"{name} should get 🍽️"

    def test_routine_icons(self):
        """Schlafen, Kochen und Netzwerken haben eigene Marker."""
        assert ICONS.icon_for("Schlafen", 0) == "🌙"
        assert ICONS.icon_for("Mittagsschlaf", 0) == "🌙"
        assert ICONS.icon_for("Kochen", 0) == "🍳"
        assert ICONS.icon_for("Netzwerken", 0) == "🕸️"
        assert ICONS.icon_for("Coding", 0) == ""

    def test_travel_icons(self):
        """Wege bekommen 🛣️."""
        travel_names = [
            "Weg: Mertensstr. >> Berlin, Galenstr. BUS 136",
            "Travel to university",
            "Fahrt nach Hause",
            "Weg: A >> B",
            "Commute",
        ]
        for name in travel_names:
            assert ICONS.icon_for(name, 0) == "🛣️", f"{name} should get 🛣️"

    def test_event_summary_includes_icon(self):
        """event_summary kombiniert Icon und (gekürzten) Namen."""
        assert event_summary("Fajr", ICONS, 0) == "🕋 Fajr"
        assert (
            event_summary("EN 732 ROBS (Uebung, Marvin)", ICONS, 0) == "🏫 EN732 ROBS (Ü, Marvin)"
        )
        assert event_summary("HE101 AnalinA (Winkert)", ICONS, 0) == "🏫 HE101 AnalinA (Winkert)"
        assert (
            event_summary("Weg: Mertensstr. >> Berlin", ICONS, 0) == "🛣️ Weg: Mertensstr. >> Berlin"
        )
        assert event_summary("Schlafen", ICONS, 0) == "🌙 Schlafen"
        assert event_summary("Kochen", ICONS, 0) == "🍳 Kochen"
        assert event_summary("Netzwerken", ICONS, 0) == "🕸️ Netzwerken"

    def test_event_summary_replaces_mode_with_icon(self):
        """🕌/🧍‍♂️ ersetzen das redundante Moschee/allein im Titel."""
        assert event_summary("Fajr (Moschee)", ICONS, 0) == "🕌 Fajr"
        assert event_summary("Isha (allein, Farz)", ICONS, 0) == "🧍‍♂️ Isha (Farz)"
        assert event_summary("Maghrib (⛓️‍💥, allein, Farz)", ICONS, 0) == (
            "🧍‍♂️ Maghrib (⛓️‍💥, Farz)"
        )
        assert (
            event_summary("Dhuhr (Moschee, Farz, 4 min von der Vorlesung)", ICONS, 0)
            == "🕌 Dhuhr (Farz, 4 min von der V)"
        )
        assert (
            event_summary("Jumuah (verschoben: Adhan 11:55 → 12:30)", ICONS, 0)
            == "🕌 Jumuah (verschoben 11:55→12:30)"
        )

    def test_icon_policy_api(self):
        """Eigene Marker per Konstruktor, Trait ohne Vererbung, Chain."""
        custom = DefaultIconPolicy(
            prayers="☪",
            lectures="📚",
            travel="🚌",
            food="🍴",
            mosque="🏛️",
            alone="👤",
            sleep="😴",
            cooking="🥘",
            networking="🔗",
        )
        assert custom.icon_for("Fajr", 0) == "☪"
        assert custom.icon_for("Fajr (Moschee)", 0) == "🏛️"
        assert custom.icon_for("Fajr (allein)", 0) == "👤"
        assert custom.icon_for("Übung Analysis", 0) == "📚"
        assert custom.icon_for("Weg: A >> B", 0) == "🚌"
        assert custom.icon_for("Suhoor", 0) == "🍴"
        assert custom.icon_for("Schlafen", 0) == "😴"
        assert custom.icon_for("Kochen", 0) == "🥘"
        assert custom.icon_for("Netzwerken", 0) == "🔗"
        assert isinstance(custom, IconPolicy)

        class SleepIcons:
            def icon_for(self, name, index):
                return "😴" if name == "Schlafen" else ""

        assert isinstance(SleepIcons(), IconPolicy)
        chain = icon_policy_chain(SleepIcons(), ICONS)
        assert chain.icon_for("Schlafen", 0) == "😴"
        assert chain.icon_for("Fajr", 0) == "🕋"

    def test_event_summary_without_policy(self):
        """Ohne Policy bleibt der Name ohne Icon und ohne Modus-Kürzung."""
        assert event_summary("Fajr") == "Fajr"
        assert event_summary("Fajr (Moschee)") == "Fajr (Moschee)"
        assert event_summary("") == ""
        assert event_summary(None) == ""

    def test_icon_policy_chain_first_marker_wins(self):
        """Eigene Icons schlagen die Defaults, leere Marker fallen durch."""

        class SleepIcons:
            def icon_for(self, name, index):
                return "😴" if "schlaf" in name.lower() else ""

        chain = icon_policy_chain(SleepIcons(), ICONS)
        assert chain.icon_for("Schlafen", 0) == "😴"
        assert chain.icon_for("Fajr", 0) == "🕋"
        assert chain.icon_for("Fajr (Moschee)", 0) == "🕌"
        assert event_summary("Fajr (Moschee)", chain) == "🕌 Fajr"
        assert chain.icon_for("Coding", 0) == ""


class TestNameShortener:
    """Namensverkürzung lässt wichtige Info unangetastet."""

    def test_lecture_names_are_compacted(self):
        """Kursnummern und Vorlesungsarten werden kompakt, Details bleiben."""
        assert shorten_event_name("EN 732 ROBS (Uebung, Marvin)") == "EN732 ROBS (Ü, Marvin)"
        assert shorten_event_name("HE101 AnalinA (Winkert)") == "HE101 AnalinA (Winkert)"
        assert shorten_event_name("MA 751 IaD (Uebung)") == "MA751 IaD (Ü)"
        assert shorten_event_name("Vorlesung: Mathematik") == "V: Mathematik"
        assert shorten_event_name("Seminar: Thema XY") == "S: Thema XY"

    def test_travel_names_keep_all_stops(self):
        assert (
            shorten_event_name("Weg: Mertensstr. >> Berlin, Galenstr. BUS 136")
            == "Weg: Mertensstr. >> Berlin, Galenstr. BUS136"
        )
        assert (
            shorten_event_name("Weg: Mertensstr. >> Berlin, Galenstr.")
            == "Weg: Mertensstr. >> Berlin, Galenstr."
        )

    def test_prayer_status_names_are_compacted(self):
        """Status + Zeiten bleiben, nur das redundante Wort Adhan fällt weg."""
        assert shorten_event_name("Fajr (Moschee)") == "Fajr (Moschee)"
        assert (
            shorten_event_name("Asr (verschoben: Adhan 14:14 → 15:48)")
            == "Asr (verschoben 14:14→15:48)"
        )
        assert (
            shorten_event_name("Asr (Kerahat, noch 42 min bis Maghrib-Adhan)")
            == "Asr (Kerahat, noch 42 min bis Maghrib)"
        )

    def test_empty_name(self):
        assert shorten_event_name("") == ""
        assert shorten_event_name(None) == ""


class TestBasilPistazienColorPolicy:
    """Farbgebung für verschobene Gebete."""

    def test_am_adhan_im_moschee_basilikum(self):
        """Am Adhan in der Moschee: Basilikum - GCal Basil (10)."""
        assert COLORS.color_for("Fajr (Moschee)", 0) == BASIL_SLOT
        assert COLORS.color_for("Dhuhr (Moschee, Farz)", 0) == BASIL_SLOT
        assert to_gcal_color_id(BASIL_SLOT) == "10"

    def test_verschoben_im_moschee_pistazie(self):
        """Verschoben in der Moschee: Pistazie - GCal Sage (2)."""
        assert (
            COLORS.color_for("Asr (Moschee, verschoben: Adhan 14:00 → 15:50)", 0) == PISTACHIO_SLOT
        )
        assert (
            COLORS.color_for("Dhuhr (Moschee, verschoben: Adhan 11:56 → 11:58)", 0)
            == PISTACHIO_SLOT
        )
        assert COLORS.color_for("Jumuah (verschoben: Adhan 11:55 → 12:30)", 0) == PISTACHIO_SLOT
        assert to_gcal_color_id(PISTACHIO_SLOT) == "2"

    def test_allein_flamingo(self):
        """Allein gebetet: Flamingo - GCal Flamingo (4), auch verschoben."""
        assert COLORS.color_for("Fajr", 0) == FLAMINGO_SLOT
        assert COLORS.color_for("Tahajjud", 0) == FLAMINGO_SLOT
        assert COLORS.color_for("Fajr (allein)", 0) == FLAMINGO_SLOT
        assert COLORS.color_for("Isha (allein, Farz)", 0) == FLAMINGO_SLOT
        assert (
            COLORS.color_for("Maghrib (allein, verschoben: Adhan 16:42 → 17:48)", 0)
            == FLAMINGO_SLOT
        )
        assert to_gcal_color_id(FLAMINGO_SLOT) == "4"

    def test_im_kerahat_tomate(self):
        """Dringendes Kerahat ist rot - GCal Tomato (11), auch in der Moschee."""
        assert COLORS.color_for("Asr (Kerahat, noch 42 min bis Maghrib-Adhan)", 0) == TOMATO_SLOT
        assert (
            COLORS.color_for("Asr (Moschee, Farz, Kerahat, noch 42 min bis Maghrib-Adhan)", 0)
            == TOMATO_SLOT
        )
        assert to_gcal_color_id(TOMATO_SLOT) == "11"

    def test_kritisch_tomate(self):
        """Kritisch: Tomate - GCal Tomato (11), auch verschoben/allein."""
        assert COLORS.color_for("Maghrib (kritisch, noch 14 min bis Isha-Adhan)", 0) == TOMATO_SLOT
        assert (
            COLORS.color_for(
                "Isha (⛓️‍💥, allein, Farz, kritisch, noch 12 min bis Fajr-Adhan)",
                0,
            )
            == TOMATO_SLOT
        )
        assert to_gcal_color_id(TOMATO_SLOT) == "11"

    def test_fallback_to_name_hash(self):
        """Nicht-Gebets-Events fallen auf den Namen-Hash zurück."""
        assert COLORS.color_for("Coding", 0) == name_slot("Coding")
        assert COLORS.color_for("Reading", 0) == name_slot("Reading")
