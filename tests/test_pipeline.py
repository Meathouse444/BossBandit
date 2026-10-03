"""End-to-end test with a fake Twitch API and synthetic video (needs ffmpeg)."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bossbandit import pipeline as pipeline_mod
from bossbandit.brain import Brain
from bossbandit.config import load_config
from bossbandit.db import DB
from bossbandit.media import probe
from bossbandit.pipeline import Pipeline

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


USERS = {
    "shroud": {"id": "1", "login": "shroud", "display_name": "shroud", "created_at": "2012-01-01T00:00:00Z", "broadcaster_type": "partner", "description": ""},
    "lirik": {"id": "2", "login": "lirik", "display_name": "LIRIK", "created_at": "2011-01-01T00:00:00Z", "broadcaster_type": "partner", "description": ""},
    "olddad": {"id": "9", "login": "olddad", "display_name": "OldDad", "created_at": "2010-05-01T00:00:00Z", "broadcaster_type": "partner", "description": "Dad of 3, gaming since the N64"},
    "youngkid": {"id": "8", "login": "youngkid", "display_name": "YoungKid", "created_at": "2021-05-01T00:00:00Z", "broadcaster_type": "partner", "description": ""},
}


def clip(cid, bid, views, hours, dur=25.0, lang="en", title="huge play"):
    login = next(u["login"] for u in USERS.values() if u["id"] == bid)
    return {"id": cid, "url": f"https://clips.twitch.tv/{cid}", "broadcaster_id": bid,
            "broadcaster_name": USERS[login]["display_name"], "game_id": "g1", "language": lang,
            "title": title, "view_count": views, "created_at": iso(hours), "duration": dur}


class FakeTwitch:
    def __init__(self):
        self.by_broadcaster = {
            "1": [clip("s1", "1", 5000, 10, title="He KILLED a whole squad"), clip("s2", "1", 300, 40, dur=30),
                  clip("s3", "1", 90, 5)],             # s3 below min views
            "2": [clip("l1", "2", 2000, 5, dur=32), clip("l2", "2", 800, 20, lang="de"),
                  clip("l3", "2", 900, 30, dur=120)],  # l2 wrong language, l3 too long
        }

    def users_by_login(self, logins):
        return {l: USERS[l] for l in logins if l in USERS}

    def users_by_id(self, ids):
        return {u["id"]: u for u in USERS.values() if u["id"] in set(ids)}

    def game_ids(self, names):
        return {"World of Warcraft": "g1"}

    def games_by_id(self, ids):
        return {"g1": "World of Warcraft"}

    def clips(self, *, broadcaster_id=None, game_id=None, days=3, limit=100):
        if game_id:
            return [clip("d1", "9", 4000, 3), clip("d2", "8", 9000, 3), clip("d3", "1", 9999, 3)]
        return list(self.by_broadcaster.get(broadcaster_id, []))


class FakeBrain(Brain):
    """Pretends to be Claude: approves olddad, keeps everything but l1's twin."""
    def __init__(self):
        super().__init__(None, "test")
        self.vetted = []

    @property
    def enabled(self):
        return True

    def vet_streamers(self, candidates):
        self.vetted = [c["login"] for c in candidates]
        return [{"login": c["login"], "likely_30_plus": c["login"] == "olddad",
                 "confidence": 0.9, "family_friendly_enough": True, "reason": "test"} for c in candidates]


@pytest.fixture
def source_video(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("src") / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=34",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=34", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)],
        check=True,
    )
    return p


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[seed]\nstreamers = ["shroud", "lirik", "ghostlogin"]\n'
        '[render]\ncaptions = false\npreset = "ultrafast"\n'
        '[schedule]\nposts_per_day = 2\n'
        '[discovery]\ngames = ["World of Warcraft"]\nmin_total_clip_views = 1000\n',
        encoding="utf-8",
    )
    return load_config(tmp_path / "config.toml")


def fake_download(source_video):
    def _dl(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy(source_video, dest)
        return dest
    return _dl


def test_full_run_rule_based(cfg, source_video, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "download_clip", fake_download(source_video))
    db = DB(cfg.data_dir / "bossbandit.db")
    pipe = Pipeline(cfg, twitch=FakeTwitch(), brain=Brain(None, "x"), db=db)
    s = pipe.run()

    # seeds: real logins approved, missing login rejected
    assert db.get_streamer("shroud")["status"] == "approved"
    assert db.get_streamer("ghostlogin")["status"] == "rejected"
    # filters: s3 (low views), l2 (language), l3 (too long) never considered
    assert s.candidates == 3
    singles = [v for v in s.videos if "BEST-OF" not in v.name]
    assert len(singles) == 2
    names = sorted(v.name.split("_")[1] for v in singles)
    assert names == ["lirik", "shroud"]          # max 1 per streamer
    for v in s.videos:
        info = probe(v)
        assert (info["width"], info["height"]) == (1080, 1920)
        assert info["has_audio"]
        assert v.with_suffix(".txt").read_text(encoding="utf-8").strip()
    # compilation: s1 25s + l1 32s + s2 30s = 87s -> eligible (>60s)
    comp = [v for v in s.videos if "BEST-OF" in v.name]
    assert len(comp) == 1 and probe(comp[0])["duration"] > 60
    # TikTok-suppressed word scrubbed from the rule-based hook
    manifest = json.loads((s.kit_dir / "manifest.json").read_text(encoding="utf-8"))
    assert all("KILLED" not in m["hook"] for m in manifest)
    assert (s.kit_dir / "index.html").exists()

    # second run: nothing reused
    s2 = Pipeline(cfg, twitch=FakeTwitch(), brain=Brain(None, "x"), db=db).run(skip_discovery=True)
    assert s2.candidates == 0 and not s2.videos
    db.close()


def test_discovery_vets_and_filters(cfg, monkeypatch):
    db = DB(cfg.data_dir / "bossbandit.db")
    brain = FakeBrain()
    pipe = Pipeline(cfg, twitch=FakeTwitch(), brain=brain, db=db)
    pipe.ensure_seeds()
    approved, pending = pipe.discover()
    # youngkid filtered by account age before AI; shroud already known
    assert brain.vetted == ["olddad"]
    assert approved == ["olddad"] and pending == []
    assert db.get_streamer("olddad")["source"] == "discovered"
    db.close()


def test_dry_run_renders_nothing(cfg, source_video, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "download_clip", fake_download(source_video))
    db = DB(cfg.data_dir / "bossbandit.db")
    s = Pipeline(cfg, twitch=FakeTwitch(), brain=Brain(None, "x"), db=db).run(dry_run=True, skip_discovery=True)
    assert s.notes and not s.videos
    assert not db.clip_known("s1")      # still available for the real run
    db.close()


def test_permission_mode_granted(cfg, source_video, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "download_clip", fake_download(source_video))
    cfg.data["permissions"]["mode"] = "granted"
    db = DB(cfg.data_dir / "bossbandit.db")
    pipe = Pipeline(cfg, twitch=FakeTwitch(), brain=Brain(None, "x"), db=db)
    pipe.ensure_seeds()
    db.upsert_streamer("lirik", permission=1)
    cands = pipe.gather_candidates()
    assert {c["broadcaster_login"] for c in cands} == {"lirik"}
    db.close()
