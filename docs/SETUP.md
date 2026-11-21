# Setup

Works on macOS and Linux. Windows: use WSL.

## 1. Install the tools

| Tool | Why | Install |
|---|---|---|
| Python 3.11+ | everything | `brew install python` / `apt install python3` |
| ffmpeg **with drawtext** | rendering text on the reel | `brew install ffmpeg` / `apt install ffmpeg fonts-dejavu-core` |
| Node 20+ | screen recording | `brew install node` / nodejs.org |

Check drawtext: `ffmpeg -hide_banner -filters | grep drawtext` should print a line.
If it prints nothing, reinstall ffmpeg with freetype (`brew reinstall ffmpeg`).

```bash
git clone https://github.com/<you>/social-autopilot.git
cd social-autopilot
pip install -r requirements.txt          # boto3 only, for R2 uploads
cd recorder && npm install && npx playwright install chromium && cd ..
cp .env.example .env                     # then fill in as below
```

## 2. Idea discovery (free)

`GITHUB_TOKEN` is optional. Without it GitHub allows about 10 searches per minute, which is enough for one scan per day. Create one at github.com/settings/tokens (no scopes needed for public repos).

```bash
python3 cli.py scan
python3 cli.py ideas
```

## 3. Script drafting (optional, recommended)

`ANTHROPIC_API_KEY` from console.anthropic.com. Without it the script is a plain template. Review it before publishing.

## 4. Narration (optional)

`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` from elevenlabs.io. Without them reels render silent with on-screen subtitles.

## 5. Instagram (required to post)

1. Switch the Instagram account to **Professional** (Creator or Business).
2. Link it to a Facebook Page you admin.
3. At developers.facebook.com create an app (type Business). Add the **Instagram** product.
4. Permissions needed: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_comments`, `instagram_business_manage_insights`. Use a short-lived user token, exchange it for a **long-lived** token (60 days), then get the Page's token. Meta's Graph API Explorer walks through this.
5. Put the Instagram user id in `IG_USER_ID` and the token in `IG_ACCESS_TOKEN`.

Advanced access is needed for other people's accounts. For your own account, development mode works.

Tokens expire. Set a reminder to renew the long-lived token every 50 days.

## 6. Video hosting (required to post)

Meta downloads the reel from a public URL, so the tool uploads it to an S3-compatible bucket. Cloudflare R2 is the default:

1. Create an R2 bucket, enable public access (or attach a custom domain).
2. Create an R2 API token with read/write on that bucket.
3. Fill `R2_ENDPOINT` (`https://<account>.r2.cloudflarestorage.com`), `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
4. Set `publish.public_base_url` in `config.json` to the bucket's public URL.

## 7. Running unattended with GitHub Actions

1. Push the repo to GitHub (private is fine).
2. Settings > Secrets and variables > Actions: add every key from `.env` that you use. Names must match.
3. Edit `config.json`: `publish.instagram`, `publish.public_base_url`, and `autopilot.auto_publish` (see below).
4. Actions tab: enable workflows. `create-reel` runs daily, `publish` every 10 minutes, `engage` every 30 minutes.

Workflows commit their state (`state/`, `data/`, `projects/*/spec.json`) back to the repo, so keep `main` free of conflicting manual edits.

## Safety switches

- `autopilot.auto_publish: false` (default): reels are queued as `ready` and need `python3 cli.py queue plan` before they can post. You approve each reel by planning it.
- `autopilot.auto_publish: true`: `auto` plans and posts on its own. Turn this on only after you have reviewed several generated reels.
- Scoring is keyword-based. Always check the repo yourself before a reel about it goes live.
