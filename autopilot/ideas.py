"""Idea discovery: GitHub search -> SQLite store -> shortlist.

Add another source by writing a function that returns dicts with the keys used in
`_row()` and registering it in SOURCES.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .config import load_config
from .scoring import score_idea
from .util import DATA_DIR, env, http, log

DB_PATH = DATA_DIR / "ideas.db"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, url TEXT UNIQUE, name TEXT, description TEXT,
            homepage TEXT, license TEXT, stars INTEGER, topics TEXT,
            created_at TEXT, score INTEGER, reasons TEXT,
            status TEXT DEFAULT 'new', found_at TEXT
        )""")
    return con


def github_search(cfg: dict) -> list[dict]:
    ideas = cfg["ideas"]
    since = (datetime.now(timezone.utc) - timedelta(days=int(ideas["lookback_days"]))).date()
    token = env("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "social-autopilot"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    found: dict[str, dict] = {}
    for topic in ideas["topics"]:
        query = f"topic:{topic} created:>={since} stars:>={ideas['min_stars']}"
        data = http("GET", "https://api.github.com/search/repositories",
                    params={"q": query, "sort": "stars", "order": "desc", "per_page": 30},
                    headers=headers)
        for repo in (data or {}).get("items", []):
            found.setdefault(repo["html_url"], repo)
    log(f"GitHub returned {len(found)} unique repos across {len(ideas['topics'])} topics")
    return [{
        "source": "github",
        "url": repo["html_url"],
        "name": repo["full_name"],
        "description": repo.get("description") or "",
        "homepage": repo.get("homepage") or "",
        "license": (repo.get("license") or {}).get("spdx_id") or "NONE",
        "stars": repo.get("stargazers_count", 0),
        "topics": repo.get("topics", []),
        "created_at": repo.get("created_at"),
    } for repo in found.values()]


SOURCES = {"github": github_search}


def scan(sources: list[str] | None = None) -> int:
    cfg = load_config()
    con = connect()
    added = 0
    for name in sources or list(SOURCES):
        for item in SOURCES[name](cfg):
            score, reasons = score_idea(item, cfg)
            cur = con.execute(
                """INSERT OR IGNORE INTO ideas
                   (source,url,name,description,homepage,license,stars,topics,created_at,
                    score,reasons,found_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["source"], item["url"], item["name"], item["description"],
                 item["homepage"], item["license"], item["stars"], json.dumps(item["topics"]),
                 item["created_at"], score, json.dumps(reasons),
                 datetime.now(timezone.utc).isoformat()))
            added += cur.rowcount
            con.execute("UPDATE ideas SET score=?, reasons=? WHERE url=?",
                        (score, json.dumps(reasons), item["url"]))
    con.commit()
    log(f"{added} new ideas stored")
    return added


def list_ideas(status: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
    con = connect()
    if status:
        rows = con.execute("SELECT * FROM ideas WHERE status=? ORDER BY score DESC LIMIT ?",
                           (status, limit)).fetchall()
    else:
        rows = con.execute("SELECT * FROM ideas WHERE status='new' ORDER BY score DESC LIMIT ?",
                           (limit,)).fetchall()
    return rows


def set_status(idea_id: int, status: str) -> None:
    con = connect()
    con.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))
    con.commit()


def best_unused(min_score: int) -> sqlite3.Row | None:
    """Highest-scoring idea that has not been drafted yet."""
    con = connect()
    return con.execute(
        "SELECT * FROM ideas WHERE status IN ('new','approved') AND score>=? "
        "ORDER BY status='approved' DESC, score DESC LIMIT 1", (min_score,)).fetchone()
