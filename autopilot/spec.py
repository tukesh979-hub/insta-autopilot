"""spec.json: the single file a reel is built from. Validated before any render."""
from __future__ import annotations

import pathlib
import re

from .util import read_json

REQUIRED = ("title", "hook", "script", "keyword", "clips", "caption")


class SpecError(ValueError):
    pass


def validate(spec: dict, project_dir: pathlib.Path) -> list[str]:
    """Return a list of problems. Empty list = valid."""
    problems: list[str] = []
    for key in REQUIRED:
        if key not in spec:
            problems.append(f"missing '{key}'")
    if problems:
        return problems

    hook = spec["hook"]
    if not isinstance(hook, list) or not 1 <= len(hook) <= 2:
        problems.append("'hook' must be a list of 1-2 lines")
    else:
        for line in hook:
            if len(str(line).split()) > 6:
                problems.append(f"hook line too long (max 6 words): {line!r}")

    script = str(spec["script"]).strip()
    words = len(script.split())
    if not 40 <= words <= 110:
        problems.append(f"script should be 40-110 words (~20-35 s spoken), got {words}")

    keyword = str(spec["keyword"])
    if not re.fullmatch(r"[A-Z]{3,12}", keyword):
        problems.append("'keyword' must be 3-12 capital letters, e.g. NEON")
    elif keyword not in script:
        problems.append(f"script must ask viewers to comment {keyword}")

    clips = spec["clips"]
    if not isinstance(clips, list) or not clips:
        problems.append("'clips' must be a non-empty list")
    else:
        for i, clip in enumerate(clips):
            src = project_dir / str(clip.get("file", ""))
            if not clip.get("file") or not src.exists():
                problems.append(f"clip {i}: file not found: {clip.get('file')}")
            if float(clip.get("duration", 4)) <= 0:
                problems.append(f"clip {i}: duration must be > 0")

    if len(str(spec["caption"])) > 2100:
        problems.append("caption longer than Instagram's 2,200 character limit")
    return problems


def load(project_dir: pathlib.Path, strict: bool = True) -> dict:
    spec = read_json(project_dir / "spec.json", None)
    if spec is None:
        raise SpecError(f"No spec.json in {project_dir}")
    problems = validate(spec, project_dir)
    if problems and strict:
        raise SpecError("spec.json invalid:\n  - " + "\n  - ".join(problems))
    return spec


def sentences(script: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p for p in parts if p]
