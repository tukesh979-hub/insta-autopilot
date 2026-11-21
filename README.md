# social-autopilot

Turn a stream of open-source repos into short Instagram Reels, on autopilot.

Each day the pipeline finds a new, permissively licensed repo, writes a script, records the
project's own page, adds narration and subtitles, checks the result with automatic QA gates,
queues it, and posts it at your chosen times. It then answers comments that contain the
reel's keyword and saves analytics.

```
scan ─► draft ─► record ─► voice ─► render ─► QA ─► queue ─► publish ─► replies ─► analytics
```

## What you get

- **Discovery**: GitHub search across your topics, scored 0-100 (relevance, traction, demo potential, licence, freshness)
- **Drafting**: Claude writes hook, script and caption from the README (or a template if you have no key)
- **Recording**: Playwright captures a scrolling clip of the project's live page
- **Voice**: ElevenLabs narration (optional; silent reels otherwise)
- **Rendering**: 1080×1920 H.264 with blurred 9:16 backgrounds, hook lines and timed subtitles
- **QA gates**: size, duration, and a "frozen screen" check, plus a contact sheet
- **Scheduling**: daily time slots, idempotent publishing, retries, state in plain JSON
- **Publishing**: Instagram Reels (and optionally Threads) via the official Graph API
- **Engagement**: keyword comment replies, weekly analytics report
- **Automation**: GitHub Actions workflows for every stage

Python standard library only (plus `boto3` for R2 uploads). Node is used only for recording.

## Quick start (local)

```bash
pip install -r requirements.txt
cd recorder && npm install && npx playwright install chromium && cd ..
cp .env.example .env
python3 cli.py scan                       # find and score repos
python3 cli.py ideas                      # see the shortlist
python3 cli.py auto                       # one full cycle: draft → record → render → QA → queue
python3 cli.py queue list                 # what is waiting
python3 cli.py queue plan --days 3        # give queued reels a time slot
python3 cli.py queue tick                 # post what is due (run this from cron)
```

Open `projects/<name>/out/contact_sheet.jpg` and `out/reel.mp4` before planning a reel.

Full setup, accounts and tokens: **[docs/SETUP.md](docs/SETUP.md)**.
How the stages and `spec.json` work: **[docs/PIPELINE.md](docs/PIPELINE.md)**.

## Commands

| Command | What it does |
|---|---|
| `scan [--source github] [--top N]` | Fetch, score and store new ideas |
| `ideas [--status S]` | List stored ideas |
| `approve ID` / `reject ID` | Mark an idea (rejected ideas are never drafted) |
| `draft [ID]` | Create `projects/<name>/spec.json` from an idea (best unused if no ID) |
| `record PROJECT URL [--seconds N]` | Record a page into the project's footage |
| `check PROJECT` | Validate `spec.json` |
| `build PROJECT` | Voice + render + QA |
| `auto` | scan → draft → record → build → queue (one reel) |
| `queue add/plan/tick/list` | Manage the publishing queue |
| `replies` | Reply to keyword comments |
| `analytics pull` / `analytics report` | Snapshot insights; write the weekly table |

## Configuration

`config.json` (committed, not secret): topics, licences, thresholds, video size and length,
time slots, publishing toggles, reply text. Secrets go in `.env` (local) or repository secrets
(GitHub Actions). Nothing secret is ever read from `config.json`.

## Automation (GitHub Actions)

| Workflow | When | Does |
|---|---|---|
| `create-reel` | daily 05:30 UTC | creates one reel candidate |
| `publish` | every 10 min | publishes due queue items |
| `engage` | every 30 min (+ daily analytics) | replies to keyword comments, saves insights |

All three commit their state back to the repo, so runs are serialised with a concurrency group.

## Safety

- `autopilot.auto_publish` defaults to **false**: a human plans each reel before it can post.
- Scoring is keyword-based. Check each repo yourself before a reel about it goes live.
- Only permissive licences are allowed by default (MIT, Apache-2.0, BSD-3-Clause, ISC, 0BSD).
- Respect the platforms' rules. Meta requires a Professional account, app review for other people's accounts, and access tokens that expire.
- Record only pages you are allowed to show. The recorder captures what a visitor sees.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

Offline tests cover scoring, spec rules, queue planning and retries, keyword matching, and a
render test that runs only when ffmpeg includes drawtext.

## Project layout

```
cli.py                 command line entry point
autopilot/             core package (ideas, scoring, draft, media, queue, publish, engagement)
recorder/capture.mjs   Playwright screen recorder
projects/              one folder per reel (spec.json tracked; media ignored)
state/                 queue.json, replied.json, analytics/ (tracked, updated by Actions)
data/ideas.db          idea memory (SQLite, tracked so the bot never re-drafts a repo)
.github/workflows/     create-reel, publish, engage
docs/                  SETUP.md, PIPELINE.md
```

## Contributing

Issues and pull requests are welcome. Keep the core dependency-free, keep secrets out of the
repo, and add a test for every new rule.

## License

MIT. See [LICENSE](LICENSE).
