"""Publishing queue: plan slots, publish due items, retry safely.

Item lifecycle:  ready -> scheduled -> published   (or -> failed after 3 attempts)

Idempotent: a container id is saved before publishing, so a crashed run resumes
where it stopped instead of posting twice.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import load_config
from .spec import load as load_spec
from .publish import IGClient, ThreadsClient, upload_public
from .util import STATE_DIR, log, now_utc, parse_iso, read_json, iso, write_json

QUEUE = STATE_DIR / "queue.json"
MAX_ATTEMPTS = 3


def _load() -> list[dict]:
    return read_json(QUEUE, [])


def _save(items: list[dict]) -> None:
    write_json(QUEUE, items)


def add(project: pathlib.Path) -> dict:
    cfg = load_config()
    spec = load_spec(project)
    items = _load()
    if any(i["project"] == str(project) and i["status"] != "failed" for i in items):
        raise SystemExit(f"{project.name} is already in the queue")
    video = project / "out" / "reel.mp4"
    item = {
        "id": f"{project.name}-{len(items) + 1}",
        "project": str(project),
        "video": str(video),
        "video_url": upload_public(video, cfg) if _needs_upload(cfg) else None,
        "caption": spec["caption"],
        "keyword": spec["keyword"],
        "link": spec.get("link", ""),
        "status": "ready",
        "when": None,
        "attempts": 0,
        "added_at": iso(now_utc()),
    }
    items.append(item)
    _save(items)
    log(f"Queued {item['id']} (ready)")
    return item


def _needs_upload(cfg: dict) -> bool:
    return bool(cfg["publish"]["instagram"] or cfg["publish"]["threads"])


def plan(days: int = 3) -> int:
    """Assign publish times to ready items, filling configured daily slots."""
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    slots = sorted(cfg["schedule"]["slots"])[: int(cfg["schedule"]["per_day"])]
    items = _load()
    ready = [i for i in items if i["status"] == "ready"]
    if not ready:
        log("Nothing ready to plan")
        return 0

    local_now = now_utc().astimezone(tz)
    candidates: list[datetime] = []
    for day in range(days + 1):
        base = (local_now + timedelta(days=day)).date()
        for slot in slots:
            hh, mm = map(int, slot.split(":"))
            when = datetime(base.year, base.month, base.day, hh, mm, tzinfo=tz)
            if when > local_now + timedelta(minutes=5):
                candidates.append(when)
    taken = {i["when"] for i in items if i.get("when") and i["status"] == "scheduled"}
    free = [c for c in candidates if iso(c) not in taken][: len(ready)]
    for item, when in zip(ready, free):
        item["when"] = iso(when)
        item["status"] = "scheduled"
    _save(items)
    log(f"Scheduled {min(len(ready), len(free))} item(s)")
    return min(len(ready), len(free))


def tick(now: datetime | None = None) -> dict:
    """Publish every scheduled item whose time has come. Safe to run every few minutes."""
    cfg = load_config()
    now = now or now_utc()
    items = _load()
    done = {"published": 0, "failed": 0}
    for item in items:
        if item["status"] != "scheduled" or parse_iso(item["when"]) > now:
            continue
        try:
            _publish_item(item, cfg)
            item["status"] = "published"
            item["published_at"] = iso(now)
            done["published"] += 1
            log(f"Published {item['id']}")
        except Exception as err:  # keep going; one bad item must not block the queue
            item["attempts"] += 1
            item["error"] = str(err)[:800]
            if item["attempts"] >= MAX_ATTEMPTS:
                item["status"] = "failed"
                done["failed"] += 1
            log(f"Failed {item['id']} (attempt {item['attempts']}): {err}")
        _save(items)  # persist after every item
    return done


def _publish_item(item: dict, cfg: dict) -> None:
    if not item.get("video_url"):
        item["video_url"] = upload_public(pathlib.Path(item["video"]), cfg)
        _save(_load_and_replace(item))
    caption = item["caption"]
    if item["link"] and item["link"] not in caption:
        caption = f"{caption}\n\n{item['link']}"

    if cfg["publish"]["instagram"] and not item.get("ig_media_id"):
        ig = IGClient(cfg)
        if not item.get("ig_container"):
            item["ig_container"] = ig.create_reel(item["video_url"], caption)
            _save(_load_and_replace(item))
        ig.wait_ready(item["ig_container"])
        item["ig_media_id"] = ig.publish(item["ig_container"])
        _save(_load_and_replace(item))

    if cfg["publish"]["threads"] and not item.get("threads_id"):
        th = ThreadsClient(cfg)
        if not item.get("threads_container"):
            item["threads_container"] = th.create_video(item["video_url"], caption[:500])
            _save(_load_and_replace(item))
        th.wait_ready(item["threads_container"])
        item["threads_id"] = th.publish(item["threads_container"])


def _load_and_replace(item: dict) -> list[dict]:
    """Merge one changed item into the on-disk queue (other items may have changed)."""
    items = _load()
    for idx, existing in enumerate(items):
        if existing["id"] == item["id"]:
            items[idx] = item
    return items


def list_items() -> list[dict]:
    return _load()


def auto_plan_enabled() -> bool:
    return bool(load_config()["autopilot"]["auto_publish"])
