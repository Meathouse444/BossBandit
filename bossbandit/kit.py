"""The daily 'posting kit': finished videos + ready-to-paste captions + a
review page you can open on your PC or phone."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

# Millennial audience: lunch break, after work, after the kids are asleep.
POST_TIMES = ["12:00 PM", "6:00 PM", "9:00 PM", "10:30 PM"]


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", text).strip("-").lower()
    return (s[:max_len].rstrip("-")) or "clip"


def full_caption(item: dict) -> str:
    tags = " ".join(item.get("hashtags", []))
    credit = f"🎥 {item['credit']}" if item.get("credit") else ""
    return "\n".join(x for x in [item.get("caption", ""), credit, tags] if x).strip()


class Kit:
    def __init__(self, output_dir: Path, day: datetime | None = None):
        self.day = (day or datetime.now()).strftime("%Y-%m-%d")
        self.dir = output_dir / self.day
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.json"
        self.items: list[dict] = []
        if self.manifest_path.exists():
            self.items = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def next_path(self, login: str, hook: str, kind: str = "clip") -> Path:
        n = len(self.items) + 1
        prefix = "BEST-OF" if kind == "compilation" else login
        return self.dir / f"{n:02d}_{prefix}_{slugify(hook)}.mp4"

    def add(self, video: Path, item: dict) -> None:
        item = {**item, "file": video.name}
        item["post_at"] = POST_TIMES[len(self.items) % len(POST_TIMES)]
        self.items.append(item)
        video.with_suffix(".txt").write_text(full_caption(item) + "\n", encoding="utf-8")
        self.save()

    def save(self) -> None:
        self.manifest_path.write_text(json.dumps(self.items, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.dir / "index.html").write_text(self.render_html(), encoding="utf-8")

    def render_html(self) -> str:
        cards = []
        for i, it in enumerate(self.items):
            cap = full_caption(it)
            badge = "Compilation · 60s+ (Creator Rewards eligible)" if it.get("kind") == "compilation" else "Clip"
            cards.append(f"""
<article class="card">
  <video src="{html.escape(it['file'])}" controls preload="metadata" playsinline></video>
  <div class="meta">
    <div class="row"><span class="badge">{badge}</span><span class="time">Post at {html.escape(it['post_at'])}</span></div>
    <h2>{html.escape(it.get('hook', ''))}</h2>
    <p class="src">{html.escape(it.get('streamer', ''))} · {html.escape(it.get('game', '') or '')} · <a href="{html.escape(it.get('source_url', '#'))}" target="_blank" rel="noopener">original</a></p>
    <textarea id="c{i}" readonly>{html.escape(cap)}</textarea>
    <div class="row">
      <button onclick="copyCap('c{i}', this)">Copy caption</button>
      <a class="btn" href="{html.escape(it['file'])}" download>Download video</a>
    </div>
    <p class="why">{html.escape(it.get('reason', ''))}</p>
  </div>
</article>""")
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BossBandit {self.day}</title>
<style>
:root {{ --bg:#0f1115; --card:#191c23; --fg:#eef0f4; --mut:#9aa3b2; --acc:#ffd400; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.4 system-ui,Segoe UI,Arial,sans-serif; padding:16px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} .sub {{ color:var(--mut); margin:0 0 16px; }}
.grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }}
.card {{ background:var(--card); border-radius:14px; overflow:hidden; }}
video {{ width:100%; aspect-ratio:9/16; background:#000; display:block; }}
.meta {{ padding:12px; }} h2 {{ font-size:18px; margin:6px 0; }}
.row {{ display:flex; gap:8px; align-items:center; justify-content:space-between; flex-wrap:wrap; }}
.badge {{ background:#2a2f3a; padding:2px 8px; border-radius:99px; font-size:12px; }}
.time {{ color:var(--acc); font-weight:600; font-size:14px; }}
.src, .why {{ color:var(--mut); font-size:13px; margin:4px 0; }} a {{ color:var(--acc); }}
textarea {{ width:100%; min-height:110px; background:#0f1115; color:var(--fg); border:1px solid #2a2f3a; border-radius:8px; padding:8px; font:inherit; font-size:14px; margin:6px 0; }}
button, .btn {{ background:var(--acc); color:#000; border:0; border-radius:8px; padding:8px 14px; font-weight:700; cursor:pointer; text-decoration:none; font-size:14px; }}
</style></head><body>
<h1>BossBandit posting kit · {self.day}</h1>
<p class="sub">{len(self.items)} videos. Watch each one first. Post 1 at each time slot, paste the caption, and reply to every comment in the first hour.</p>
<div class="grid">{''.join(cards)}</div>
<script>
function copyCap(id, btn) {{
  const t = document.getElementById(id);
  const done = () => {{ btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy caption', 1500); }};
  if (navigator.clipboard) navigator.clipboard.writeText(t.value).then(done, () => {{ t.select(); document.execCommand('copy'); done(); }});
  else {{ t.select(); document.execCommand('copy'); done(); }}
}}
</script>
</body></html>
"""
