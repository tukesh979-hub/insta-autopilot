"""Load config.json (falls back to config.example.json so the tool runs out of the box)."""
from __future__ import annotations

import json
from functools import lru_cache

from .util import ROOT, read_json


@lru_cache(maxsize=1)
def load_config() -> dict:
    user = ROOT / "config.json"
    example = ROOT / "config.example.json"
    cfg = read_json(user, None)
    if cfg is None:
        cfg = read_json(example, None)
        if cfg is None:
            raise SystemExit("config.example.json is missing from the repo.")
    return cfg


def dump_config() -> str:
    return json.dumps(load_config(), indent=2)
