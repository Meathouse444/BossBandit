"""Tiny Twitch Helix API client (app access token, read-only, free).

Get a Client ID + Secret at https://dev.twitch.tv/console/apps (see README).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

import requests

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class TwitchError(RuntimeError):
    pass


def _chunks(items: list, n: int) -> Iterator[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Twitch:
    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None):
        if not client_id or not client_secret:
            raise TwitchError(
                "Missing TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET. Put them in your .env file "
                "(see README, step 3)."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = session or requests.Session()
        self._token: str | None = None
        self._token_expiry = 0.0

    # ---- auth ------------------------------------------------------------
    def _auth(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        r = self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise TwitchError(f"Twitch login failed ({r.status_code}): {r.text[:200]}. Check your keys.")
        body = r.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, path: str, params: list[tuple[str, str]] | dict) -> dict:
        for attempt in range(5):
            r = self.http.get(
                f"{HELIX}/{path}",
                params=params,
                headers={"Client-Id": self.client_id, "Authorization": f"Bearer {self._auth()}"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and attempt == 0:
                self._token = None  # token expired/revoked: refresh once
                continue
            if r.status_code == 429 or r.status_code >= 500:
                reset = r.headers.get("Ratelimit-Reset")
                wait = max(1.0, float(reset) - time.time()) if reset else 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            raise TwitchError(f"Twitch API {path} -> {r.status_code}: {r.text[:200]}")
        raise TwitchError(f"Twitch API {path} kept failing; try again later.")

    def paginate(self, path: str, params: list[tuple[str, str]], limit: int) -> Iterator[dict]:
        cursor = None
        seen = 0
        while seen < limit:
            p = list(params) + [("first", str(min(100, limit - seen)))]
            if cursor:
                p.append(("after", cursor))
            body = self.get(path, p)
            data = body.get("data", [])
            for item in data:
                yield item
            seen += len(data)
            cursor = body.get("pagination", {}).get("cursor")
            if not cursor or not data:
                return

    # ---- endpoints -------------------------------------------------------
    def users_by_login(self, logins: Iterable[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for chunk in _chunks(sorted({l.lower() for l in logins}), 100):
            body = self.get("users", [("login", l) for l in chunk])
            for u in body.get("data", []):
                out[u["login"]] = u
        return out

    def users_by_id(self, ids: Iterable[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for chunk in _chunks(sorted(set(ids)), 100):
            body = self.get("users", [("id", i) for i in chunk])
            for u in body.get("data", []):
                out[u["id"]] = u
        return out

    def game_ids(self, names: Iterable[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for chunk in _chunks(list(names), 100):
            body = self.get("games", [("name", n) for n in chunk])
            for g in body.get("data", []):
                out[g["name"]] = g["id"]
        return out

    def games_by_id(self, ids: Iterable[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        ids = [i for i in set(ids) if i]
        for chunk in _chunks(ids, 100):
            body = self.get("games", [("id", i) for i in chunk])
            for g in body.get("data", []):
                out[g["id"]] = g["name"]
        return out

    def clips(self, *, broadcaster_id: str | None = None, game_id: str | None = None,
              days: int = 3, limit: int = 100) -> list[dict]:
        if not (broadcaster_id or game_id):
            raise ValueError("need broadcaster_id or game_id")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        params = [("started_at", rfc3339(start)), ("ended_at", rfc3339(end))]
        params.append(("broadcaster_id", broadcaster_id) if broadcaster_id else ("game_id", game_id))
        # Helix returns clips sorted by view count, most viewed first.
        return list(self.paginate("clips", params, limit))
