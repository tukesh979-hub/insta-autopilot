"""Comment keyword replies and weekly analytics for published reels."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .config import load_config
from .publish import IGClient
from .queue import list_items
from .util import STATE_DIR, ApiError, iso, log, now_utc, read_json, write_json

REPLIED = STATE_DIR / "replied.json"
ANALYTICS_DIR = STATE_DIR / "analytics"
LOOKBACK_DAYS = 14


def _matches(text: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None


def reply_to_keywords() -> int:
    """Reply to comments that contain a reel's keyword. Each comment is answered once."""
    cfg = load_config()
    ig = IGClient(cfg)
    replied = read_json(REPLIED, {})
    cutoff = now_utc() - timedelta(days=LOOKBACK_DAYS)
    sent = 0
    for item in list_items():
        media_id = item.get("ig_media_id")
        if not media_id or item.get("status") != "published":
            continue
        if item.get("published_at") and datetime.fromisoformat(
                item["published_at"].replace("Z", "+00:00")) < cutoff:
            continue
        try:
            comments = ig.comments(media_id)
        except ApiError as err:
            log(f"Could not read comments for {item['id']}: {err}")
            continue
        for comment in comments:
            cid = comment["id"]
            if cid in replied or not _matches(comment.get("text", ""), item["keyword"]):
                continue
            message = cfg["comments"]["reply_template"].format(
                link=item.get("link") or "in my bio", keyword=item["keyword"])
            try:
                ig.reply(cid, message)
            except ApiError as err:
                log(f"Reply failed for comment {cid}: {err}")
                continue
            replied[cid] = {"media": media_id, "user": comment.get("username"),
                            "at": iso(now_utc())}
            sent += 1
            log(f"Replied to @{comment.get('username')} on {item['id']}")
    write_json(REPLIED, replied)
    log(f"{sent} new keyword replies")
    return sent


def pull_analytics() -> dict:
    """Snapshot insights for every published reel. Keeps a dated JSON per run."""
    cfg = load_config()
    ig = IGClient(cfg)
    snapshot = {}
    for item in list_items():
        media_id = item.get("ig_media_id")
        if not media_id or item.get("status") != "published":
            continue
        try:
            snapshot[item["id"]] = ig.insights(media_id, cfg["analytics"]["metrics"])
        except ApiError as err:
            snapshot[item["id"]] = {"error": str(err)[:200]}
    stamp = now_utc().strftime("%Y-%m-%d")
    write_json(ANALYTICS_DIR / f"{stamp}.json", snapshot)
    log(f"Analytics snapshot saved for {len(snapshot)} reel(s)")
    return snapshot


def weekly_report() -> str:
    """Markdown table from the last 7 daily snapshots (latest value per reel)."""
    files = sorted(ANALYTICS_DIR.glob("*.json"))[-7:] if ANALYTICS_DIR.exists() else []
    latest: dict[str, dict] = {}
    for f in files:
        for reel, metrics in read_json(f, {}).items():
            latest[reel] = metrics
    lines = ["# Weekly reel report", "",
             "| Reel | Plays | Reach | Likes | Comments | Saves | Shares |",
             "|---|---|---|---|---|---|---|"]
    for reel, m in sorted(latest.items()):
        if "error" in m:
            continue
        lines.append(f"| {reel} | {m.get('plays', '-')} | {m.get('reach', '-')} | "
                     f"{m.get('likes', '-')} | {m.get('comments', '-')} | "
                     f"{m.get('saved', '-')} | {m.get('shares', '-')} |")
    report = "\n".join(lines) + "\n"
    out = STATE_DIR / "weekly_report.md"
    out.write_text(report, encoding="utf-8")
    log(f"Wrote {out}")
    return report
