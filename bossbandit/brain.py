"""The AI editor: picks clips, writes hooks/captions, vets new streamers.

Uses Claude when ANTHROPIC_API_KEY is set; otherwise falls back to simple
rules so the bot never stops working.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

AUDIENCE = """\
The channel posts short vertical clips of streamers who are 30+ years old
(millennials) for an audience of 30-45 year old gamers: people with jobs,
kids, mortgages and bad backs, who grew up on N64/PS1/Xbox 360/WoW/Halo LAN
parties and are tired of feeds full of teenagers screaming. What lands with
them: genuine skill and clutch plays, dry or self-deprecating humor, "dad
gamer" relatability (back pain, bedtime, no time to play, aging reflexes),
nostalgia, veteran game knowledge, wholesome moments, and big laughs.
What does NOT land: rage-bait, drama, gambling, cringe sexual stuff, try-hard
zoomer slang."""

TIKTOK_RULES = """\
TikTok rules to respect:
- Hook text and caption must not contain words TikTok suppresses: kill,
  killed, dead, die, death, gun, shoot, blood, suicide, sex. Use gamer-safe
  alternatives (eliminated, wiped, clutched, sent him back to the lobby,
  unalived, cooked, fragged).
- Reject (keep=false) anything with slurs, sexual content, nudity, real-world
  violence, gambling/casino, minors on screen, harassment of a real private
  person, drama/beef, or medical/political content.
- Reject clips that only make sense with outside context (inside jokes, chat
  references), clips that are mostly a menu/loading screen, and clips where
  nothing happens."""

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip_id": {"type": "string"},
                    "keep": {"type": "boolean"},
                    "score": {"type": "integer", "description": "1-10 viral potential for this audience"},
                    "hook": {"type": "string", "description": "On-screen headline, max 8 words"},
                    "caption": {"type": "string", "description": "TikTok description, 1-2 short sentences, ends with a question or call to comment"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["clip_id", "keep", "score", "hook", "caption", "hashtags", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}

STREAMER_SCHEMA = {
    "type": "object",
    "properties": {
        "streamers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "login": {"type": "string"},
                    "likely_30_plus": {"type": "boolean"},
                    "confidence": {"type": "number", "description": "0-1"},
                    "family_friendly_enough": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["login", "likely_30_plus", "confidence", "family_friendly_enough", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["streamers"],
    "additionalProperties": False,
}

TITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "Compilation headline, max 7 words"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "caption", "hashtags"],
    "additionalProperties": False,
}

SUPPRESSED = {
    "kill": "eliminate", "killed": "eliminated", "kills": "eliminations", "killing": "wiping",
    "dead": "cooked", "die": "go down", "died": "went down", "dies": "goes down",
    "death": "wipe", "gun": "blaster", "guns": "blasters", "shoot": "blast",
    "shot": "hit", "blood": "red stuff", "suicide": "self-wipe", "sex": "spicy",
}


# Game titles that contain "suppressed" words but must stay intact.
PROTECTED_TITLES = [
    "Dead by Daylight", "Red Dead Redemption", "Red Dead", "Left 4 Dead", "Dead Island",
    "Dead Space", "Death Stranding", "Killing Floor", "Kill Team", "Deathloop",
    "Dead Cells", "Hunt: Showdown",
]


def scrub(text: str) -> str:
    """Swap words TikTok suppresses for gamer-safe ones (case-preserving-ish)."""
    saved: list[str] = []

    def protect(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"\x00{len(saved) - 1}\x00"

    for title in PROTECTED_TITLES:
        text = re.sub(re.escape(title), protect, text, flags=re.IGNORECASE)

    def repl(m: re.Match) -> str:
        word = m.group(0)
        new = SUPPRESSED[word.lower()]
        if word.isupper():
            return new.upper()
        if word[0].isupper():
            return new[0].upper() + new[1:]
        return new
    pattern = r"\b(" + "|".join(sorted(SUPPRESSED, key=len, reverse=True)) + r")\b"
    text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m.group(1))], text)


def clean_hashtags(tags: list[str], base: list[str], limit: int = 6) -> list[str]:
    out: list[str] = []
    for t in [*tags, *base]:
        t = "#" + re.sub(r"[^0-9A-Za-z_]", "", t.lstrip("#"))
        if len(t) > 1 and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:limit]


class Brain:
    def __init__(self, api_key: str | None, model: str, effort: str = "low"):
        self.model = model
        self.effort = effort
        self.client = None
        if api_key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            except ImportError:  # pragma: no cover
                log.warning("anthropic package missing; using rule-based picks")

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _ask(self, system: str, prompt: str, schema: dict, max_tokens: int = 16000) -> dict | None:
        if not self.client:
            return None
        import anthropic
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            log.error("ANTHROPIC_API_KEY was rejected; using rule-based picks this run")
            return None
        except anthropic.RateLimitError:
            log.warning("Claude rate limited; using rule-based picks this run")
            return None
        except anthropic.APIStatusError as e:
            log.warning("Claude API error %s; using rule-based picks this run", e.status_code)
            return None
        except anthropic.APIConnectionError:
            log.warning("Couldn't reach Claude; using rule-based picks this run")
            return None
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("Claude stopped early (%s); using rule-based picks", resp.stop_reason)
            return None
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Claude returned unparseable JSON; using rule-based picks")
            return None

    # ---- clip selection --------------------------------------------------
    def judge_clips(self, candidates: list[dict], base_hashtags: list[str]) -> list[dict]:
        """candidates: dicts with id, broadcaster_name, title, game_name, view_count,
        duration, age_hours, transcript. Returns picks sorted best-first (keep only)."""
        lines = []
        for c in candidates:
            lines.append(json.dumps({
                "clip_id": c["id"],
                "streamer": c.get("broadcaster_name"),
                "game": c.get("game_name") or "unknown",
                "clip_title": c.get("title"),
                "views": c.get("view_count"),
                "hours_old": round(c.get("age_hours", 0), 1),
                "seconds": round(c.get("duration", 0), 1),
                "transcript": (c.get("transcript") or "")[:1500] or "(no speech / not transcribed)",
            }, ensure_ascii=False))
        prompt = (
            "Judge each candidate Twitch clip below for our channel. For every clip return one "
            "pick entry (same clip_id). Set keep=false for anything that breaks the rules or is "
            "boring. For keepers write:\n"
            "- hook: punchy on-screen headline, max 8 words, makes a 35-year-old stop scrolling "
            "(no emojis, no clickbait lies, don't just repeat the clip title).\n"
            "- caption: 1-2 short sentences in a relatable millennial voice, credit the streamer "
            "by name, end with a question that invites comments.\n"
            "- hashtags: 3-5 specific tags (game, streamer, moment type), no '#fyp' spam.\n"
            "- score: 1-10 viral potential for THIS audience. Views per hour is a strong signal "
            "that real viewers found it funny or impressive.\n\n"
            "Candidates (one JSON object per line):\n" + "\n".join(lines)
        )
        result = self._ask(AUDIENCE + "\n\n" + TIKTOK_RULES, prompt, PICK_SCHEMA)
        if result is None:
            return self._rule_picks(candidates, base_hashtags)
        by_id = {c["id"]: c for c in candidates}
        picks = []
        for p in result.get("picks", []):
            if p.get("clip_id") not in by_id or not p.get("keep"):
                continue
            c = by_id[p["clip_id"]]
            picks.append({
                "clip_id": p["clip_id"],
                "score": max(1, min(10, int(p.get("score", 5)))),
                "hook": scrub(p.get("hook", "").strip())[:80] or scrub(c.get("title", "")),
                "caption": scrub(p.get("caption", "").strip()),
                "hashtags": clean_hashtags(p.get("hashtags", []), base_hashtags),
                "reason": p.get("reason", ""),
            })
        picks.sort(key=lambda p: (-p["score"], -by_id[p["clip_id"]].get("velocity", 0)))
        return picks

    @staticmethod
    def _rule_picks(candidates: list[dict], base_hashtags: list[str]) -> list[dict]:
        picks = []
        for c in sorted(candidates, key=lambda c: -c.get("velocity", 0)):
            name = c.get("broadcaster_name", "")
            game = c.get("game_name") or ""
            game_tag = "#" + re.sub(r"[^0-9A-Za-z]", "", game) if game else ""
            picks.append({
                "clip_id": c["id"],
                "score": 5,
                "hook": scrub(c.get("title") or f"{name} moment")[:80],
                "caption": scrub(f"{name} in {game or 'the game'}. Would you have done better? 👇"),
                "hashtags": clean_hashtags([f"#{name}", game_tag], base_hashtags),
                "reason": "rule-based (no AI key): ranked by views per hour",
            })
        return picks

    # ---- streamer vetting --------------------------------------------------
    def vet_streamers(self, candidates: list[dict]) -> list[dict]:
        """candidates: login, display_name, description, created_at, games, clip_titles."""
        if not candidates:
            return []
        prompt = (
            "We only feature Twitch streamers who are 30 years old or older (born 1996 or "
            "earlier). For each streamer below, use what you know about them plus the clues "
            "given (account age, bio, games, clip titles) to estimate whether they are 30+. "
            "Only give confidence >= 0.8 when you actually know who they are or the evidence "
            "is strong (e.g. they mention their kids/wife/age, or their account is 12+ years old "
            "and they were already an adult then). Unknown small streamers should get low "
            "confidence. Also flag family_friendly_enough=false for streamers known for "
            "gambling streams, hate speech, or constant sexual content.\n\n"
            + "\n".join(json.dumps(c, ensure_ascii=False) for c in candidates)
        )
        result = self._ask(AUDIENCE, prompt, STREAMER_SCHEMA)
        if result is None:
            return [
                {"login": c["login"], "likely_30_plus": False, "confidence": 0.0,
                 "family_friendly_enough": True,
                 "reason": "no AI key: needs a manual look (`bossbandit streamers review`)"}
                for c in candidates
            ]
        return result.get("streamers", [])

    # ---- compilation copy --------------------------------------------------
    def compilation_copy(self, segments: list[dict], base_hashtags: list[str]) -> dict:
        prompt = (
            "Write the headline, caption and hashtags for a 60-90 second compilation of these "
            "clips, posted as a 'best of the week' for millennial gamers:\n"
            + "\n".join(f"- {s['broadcaster_name']} ({s.get('game_name') or 'game'}): {s['hook']}" for s in segments)
        )
        result = self._ask(AUDIENCE + "\n\n" + TIKTOK_RULES, prompt, TITLE_SCHEMA, max_tokens=4000)
        names = ", ".join(dict.fromkeys(s["broadcaster_name"] for s in segments))
        if result is None:
            return {
                "hook": "Millennial Gamer Moments of the Week",
                "caption": f"This week's best from {names}. Which one got you? 👇",
                "hashtags": clean_hashtags(["#bestof", "#streamerhighlights"], base_hashtags),
            }
        return {
            "hook": scrub(result["hook"])[:80],
            "caption": scrub(result["caption"]),
            "hashtags": clean_hashtags(result.get("hashtags", []), base_hashtags),
        }
