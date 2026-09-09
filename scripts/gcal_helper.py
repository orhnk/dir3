#!/usr/bin/env python3
"""Google-Calendar-OAuth-Helfer fuer dir3 - standalone, nur Standardbibliothek.

Alles laeuft ueber den Browser: Dieses Script startet einen lokalen
Loopback-Server auf 127.0.0.1, oeffnet den Google-Login, fängt den Code ab,
tauscht ihn gegen ein refresh_token und schreibt die Zugangsdaten

    * nach ~/.gcal-helper/token.json   (fuer Wiederverwendung) und
    * optional direkt in dein Planfile (``gcal = GoogleCalendar(...)``).

Kein Teil von dir3: es importiert nichts aus dem dir3-Paket, du brauchst
nur ``python3`` (+ einen Browser).

Anleitung:
  python3 scripts/gcal_helper.py --planfile examples/gebets_woche.py
  python3 scripts/gcal_helper.py --planfile examples/gebets_woche.py --force

Fehlt die OAuth-Client-ID, oeffnet das Script die Google Console und fragt
die beiden Strings einmal am Terminal ab (sie landen in ~/.gcal-helper/client.json).
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CONSOLE_URL = "https://console.cloud.google.com/apis/credentials"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
STATE_DIR = Path.home() / ".gcal-helper"
CLIENT_FILE = STATE_DIR / "client.json"
TOKEN_FILE = STATE_DIR / "token.json"
TIMEOUT_SECONDS = 300

#: Kann hier fest eintragen werden, ersetzt dann die Console-Abfrage.
DEFAULT_CLIENT_ID = ""
DEFAULT_CLIENT_SECRET = ""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Sammelt den OAuth-Code aus dem Loopback-Redirect."""

    code: str | None = None
    done = False

    def do_GET(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = query.get("code", [None])[0]
        if _CallbackHandler.code:
            body = (
                b"<html><body><p>Anmeldung erfolgreich - "
                b"Fenster kann geschlossen werden.</p></body></html>"
            )
        else:
            body = b"<html><body><p>Anmeldung abgebrochen - zurueck zum Terminal.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _CallbackHandler.done = True

    def log_message(self, *args):  # pragma: no cover - still halten
        pass


# ---------------------------------------------------------------------------


def _load_credentials() -> tuple[str, str]:
    """client_id / client_secret - aus Env, Sidecar-Datei oder Konstanten."""
    env = (os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    if all(env):
        return env
    if CLIENT_FILE.exists():
        try:
            data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("client_id") and data.get("client_secret"):
            return data["client_id"], data["client_secret"]
    return DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET


def _store_credentials(client_id: str, client_secret: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_text(
        json.dumps({"client_id": client_id, "client_secret": client_secret}, indent=2),
        encoding="utf-8",
    )


def _ask_credentials() -> tuple[str, str]:
    print("Es fehlen noch OAuth-Credentials (einmalige Einrichtung).")
    print("In der Google Cloud Console: OAuth-Client vom Typ 'Desktopanwendung'.")
    webbrowser.open(CONSOLE_URL)
    client_id = input("  client_id: ").strip()
    client_secret = input("  client_secret: ").strip()
    if client_id and client_secret:
        _store_credentials(client_id, client_secret)
        return client_id, client_secret
    print("Abgebrochen - bitte beide Werte eintragen.", file=sys.stderr)
    raise SystemExit(1)


def _auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_browser_flow(client_id: str, no_browser: bool) -> tuple[str, str]:
    """Startet den Loopback-Server, bittet um Browser-Login und liefert
    (code, redirect_uri) zurück. Fallback: Code manuell aus der URL pasten."""
    with http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler) as server:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/"
        print("Bitte im Browser anmelden:")
        print(_auth_url(client_id, redirect_uri))
        if not no_browser:
            webbrowser.open(_auth_url(client_id, redirect_uri))

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while not _CallbackHandler.done and time.monotonic() < deadline:
            time.sleep(0.2)
        server.shutdown()
        thread.join(timeout=2.0)

    code = _CallbackHandler.code
    if not code:
        print("\nKein Redirect im Browser angekommen (z. B. anderer Rechner?).")
        raw = input("Adressleiste kopieren (die URL mit code=...): ").strip()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        code = query.get("code", [None])[0]
    if not code:
        raise SystemExit("Kein Code empfangen - Zugang nicht eingerichtet.")
    return code, redirect_uri


def _block(client_id: str, client_secret: str, refresh: str) -> str:
    return (
        "gcal = GoogleCalendar(\n"
        f"    client_id={client_id!r},\n"
        f"    client_secret={client_secret!r},\n"
        f"    refresh_token={refresh!r},\n"
        '    calendar_id="primary",\n'
        ")"
    )


_BLOCK_RE = re.compile(r"(?ms)^gcal\s*=\s*GoogleCalendar\(.*?\)\n?")


def _patch_planfile(path: Path, client_id: str, client_secret: str, refresh: str) -> bool:
    """Ersetzt einen bestehenden gcal-Block oder hängt ihn ans Planfile an,
    ergänzt dabei notfalls das GoogleCalendar-Import."""
    text = path.read_text(encoding="utf-8")
    block = _block(client_id, client_secret, refresh)

    if _BLOCK_RE.search(text):
        text = _BLOCK_RE.sub(block + "\n", text, count=1)
    else:
        import_line = re.search(r"(?m)^from dir3 import (.+)$", text)
        if import_line and "GoogleCalendar" not in import_line.group(1):
            text = (
                text[: import_line.start()]
                + f"from dir3 import {import_line.group(1)}, GoogleCalendar"
                + text[import_line.end() :]
            )
        elif import_line is None:
            text = "from dir3 import GoogleCalendar\n\n" + text
        text = text.rstrip("\n") + "\n\n" + block + "\n"

    path.write_text(text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gcal-helper",
        description="Google-Calendar-OAuth fuer dir3 - alles ueber den Browser.",
    )
    parser.add_argument("--planfile", type=Path, help="Planfile, in das gcal(...) geschrieben wird")
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht selbst oeffnen")
    parser.add_argument("--force", action="store_true", help="Browser-Flow erneut erzwingen")
    parser.add_argument("--print-token", action="store_true", help="refresh_token anzeigen")
    args = parser.parse_args(argv)

    client_id, client_secret = _load_credentials()
    if not client_id or not client_secret:
        client_id, client_secret = _ask_credentials()

    saved = None
    if not args.force and TOKEN_FILE.exists():
        try:
            saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = None
        if saved and saved.get("client_id") != client_id:
            saved = None

    if saved and saved.get("refresh_token"):
        refresh = saved["refresh_token"]
        print("Refresh-Token aus ~/.gcal-helper/token.json wiederverwendet.")
    else:
        code, redirect_uri = _run_browser_flow(client_id, args.no_browser)
        tokens = _exchange_code(client_id, client_secret, code, redirect_uri)
        refresh = tokens.get("refresh_token") or ""
        if not refresh:
            print(f"Kein refresh_token in der Antwort: {tokens}", file=sys.stderr)
            return 1
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(
            json.dumps(
                {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh},
                indent=2,
            ),
            encoding="utf-8",
        )

    if args.print_token:
        print(f"\nrefresh_token: {refresh}")

    if args.planfile:
        if not args.planfile.exists():
            parser.error(f"Planfile existiert nicht: {args.planfile}")
        if _patch_planfile(args.planfile, client_id, client_secret, refresh):
            print(f"\nPlanfile aktualisiert: {args.planfile}")
        else:
            print(f"\nPlanfile unveraendert: {args.planfile}")
        print("Jetzt ausfuehren:  dir3 <planfile> --sync-gcal")
    else:
        print("\nAchtung: Secrets sind nur in ~/.gcal-helper gespeichert; ein Planfile")
        print("hast du nicht angegeben (--planfile).")

    print("\nHinweis: client_secret/refresh_token sind Secrets - wenn das Planfile in")
    print("einem Git-Repo liegt, diesen Block am besten per env/untracked halten.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
