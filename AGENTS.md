# Project knowledge

This file gives Codebuff context about your project: goals, commands, conventions, and gotchas.

## Quickstart
- Setup: `python -m venv .venv && . .venv/bin/activate && pip install -e .[dev]`
- Dev: `dir3 examples/pray_week.py --compile` (or `nix develop`)
- Test: `python -m pytest tests/` and `ruff check src tests examples`
- Phone: `dir3 serve gebetsplan.py` (LAN server); APK: `cd android && ./gradlew assembleDebug`

## Architecture
- Key directories:
  - `src/dir3/` — the engine and all generic scheduling logic. Planfiles stay small.
  - `src/dir3/alarm.py` — portable `Alarm` spec + `WakeAlarmPolicy` (Fajr/Tahajjud/Suhoor auto alarms, chain dedupe).
  - `src/dir3/export.py` — plan → phone JSON (events, hex colours, resolved alarm triggers); also `dir3 export`.
  - `src/dir3/server.py` — `dir3 serve`: plan/file/event API, token auth, whitelisted CLI runner.
  - `src/dir3/phone_ui/` — the single web UI (calendar via Toast UI Calendar, editor via CodeMirror). Served by the Python server **and** copied into the APK as assets.
  - `android/` — native Kotlin shell: WebView host, `AlarmManager` scheduling, foreground alarm service, TTS, full-screen alarm activity. No AndroidX dependencies.
- Data flow: planfile → `compile_pattern` → `alarm.apply_wake_alarms` per day → `Plan` → `plan_to_dict` → `/api/plan` → phone cache → `AlarmScheduler`.
- Phone edits flow back via `PUT /api/file` (atomic write + `.dir3/backups/`). One-off phone events live in `.dir3/phone_events.json` and are merged at export time.

## Conventions
- Formatting/linting: ruff (line length 100), pytest. Keep the Android app dependency-free; it is plain `android.app.*` + `org.json`.
- Patterns to follow: Generic scheduling logic belongs in `src/dir3` (e.g. `prayerplan`, `night`, `islamic`, `intervals`, `whereabouts`, `home`, `alarm`); plan files stay small: data, settings and day composition only.
- Alarm semantics live in `src/dir3/alarm.py`; never hard-code Fajr/Tahajjud names in the engine or the app.
- The web UI lives only in `src/dir3/phone_ui/`; `android/app/build.gradle.kts` points its assets at that directory. Do not copy it into `android/`.
- Things to avoid: adding AndroidX/Compose just for a small widget; duplicating the calendar or editor in Kotlin; putting server credentials in the repo.
