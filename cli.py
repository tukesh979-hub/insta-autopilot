#!/usr/bin/env python3
"""social-autopilot: idea -> script -> footage -> voice -> render -> QA -> queue -> post.

Run `python3 cli.py --help` for commands. Typical day:

    python3 cli.py auto            # find, draft, record, render, QA, queue one reel
    python3 cli.py queue tick      # publish anything due (run every 10 min via cron/CI)
    python3 cli.py replies         # answer keyword comments
"""
from __future__ import annotations

import argparse
import json
import sys

from autopilot import ideas as ideas_mod
from autopilot import draft as draft_mod
from autopilot import engagement, media, queue as queue_mod, spec as spec_mod
from autopilot.config import load_config
from autopilot.util import PROJECTS_DIR, load_env, log, read_json, write_json, ROOT

load_env()


def _project(name: str):
    path = PROJECTS_DIR / name
    if not path.exists():
        path = ROOT / name
    if not (path / "spec.json").exists():
        raise SystemExit(f"No project '{name}' (expected projects/{name}/spec.json)")
    return path


def cmd_scan(args):
    ideas_mod.scan(args.source)
    for row in ideas_mod.list_ideas(limit=args.top):
        print(f"{row['score']:>3}  {row['name']:<45} {row['stars']:>6}★  {row['license']}  {row['url']}")


def cmd_ideas(args):
    for row in ideas_mod.list_ideas(args.status, args.limit):
        print(f"#{row['id']:<4} {row['score']:>3}  {row['status']:<9} {row['name']}  {row['url']}")


def cmd_mark(args):
    ideas_mod.set_status(args.id, args.status)
    print(f"idea #{args.id} -> {args.status}")


def cmd_draft(args):
    row = ideas_mod.connect().execute("SELECT * FROM ideas WHERE id=?", (args.id,)).fetchone() \
        if args.id else ideas_mod.best_unused(load_config()["ideas"]["min_score"])
    if not row:
        raise SystemExit("No idea available to draft. Run `scan` first or lower min_score.")
    project = draft_mod.draft_from_idea(dict(row))
    print(project)


def cmd_record(args):
    project = _project(args.project)
    video = media.record(project, args.url, args.seconds)
    attach_clip(project, video, args.seconds)


def attach_clip(project, video, seconds: float) -> None:
    """Add the recording to spec.json as the first clip (only when none exist)."""
    data = read_json(project / "spec.json", {})
    if not data.get("clips"):
        data["clips"] = [{"file": str(video.relative_to(project)), "start": 0,
                          "duration": seconds}]
        write_json(project / "spec.json", data)


def cmd_check(args):
    problems = draft_mod.check(_project(args.project))
    print("OK" if not problems else "\n".join(f"- {p}" for p in problems))
    sys.exit(1 if problems else 0)


def cmd_build(args):
    project = _project(args.project)
    spec_mod.load(project)
    media.voice(project)
    media.render(project)
    failures = media.qa(project)
    if failures:
        print("QA FAILED:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print(project / "out" / "reel.mp4")


def cmd_queue(args):
    if args.action == "add":
        queue_mod.add(_project(args.project))
    elif args.action == "plan":
        queue_mod.plan(args.days)
    elif args.action == "tick":
        print(json.dumps(queue_mod.tick()))
    elif args.action == "list":
        for i in queue_mod.list_items():
            print(f"{i['id']:<36} {i['status']:<10} {i.get('when') or '-':<22} {i.get('error', '')[:60]}")


def cmd_auto(args):
    cfg = load_config()
    ideas_mod.scan()
    row = ideas_mod.best_unused(cfg["ideas"]["min_score"])
    if not row:
        log("No idea above min_score. Nothing to make today.")
        return
    project = draft_mod.draft_from_idea(dict(row))
    ideas_mod.set_status(row["id"], "drafted")
    url = row["homepage"] or row["url"]
    video = media.record(project, url, cfg["video"]["record_seconds"])
    attach_clip(project, video, cfg["video"]["record_seconds"])
    media.voice(project, cfg)
    media.render(project, cfg)
    failures = media.qa(project, cfg)
    if failures:
        log("QA failed, not queued: " + "; ".join(failures))
        ideas_mod.set_status(row["id"], "qa_failed")
        return
    queue_mod.add(project)
    ideas_mod.set_status(row["id"], "queued")
    if queue_mod.auto_plan_enabled():
        queue_mod.plan(cfg["schedule"].get("days_ahead", 3))


def cmd_replies(_):
    engagement.reply_to_keywords()


def cmd_analytics(args):
    if args.action == "pull":
        engagement.pull_analytics()
    else:
        print(engagement.weekly_report())


def build_parser():
    p = argparse.ArgumentParser(prog="cli.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="find new repos and score them")
    s.add_argument("--source", action="append", choices=list(ideas_mod.SOURCES))
    s.add_argument("--top", type=int, default=15)
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("ideas", help="list stored ideas")
    s.add_argument("--status")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_ideas)

    for name, status in (("approve", "approved"), ("reject", "rejected")):
        s = sub.add_parser(name, help=f"mark an idea {status}")
        s.add_argument("id", type=int)
        s.set_defaults(fn=cmd_mark, status=status)

    s = sub.add_parser("draft", help="create projects/<name>/spec.json from an idea")
    s.add_argument("id", type=int, nargs="?")
    s.set_defaults(fn=cmd_draft)

    s = sub.add_parser("record", help="record a page into projects/<name>/footage")
    s.add_argument("project")
    s.add_argument("url")
    s.add_argument("--seconds", type=float, default=12)
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("check", help="validate spec.json")
    s.add_argument("project")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("build", help="voice + render + QA for a project")
    s.add_argument("project")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("queue", help="manage the publishing queue")
    s.add_argument("action", choices=["add", "plan", "tick", "list"])
    s.add_argument("project", nargs="?")
    s.add_argument("--days", type=int, default=3)
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("auto", help="scan -> draft -> record -> render -> QA -> queue")
    s.set_defaults(fn=cmd_auto)

    s = sub.add_parser("replies", help="reply to keyword comments")
    s.set_defaults(fn=cmd_replies)

    s = sub.add_parser("analytics", help="pull insights or print the weekly report")
    s.add_argument("action", choices=["pull", "report"])
    s.set_defaults(fn=cmd_analytics)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
