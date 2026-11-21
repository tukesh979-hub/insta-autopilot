"""Shared helpers: paths, .env loading, HTTP, JSON state, logging, subprocess."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
PROJECTS_DIR = ROOT / "projects"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_env(path: pathlib.Path = ROOT / ".env") -> dict:
    """Read KEY=VALUE lines into os.environ without overriding real env vars."""
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    return dict(os.environ)


def env(name: str, required: bool = False) -> str | None:
    value = os.environ.get(name)
    if required and not value:
        raise SystemExit(f"Missing {name}. Add it to .env (see .env.example).")
    return value


def http(method: str, url: str, *, params: dict | None = None,
         form: dict | None = None, body: dict | None = None,
         headers: dict | None = None, timeout: int = 60):
    """Small JSON HTTP client. POST `form` is sent urlencoded (what Graph API expects)."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = None
    hdrs = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        raise ApiError(err.code, err.read().decode(errors="replace")) from None
    return json.loads(raw.decode() or "null")


def http_bytes(url: str, timeout: int = 120) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def read_json(path: pathlib.Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, obj) -> None:
    """Atomic write so a crashed tick never leaves a half-written queue."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def run(cmd: list[str], *, capture: bool = False, cwd: pathlib.Path | None = None) -> str:
    """Run an external tool and fail loudly with its stderr tail."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}):\n{tail}")
    return proc.stdout if capture else ""


def ffprobe_duration(path: pathlib.Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture=True)
    return float(out.strip())


def require_tool(name: str) -> None:
    from shutil import which
    if which(name) is None:
        sys.exit(f"'{name}' is not installed. See docs/SETUP.md.")


def ffmpeg_has_filter(name: str) -> bool:
    """True if this ffmpeg build ships the filter (drawtext needs libfreetype)."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())
