"""Deterministic idea scoring (0-100). Pure functions, no network, easy to test."""
from __future__ import annotations

import math
from datetime import datetime, timezone


def _hits(text: str, words: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for w in words if w.lower() in lowered)


def score_idea(item: dict, cfg: dict, now: datetime | None = None) -> tuple[int, list[str]]:
    """Return (score, reasons). A score of 0 with a 'rejected:' reason means never shortlist.

    Weights (sum 100): relevance 30 · traction 20 · demonstrability 20 ·
    license 15 · freshness 15.
    """
    now = now or datetime.now(timezone.utc)
    ideas = cfg["ideas"]
    text = " ".join(filter(None, [item.get("name"), item.get("description"),
                                  " ".join(item.get("topics", []))]))
    reasons: list[str] = []

    if _hits(text, ideas.get("reject_keywords", [])):
        return 0, ["rejected: matches reject_keywords"]
    license_id = (item.get("license") or "NONE").upper()
    allowed = [x.upper() for x in ideas.get("allowed_licenses", [])]
    if license_id not in allowed:
        return 0, [f"rejected: licence {license_id} not in allowed list"]

    relevance = min(30, _hits(text, ideas.get("keywords", [])) * 10)
    reasons.append(f"relevance {relevance}/30")

    stars = int(item.get("stars") or 0)
    traction = min(20, round(math.log10(stars + 1) * 7))
    reasons.append(f"traction {traction}/20 ({stars} stars)")

    demo = 0
    if item.get("homepage"):
        demo += 12
    if _hits(text, ["demo", "playground", "gallery", "showcase", "example"]):
        demo += 8
    demo = min(20, demo)
    reasons.append(f"demonstrability {demo}/20")

    license_points = 15
    reasons.append(f"license {license_id} ok")

    created = item.get("created_at")
    fresh = 5
    if created:
        age_days = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
        fresh = 15 if age_days <= 30 else 8 if age_days <= 180 else 3
    reasons.append(f"freshness {fresh}/15")

    total = relevance + traction + demo + license_points + fresh
    if stars < int(ideas.get("min_stars", 0)):
        reasons.append("below min_stars (watchlist only)")
        total = min(total, int(ideas.get("min_score", 60)) - 1)
    return total, reasons
