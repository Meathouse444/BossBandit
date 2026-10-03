"""The daily run: find streamers -> find clips -> AI picks -> render -> posting kit."""
from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .brain import Brain
from .captions import Word
from .config import Config
from .db import DB
from .kit import Kit
from .media import (MediaError, download_clip, require_ffmpeg, transcribe, whisper_available,
                    words_to_text)
from .render import RenderSettings, concat_videos, render_vertical
from .twitch import Twitch

log = logging.getLogger(__name__)

COMP_MIN_SECONDS = 61.0   # TikTok Creator Rewards counts videos over 1 minute
COMP_MAX_SECONDS = 95.0


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class RunSummary:
    discovered: list[str] = field(default_factory=list)
    pending_review: list[str] = field(default_factory=list)
    candidates: int = 0
    videos: list[Path] = field(default_factory=list)
    kit_dir: Path | None = None
    notes: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, cfg: Config, *, twitch: Twitch | None = None, brain: Brain | None = None,
                 db: DB | None = None):
        self.cfg = cfg
        self.db = db or DB(cfg.data_dir / "bossbandit.db")
        self.twitch = twitch or Twitch(cfg.secret("TWITCH_CLIENT_ID") or "",
                                       cfg.secret("TWITCH_CLIENT_SECRET") or "")
        self.brain = brain or Brain(cfg.secret("ANTHROPIC_API_KEY"), cfg["ai"]["model"],
                                    cfg["ai"]["effort"])
        self.cache_dir = cfg.data_dir / "cache"
        self._games: dict[str, str] = {}

    # ------------------------------------------------------------------ seeds
    def ensure_seeds(self) -> None:
        seeds = [s.lower() for s in self.cfg["seed"]["streamers"]]
        missing = [s for s in seeds if self.db.get_streamer(s) is None]
        if not missing:
            return
        users = self.twitch.users_by_login(missing)
        for login in missing:
            u = users.get(login)
            if not u:
                log.info("seed streamer %s not found on Twitch; skipping", login)
                self.db.upsert_streamer(login, status="rejected", source="seed",
                                        ai_reason="login not found on Twitch")
                continue
            self.db.upsert_streamer(
                login, user_id=u["id"], display_name=u["display_name"], status="approved",
                source="seed", account_created=u.get("created_at"),
            )
        log.info("added %d seed streamers", len(missing))

    def _resolve_ids(self) -> None:
        rows = [r for r in self.db.streamers("approved") if not r["user_id"]]
        if not rows:
            return
        users = self.twitch.users_by_login(r["login"] for r in rows)
        for r in rows:
            u = users.get(r["login"])
            if u:
                self.db.upsert_streamer(r["login"], user_id=u["id"], display_name=u["display_name"],
                                        account_created=u.get("created_at"))
            else:
                self.db.upsert_streamer(r["login"], status="rejected", ai_reason="login not found on Twitch")

    # -------------------------------------------------------------- discovery
    def discover(self) -> tuple[list[str], list[str]]:
        """Find new likely-30+ streamers from popular clips in millennial games.
        Returns (auto_approved, pending_review)."""
        d = self.cfg["discovery"]
        sched = self.cfg["schedule"]
        if not self._games:
            self._games = self.twitch.game_ids(d["games"])
        unknown_games = sorted(set(d["games"]) - set(self._games))
        if unknown_games:
            log.info("discovery: Twitch doesn't know these game names: %s", ", ".join(unknown_games))
        known_ids = {r["user_id"] for r in self.db.streamers() if r["user_id"]}
        known_logins = {r["login"] for r in self.db.streamers()}
        langs = set(sched["languages"])

        agg: dict[str, dict] = defaultdict(lambda: {"views": 0, "titles": [], "games": set()})
        for game_name, game_id in self._games.items():
            try:
                clips = self.twitch.clips(game_id=game_id, days=sched["lookback_days"], limit=100)
            except Exception as e:
                log.warning("discovery: clips for %s failed: %s", game_name, e)
                continue
            for c in clips:
                if c["broadcaster_id"] in known_ids or (langs and c.get("language") not in langs):
                    continue
                a = agg[c["broadcaster_id"]]
                a["views"] += c["view_count"]
                a["games"].add(game_name)
                if len(a["titles"]) < 5:
                    a["titles"].append(c["title"])

        hot = sorted(
            (bid for bid, a in agg.items() if a["views"] >= d["min_total_clip_views"]),
            key=lambda b: -agg[b]["views"],
        )[:25]
        if not hot:
            return [], []
        users = self.twitch.users_by_id(hot)
        candidates = []
        for bid in hot:
            u = users.get(bid)
            if not u or u["login"] in known_logins:
                continue
            if d["require_partner"] and u.get("broadcaster_type") != "partner":
                continue
            created = parse_time(u["created_at"]) if u.get("created_at") else None
            if created and created.year > int(d["max_account_year"]):
                continue
            candidates.append({
                "login": u["login"],
                "display_name": u["display_name"],
                "bio": (u.get("description") or "")[:300],
                "twitch_account_created": created.year if created else None,
                "games": sorted(agg[bid]["games"]),
                "recent_clip_titles": agg[bid]["titles"],
                "_user": u,
            })
        if not candidates:
            return [], []

        verdicts = {v["login"].lower(): v for v in self.brain.vet_streamers(
            [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
        )}
        approved, pending = [], []
        for c in candidates:
            v = verdicts.get(c["login"], {})
            conf = float(v.get("confidence", 0) or 0)
            likely = bool(v.get("likely_30_plus"))
            friendly = bool(v.get("family_friendly_enough", True))
            if not friendly or (not likely and conf >= 0.8):
                status = "rejected"
            elif likely and conf >= float(d["auto_approve_confidence"]) and d["auto_approve"]:
                status = "approved"
            else:
                status = "pending"
            u = c["_user"]
            self.db.upsert_streamer(
                c["login"], user_id=u["id"], display_name=u["display_name"], status=status,
                source="discovered", account_created=u.get("created_at"),
                ai_confidence=conf, ai_reason=v.get("reason", ""),
            )
            if status == "approved":
                approved.append(c["login"])
            elif status == "pending":
                pending.append(c["login"])
        return approved, pending

    # -------------------------------------------------------------- candidates
    def gather_candidates(self) -> list[dict]:
        s = self.cfg["schedule"]
        mode = self.cfg["permissions"]["mode"]
        rows = self.db.streamers("approved")
        if mode == "granted":
            rows = [r for r in rows if r["permission"]]
            if not rows:
                log.warning("permissions.mode is 'granted' but no streamer is marked permitted yet")
        langs = set(s["languages"])
        now = datetime.now(timezone.utc)
        recent = self.db.recent_broadcasters(days=1)

        clips: list[dict] = []
        for r in rows:
            if not r["user_id"]:
                continue
            try:
                got = self.twitch.clips(broadcaster_id=r["user_id"], days=s["lookback_days"], limit=20)
            except Exception as e:
                log.warning("clips for %s failed: %s", r["login"], e)
                continue
            for c in got:
                if langs and c.get("language") not in langs:
                    continue
                if not (s["min_clip_seconds"] <= c["duration"] <= s["max_clip_seconds"]):
                    continue
                if c["view_count"] < s["min_clip_views"] or self.db.clip_known(c["id"]):
                    continue
                age_h = max(1.0, (now - parse_time(c["created_at"])).total_seconds() / 3600)
                c["broadcaster_login"] = r["login"]
                c["age_hours"] = age_h
                c["velocity"] = c["view_count"] / age_h ** 0.8
                if r["login"] in recent:
                    c["velocity"] *= 0.5   # featured yesterday: let others have a turn
                clips.append(c)

        game_names = self.twitch.games_by_id(c.get("game_id") for c in clips) if clips else {}
        for c in clips:
            c["game_name"] = game_names.get(c.get("game_id"), "")

        clips.sort(key=lambda c: -c["velocity"])
        per: dict[str, int] = defaultdict(int)
        chosen = []
        for c in clips:
            if per[c["broadcaster_login"]] >= 2:
                continue
            per[c["broadcaster_login"]] += 1
            chosen.append(c)
            if len(chosen) >= int(s["candidates_to_analyze"]):
                break
        return chosen

    # -------------------------------------------------------------------- run
    def run(self, *, dry_run: bool = False, skip_discovery: bool = False) -> RunSummary:
        require_ffmpeg()
        summary = RunSummary()
        cfg = self.cfg
        self.ensure_seeds()
        self._resolve_ids()

        if cfg["discovery"]["enabled"] and not skip_discovery:
            try:
                summary.discovered, summary.pending_review = self.discover()
            except Exception as e:  # discovery is a bonus; never block the daily run
                log.warning("discovery failed: %s", e)

        candidates = self.gather_candidates()
        summary.candidates = len(candidates)
        if not candidates:
            summary.notes.append("No new clips matched today. Try a bigger lookback_days or a lower min_clip_views.")
            return summary

        want_captions = bool(cfg["render"]["captions"])
        can_transcribe = want_captions and whisper_available()
        if want_captions and not can_transcribe:
            summary.notes.append("Captions are on but faster-whisper isn't installed (pip install faster-whisper).")

        words_by_id: dict[str, list[Word]] = {}
        files: dict[str, Path] = {}
        ready = []
        for c in candidates:
            try:
                files[c["id"]] = download_clip(c["url"], self.cache_dir / f"{c['id']}.mp4")
            except MediaError as e:
                log.warning("%s", e)
                continue
            if can_transcribe:
                try:
                    words_by_id[c["id"]] = transcribe(files[c["id"]], cfg["whisper"]["model"],
                                                      cfg["whisper"]["device"])
                except Exception as e:
                    log.warning("transcription failed for %s: %s", c["id"], e)
            c["transcript"] = words_to_text(words_by_id.get(c["id"], []))
            ready.append(c)
            self.db.record_clip(c, status="seen")

        base_tags = cfg["brand"]["base_hashtags"]
        picks = self.brain.judge_clips(ready, base_tags)
        by_id = {c["id"]: c for c in ready}
        kept = {p["clip_id"] for p in picks}
        for c in ready:
            if c["id"] not in kept and self.brain.enabled:
                self.db.set_clip_status(c["id"], "rejected")

        singles, extra = [], []
        per: dict[str, int] = defaultdict(int)
        for p in picks:
            login = by_id[p["clip_id"]]["broadcaster_login"]
            if len(singles) < int(cfg["schedule"]["posts_per_day"]) and per[login] < int(cfg["schedule"]["max_per_streamer"]):
                per[login] += 1
                singles.append(p)
            else:
                extra.append(p)

        if dry_run:
            for p in singles:
                c = by_id[p["clip_id"]]
                summary.notes.append(f"[{p['score']}/10] {c['broadcaster_name']}: {p['hook']}  ({c['url']})")
            return summary

        kit = Kit(cfg.output_dir)
        summary.kit_dir = kit.dir
        settings = RenderSettings.from_config(cfg["render"])
        watermark = f"@{cfg['brand']['channel_name']}" if cfg["brand"]["channel_name"] else ""

        for p in singles:
            c = by_id[p["clip_id"]]
            dest = kit.next_path(c["broadcaster_login"], p["hook"])
            try:
                self._render_one(c, p, files[c["id"]], dest, settings, watermark,
                                 words_by_id.get(c["id"]), hook=p["hook"])
            except MediaError as e:
                log.error("render failed for %s: %s", c["id"], e)
                continue
            kit.add(dest, self._kit_item(c, p))
            self.db.record_clip(c, status="rendered", hook=p["hook"], caption=p["caption"],
                                reason=p["reason"], video_path=str(dest))
            summary.videos.append(dest)

        if cfg["schedule"]["make_compilation"]:
            comp = self._compilation(extra + singles, by_id, files, words_by_id, kit, settings, watermark)
            if comp:
                summary.videos.append(comp)
            else:
                summary.notes.append("Not enough good footage today for a 60s+ compilation.")

        self._clean_cache()
        return summary

    # ----------------------------------------------------------------- helpers
    def _render_one(self, c, p, src, dest, settings, watermark, words, hook):
        render_vertical(
            src, dest, settings,
            hook=hook if self.cfg["render"]["hook_text"] else None,
            words=words if self.cfg["render"]["captions"] else None,
            credit=f"twitch.tv/{c['broadcaster_login']}",
            watermark=watermark,
            facecam=self.db.facecam(c["broadcaster_login"]),
        )

    @staticmethod
    def _kit_item(c: dict, p: dict, kind: str = "clip") -> dict:
        return {
            "kind": kind,
            "clip_id": c["id"],
            "streamer": c.get("broadcaster_name", c["broadcaster_login"]),
            "game": c.get("game_name", ""),
            "hook": p["hook"],
            "caption": p["caption"],
            "hashtags": p["hashtags"],
            "credit": f"twitch.tv/{c['broadcaster_login']}",
            "source_url": c.get("url", ""),
            "reason": p.get("reason", ""),
        }

    def _compilation(self, pool, by_id, files, words_by_id, kit, settings, watermark) -> Path | None:
        chosen, total = [], 0.0
        for p in pool:
            c = by_id[p["clip_id"]]
            if total + c["duration"] > COMP_MAX_SECONDS:
                continue
            chosen.append(p)
            total += c["duration"]
            if total >= COMP_MIN_SECONDS and len(chosen) >= 3:
                break
        if total < COMP_MIN_SECONDS or len(chosen) < 2:
            return None
        segments = [{**by_id[p["clip_id"]], "hook": p["hook"]} for p in chosen]
        copy = self.brain.compilation_copy(segments, self.cfg["brand"]["base_hashtags"])
        dest = kit.next_path("", copy["hook"], kind="compilation")
        with tempfile.TemporaryDirectory(prefix="bb_comp_") as tmp:
            parts = []
            for i, p in enumerate(chosen):
                c = by_id[p["clip_id"]]
                part = Path(tmp) / f"part{i:02d}.mp4"
                hook = copy["hook"] if i == 0 else f"#{i + 1}  {p['hook']}"
                try:
                    self._render_one(c, p, files[c["id"]], part, settings, watermark,
                                     words_by_id.get(c["id"]), hook=hook)
                except MediaError as e:
                    log.error("compilation segment failed: %s", e)
                    return None
                parts.append(part)
            concat_videos(parts, dest)
        names = ", ".join(dict.fromkeys(f"twitch.tv/{by_id[p['clip_id']]['broadcaster_login']}" for p in chosen))
        kit.add(dest, {
            "kind": "compilation",
            "clip_id": ",".join(p["clip_id"] for p in chosen),
            "streamer": ", ".join(dict.fromkeys(by_id[p["clip_id"]]["broadcaster_name"] for p in chosen)),
            "game": "",
            "hook": copy["hook"],
            "caption": copy["caption"],
            "hashtags": copy["hashtags"],
            "credit": names,
            "source_url": by_id[chosen[0]["clip_id"]]["url"],
            "reason": f"{len(chosen)} clips, {total:.0f}s",
        })
        for p in chosen:
            c = by_id[p["clip_id"]]
            if not self.db.clip_known(c["id"]):
                self.db.record_clip(c, status="rendered", hook=p["hook"], caption=p["caption"],
                                    reason="compilation", video_path=str(dest))
        return dest

    def _clean_cache(self, max_age_days: float = 3) -> None:
        if not self.cache_dir.exists():
            return
        cutoff = time.time() - max_age_days * 86400
        for f in self.cache_dir.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def disk_free_gb(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free / 1e9
