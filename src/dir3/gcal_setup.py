"""Einmaligen Google-Calendar-Zugang holen (OAuth2, Loopback-Redirect).

    dir3-gcal-setup --client-id <CLIENT_ID> --client-secret <CLIENT_SECRET>

Voraussetzung in der Google Cloud Console:
  1. Projekt anlegen und die "Google Calendar API" **und** die
     "Google Tasks API" aktivieren;
  2. OAuth-Berechtigungsdaten vom Typ "Desktopanwendung" erzeugen
     (client_id + client_secret).

Danach startet das Script einen lokalen Redirect-Server auf 127.0.0.1, öffnet
den Consent im Browser und tauscht den Code gegen ein Refresh-Token.  Dieses
Refresh-Token plus client_id/client_secret gehören als ``gcal`` ins Planfile.
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import sys
import threading
import time
import urllib.parse
import webbrowser

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
#: Calendar-Events plus Google Tasks (hybrid: Event mit Dauer + Aufgabe).
SCOPE = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/tasks"
)
#: Wie lange auf den Browser-Consent gewartet wird.
TIMEOUT_SECONDS = 300


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    done = False

    def do_GET(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = query.get("code", [None])[0]
        if _CallbackHandler.code:
            body = (
                b"<html><body><p>Anmeldung erfolgreich. "
                b"Dieses Fenster kann geschlossen werden.</p></body></html>"
            )
        else:
            body = (
                b"<html><body><p>Anmeldung fehlgeschlagen - "
                b"zurueck zum Terminal.</p></body></html>"
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _CallbackHandler.done = True

    def log_message(self, *args):  # pragma: no cover - stiller Log-Output
        pass


def auth_url(client_id: str, redirect_uri: str, scope: str = SCOPE) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",  # liefert einen refresh_token
        "prompt": "consent",  # Refresh-Token auch bei erneuter Anmeldung
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
        response = await client.post(TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dir3-gcal-setup",
        description="Einmaligen Google-Calendar-Refresh-Token holen (OAuth2).",
    )
    parser.add_argument("--client-id", required=True, help="OAuth-Client-ID (Desktopanwendung)")
    parser.add_argument("--client-secret", required=True, help="OAuth-Client-Secret")
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht selbst öffnen")
    args = parser.parse_args(argv)

    with http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler) as server:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/"
        print("Bitte in deinem Browser anmelden:")
        print(auth_url(args.client_id, redirect_uri))
        if not args.no_browser:
            webbrowser.open(auth_url(args.client_id, redirect_uri))

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while not _CallbackHandler.done and time.monotonic() < deadline:
            time.sleep(0.2)
        server.shutdown()
        thread.join(timeout=2.0)

    code = _CallbackHandler.code
    if not code:
        print("Kein Code empfangen (Timeout oder Abbruch).", file=sys.stderr)
        return 1

    try:
        tokens = asyncio.run(
            exchange_code(args.client_id, args.client_secret, code, redirect_uri)
        )
    except httpx.HTTPStatusError as exc:  # pragma: no cover - echtes Tokenproblem
        print(f"Token-Tausch fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    refresh = tokens.get("refresh_token")
    if not refresh:
        print(f"Kein refresh_token in der Antwort: {tokens}", file=sys.stderr)
        return 1

    print("\nZugang eingerichtet! Diesen Block in dein Planfile einfügen:\n")
    print("    from dir3 import GoogleCalendar")
    print("    gcal = GoogleCalendar(")
    print(f"        client_id={args.client_id!r},")
    print(f"        client_secret={args.client_secret!r},")
    print(f"        refresh_token={refresh!r},")
    print("        calendar_id=\"primary\",")
    print("    )")
    print("\nDer Token umfasst Kalender-Events und Google Tasks.")
    print("Danach: dir3 <planfile> --sync-gcal")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
