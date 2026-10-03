"""Downloading clips, probing files, and speech-to-text."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .captions import Word

log = logging.getLogger(__name__)


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(
                f"{tool} not found. Install it (Windows: `winget install Gyan.FFmpeg`, then "
                "open a NEW terminal) - see README step 1."
            )


def download_clip(url: str, dest: Path) -> Path:
    """Download a Twitch clip as mp4 with yt-dlp. Returns the file path."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    import yt_dlp

    opts = {
        "outtmpl": str(dest.with_suffix("")) + ".%(ext)s",
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:  # yt-dlp raises many types
        raise MediaError(f"download failed for {url}: {e}") from e
    matches = sorted(dest.parent.glob(dest.stem + ".*"))
    if not matches:
        raise MediaError(f"download produced no file for {url}")
    got = matches[0]
    if got != dest:
        got.replace(dest)
    return dest


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed on {path.name}: {out.stderr.strip()[:300]}")
    info = json.loads(out.stdout)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise MediaError(f"{path.name} has no video stream")
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "duration": duration,
        "has_audio": has_audio,
    }


_WHISPER_CACHE: dict[tuple, object] = {}


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe(path: Path, model_size: str = "small", device: str = "auto") -> list[Word]:
    """Word-level transcript of the clip (timestamps relative to clip start)."""
    from faster_whisper import WhisperModel

    key = (model_size, device)
    model = _WHISPER_CACHE.get(key)
    if model is None:
        compute = "int8"
        if device == "cuda":
            compute = "float16"
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute)
        except Exception as e:
            if device != "cpu":
                log.warning("Whisper on %s failed (%s); falling back to CPU", device, e)
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
            else:
                raise
        _WHISPER_CACHE[key] = model
    try:
        return _words(model, path)
    except Exception as e:
        if device == "cpu":
            raise
        # GPU libraries often load fine but fail on first use. Switch this
        # model to CPU for the rest of the run.
        log.warning("Whisper on %s failed (%s); switching to CPU", device, e)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _WHISPER_CACHE[key] = model
        return _words(model, path)


def _words(model, path: Path) -> list[Word]:
    segments, _info = model.transcribe(
        str(path), word_timestamps=True, vad_filter=True, beam_size=5,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(start=float(w.start), end=float(w.end), text=text))
    return words


def words_to_text(words: list[Word]) -> str:
    return " ".join(w.text for w in words)
