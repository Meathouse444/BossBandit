"""ffmpeg rendering: 16:9 Twitch clip -> 9:16 phone video with burned-in text."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .captions import Layout, Word, build_ass
from .media import MediaError, probe

log = logging.getLogger(__name__)


@dataclass
class RenderSettings:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    layout: str = "blur"          # blur | zoom | split
    font: str = "Arial Black"
    caption_color: str = "#FFFFFF"
    highlight_color: str = "#FFD400"
    hook_seconds: float = 4.0
    crf: int = 20
    preset: str = "medium"

    @classmethod
    def from_config(cls, r: dict) -> "RenderSettings":
        return cls(
            width=int(r["width"]), height=int(r["height"]), fps=int(r["fps"]),
            layout=r["layout"], font=r["font"], caption_color=r["caption_color"],
            highlight_color=r["highlight_color"], hook_seconds=float(r["hook_seconds"]),
            crf=int(r["crf"]), preset=r["preset"],
        )


def _even(n: float) -> int:
    n = int(round(n))
    return n - (n % 2)


def video_filter(s: RenderSettings, src_w: int, src_h: int,
                 facecam: list[float] | None) -> tuple[str, Layout]:
    """Return the filter_complex for the picture (ending in [base]) + text layout."""
    W, H = s.width, s.height
    layout = s.layout
    if layout == "split" and not facecam:
        layout = "blur"

    # Cheap blur: shrink, blur, grow (blurring at full 1080x1920 is slow).
    bg = (
        f"[0:v]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
        f"crop={W // 4}:{H // 4},boxblur=12:2,eq=brightness=-0.12:saturation=1.2,"
        f"scale={W}:{H},setsar=1[bg]"
    )

    if layout == "split":
        fx, fy, fw, fh = facecam
        cam_h = _even(H * 0.38)
        game_h = H - cam_h
        cam = (
            f"[0:v]crop=iw*{fw:.4f}:ih*{fh:.4f}:iw*{fx:.4f}:ih*{fy:.4f},"
            f"scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h},setsar=1[cam]"
        )
        game = (
            f"[0:v]scale=-2:{game_h},crop={W}:{game_h},setsar=1[game]"
            if src_w / src_h >= W / game_h else
            f"[0:v]scale={W}:-2,crop={W}:{game_h},setsar=1[game]"
        )
        graph = f"{cam};{game};[cam][game]vstack=inputs=2[base]"
        return graph, Layout(hook_y=_even(H * 0.10), credit_y=cam_h - _even(H * 0.035),
                             caption_y=cam_h + _even(H * 0.02))

    if layout == "zoom":
        # Center-crop to 4:3 so the action is bigger on a phone.
        fg_h = _even(W * 3 / 4)
        fg = (
            f"[0:v]crop='min(iw,ih*4/3)':ih,scale={W}:{fg_h},setsar=1[fg]"
        )
    else:  # blur
        fg_h = _even(W * src_h / src_w)
        fg = f"[0:v]scale={W}:{fg_h},setsar=1[fg]"

    top = (H - fg_h) // 2
    graph = f"{bg};{fg};[bg][fg]overlay=(W-w)/2:{top}[base]"
    hook_y = max(_even(H * 0.08), top - _even(H * 0.17))
    credit_y = top + fg_h + _even(H * 0.012)
    caption_y = top + fg_h + _even(H * 0.05)
    return graph, Layout(hook_y=hook_y, credit_y=credit_y, caption_y=caption_y)


def render_vertical(src: Path, dest: Path, s: RenderSettings, *, hook: str | None,
                    words: list[Word] | None, credit: str, watermark: str,
                    facecam: list[float] | None = None, max_seconds: float | None = None) -> Path:
    info = probe(src)
    duration = info["duration"]
    if max_seconds:
        duration = min(duration, max_seconds)
    graph, layout = video_filter(s, info["width"], info["height"], facecam)
    ass = build_ass(
        width=s.width, height=s.height, duration=duration, layout=layout, words=words,
        hook=hook, hook_seconds=s.hook_seconds, credit=credit, watermark=watermark,
        font=s.font, caption_color=s.caption_color, highlight_color=s.highlight_color,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bb_") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "subs.ass").write_text(ass, encoding="utf-8")
        # The ass filter gets a bare filename and ffmpeg runs inside tmpdir:
        # this sidesteps ffmpeg's painful Windows path escaping (C\:/...).
        graph += f";[base]fps={s.fps},ass=subs.ass,format=yuv420p[v]"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src.resolve())]
        if info["has_audio"]:
            audio = ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            audio = ["-map", "1:a:0"]
        out_tmp = tmpdir / "out.mp4"
        cmd += [
            "-filter_complex", graph, "-map", "[v]", *audio,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", s.preset, "-crf", str(s.crf),
            "-profile:v", "high", "-level", "4.2", "-r", str(s.fps), "-g", str(s.fps * 2),
            "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000",
            "-movflags", "+faststart", str(out_tmp),
        ]
        proc = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True)
        if proc.returncode != 0 or not out_tmp.exists():
            raise MediaError(f"ffmpeg failed on {src.name}: {proc.stderr.strip()[-600:]}")
        shutil.move(str(out_tmp), dest)
    return dest


def concat_videos(parts: list[Path], dest: Path) -> Path:
    """Join already-rendered parts (identical encode settings) losslessly."""
    if not parts:
        raise MediaError("nothing to concatenate")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bb_") as tmp:
        listing = Path(tmp) / "list.txt"
        listing.write_text(
            "".join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'\n" for p in parts), encoding="utf-8"
        )
        proc = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(dest)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise MediaError(f"ffmpeg concat failed: {proc.stderr.strip()[-600:]}")
    return dest
