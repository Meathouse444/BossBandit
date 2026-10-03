"""Command line: `bossbandit <command>`. Run `bossbandit --help`."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, SECRET_KEYS, load_config

ENV_TEMPLATE = """\
# BossBandit secrets. Never share this file or commit it.
# 1) Twitch: https://dev.twitch.tv/console/apps -> Register Your Application
#    (OAuth Redirect URL: http://localhost , Category: Application Integration,
#    Client Type: Confidential) -> copy Client ID, click "New Secret".
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
# 2) Claude (optional but makes the picks/hooks MUCH better):
#    https://console.anthropic.com -> API Keys -> Create Key. Add $5-10 credit.
ANTHROPIC_API_KEY=
"""


def setup_logging(data_dir: Path, verbose: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = logging.FileHandler(data_dir / "bossbandit.log", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.WARNING)
    root.addHandler(fh)
    root.addHandler(ch)
    for noisy in ("urllib3", "httpx", "httpcore", "faster_whisper", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def say(msg: str = "") -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------- commands
def cmd_init(args) -> int:
    cfg_path = Path(args.config or "config.toml")
    env_path = cfg_path.resolve().parent / ".env"
    if cfg_path.exists():
        say(f"• {cfg_path} already exists (left untouched)")
    else:
        shutil.copy(DEFAULT_CONFIG_PATH, cfg_path)
        say(f"✓ created {cfg_path}  (your settings)")
    if env_path.exists():
        say(f"• {env_path.name} already exists (left untouched)")
    else:
        env_path.write_text(ENV_TEMPLATE, encoding="utf-8")
        say(f"✓ created {env_path.name}  (paste your API keys in here)")
    say("\nNext: fill in .env, then run:  bossbandit doctor")
    return 0


def cmd_doctor(args) -> int:
    from .media import whisper_available
    cfg = load_config(args.config)
    ok = True

    def check(good: bool, label: str, fix: str = "") -> None:
        nonlocal ok
        say(f"  {'✓' if good else '✗'} {label}" + ("" if good or not fix else f"\n      → {fix}"))
        ok = ok and good

    say("BossBandit health check\n")
    check(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Install Python 3.11 or newer")
    check(bool(shutil.which("ffmpeg")), "ffmpeg installed", "Windows: winget install Gyan.FFmpeg  (then open a NEW terminal)")
    check(bool(shutil.which("ffprobe")), "ffprobe installed", "comes with ffmpeg")
    try:
        import yt_dlp  # noqa: F401
        check(True, "yt-dlp installed")
    except ImportError:
        check(False, "yt-dlp installed", "pip install -U yt-dlp")
    for key in SECRET_KEYS:
        present = bool(cfg.secret(key))
        if key == "ANTHROPIC_API_KEY":
            say(f"  {'✓' if present else '•'} {key} {'set' if present else 'not set (optional - rule-based picks will be used)'}")
        else:
            check(present, f"{key} set", "put it in .env (see README step 3)")
    if cfg.secret("TWITCH_CLIENT_ID") and cfg.secret("TWITCH_CLIENT_SECRET"):
        try:
            from .twitch import Twitch
            u = Twitch(cfg.secret("TWITCH_CLIENT_ID"), cfg.secret("TWITCH_CLIENT_SECRET")).users_by_login(["shroud"])
            check(bool(u), "Twitch API login works")
        except Exception as e:
            check(False, "Twitch API login works", str(e))
    if cfg["render"]["captions"]:
        w = whisper_available()
        say(f"  {'✓' if w else '•'} captions engine (faster-whisper) {'installed' if w else 'missing → pip install faster-whisper  (videos still render, just without captions)'}")
    from .pipeline import disk_free_gb
    free = disk_free_gb(cfg.output_dir)
    check(free > 2, f"{free:.0f} GB free for videos", "free up some disk space")
    say(f"\n  output folder: {cfg.output_dir}")
    say("\nAll good! Run:  bossbandit run" if ok else "\nFix the ✗ items above, then run doctor again.")
    return 0 if ok else 1


def cmd_run(args) -> int:
    from .pipeline import Pipeline
    cfg = load_config(args.config)
    setup_logging(cfg.data_dir, args.verbose)
    say("BossBandit: finding today's clips… (first run downloads the captions model, ~500 MB)")
    pipe = Pipeline(cfg)
    try:
        s = pipe.run(dry_run=args.dry_run, skip_discovery=args.no_discover)
    finally:
        pipe.db.close()
    if s.discovered:
        say(f"\n+ New streamers auto-approved: {', '.join(s.discovered)}")
    if s.pending_review:
        say(f"? Waiting for your OK: {', '.join(s.pending_review)}  →  bossbandit streamers review")
    say(f"\nLooked at {s.candidates} candidate clips.")
    for n in s.notes:
        say(f"  {n}")
    if s.videos:
        say(f"\n✓ {len(s.videos)} videos ready in: {s.kit_dir}")
        say(f"  Open {s.kit_dir / 'index.html'} to review + copy captions.")
    return 0


def cmd_discover(args) -> int:
    from .pipeline import Pipeline
    cfg = load_config(args.config)
    setup_logging(cfg.data_dir, args.verbose)
    pipe = Pipeline(cfg)
    pipe.ensure_seeds()
    approved, pending = pipe.discover()
    say(f"Auto-approved: {', '.join(approved) or '-'}")
    say(f"Needs review:  {', '.join(pending) or '-'}")
    return 0


def cmd_streamers(args) -> int:
    from .db import DB
    import json
    cfg = load_config(args.config)
    db = DB(cfg.data_dir / "bossbandit.db")
    action = args.action
    names = [n.lower().lstrip("@") for n in args.names]
    try:
        if action == "list":
            rows = db.streamers(args.status)
            if not rows:
                say("No streamers yet. Run `bossbandit run` (seeds the starter list) or `bossbandit streamers add NAME`.")
            for r in rows:
                flags = []
                if r["permission"]:
                    flags.append("permitted")
                if r["facecam"]:
                    flags.append("facecam")
                conf = f" ai={r['ai_confidence']:.2f}" if r["ai_confidence"] is not None else ""
                say(f"  {r['status']:<9} {r['login']:<20} {r['source']:<10}{conf} {' '.join(flags)}")
                if args.status == "pending" and r["ai_reason"]:
                    say(f"            ↳ {r['ai_reason']}")
        elif action in ("add", "approve"):
            for n in names:
                db.upsert_streamer(n, status="approved")
                say(f"✓ {n} approved")
        elif action == "reject":
            for n in names:
                db.upsert_streamer(n, status="rejected")
                say(f"✗ {n} rejected (won't be clipped or suggested again)")
        elif action in ("permit", "unpermit"):
            for n in names:
                db.upsert_streamer(n, permission=1 if action == "permit" else 0)
                say(f"{'✓' if action == 'permit' else '•'} {n} permission {'granted' if action == 'permit' else 'removed'}")
        elif action == "facecam":
            if len(names) != 5:
                say("usage: bossbandit streamers facecam NAME X Y W H   (fractions 0-1 of the screen,\n"
                    "e.g. bottom-left cam: facecam lirik 0 0.7 0.25 0.3)  ·  `facecam NAME off` to clear")
                if len(names) == 2 and names[1] == "off":
                    db.upsert_streamer(names[0], facecam=None)
                    say(f"• facecam cleared for {names[0]}")
                    return 0
                return 1
            vals = [float(v) for v in names[1:]]
            if not all(0 <= v <= 1 for v in vals) or vals[0] + vals[2] > 1.001 or vals[1] + vals[3] > 1.001:
                say("facecam numbers must be fractions between 0 and 1 that stay inside the screen")
                return 1
            db.upsert_streamer(names[0], facecam=json.dumps(vals))
            say(f"✓ facecam saved for {names[0]}. Set render.layout = \"split\" in config.toml to use it.")
        elif action == "review":
            rows = db.streamers("pending")
            if not rows:
                say("Nothing waiting for review.")
            for r in rows:
                say(f"\n{r['display_name'] or r['login']}  →  https://twitch.tv/{r['login']}")
                say(f"   AI says: {r['ai_reason'] or '-'}")
                ans = input("   Feature them? [y]es / [n]o / [s]kip: ").strip().lower()
                if ans.startswith("y"):
                    db.upsert_streamer(r["login"], status="approved")
                elif ans.startswith("n"):
                    db.upsert_streamer(r["login"], status="rejected")
    finally:
        db.close()
    return 0


def cmd_render(args) -> int:
    """One-off: render any Twitch clip URL or local video file."""
    from .media import download_clip, require_ffmpeg, transcribe, whisper_available
    from .render import RenderSettings, render_vertical
    cfg = load_config(args.config)
    setup_logging(cfg.data_dir, args.verbose)
    require_ffmpeg()
    src = Path(args.source)
    if not src.exists():
        import hashlib
        name = hashlib.sha1(args.source.encode()).hexdigest()[:12]
        src = download_clip(args.source, cfg.data_dir / "cache" / f"manual_{name}.mp4")
    words = None
    if cfg["render"]["captions"] and whisper_available() and not args.no_captions:
        words = transcribe(src, cfg["whisper"]["model"], cfg["whisper"]["device"])
    settings = RenderSettings.from_config(cfg["render"])
    if args.layout:
        settings.layout = args.layout
    facecam = [float(v) for v in args.facecam.split(",")] if args.facecam else None
    out = Path(args.out) if args.out else cfg.output_dir / "manual" / (src.stem + "_vertical.mp4")
    render_vertical(src, out, settings, hook=args.hook, words=words,
                    credit=args.credit or "", watermark=f"@{cfg['brand']['channel_name']}",
                    facecam=facecam)
    say(f"✓ {out}")
    return 0


def cmd_mark(args) -> int:
    from .db import DB
    cfg = load_config(args.config)
    db = DB(cfg.data_dir / "bossbandit.db")
    try:
        for cid in args.clip_ids:
            for one in cid.split(","):
                say(f"{'✓' if db.set_clip_status(one, args.status) else '?'} {one} → {args.status}")
    finally:
        db.close()
    return 0


def cmd_open(args) -> int:
    import webbrowser
    cfg = load_config(args.config)
    days = sorted(d for d in cfg.output_dir.glob("20*-*-*") if (d / "index.html").exists()) if cfg.output_dir.exists() else []
    if not days:
        say("No posting kits yet. Run `bossbandit run` first.")
        return 1
    page = days[-1] / "index.html"
    webbrowser.open(page.resolve().as_uri())
    say(f"Opened {page}")
    return 0


def cmd_stats(args) -> int:
    from .db import DB
    cfg = load_config(args.config)
    db = DB(cfg.data_dir / "bossbandit.db")
    try:
        for k, v in sorted(db.stats().items()):
            say(f"  {k:<20} {v}")
    finally:
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    # -c/-v work before or after the command (`bossbandit run -v`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default=argparse.SUPPRESS,
                        help="path to config.toml (default: ./config.toml)")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
                        help="show detailed logs")
    p = argparse.ArgumentParser(prog="bossbandit", description="Millennial-streamer clip machine.",
                                parents=[common])
    p.set_defaults(config=None, verbose=False)
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser

    def add_parser(name, **kw):
        return _add(name, parents=[common], **kw)
    sub.add_parser = add_parser

    sub.add_parser("init", help="create config.toml and .env").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="check that everything is installed and keys work").set_defaults(func=cmd_doctor)

    r = sub.add_parser("run", help="the daily job: find, judge, render, package")
    r.add_argument("--dry-run", action="store_true", help="show what would be picked; render nothing")
    r.add_argument("--no-discover", action="store_true", help="skip looking for new streamers")
    r.set_defaults(func=cmd_run)

    sub.add_parser("discover", help="look for new 30+ streamers now").set_defaults(func=cmd_discover)

    s = sub.add_parser("streamers", help="manage who gets clipped")
    s.add_argument("action", choices=["list", "add", "approve", "reject", "permit", "unpermit", "facecam", "review"])
    s.add_argument("names", nargs="*")
    s.add_argument("--status", choices=["approved", "pending", "rejected"])
    s.set_defaults(func=cmd_streamers)

    rd = sub.add_parser("render", help="turn one clip URL or video file into a vertical video")
    rd.add_argument("source", help="Twitch clip URL or local video path")
    rd.add_argument("--hook", help="headline text for the top")
    rd.add_argument("--credit", help='e.g. "twitch.tv/shroud"')
    rd.add_argument("--layout", choices=["blur", "zoom", "split"])
    rd.add_argument("--facecam", help="x,y,w,h fractions for split layout, e.g. 0.75,0,0.25,0.3")
    rd.add_argument("--no-captions", action="store_true")
    rd.add_argument("--out")
    rd.set_defaults(func=cmd_render)

    m = sub.add_parser("mark", help="mark clip(s) as posted (or rejected) so they're never reused")
    m.add_argument("status", choices=["posted", "rejected"])
    m.add_argument("clip_ids", nargs="+")
    m.set_defaults(func=cmd_mark)

    sub.add_parser("open", help="open the newest posting kit in your browser").set_defaults(func=cmd_open)
    sub.add_parser("stats", help="totals so far").set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:  # Windows consoles default to cp1252; keep ✓/✗ from crashing
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        say("\nStopped.")
        return 130
    except Exception as e:
        logging.getLogger("bossbandit").debug("fatal", exc_info=True)
        say(f"\nERROR: {e}")
        say("Run `bossbandit doctor` to check your setup, or add -v for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
