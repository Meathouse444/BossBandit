"""Builds the .ass subtitle file burned into each video: hook headline,
word-by-word highlighted captions, streamer credit and channel watermark.

All timestamps here are relative to the start of the clip being rendered.
Whisper is run on that same clip file, so there is no chunk-vs-absolute
timestamp mismatch to get wrong.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Layout:
    """Vertical positions (pixels from top) for each text element."""
    hook_y: int
    credit_y: int
    caption_y: int


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS is BGR with inverted alpha)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_escape(text: str) -> str:
    # Braces start override blocks and backslashes start escapes in ASS.
    return (
        text.replace("\\", "/")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", " ")
        .strip()
    )


def group_words(words: list[Word], max_words: int = 3, max_chars: int = 18,
                max_gap: float = 0.6) -> list[list[Word]]:
    """Split the transcript into short on-screen chunks (TikTok style)."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if not w.text.strip():
            continue
        if cur:
            chars = sum(len(x.text.strip()) + 1 for x in cur) + len(w.text.strip())
            gap = w.start - cur[-1].end
            ends_sentence = cur[-1].text.strip()[-1:] in ".!?"
            if len(cur) >= max_words or chars > max_chars or gap > max_gap or ends_sentence:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(*, width: int, height: int, duration: float, layout: Layout,
              words: list[Word] | None, hook: str | None, hook_seconds: float,
              credit: str, watermark: str, font: str,
              caption_color: str = "#FFFFFF", highlight_color: str = "#FFD400") -> str:
    white = ass_color("#FFFFFF")
    black = ass_color("#000000")
    shadow = ass_color("#000000", 0x60)
    cap = ass_color(caption_color)
    hi = ass_color(highlight_color)
    hook_size = round(height * 0.042)      # ~80px at 1920
    cap_size = round(height * 0.047)       # ~90px
    credit_size = round(height * 0.022)    # ~42px
    wm_size = round(height * 0.019)
    margin = round(width * 0.07)

    # Style fields: Name, Fontname, Fontsize, Primary, Secondary, Outline, Back,
    # Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,
    # BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
    styles = [
        # Hook: white text in a solid black box (BorderStyle 3), top-center.
        f"Style: Hook,{font},{hook_size},{white},{white},{black},{black},-1,0,0,0,100,100,0,0,3,14,0,8,{margin},{margin},{layout.hook_y},1",
        f"Style: Caption,{font},{cap_size},{cap},{cap},{black},{shadow},-1,0,0,0,100,100,1,0,1,7,3,8,{margin},{margin},{layout.caption_y},1",
        f"Style: Credit,{font},{credit_size},{white},{white},{black},{shadow},-1,0,0,0,100,100,0,0,1,4,2,8,{margin},{margin},{layout.credit_y},1",
        f"Style: Mark,{font},{wm_size},{ass_color('#FFFFFF', 0x70)},{white},{ass_color('#000000', 0x90)},{shadow},-1,0,0,0,100,100,0,0,1,2,0,9,{margin},{margin},{round(height * 0.06)},1",
    ]

    events: list[str] = []

    def ev(start: float, end: float, style: str, text: str) -> None:
        end = min(end, duration)
        if end - start < 0.04:
            return
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}")

    if hook:
        ev(0, min(hook_seconds, duration), "Hook", r"{\fad(0,250)}" + ass_escape(hook))
    ev(0, duration, "Credit", ass_escape(credit))
    if watermark:
        ev(0, duration, "Mark", ass_escape(watermark))

    if words:
        for group in group_words(words):
            tokens = [ass_escape(w.text).upper() for w in group]
            for i, w in enumerate(group):
                start = w.start
                # Hold each highlighted word until the next one starts so the
                # caption never blinks off mid-sentence.
                end = group[i + 1].start if i + 1 < len(group) else max(w.end, w.start + 0.3)
                parts = []
                for j, tok in enumerate(tokens):
                    if j == i:
                        parts.append(r"{\c" + hi + r"&\fscx108\fscy108}" + tok + r"{\c" + cap + r"&\fscx100\fscy100}")
                    else:
                        parts.append(tok)
                pop = r"{\fscx92\fscy92\t(0,80,\fscx100\fscy100)}" if i == 0 else ""
                ev(start, end, "Caption", pop + " ".join(parts))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(events) + "\n"
