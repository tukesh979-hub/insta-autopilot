# How the pipeline works

```
scan ─► ideas (SQLite) ─► draft ─► record ─► voice ─► render ─► QA ─► queue ─► tick ─► replies / analytics
 GitHub   score ≥ min     spec.json  Playwright  ElevenLabs  ffmpeg   gates   due time  Graph API  Graph API
```

Each reel lives in `projects/<name>/`:

| File | Made by | Keep in git? |
|---|---|---|
| `spec.json` | draft (edit it freely) | yes |
| `footage/demo.mp4` | record | no (large) |
| `out/voice.mp3` | voice | no |
| `out/reel.mp4` | render | no |
| `out/contact_sheet.jpg` | QA | no |

## spec.json

```json
{
  "title": "neon-city",
  "hook": ["Whole City In A Browser", "Built From One File"],
  "script": "Here is a city you can walk through. ... Comment NEON and I'll send you the link.",
  "keyword": "NEON",
  "caption": "Neon city, free and open source.",
  "hashtags": [],
  "link": "https://github.com/acme/neon-city",
  "clips": [{"file": "footage/demo.mp4", "start": 0, "duration": 20}]
}
```

Rules enforced by `cli.py check`:

- `hook`: 1-2 lines, at most 6 words each. Line 1 is the surprise, line 2 the proof.
- `script`: 40-110 words (about 20-35 s spoken). It must contain the keyword in the form `Comment KEYWORD`.
- `keyword`: 3-12 capital letters.
- `clips`: each file must exist. `start` and `duration` are seconds.
- `caption`: at most 2,100 characters.

## Rendering

- Each clip becomes a 1080x1920 segment: a blurred copy of the footage fills the frame, and the sharp footage sits centred on top.
- Hook lines are drawn at the top. Script sentences are drawn at the bottom, timed by character length across the narration.
- Narration sets the length. Without narration, the length is the sum of clip durations.
- Output: H.264, yuv420p, 30 fps, AAC audio (silent track if there is no narration).

## QA gates (automatic)

A reel is queued only if it passes:

- exact size 1080x1920
- duration between `video.min_seconds` and `video.max_seconds`
- at most `qa.max_freeze_ratio` of the reel is frozen (a static page fails)

A contact sheet (`out/contact_sheet.jpg`) is written every time. Look at it before you approve the reel.

## Queue lifecycle

`ready` (queued, no time) → `scheduled` (time set by `queue plan`) → `published`.
After 3 failed attempts an item becomes `failed` and is kept for inspection.

Publishing is idempotent. The Meta container id is stored before publishing, so a crash resumes instead of double-posting.

## Engagement

- `replies` finds comments containing an active reel's keyword (whole word, case-insensitive) and replies once with `comments.reply_template`. Replied comment ids are stored in `state/replied.json`.
- `analytics pull` saves a dated snapshot in `state/analytics/`. `analytics report` writes `state/weekly_report.md`.

Meta's API does not allow sending DMs to arbitrary users without app review, so this tool replies publicly with the link rather than DMing.

## Adding an idea source

1. Write `def my_source(cfg) -> list[dict]` in `autopilot/ideas.py`. Each dict needs `source, url, name, description, homepage, license, stars, topics, created_at`.
2. Add it to `SOURCES`.
3. `python3 cli.py scan --source my_source`.
