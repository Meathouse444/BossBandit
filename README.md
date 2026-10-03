# BossBandit

**Clips of 30+ streamers, for 30+ gamers.** BossBandit finds established
millennial streamers, pulls their best moments each day, and turns them into
ready-to-post vertical videos with captions, so millennial gamers get a feed
that isn't all teenagers screaming.

You don't have to find streamers, watch VODs, or edit anything. Each morning
you get a folder of finished videos plus a caption to paste for each one.
Your part is about 10 minutes of posting from your phone.

```
Twitch API ──► 1. FIND STREAMERS   starter list of 28 30+ streamers, plus daily auto-discovery
               2. FIND MOMENTS     clips that real viewers already made and watched, ranked by views/hour
               3. AI EDITOR        Claude watches the transcript, rejects risky/boring clips,
                                   writes the hook, caption and hashtags for a 30-45 y/o audience
               4. RENDER           9:16 video, headline, word-by-word captions, streamer credit,
                                   loudness fixed for phones
               5. POSTING KIT      output/2026-10-03/  → videos + captions + review page
                                   (+ one 60-90s "best of" that meets TikTok's 1-minute payout rule)
```

---

## How this beats the Reddit bot

| Reddit bot | BossBandit | Why it matters for you |
|---|---|---|
| Scrubs 6-hour VODs with AI | Starts from **clips viewers already made**, ranked by views per hour | Viewers have already found the best moments, so the bot doesn't have to guess. It also runs much faster and costs almost nothing. |
| You bring the streamer | **Finds 30+ streamers for you**: a starter list, then daily discovery in millennial games (WoW, Halo, CoD, Tarkov, RuneScape…), with AI vetting | This was your main requirement |
| Generic "hype" scoring | AI editor written for **millennial gamers**: dad-gamer humor, nostalgia, skill. It rejects drama, gambling and anything with slurs | Your niche is your edge |
| Playwright auto-uploads to TikTok | **You post from your phone** (2 min/video) | Browser bots break TikTok's rules and get accounts shadow-banned or banned, and a banned account is the fastest way to lose this income. |
| Captions shipped broken | Captions work and are tested: word-by-word highlight, TikTok style | Most people watch with the sound off, so captions matter |
| Clips only, all under 60s | Also builds a **60-90s compilation** every day | TikTok only pays Creator Rewards on videos **over 1 minute** |
| — | Swaps words TikTok suppresses (kill, dead, gun…) for gamer slang (eliminated, cooked…) | Keeps the algorithm from quietly limiting your reach |
| — | Never reuses a clip, max 1 clip per streamer per day, credits every streamer on screen and in the caption | Keeps the feed fresh and keeps you on good terms with streamers |

---

## The money: how this actually pays (please read)

I'm going to be straight with you, because your family is counting on this.
**This is not instant money.** Realistic timelines run from weeks to a few
months. Here are the ways it pays, fastest first:

### 1. Clipping programs: the fastest path to your first dollar
Streamers and agencies pay clippers per 1,000 views to spread their content.
Rates vary, often around $0.50–$3 per 1,000 views. You don't need 10k
followers first, because you get paid on views from day one.
- Search **Whop "Content Rewards"** and similar clipping marketplaces for
  campaigns from streamers on your list (or any 30+ streamer).
- Many big streamers run their own clipper program through their Discord.
  Check their Discord for a "#clippers" channel or ask a mod.
- For a campaign streamer, run `bossbandit streamers add theirname` and follow
  that campaign's rules on hashtags, caption tags and links. Edit the `.txt`
  caption before you post.

### 2. TikTok Creator Rewards Program
Requirements: 18+, **10,000 followers**, **100,000 views in the last 30 days**,
an eligible country (the US is one), and **videos over 1 minute** of
**original** content. People usually report earning roughly $0.40–$1.00 per
1,000 qualified views. That's why BossBandit makes a 60s+ compilation every
day. Reposted clips with no changes can get flagged as "unoriginal". Your
hook text, captions, curation and (best of all) **your own voice-over or
reaction** are what make a video count as yours. Recording a 10-second
intro in TikTok's editor ("Millennial gamer moment of the day…") adds a lot.

### 3. YouTube Shorts + Instagram Reels + Facebook Reels: same videos, triple the reach
Upload the **exact same files** to all of them. It's free extra reach.
YouTube pays Shorts creators once you hit 1,000 subscribers and 10M Shorts
views in 90 days. Facebook also pays for Reels. Diversifying protects you if
one platform bans or throttles your account.

### Permission: protect the account
Clips belong to the streamer. Most streamers love clippers because you're
free promotion, but **asking first is what makes this a business and not a
gamble**. Send this DM/email to the streamer, their editor or their manager
(Discord or business email):

> Hey [name]! I run a TikTok channel for millennial gamers (30+ crowd)
> featuring streamers like you. I'd love to post clips of your streams with
> full credit and a link to your Twitch in every post. Are you cool with that?
> Happy to tag you, use your hashtags, or join your clip program if you have one.

When someone says yes, run `bossbandit streamers permit theirname`. Once
5–10 have said yes, set `mode = "granted"` in `config.toml` so the bot only
uses their clips. If you ever get a takedown or a "please stop", delete the
video and run `bossbandit streamers reject name`. Never pretend to be the
streamer, and never use their name as your channel name.

---

## Setup (Windows, about 20 minutes, no experience needed)

### Step 1: Get the code
On this GitHub page, click the green **Code** button, then **Download ZIP**.
Unzip it somewhere easy, e.g. `Documents\BossBandit`.

### Step 2: Install everything (one command)
Open the `BossBandit` folder, right-click an empty spot, and choose **Open in
Terminal**. Paste this and press Enter:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

This installs Python, ffmpeg (the video engine) and BossBandit. If it asks
you to close and reopen the terminal, do that and run the same command again.
At the end it opens a file called `.env` in Notepad.

### Step 3: Get your Twitch key (free, 3 minutes)
1. Go to https://dev.twitch.tv/console/apps and log in with any Twitch
   account. Twitch requires two-factor authentication on that account; it
   will walk you through turning it on.
2. Click **Register Your Application**:
   - Name: `bossbandit-yourname` (anything unique)
   - OAuth Redirect URL: `http://localhost`
   - Category: `Application Integration`
   - Client Type: **Confidential**
3. Click **Manage** on your app. Copy the **Client ID** into `.env` after
   `TWITCH_CLIENT_ID=`. Click **New Secret** and copy it after
   `TWITCH_CLIENT_SECRET=`.

### Step 4: Get your Claude key (recommended, about $1–3/month)
This is the AI editor that picks the clips and writes the hooks. The bot works
without it, but the hooks are much better with it.
1. https://console.anthropic.com → sign up → **Billing**, add $5 of credit.
2. **API Keys** → **Create Key** → paste it after `ANTHROPIC_API_KEY=` in `.env`.
3. Save and close `.env`.

### Step 5: First run
Double-click **`scripts\run_now.bat`**. It checks your setup, finds clips,
renders them, and opens the review page in your browser. The first run is
slow because it downloads the captions model (about 500 MB, one time only).

### Step 6: Make it automatic
In the terminal:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
```
Now it runs every morning at 7:00 AM. If your PC is off at 7, it runs as soon
as you turn it on. To use a different time, add `-Time 05:30`.

**Tip:** to get the videos on your phone automatically, install Google Drive
for desktop (or OneDrive) and set `output_dir` in `config.toml` to a folder
inside it, e.g. `output_dir = "G:/My Drive/BossBandit"`. Videos then show up
in the Drive app on your phone, ready to post.

---

## Your daily routine (about 10 minutes)

1. Open today's kit: on your PC, run `bossbandit open` or open
   `output\<today>\index.html`; on your phone, open the Drive app.
2. **Watch every video before you post it.** You're the last line of quality
   control. If one is bad, skip it and run `bossbandit mark rejected <clip id>`.
3. Post one at each suggested time (**12 PM, 6 PM, 9 PM**, which is lunch,
   after work, and after the kids are asleep). Upload in the TikTok app, then
   paste the caption from the matching `.txt` file or the "Copy caption" button.
4. Reply to every comment in the first hour. That's the strongest growth
   lever you control.
5. Upload the same videos to YouTube Shorts and Instagram Reels when you have
   a minute.

### TikTok account tips for a brand-new account
- Make a dedicated account with a niche name and bio, e.g. *"Clips from
  streamers who remember LAN parties. 30+ gamers only 🎮"*.
- For the first few days, scroll and like gaming content as a normal user
  before you post. That teaches TikTok what your account is about.
- Post **every day**, 2–3 times. Consistency beats volume.
- Don't use a VPN, don't post the same video twice, and don't buy followers.
- Pin your best-performing video to your profile.
- Watch which streamers and games get views in TikTok's analytics. Use
  `bossbandit streamers reject` on duds and `bossbandit streamers add` for
  more of what works.

---

## Commands

All commands run from the BossBandit folder. If you're not using the `.bat`
files, activate the environment first with `.venv\Scripts\activate`.

| Command | What it does |
|---|---|
| `bossbandit run` | The daily job. `--dry-run` shows the picks without rendering. |
| `bossbandit open` | Opens the newest posting kit in your browser |
| `bossbandit doctor` | Checks the install and your keys |
| `bossbandit streamers list` | Who's on the list (`--status pending` shows ones waiting for you) |
| `bossbandit streamers review` | Approve or reject streamers the AI wasn't sure about |
| `bossbandit streamers add NAME` | Add a streamer by hand (their Twitch login) |
| `bossbandit streamers reject NAME` | Never use this streamer again |
| `bossbandit streamers permit NAME` | Record that they gave permission |
| `bossbandit streamers facecam NAME X Y W H` | Facecam position, for the split layout (see below) |
| `bossbandit discover` | Look for new 30+ streamers right now |
| `bossbandit render URL --hook "text"` | Make a video from any one Twitch clip link or video file |
| `bossbandit mark posted CLIP_ID` | Record that a clip was posted |
| `bossbandit stats` | Totals |

### Settings (`config.toml`)
Every setting is explained in the file itself. The ones you're most likely to change:
- `posts_per_day`: 3 to start.
- `layout`: `blur` (default), `zoom` (bigger action), or `split` (facecam on top,
  gameplay below, which is the classic TikTok look and needs a facecam position).
- `[discovery] games`: the games to search for new streamers.
- `[permissions] mode`: switch to `"granted"` once you have permissions.
- `[seed] streamers`: the starter list. Birth years come from public info, so
  double-check anyone you care about.

**Facecam position:** pause a stream and estimate where the webcam box sits,
as fractions of the screen from the top-left corner. For a cam in the
bottom-left quarter: `bossbandit streamers facecam lirik 0 0.7 0.25 0.3`
means 0% from the left, 70% from the top, 25% wide, 30% tall. Test it with
`bossbandit render <clip link> --layout split --facecam 0,0.7,0.25,0.3`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ffmpeg not found` | Close the terminal and open a new one. If that doesn't help: `winget install Gyan.FFmpeg` |
| `Twitch login failed` | Re-copy the Client ID and Secret into `.env` with no spaces, then click **New Secret** again if needed |
| Downloads fail | Twitch changed something. Run `.venv\Scripts\python -m pip install -U yt-dlp` (the daily job already does this) |
| "No new clips matched today" | Increase `lookback_days` or lower `min_clip_views` in `config.toml` |
| No captions on videos | Run `.venv\Scripts\python -m pip install faster-whisper`, then `bossbandit doctor` |
| Anything else | Check `data\bossbandit.log` and `data\daily.log`, or run with `-v` for details |

## Costs
- Twitch API, ffmpeg, Whisper captions: **free** (everything runs on your PC).
- Claude: one request per day for clip judging, plus one for discovery. That
  comes to a few cents a day, roughly $1–3 a month.
- Nothing else. No server and no subscription.

## Why there's no auto-upload
TikTok's official upload API needs an app audit before posts can be public,
and browser-automation uploaders break TikTok's terms and are the most common
cause of shadow bans. Posting by hand from your phone takes about 2 minutes
per video, and it keeps the account (your income) safe. If you later get an
approved TikTok developer app, it can be added on top of the posting kit.

## For developers
```bash
pip install -e ".[captions,dev]"
pytest              # includes an end-to-end run against a fake Twitch API (needs ffmpeg)
```
Code map: `twitch.py` (Helix API), `pipeline.py` (daily run + discovery),
`brain.py` (Claude editor + rule-based fallback), `media.py` (yt-dlp, ffprobe,
faster-whisper), `captions.py` (ASS subtitles), `render.py` (ffmpeg),
`kit.py` (posting kit), `db.py` (SQLite state), `cli.py`.
