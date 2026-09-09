#!/usr/bin/env python3
"""Google-Calendar-OAuth-Helfer fuer dir3 - standalone, nur Standardbibliothek.

Wie im Munazzim: Das Script oeffnet den Browser, du loggst dich in dein
Google-Konto ein - fertig. Es startet einen lokalen Loopback-Server auf
127.0.0.1, faengt den Code aus dem Redirect ab, tauscht ihn gegen ein
refresh_token und schreibt die Zugangsdaten

    * nach ~/.gcal-helper/token.json   (fuer Wiederverwendung) und
    * optional direkt in dein Planfile (``gcal = GoogleCalendar(...)``).

Kein Teil von dir3: es importiert nichts aus dem dir3-Paket, du brauchst
nur ``python3`` (+ einen Browser).

Einmalige Einrichtung: In der Google Cloud Console einen OAuth-Client vom
Typ "Desktopanwendung" erzeugen und die heruntergeladene ``client_secret*.json``
in den Download-Ordner legen - das Script findet sie automatisch.
Nur wenn sie dort (und unter ~/.gcal-helper/) nicht liegt, fragt es nach
den Werten (oder uebergib die Datei direkt per ``--client-secrets``).
Danach ist jedes Mal nur noch: Browser oeffnet sich, einloggen, fertig.

Anleitung:
  python3 scripts/gcal_helper.py --planfile examples/gebets_woche.py
  python3 scripts/gcal_helper.py --planfile examples/gebets_woche.py --force
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
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CONSOLE_URL = "https://console.cloud.google.com/apis/credentials"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
STATE_DIR = Path.home() / ".gcal-helper"
CLIENT_FILE = STATE_DIR / "client_secret.json"
TOKEN_FILE = STATE_DIR / "token.json"
TIMEOUT_SECONDS = 300

#: Optional fest eintragen, ersetzt dann die Client-Secrets-Datei.
DEFAULT_CLIENT_ID = ""
DEFAULT_CLIENT_SECRET = ""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Sammelt den OAuth-Code aus dem Loopback-Redirect."""

    code: str | None = None
    error: str | None = None
    done = False

    def do_GET(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = query.get("code", [None])[0]
        _CallbackHandler.error = query.get("error", [None])[0]
        if _CallbackHandler.code:
            body = (
                b"<html><body><p>Anmeldung erfolgreich - "
                b"Fenster kann geschlossen werden.</p></body></html>"
            )
        elif _CallbackHandler.error:
            body = (
                b"<html><body><p>Anmeldung fehlgeschlagen - "
                b"zurueck zum Terminal.</p></body></html>"
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


def _secrets_from_file(path: Path) -> tuple[str, str]:
    """Client-ID/Secret aus einer OAuth-Client-JSON der Google Cloud Console."""
    data = json.loads(path.read_text(encoding="utf-8"))
    inst = data.get("installed") or data.get("web") or data
    return inst.get("client_id") or "", inst.get("client_secret") or ""


def _downloads_client_secret() -> Path | None:
    """Neueste ``client_secret*.json`` aus dem Download-Ordner."""
    folder = Path.home() / "Downloads"
    if not folder.is_dir():
        return None
    matches = sorted(
        (p for p in folder.glob("client_secret*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _load_credentials(client_secrets: Path | None) -> tuple[str, str]:
    """client_id / client_secret - --client-secrets, Env, Downloads, Sidecar
    oder Konstanten (in dieser Reihenfolge)."""
    if client_secrets is not None:
        if not client_secrets.exists():
            raise SystemExit(f"Client-Secrets-Datei existiert nicht: {client_secrets}")
        try:
            return _secrets_from_file(client_secrets)
        except (OSError, json.JSONDecodeError) as err:
            raise SystemExit(f"Ungueltige Client-Secrets-Datei {client_secrets}: {err}") from err
    env = (os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    if all(env):
        return env
    for source in (_downloads_client_secret(), CLIENT_FILE):
        if source is None or not source.exists():
            continue
        try:
            cid, csecret = _secrets_from_file(source)
        except (OSError, json.JSONDecodeError):
            continue
        if cid and csecret:
            print(f"Client-Secrets verwendet: {source}")
            return cid, csecret
    return DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET


def _ask_credentials() -> tuple[str, str]:
    """Letzte Ausweichmoeglichkeit: Werte erfragen und fuer spaeter merken."""
    print("Kein OAuth-client_secret gefunden (weder in ~/Downloads noch in", file=sys.stderr)
    print(f"{CLIENT_FILE}). Bitte einmalig eingeben:", file=sys.stderr)
    print(f"  (Google Cloud Console: {CONSOLE_URL})", file=sys.stderr)
    client_id = input("  client_id: ").strip()
    client_secret = input("  client_secret: ").strip()
    if not (client_id and client_secret):
        print("Abgebrochen - beide Werte werden gebraucht.", file=sys.stderr)
        raise SystemExit(1)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": ["http://localhost"],
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Gespeichert unter {CLIENT_FILE} - ab jetzt automatisch gefunden.")
    return client_id, client_secret


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
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        raise SystemExit(f"Token-Tausch fehlgeschlagen (HTTP {err.code}): {detail}") from err


def _run_browser_flow(client_id: str, no_browser: bool) -> tuple[str, str]:
    """Startet den Loopback-Server, oeffnet den Login und liefert
    (code, redirect_uri). Fallback: Code manuell aus der URL pasten."""
    with http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler) as server:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/"
        auth_url = _auth_url(client_id, redirect_uri)
        print("Bitte im Browser anmelden:")
        print(auth_url)
        if not no_browser:
            webbrowser.open(auth_url)

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while not _CallbackHandler.done and time.monotonic() < deadline:
            time.sleep(0.2)
        server.shutdown()
        thread.join(timeout=2.0)

    if _CallbackHandler.error:
        raise SystemExit(
            f"Anmeldung fehlgeschlagen ({_CallbackHandler.error}) - "
            "Zugriff wurde nicht gewaehrt."
        )
    code = _CallbackHandler.code
    if not code:
        print("\nKein Redirect im Browser angekommen (z. B. anderer Rechner?).")
        raw = input("Adressleiste kopieren (die URL mit code=...): ").strip()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        code = query.get("code", [None])[0]
        if not code and query.get("error"):
            raise SystemExit(f"Anmeldung fehlgeschlagen ({query['error'][0]}).")
    if not code:
        raise SystemExit("Kein Code empfangen - Zugang nicht eingerichtet.")
    return code, redirect_uri


def _safe_load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_token(client_id: str, client_secret: str, refresh: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps(
            {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh},
            indent=2,
        ),
        encoding="utf-8",
    )


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
    """Ersetzt einen bestehenden gcal-Block oder haengt ihn ans Planfile an,
    ergaenzt dabei notfalls den GoogleCalendar-Import."""
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
        description="Google-Calendar-OAuth fuer dir3 - Browser oeffnen, einloggen, fertig.",
    )
    parser.add_argument("--planfile", type=Path, help="Planfile, in das gcal(...) geschrieben wird")
    parser.add_argument(
        "--client-secrets",
        type=Path,
        metavar="JSON",
        help="OAuth-Client-JSON aus der Google Cloud Console (Desktopanwendung)",
    )
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht selbst oeffnen")
    parser.add_argument("--force", action="store_true", help="Browser-Flow erneut erzwingen")
    parser.add_argument("--print-token", action="store_true", help="refresh_token anzeigen")
    args = parser.parse_args(argv)

    client_id, client_secret = _load_credentials(args.client_secrets)
    if not client_id or not client_secret:
        client_id, client_secret = _ask_credentials()

    saved = _safe_load(TOKEN_FILE)
    if args.force:
        saved = {}
    if saved.get("client_id") != client_id:
        saved = {}

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
        _save_token(client_id, client_secret, refresh)
        print("Refresh-Token gespeichert unter ~/.gcal-helper/token.json.")

    if args.print_token:
        print(f"\nrefresh_token: {refresh}")

    if args.planfile:
        if not args.planfile.exists():
            parser.error(f"Planfile existiert nicht: {args.planfile}")
        _patch_planfile(args.planfile, client_id, client_secret, refresh)
        print(f"\nPlanfile aktualisiert: {args.planfile}")
        print("Jetzt ausfuehren:  dir3 <planfile> --sync-gcal")
    else:
        print("\nAchtung: Secrets sind nur in ~/.gcal-helper gespeichert; ein Planfile")
        print("hast du nicht angegeben (--planfile).")

    print("\nHinweis: client_secret/refresh_token sind Secrets - wenn das Planfile in")
    print("einem Git-Repo liegt, diesen Block am besten per env/untracked halten.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
