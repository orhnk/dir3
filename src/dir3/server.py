"""``dir3 serve`` - the bridge between the PC and the Android app.

The phone is deliberately *not* a second compiler.  The PC keeps compiling the
Python plan, and this small LAN server exposes it:

* ``GET  /api/plan``    compiled plan + resolved alarms as JSON;
* ``GET  /api/files``   editable plan code (planfile, ``plan/``, ``examples/``);
* ``GET  /api/file``    one file's source;
* ``PUT  /api/file``    save source (atomic write + backup);
* ``POST /api/run``     run a whitelisted dir3 command (compile/sync/clear);
* ``GET/POST/DELETE /api/events``  one-off events created on the phone;
* ``GET  /``            the same web UI the Android app bundles.

Security is LAN-grade on purpose: a random token (printed on startup, passed as
``?token=`` or ``X-Dir3-Token``), path traversal guards, and a command
whitelist.  It binds to all interfaces so the phone can reach it; use
``--host 127.0.0.1`` to keep it local.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .alarm import AlarmError, coerce_alarm
from .export import Runtime, load_runtime, runtime_document

PHONE_UI = Path(__file__).with_name("phone_ui")
#: Directories (relative to the planfile) the phone editor may touch.
EDITABLE_DIRS = ("", "plan", "examples", "days", "weeks", "templates")
EDITABLE_SUFFIXES = (".py", ".json", ".md", ".txt")
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".ruff_cache",
    ".pytest_cache", "data", "src", "tests", "android", ".android-sdk", "result",
}
MAX_FILE_BYTES = 512 * 1024
PLAN_CACHE_SECONDS = 45.0


class PhoneEventStore:
    """One-off events created on the phone, stored next to the planfile."""

    def __init__(self, base_dir: Path) -> None:
        self.base = base_dir
        self.path = base_dir / ".dir3" / "phone_events.json"
        self._lock = threading.Lock()

    def load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(raw, dict):
            raw = raw.get("events", [])
        return [item for item in raw if isinstance(item, dict)]

    def save(self, events: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            self.path,
            json.dumps({"schema": 1, "events": events}, ensure_ascii=False, indent=2) + "\n",
        )

    def upsert(self, item: dict[str, Any]) -> dict[str, Any]:
        event = _normalize_phone_event(item)
        with self._lock:
            events = self.load()
            existing = {str(entry.get("id")): index for index, entry in enumerate(events)}
            event_id = str(event.get("id") or "")
            if event_id and event_id in existing:
                event["id"] = event_id
                events[existing[event_id]] = event
            else:
                event["id"] = event_id or uuid.uuid4().hex[:16]
                events.append(event)
            self.save(events)
        return event

    def delete(self, event_id: str) -> bool:
        with self._lock:
            events = self.load()
            kept = [entry for entry in events if str(entry.get("id")) != event_id]
            if len(kept) == len(events):
                return False
            self.save(kept)
        return True


def _normalize_phone_event(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Event muss ein JSON-Objekt sein")
    title = str(item.get("title") or item.get("name") or "").strip()
    if not title:
        raise ValueError("Event braucht einen Titel")
    if len(title) > 200:
        raise ValueError("Titel ist zu lang (max. 200 Zeichen)")
    try:
        event_date = date.fromisoformat(str(item.get("date")))
    except ValueError:
        raise ValueError("date muss YYYY-MM-DD sein") from None
    start = _clock(item.get("start"), "start")
    # An end before the start means the event runs past midnight; the
    # exporter rolls it to the next day.
    end = _clock(item.get("end"), "end") if item.get("end") else None
    notes = str(item.get("notes") or "")[:4000]
    raw_alarms = item.get("alarms", item.get("alarm"))
    parsed = coerce_alarm(raw_alarms) or ()
    return {
        "id": str(item.get("id") or ""),
        "title": title,
        "date": event_date.isoformat(),
        "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M") if end is not None else None,
        "color": str(item.get("color") or ""),
        "notes": notes,
        "alarms": [spec.to_dict() for spec in parsed],
    }


def _clock(value: object, field: str):
    text = str(value or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"{field} muss HH:MM sein")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".dir3-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _looks_secret(path: Path) -> bool:
    """True for files that carry OAuth credentials (never shown on the phone)."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(
        marker in text
        for marker in ("refresh_token", "client_secret", "access_token")
    )


def _editable_files(base: Path) -> list[Path]:
    found: list[Path] = []
    for relative in EDITABLE_DIRS:
        root = base / relative
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.py")):
            if path.is_file() and path not in found and not _looks_secret(path):
                found.append(path)
        if relative:
            for path in sorted(root.rglob("*.py")):
                if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
                    continue
                if (
                    path.is_file()
                    and path not in found
                    and not _looks_secret(path)
                ):
                    found.append(path)
    for suffix in EDITABLE_SUFFIXES[1:]:
        for path in sorted(base.glob(f"*{suffix}")):
            if path.is_file() and path not in found:
                found.append(path)
    try:
        return sorted(found, key=lambda item: item.relative_to(base).as_posix())
    except ValueError:  # pragma: no cover - defensive
        return sorted(found)


class Dir3Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        runtime: Runtime,
        token: str | None,
        debug: bool = False,
    ) -> None:
        super().__init__(address, Dir3Handler)
        self.runtime = runtime
        self.token = token
        self.debug = debug
        self.base = runtime.planfile.resolve().parent
        self.store = PhoneEventStore(self.base)
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


class Dir3Handler(BaseHTTPRequestHandler):
    server: Dir3Server

    # -- plumbing ---------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # keep the terminal calm
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    def _authorized(self) -> bool:
        if not self.server.token:
            return True
        supplied = self.headers.get("X-Dir3-Token", "")
        if not supplied:
            supplied = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return secrets.compare_digest(supplied, self.server.token)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Dir3-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_FILE_BYTES:
            raise ValueError("Anfrage ist zu gross")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Body muss gueltiges JSON sein") from None
        if not isinstance(value, dict):
            raise ValueError("Body muss ein JSON-Objekt sein")
        return value

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(HTTPStatus.NO_CONTENT, b"", "text/plain")

    # -- routes -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        # The UI itself is public (it contains no data); every API call needs
        # the token.  Relative asset URLs like /style.css must not 401, or a
        # browser/PWA opened with ?token= would render unstyled and dead.
        if not path.startswith("/api/"):
            relative = path.lstrip("/") or "index.html"
            if relative.startswith("static/"):
                relative = relative[len("static/"):]
            return self._static(relative)
        if not self._authorized():
            return self._error(HTTPStatus.UNAUTHORIZED, "Token fehlt oder ist falsch")
        try:
            if path == "/api/ping":
                return self._json(200, {"ok": True, "app": "dir3", "schema": 1})
            if path == "/api/status":
                return self._status()
            if path == "/api/plan":
                return self._plan(parse_qs(parsed.query))
            if path == "/api/files":
                return self._files()
            if path == "/api/file":
                return self._read_file(parse_qs(parsed.query))
            if path == "/api/events":
                return self._json(200, {"ok": True, "events": self.server.store.load()})
        except (ValueError, AlarmError, FileNotFoundError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # pragma: no cover - unexpected
            if self.server.debug:
                traceback.print_exc()
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")
        self._error(HTTPStatus.NOT_FOUND, f"unbekannter Pfad {path}")

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._error(HTTPStatus.UNAUTHORIZED, "Token fehlt oder ist falsch")
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/file":
                return self._write_file(self._body())
        except (ValueError, AlarmError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # pragma: no cover
            if self.server.debug:
                traceback.print_exc()
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")
        self._error(HTTPStatus.NOT_FOUND, f"unbekannter Pfad {parsed.path}")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._error(HTTPStatus.UNAUTHORIZED, "Token fehlt oder ist falsch")
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/run":
                return self._run(self._body())
            if parsed.path == "/api/events":
                event = self.server.store.upsert(self._body())
                self._drop_cache()
                return self._json(200, {"ok": True, "event": event})
        except (ValueError, AlarmError, FileNotFoundError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # pragma: no cover
            if self.server.debug:
                traceback.print_exc()
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")
        self._error(HTTPStatus.NOT_FOUND, f"unbekannter Pfad {parsed.path}")

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._error(HTTPStatus.UNAUTHORIZED, "Token fehlt oder ist falsch")
        parsed = urlparse(self.path)
        if parsed.path != "/api/events":
            return self._error(HTTPStatus.NOT_FOUND, f"unbekannter Pfad {parsed.path}")
        event_id = (parse_qs(parsed.query).get("id") or [""])[0]
        if not event_id:
            return self._error(HTTPStatus.BAD_REQUEST, "id fehlt")
        try:
            deleted = self.server.store.delete(event_id)
        except OSError as exc:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
        if not deleted:
            return self._error(HTTPStatus.NOT_FOUND, "Event nicht gefunden")
        self._drop_cache()
        return self._json(200, {"ok": True})

    # -- handlers ---------------------------------------------------------
    def _status(self) -> None:
        runtime = self.server.runtime
        return self._json(
            200,
            {
                "ok": True,
                "app": "dir3",
                "schema": 1,
                "planfile": str(runtime.planfile),
                "base": str(self.server.base),
                "host": socket.gethostname(),
                "time": datetime.now().isoformat(),
                "auth": bool(self.server.token),
                "title": getattr(runtime.module, "__title__", None),
            },
        )

    def _plan(self, query: dict[str, list[str]]) -> None:
        def param(name: str) -> str | None:
            return (query.get(name) or [None])[0]

        until_raw = param("until")
        until = int(until_raw) if until_raw else None
        start_raw = param("from")
        start = date.fromisoformat(start_raw) if start_raw else None
        no_alarms = param("no_alarms") in ("1", "true", "yes")
        offline = param("offline") in ("1", "true", "yes")
        refresh = param("refresh") in ("1", "true", "yes")
        key = (until, start, no_alarms, offline)
        now = time.monotonic()
        with self.server._lock:
            cached = self.server._cache.get(key)
            if cached and not refresh and now - cached[0] < PLAN_CACHE_SECONDS:
                return self._json(200, cached[1])
            runtime = self.server.runtime
            if offline and runtime.config.prayer.provider != "offline":
                runtime = load_runtime(runtime.planfile, offline=True)
                self.server.runtime = runtime
            document = runtime_document(
                runtime,
                until=until,
                start=start,
                no_alarms=no_alarms,
                phone_events=self.server.store.load(),
            )
            self.server._cache[key] = (now, document)
        return self._json(200, document)

    def _files(self) -> None:
        base = self.server.base
        result = []
        for path in _editable_files(base):
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append(
                {
                    "path": path.relative_to(base).as_posix(),
                    "name": path.name,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
        return self._json(200, {"ok": True, "files": result, "editable": EDITABLE_SUFFIXES})

    def _resolve_file(self, raw: str) -> Path:
        base = self.server.base
        if not raw or not str(raw).strip():
            raise ValueError("path fehlt")
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (base / candidate).resolve()
        planfile = self.server.runtime.planfile.resolve()
        if resolved != planfile and not _inside(base, resolved):
            raise ValueError("Pfad liegt ausserhalb des Projektordners")
        if resolved.suffix.lower() not in EDITABLE_SUFFIXES:
            raise ValueError(f"nur {', '.join(EDITABLE_SUFFIXES)} bearbeitbar")
        if resolved != planfile:
            if resolved.exists() and _looks_secret(resolved):
                raise ValueError(
                    "Datei enthaelt Zugangsdaten und ist fuer den Editor gesperrt"
                )
            relative = resolved.relative_to(base)
            if any(part in SKIP_DIRS for part in relative.parts):
                raise ValueError("dieser Ordner ist vom Editor ausgeschlossen")
            if relative.parent.as_posix() not in EDITABLE_DIRS:
                # allow nested plan/ and examples/ directories
                if relative.parent.as_posix() != "." and not any(
                    relative.parent.as_posix() == entry
                    or relative.parent.as_posix().startswith(entry + "/")
                    for entry in EDITABLE_DIRS
                    if entry
                ):
                    raise ValueError("Datei ist nicht als Plan-Code freigegeben")
        return resolved

    def _read_file(self, query: dict[str, list[str]]) -> None:
        raw = (query.get("path") or [""])[0]
        path = self._resolve_file(raw)
        if not path.exists():
            raise FileNotFoundError(f"Datei existiert nicht: {raw}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Datei ist zu gross fuer den Editor (max. 512 KiB)")
        text = path.read_text(encoding="utf-8")
        return self._json(
            200,
            {
                "ok": True,
                "path": path.relative_to(self.server.base).as_posix(),
                "text": text,
                "mtime": path.stat().st_mtime,
            },
        )

    def _write_file(self, body: dict[str, Any]) -> None:
        raw = str(body.get("path") or "")
        path = self._resolve_file(raw)
        if "text" not in body or not isinstance(body["text"], str):
            raise ValueError("text fehlt")
        text = body["text"]
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Datei ist zu gross (max. 512 KiB)")
        backup = None
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_dir = self.server.base / ".dir3" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{stamp}-{path.name}"
            shutil.copy2(path, backup)
        _atomic_write(path, text)
        self._drop_cache()
        return self._json(
            200,
            {
                "ok": True,
                "path": path.relative_to(self.server.base).as_posix(),
                "backup": backup.name if backup else None,
                "bytes": len(text.encode("utf-8")),
            },
        )

    def _drop_cache(self) -> None:
        with self.server._lock:
            self.server._cache.clear()

    def _run(self, body: dict[str, Any]) -> None:
        action = str(body.get("action") or "compile").strip().lower()
        flags = {
            "compile": ["--compile"],
            "sync": ["--sync"],
            "clear": ["--clear", "--yes"],
        }
        if action not in flags:
            raise ValueError("action muss compile, sync oder clear sein")
        command = [sys.executable, "-m", "dir3", str(self.server.runtime.planfile), *flags[action]]
        until = body.get("until")
        if until not in (None, ""):
            command.extend(["--until", str(int(until))])
        start = body.get("from")
        if start:
            date.fromisoformat(str(start))  # validate
            command.extend(["--from", str(start)])
        if body.get("offline"):
            command.append("--offline")
        if body.get("dry_run"):
            command.append("--dry-run")
        env = dict(os.environ)
        src = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(src), env.get("PYTHONPATH", "")) if part
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.server.base),
                capture_output=True,
                text=True,
                timeout=240,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return self._json(
                504,
                {"ok": False, "error": "dir3-Lauf hat zu lange gedauert (240 s)"},
            )
        output = (completed.stdout or "") + (completed.stderr or "")
        self._drop_cache()
        return self._json(
            200,
            {
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
                "action": action,
                "command": command,
                "output": output[-200_000:],
            },
        )

    def _static(self, relative: str) -> None:
        root = PHONE_UI.resolve()
        candidate = (root / relative).resolve()
        if not _inside(root, candidate) or not candidate.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "Datei nicht gefunden")
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        if candidate.suffix in (".js", ".css", ".html"):
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, candidate.read_bytes(), content_type)


def _lan_urls(port: int, token: str | None) -> list[str]:
    query = f"?token={token}" if token else ""
    hosts: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                hosts.add(address)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        hosts.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    hosts.add("127.0.0.1")
    return [f"http://{host}:{port}/{query}" for host in sorted(hosts)]


def serve_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dir3 serve",
        description="LAN-Server fuer die dir3-Android-App (Plan, Editor, CLI).",
    )
    parser.add_argument("planfile", type=Path)
    parser.add_argument("--host", default="0.0.0.0", help="Bind-Adresse (Default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port (Default: 8765)")
    parser.add_argument(
        "--token",
        default=None,
        help="Zugangstoken (Default: zufaellig, wird angezeigt)",
    )
    parser.add_argument("--no-auth", action="store_true", help="Kein Token (nur im eigenen Netz)")
    parser.add_argument("--offline", action="store_true", help="Gebetszeiten offline")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--debug", action="store_true", help="Volle Tracebacks")
    args = parser.parse_args(argv)

    if not args.planfile.exists():
        parser.error(f"Planfile existiert nicht: {args.planfile}")
    token = None if args.no_auth else (args.token or secrets.token_urlsafe(12))
    runtime = load_runtime(args.planfile, config_path=args.config, offline=args.offline)
    server = Dir3Server(
        (args.host, args.port), runtime=runtime, token=token, debug=args.debug
    )
    print(f"dir3 serve - {runtime.planfile}")
    print(f"Token: {token or '(kein Token)'}")
    for url in _lan_urls(args.port, token):
        print(f"  {url}")
    print("Android-App: URL und Token in den Einstellungen eintragen.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(serve_main())
