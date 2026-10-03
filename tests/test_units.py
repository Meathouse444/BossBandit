from __future__ import annotations

import json
from types import SimpleNamespace

from bossbandit.brain import Brain, clean_hashtags, scrub
from bossbandit.captions import Layout, Word, ass_color, ass_time, build_ass, group_words
from bossbandit.config import load_config
from bossbandit.kit import Kit, full_caption, slugify


def test_ass_time_and_color():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(61.234) == "0:01:01.23"
    assert ass_time(3725.5) == "1:02:05.50"
    assert ass_color("#FFD400") == "&H0000D4FF"


def test_group_words_breaks_on_size_gap_and_sentence():
    words = [Word(0, .2, "no"), Word(.2, .4, "way"), Word(.4, .6, "dude."), Word(.6, .8, "he"),
             Word(2.0, 2.2, "actually"), Word(2.2, 2.4, "hit"), Word(2.4, 2.6, "it")]
    groups = [[w.text for w in g] for g in group_words(words)]
    assert groups == [["no", "way", "dude."], ["he"], ["actually", "hit", "it"]]


def test_build_ass_escapes_and_times():
    ass = build_ass(width=1080, height=1920, duration=3.0, layout=Layout(100, 1300, 1400),
                    words=[Word(0.1, 0.5, "{evil}"), Word(0.5, 0.9, "back\\slash")],
                    hook="Clutch {play}", hook_seconds=4, credit="twitch.tv/x", watermark="@me",
                    font="Arial")
    events = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    # hook clipped to clip duration, braces from user text neutralised
    assert any("Hook" in e and "0:00:03.00" in e and "Clutch (play)" in e for e in events)
    assert "{evil}" not in ass and "(EVIL)" in ass and "BACK/SLASH" in ass
    assert sum("Caption" in e for e in events) == 2


def test_scrub_keeps_game_titles():
    assert scrub("Killed in Dead by Daylight") == "Eliminated in Dead by Daylight"
    assert scrub("he died") == "he went down"
    assert scrub("Diablo headshot") == "Diablo headshot"


def test_clean_hashtags():
    assert clean_hashtags(["wow", "#World of Warcraft!", "#WOW"], ["#gaming"]) == ["#wow", "#WorldofWarcraft", "#gaming"]


class FakeMessages:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.calls = payload, stop, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def brain_with(payload, stop="end_turn"):
    b = Brain(None, "claude-opus-5-5")
    msgs = FakeMessages(payload, stop)
    b.client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return b, msgs


CANDS = [
    {"id": "a", "broadcaster_name": "shroud", "title": "t1", "game_name": "CS", "view_count": 10, "velocity": 1, "duration": 20},
    {"id": "b", "broadcaster_name": "lirik", "title": "t2", "game_name": "WoW", "view_count": 50, "velocity": 9, "duration": 20},
]


def test_judge_clips_uses_claude_and_filters():
    b, msgs = brain_with({"picks": [
        {"clip_id": "a", "keep": True, "score": 9, "hook": "He shot first", "caption": "c", "hashtags": ["cs2"], "reason": "r"},
        {"clip_id": "b", "keep": False, "score": 2, "hook": "x", "caption": "x", "hashtags": [], "reason": "boring"},
        {"clip_id": "zzz", "keep": True, "score": 10, "hook": "ghost", "caption": "", "hashtags": [], "reason": ""},
    ]})
    picks = b.judge_clips(CANDS, ["#gaming"])
    assert [p["clip_id"] for p in picks] == ["a"]
    assert picks[0]["hook"] == "He hit first"
    assert picks[0]["hashtags"] == ["#cs2", "#gaming"]
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_judge_clips_falls_back_on_refusal():
    b, _ = brain_with({}, stop="refusal")
    picks = b.judge_clips(CANDS, [])
    assert [p["clip_id"] for p in picks] == ["b", "a"]   # by velocity


def test_kit_writes_captions_and_html(tmp_path):
    kit = Kit(tmp_path)
    v = kit.next_path("shroud", "Insane <clutch> & stuff!")
    assert v.name == "01_shroud_insane-clutch-stuff.mp4"
    v.write_bytes(b"x")
    item = {"hook": "Insane <clutch>", "caption": "Wow.", "hashtags": ["#a"], "credit": "twitch.tv/shroud",
            "streamer": "shroud", "source_url": "https://x"}
    kit.add(v, item)
    assert "twitch.tv/shroud" in v.with_suffix(".txt").read_text(encoding="utf-8")
    page = (kit.dir / "index.html").read_text(encoding="utf-8")
    assert "Insane &lt;clutch&gt;" in page and "<clutch>" not in page
    assert Kit(tmp_path).items[0]["post_at"] == "12:00 PM"   # reloads manifest
    assert full_caption({"caption": "c", "hashtags": []}) == "c"
    assert slugify("!!!") == "clip"


def test_config_merges_and_reads_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    (tmp_path / "config.toml").write_text('[schedule]\nposts_per_day = 5\n', encoding="utf-8")
    (tmp_path / ".env").write_text('TWITCH_CLIENT_ID="abc"\n# comment\n', encoding="utf-8")
    cfg = load_config(tmp_path / "config.toml")
    assert cfg["schedule"]["posts_per_day"] == 5
    assert cfg["schedule"]["lookback_days"] == 3       # default kept
    assert cfg.secret("TWITCH_CLIENT_ID") == "abc"
    assert cfg.output_dir == tmp_path / "output"
