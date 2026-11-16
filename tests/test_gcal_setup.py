"""gcal_setup: OAuth-URL-Bau und Token-Tausch (Loopback-Flow) - ohne Browser."""
from __future__ import annotations

import asyncio
import urllib.parse

import httpx

from dir3.gcal_setup import SCOPE, auth_url, exchange_code


def test_auth_url_contains_oauth_params():
    url = auth_url("cid", "http://127.0.0.1:8123/")
    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == "https"
    query = urllib.parse.parse_qs(parsed.query)
    assert query["client_id"] == ["cid"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8123/"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [SCOPE]
    assert "auth/calendar.events" in query["scope"][0]
    assert "auth/tasks" in query["scope"][0]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


def test_exchange_code_posts_authorization_grant():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        captured["data"] = dict(urllib.parse.parse_qsl(request.content.decode("utf-8")))
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt"})

    transport = httpx.MockTransport(handler)
    tokens = asyncio.run(
        exchange_code("cid", "cs", "the-code", "http://127.0.0.1:9/", transport=transport)
    )

    assert tokens == {"access_token": "at", "refresh_token": "rt"}
    assert captured["url"].host == "oauth2.googleapis.com"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "the-code"
    assert captured["data"]["redirect_uri"] == "http://127.0.0.1:9/"


def test_exchange_code_raises_on_token_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    transport = httpx.MockTransport(handler)
    try:
        asyncio.run(
            exchange_code("cid", "cs", "bad", "http://127.0.0.1:9/", transport=transport)
        )
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 400
    else:  # pragma: no cover - assert via except arm
        raise AssertionError("expected HTTPStatusError")
