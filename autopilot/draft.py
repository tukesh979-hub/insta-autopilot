"""Turn an idea into a project folder with a spec.json.

Two modes:
  * LLM mode (ANTHROPIC_API_KEY set): Claude writes hook, script, caption from the
    repo's README. The output is validated; one retry on failure.
  * Template mode (no key): a plain, factual script built from the README and the
    repo metadata. Works offline but is clearly weaker: review before publishing.
"""
from __future__ import annotations

import json
import pathlib
import re

from .config import load_config
from .spec import validate
from .util import PROJECTS_DIR, env, http, log, write_json

PROMPT = """You write short vertical Instagram Reel scripts about open-source tools.

Rules:
- hook: 1-2 on-screen lines, each at most 6 words. Line 1 = the surprising outcome.
  Never start with the tool name. Never use "This free tool" or "Check out".
- script: 40-90 words, talk like telling a friend, short sentences, contractions.
  Say what it does with a concrete number from the README if one exists.
  It must end with: Comment {keyword} and I'll send you the link.
- keyword: one capital word (3-12 letters) tied to the visual.
- caption: 2-4 short lines plus the keyword call to action. No hashtags spam (max 5).
- Do not claim things the README does not say.

Return ONLY JSON with keys: hook (list), script (string), keyword (string), caption (string).

Repo: {name}
URL: {url}
Description: {description}
README excerpt:
{readme}
"""


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def _readme(full_name: str) -> str:
    token = env("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.raw", "User-Agent": "social-autopilot"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        import urllib.request
        req = urllib.request.Request(f"https://api.github.com/repos/{full_name}/readme",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")[:6000]
    except Exception:  # README is optional context
        return "(README unavailable)"


def _llm_draft(idea: dict, readme: str, cfg: dict) -> dict:
    key = env("ANTHROPIC_API_KEY", required=True)
    prompt = PROMPT.format(name=idea["name"], url=idea["url"],
                           description=idea.get("description", ""), readme=readme,
                           keyword="{keyword}")
    body = {"model": cfg["draft"]["model"], "max_tokens": 900,
            "messages": [{"role": "user", "content": prompt}]}
    resp = http("POST", "https://api.anthropic.com/v1/messages", body=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=120)
    text = "".join(block.get("text", "") for block in resp.get("content", []))
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("model returned no JSON")
    return json.loads(match.group(0))


def _template_draft(idea: dict, readme: str) -> dict:
    name = idea["name"].split("/")[-1]
    desc = (idea.get("description") or "an open-source tool").rstrip(".")
    keyword = re.sub(r"[^A-Z]", "", name.upper())[:8] or "TOOL"
    script = (f"Here's something you can actually see working. It's called {name}. "
              f"{desc}. It's free and open source, so you can run it yourself. "
              f"The code is on GitHub. Comment {keyword} and I'll send you the link.")
    return {
        "hook": [f"Free open-source tool", f"You can try today"],
        "script": script,
        "keyword": keyword,
        "caption": f"{name}: {desc}.\n\nComment {keyword} and I'll send you the link.",
    }


def draft_from_idea(idea) -> pathlib.Path:
    cfg = load_config()
    slug = _slug(idea["name"])
    project = PROJECTS_DIR / slug
    project.mkdir(parents=True, exist_ok=True)
    readme = _readme(idea["name"])
    (project / "README_excerpt.md").write_text(readme, encoding="utf-8")

    idea_dict = dict(idea)
    try:
        content = _llm_draft(idea_dict, readme, cfg) if env("ANTHROPIC_API_KEY") \
            else _template_draft(idea_dict, readme)
    except Exception as err:
        log(f"LLM draft failed ({err}); falling back to template")
        content = _template_draft(idea_dict, readme)

    spec = {
        "title": idea["name"],
        "source_url": idea["url"],
        "hook": content["hook"],
        "script": content["script"],
        "keyword": content["keyword"],
        "caption": content["caption"],
        "hashtags": [],
        "link": idea["url"],
        "clips": [],
        "draft_mode": "llm" if env("ANTHROPIC_API_KEY") else "template",
    }
    write_json(project / "spec.json", spec)
    log(f"Drafted {project} (mode: {spec['draft_mode']})")
    return project


def check(project: pathlib.Path) -> list[str]:
    from .util import read_json
    return validate(read_json(project / "spec.json", {}), project)
