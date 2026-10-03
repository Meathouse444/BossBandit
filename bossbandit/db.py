"""SQLite state: which streamers we follow and which clips we've already used.

SQLite gives us atomic writes for free, so there's no hand-rolled queue file
to corrupt (the Reddit build lost clips to exactly that race).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS streamers (
    login          TEXT PRIMARY KEY,
    user_id        TEXT,
    display_name   TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',   -- approved | pending | rejected
    source         TEXT NOT NULL DEFAULT 'manual',    -- seed | discovered | manual
    permission     INTEGER NOT NULL DEFAULT 0,        -- 1 = they said yes to clipping
    facecam        TEXT,                              -- JSON [x, y, w, h] as 0-1 fractions
    followers      INTEGER,
    account_created TEXT,
    ai_confidence  REAL,
    ai_reason      TEXT,
    added_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id             TEXT PRIMARY KEY,
    broadcaster    TEXT NOT NULL,
    title          TEXT,
    url            TEXT,
    view_count     INTEGER,
    created_at     TEXT,
    duration       REAL,
    game_name      TEXT,
    status         TEXT NOT NULL DEFAULT 'seen',      -- seen | rejected | rendered | posted
    hook           TEXT,
    caption        TEXT,
    reason         TEXT,
    video_path     TEXT,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS clips_status ON clips(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- streamers -------------------------------------------------------
    def upsert_streamer(self, login: str, **fields) -> None:
        login = login.lower()
        existing = self.get_streamer(login)
        if existing is None:
            fields.setdefault("status", "pending")
            fields.setdefault("source", "manual")
            cols = ["login", "added_at", *fields]
            vals = [login, _now(), *fields.values()]
            self.conn.execute(
                f"INSERT INTO streamers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                vals,
            )
        elif fields:
            sets = ",".join(f"{k}=?" for k in fields)
            self.conn.execute(f"UPDATE streamers SET {sets} WHERE login=?", [*fields.values(), login])
        self.conn.commit()

    def get_streamer(self, login: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM streamers WHERE login=?", (login.lower(),)).fetchone()

    def streamers(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.conn.execute(
                "SELECT * FROM streamers WHERE status=? ORDER BY login", (status,)
            ).fetchall()
        return self.conn.execute("SELECT * FROM streamers ORDER BY status, login").fetchall()

    def facecam(self, login: str) -> list[float] | None:
        row = self.get_streamer(login)
        if row and row["facecam"]:
            return json.loads(row["facecam"])
        return None

    # ---- clips -----------------------------------------------------------
    def clip_known(self, clip_id: str) -> bool:
        row = self.conn.execute("SELECT status FROM clips WHERE id=?", (clip_id,)).fetchone()
        return row is not None and row["status"] != "seen"

    def record_clip(self, clip: dict, status: str = "seen", **fields) -> None:
        data = {
            "broadcaster": clip["broadcaster_login"],
            "title": clip.get("title"),
            "url": clip.get("url"),
            "view_count": clip.get("view_count"),
            "created_at": clip.get("created_at"),
            "duration": clip.get("duration"),
            "game_name": clip.get("game_name"),
            "status": status,
            "updated_at": _now(),
            **fields,
        }
        cols = ["id", *data]
        updates = ",".join(f"{k}=excluded.{k}" for k in data)
        self.conn.execute(
            f"INSERT INTO clips ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [clip["id"], *data.values()],
        )
        self.conn.commit()

    def set_clip_status(self, clip_id: str, status: str) -> bool:
        cur = self.conn.execute(
            "UPDATE clips SET status=?, updated_at=? WHERE id=?", (status, _now(), clip_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def recent_broadcasters(self, days: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT broadcaster FROM clips WHERE status IN ('rendered','posted') "
            "AND updated_at >= ?",
            ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"),),
        ).fetchall()
        return {r["broadcaster"] for r in rows}

    def stats(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) n FROM clips GROUP BY status").fetchall()
        out = {r["status"]: r["n"] for r in rows}
        for s in ("approved", "pending", "rejected"):
            out[f"streamers_{s}"] = self.conn.execute(
                "SELECT COUNT(*) FROM streamers WHERE status=?", (s,)
            ).fetchone()[0]
        return out
