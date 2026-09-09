# dir3

> Arabisch درع (Rüstung, Panzer, Schild) — the tool for discipline.

**dir3 turns your life into a program.** You *time-program* your days: instead of
a rigid list of appointments, you write a Python function that *decides* what
happens — and everything is anchored to real events, soft and adjustable.

The red thread: **your life is a function.** Any function you write can become a
time anchor with `@anchor`. The engine then compiles your day/week/month or your
whole calendar into a concrete printable plan.

## Quickstart

```bash
# run a plan file
dir3 examples/schlafen.py                 # next 30 days (default)
dir3 examples/lebensjahr.py --until 365   # one whole year
dir3 examples/lebensjahr.py --from 2026-03-01
dir3 examples/ramadan.py --offline        # prayer times offline, no network
dir3 examples/dir3.py --sync-gcal         # + push the plan into Google Calendar
```

Python ≥ 3.10 ist nötig (ZoneInfo, Dataclass-Slots). Installation und Start:

```bash
# Variante 1 - pip (funktioniert auf jedem Rechner)
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]

# Variante 2 - Nix
nix develop                       # dev shell with all deps + PYTHONPATH=src
nix build                         # installs the `dir3` binary + runs the tests
```

Abhängigkeiten: `requests`, `httpx` (nur für den Google-Calendar-Sync) und
`tzdata` (damit `ZoneInfo` auch ohne System-tzdb auf Windows/Slim-Containern
stabil ist). Wird der Standort nirgends gesetzt, ermittelt ihn dir3 per
Geolocation und cached das Ergebnis (TTL 6 h).

**Kein Config-File** — alles lebt im Python-Planfile. Der Standort bestimmt
sich automatisch per Geolocation (ipapi.co); optional überschreibst du ihn im
Planfile, und zwar nur so viel, wie nötig:

```python
location = (40.7992, 29.4305, "Europe/Istanbul")    # lat, lon, IANA-Zeitzone
prayer   = "ezanvakti"     # "auto" | "aladhan" | "ezanvakti"/"diyanet" | "offline"
```

- Standort nicht gesetzt → selbst bestimmt (funktioniert überall);
- `prayer = "auto"` (default) — Aladhan first, offline calculator as fallback;
- `prayer = "ezanvakti"` / `"diyanet"` — offizielle türkische Diyanet-Zeiten pro
  Bezirk (Bezirk aus dem Standort aufgelöst; eine Anfrage pro Horizont);
- `prayer = "offline"` — niemals Netzwerk; `--offline` auf der CLI ist das Kürzel.

## Google Calendar sync

Der kompilierte Plan lässt sich **in Google Calendar schreiben**
(`dir3 plan.py --sync-gcal`). Die Credentials liegen — wie alles andere — im
Python-Planfile:

```python
from dir3 import GoogleCalendar

gcal = GoogleCalendar(
    client_id="…",
    client_secret="…",
    refresh_token="…",
    calendar_id="primary",   # optional, default "primary"
)
```

- OAuth2: `refresh_token` + `client_id`/`client_secret` (Token wird pro Lauf
  frisch geholt) oder direkt ein `access_token`.
- Der Sync ist **idempotent**: jedes Event bekommt eine deterministische
  Custom-ID (`dir3<sha1>`) aus Titel/Datum/Name/Zeiten — ein zweiter Lauf
  aktualisiert vorhandene Events statt zu duplizieren (POST → 409 → PUT).
- Events werden in der **Plan-Zeitzone** angelegt (mit explizitem Offset und
  IANA-Label); Carry-Events (Schlaf bis `next_event`) enden am realen
  Folge-Morgen.
- `--gcal-dry-run` zeigt nur den Umfang, ohne Netzwerk/Credentials.
- Der GCal-Code pfad nutzt **`httpx` (async)** statt der blocking-`requests`
  für den Rest von dir3.

## The idea

Nothing is carved in stone. A plan is a **function** that answers *"what kind of
day is today?"* Tasks are soft: they chain, they compress when a day overflows,
they follow sun and prayer times, and they never break because a bus was late.

```python
from dir3 import anchor, day, task
from dir3 import week as _week

@anchor
def open_exchange(ctx):            # your own anchor: "when the market opens today"
    return time(9, 0)

@day(name="Exchange Day")
def trading_day(ctx):
    return [
        task("Review news", start=time(7, 30), duration="30m"),
        task("Order run", start=open_exchange, duration="2h", flex=True),
        task("Deep Work", start=time(12, 0), until=time(17, 0), flex=True),
        task("Evening reading", duration="1h", flex=True),
        task("Sleep", until=next_event),
    ]

def make_plan():
    return _week(mon=trading_day, tue=trading_day, wed=trading_day,
                 thu=trading_day, fri=trading_day, sat=trading_day, sun=trading_day)

__title__ = "My week"
```

## DSL

**Planfile-Konfiguration** (optional, als Modul-Attribute — sonst per Autodetect):

```python
location = (40.7992, 29.4305, "Europe/Istanbul")  # hier, im Planfile - keine TOML
prayer   = "ezanvakti"                             # Gebetsquelle des Planfiles
provider = "ezanvakti"                             # Kurzform für `prayer`
```

### Task

```python
task(name, *,
     start=None, until=None, duration=None, space=None,
     unless=None, flex=True)
```

| arg | meaning |
|-----|---------|
| `start` | anchor or plain `time` that starts the task |
| `until` | anchor or `time` that ends it (wraps across midnight) |
| `duration` | `timedelta`, or a string like `"1h30m"` / `"45m"` |
| `space` | gap left *before* this task when chaining |
| `unless` | predicate or tuple of predicates; `True` skips the task that day |
| `flex` | `True` (default) → the compiler *may* shrink this task to absorb overflow |

**Flex rules of thumb:**

- `flex=True` → compressible when the day overflows.
- `flex=False` → hard block; overflow is reported loudly.
- anchored tasks (`start=`/`until=` given) are **never** shrunk, regardless of
  `flex`.
- open tasks (`flex=True`, no `until`/`duration`) stretch as slack but are never
  trimmed themselves.

### Day, week, month — patterns

```python
day("Name", task(...), task(...), start=morning_anchor)   # builder
@day(name="Mein Tag", start=time(9, 0))                   # decorator (start also works)
def my_day(ctx): return [task(...), ...]

week(mon=..., tue=..., ..., sun=...)      # one pattern per weekday
month(week_1, week_2)                     # a repeating month unit
```

The `@day(start=…)` decorator pins the day's start anchor instead of chaining the
first task.

### Calendar — your whole life as one function

`@calendar` takes a `(date) -> day_pattern | None` function. `None` = free day.
Every calendar entry is just a branch in code:

```python
@calendar
def lebensjahr(today):
    if today in PRUEFUNGEN: return pruefung
    if today in FREIE_TAGE: return None
    if today.weekday() >= 5: return wochenende
    return schul
```

See `examples/lebensjahr.py` — a full year as *one* function.

### Anchors

- `@anchor` on your own function → `(ctx) -> time`; register it and use it in any
  task.
- `midnight` / `next_day_start` (end-of-day marker).
- `next_event` — the softest anchor of all: `task("Sleep", until=next_event)`
  runs until the **first event of the next active day** (free days are skipped,
  it carries past midnight, tracks the sun for e.g. `prayer.fajr`).
- `prayer.*` — `prayer.fajr/sunrise/dhuhr/asr/maghrib/isha` (module-level
  anchors). `sun.*` — `sun.sunrise/sunset`.
- `named_anchor(...)` / `register(...)` / `all_anchors()` for manual registration.

### Context

Day functions receive a `ctx` with the date, the prayer schedule, sun times,
weather data and `ctx.schedule(ctx)` helpers:

```python
@anchor
def iftar(ctx):
    return ctx.prayer.schedule(ctx).maghrib     # fast-break with the sun
```

Predicates for `unless`, e.g. `regnet(ctx)` → weather-driven days
(see `examples/autopilot.py`).

## Engine semantics

- **Chaining:** tasks line up after each other; `space` inserts a gap.
- **Overflow:** if everything does not fit until 24:00 the compiler trims
  `flex`/unanchored tasks **from the end backwards** (only `active`, non-open,
  `flex=True`, non-anchored tasks with a duration), then reports the remainder
  as `⚠ Überlauf`.
- **Carry:** a carried event (sleep `until=next_event`) intentionally runs into
  the next morning — that is not overflow.
- **Post-midnight:** early hours (e.g. Tahajjud) and late Isha roll to the next
  day instead of erroring.
- **Pinned events** (prayers, hard blocks) never move.

## Examples

| file | shows |
|------|-------|
| `examples/schlafen.py` | `until=next_event` — sleep until tomorrow's first event |
| `examples/ramadan.py` | a day from sun/moon-derived anchors: `imsak`, `iftar` |
| `examples/autopilot.py` | data-driven plan: weather, energy log, gym hours, deadlines |
| `examples/lebensjahr.py` | one `@calendar` function for a whole year |

```bash
dir3 examples/lebensjahr.py --until 365
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
python -m pytest tests/        # 105 tests
ruff check src tests examples
```

Cross-platform: `tests/test_portability.py` simulates the machine-dependent
failure modes (legacy console encodings, missing system tzdb, read-only/corrupt
cache dirs, non-ASCII planfiles) so they fail *before* hitting a real machine.
`.github/workflows/ci.yml` runs the whole suite on ubuntu/macOS/Windows and
Python 3.10/3.12/3.14 plus a full-offline CLI smoke test.

`flake.nix` runs the tests via `pytestCheckHook` in the sandboxed build. The
output forces UTF-8 (`errors="replace"`), so rendering never dies on legacy
consoles (Windows cp1252) - set `DIR3_DEBUG=1` to see full tracebacks instead
of the compact error message.