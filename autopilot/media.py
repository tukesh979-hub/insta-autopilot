"""Media stages: record footage, generate voice, render the reel, run QA gates.

All ffmpeg work happens here. Text is passed to ffmpeg through textfile= so quotes and
colons in your script never break the filter graph.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

from .config import load_config
from .spec import load as load_spec, sentences
from .util import ROOT, ApiError, ffmpeg_has_filter, ffprobe_duration, env, log, require_tool, run

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def font_path(cfg: dict) -> str:
    configured = cfg["video"].get("font")
    for candidate in ([configured] if configured else []) + FONT_CANDIDATES:
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    raise SystemExit("No bold font found. Set video.font in config.json to a .ttf path.")


def _ff_escape(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


# ---------- record ----------

def record(project: pathlib.Path, url: str, seconds: float = 8) -> pathlib.Path:
    require_tool("node")
    out = project / "footage" / "demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["node", str(ROOT / "recorder" / "capture.mjs"), url, str(out), str(seconds)])
    log(f"Recorded {out} ({seconds}s from {url})")
    return out


# ---------- voice ----------

def voice(project: pathlib.Path, cfg: dict | None = None) -> pathlib.Path | None:
    """ElevenLabs narration. Returns None when no key is set (reel renders silent)."""
    cfg = cfg or load_config()
    key = env("ELEVENLABS_API_KEY")
    voice_id = env(cfg["voice"]["voice_id_env"])
    if not key or not voice_id:
        log("No ELEVENLABS_API_KEY/voice id: rendering without narration")
        return None
    spec = load_spec(project, strict=False)
    body = json.dumps({"text": spec["script"], "model_id": cfg["voice"]["model_id"]}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        data=body, method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as err:
        raise ApiError(err.code, err.read().decode(errors="replace")) from None
    out = project / "out" / "voice.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    log(f"Voice saved: {out}")
    return out


# ---------- render ----------

def _segment(src: pathlib.Path, dst: pathlib.Path, start: float, dur: float, cfg: dict) -> None:
    w, h, fps = cfg["video"]["width"], cfg["video"]["height"], cfg["video"]["fps"]
    graph = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:3[blur];"
        f"[fg]scale={w}:-2[fit];"
        f"[blur][fit]overlay=(W-w)/2:(H-h)/2,fps={fps},format=yuv420p[v]"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(dur),
         "-i", str(src), "-filter_complex", graph, "-map", "[v]", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(dst)])


def _weighted_timings(lines: list[str], total: float) -> list[tuple[float, float]]:
    weights = [max(1, len(line)) for line in lines]
    scale = total / sum(weights)
    t, out = 0.0, []
    for w in weights:
        out.append((t, t + w * scale))
        t += w * scale
    return out


def render(project: pathlib.Path, cfg: dict | None = None) -> pathlib.Path:
    require_tool("ffmpeg")
    require_tool("ffprobe")
    if not ffmpeg_has_filter("drawtext"):
        raise SystemExit("This ffmpeg has no drawtext filter. Install a build with libfreetype "
                         "(macOS: brew install ffmpeg; Ubuntu: apt install ffmpeg).")
    cfg = cfg or load_config()
    spec = load_spec(project)
    out_dir = project / "out"
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    font = _ff_escape(font_path(cfg))
    w, h, fps = cfg["video"]["width"], cfg["video"]["height"], cfg["video"]["fps"]

    # 1. Normalise every clip to a 9:16 segment.
    segments: list[pathlib.Path] = []
    clip_total = 0.0
    for i, clip in enumerate(spec["clips"]):
        dur = float(clip.get("duration", 4))
        seg = work / f"seg{i:02d}.mp4"
        _segment(project / clip["file"], seg, float(clip.get("start", 0)), dur, cfg)
        segments.append(seg)
        clip_total += dur

    listing = work / "segments.txt"
    listing.write_text("".join(f"file '{s.resolve()}'\n" for s in segments), encoding="utf-8")
    joined = work / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(joined)])

    # 2. Narration decides the length if present.
    audio = out_dir / "voice.mp3"
    has_voice = audio.exists()
    target = ffprobe_duration(audio) if has_voice else clip_total
    gap = max(0.0, target - clip_total)

    # 3. Text: hook lines at top, subtitles timed to the narration.
    filters = []
    hook = spec["hook"]
    accent = cfg["video"].get("accent", "FF3B3B")
    for j, line in enumerate(hook):
        tf = work / f"hook{j}.txt"
        tf.write_text(str(line), encoding="utf-8")
        color = "white" if j == 0 else accent
        y = 220 + j * 120
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{_ff_escape(str(tf))}':fontcolor={color}:"
            f"fontsize=100:x=(w-text_w)/2:y={y}:box=1:boxcolor=black@0.45:boxborderw=28")

    lines = sentences(spec["script"])
    for k, ((t0, t1), line) in enumerate(zip(_weighted_timings(lines, target), lines)):
        tf = work / f"sub{k:02d}.txt"
        tf.write_text(line, encoding="utf-8")
        filters.append(
            f"drawtext=fontfile='{font}':textfile='{_ff_escape(str(tf))}':fontcolor=white:"
            f"fontsize=54:x=(w-text_w)/2:y=h-560:box=1:boxcolor=black@0.55:boxborderw=20:"
            f"enable='between(t,{t0:.2f},{t1:.2f})'")

    graph = f"[0:v]tpad=stop_mode=clone:stop_duration={gap:.2f}," + ",".join(filters) + "[v]"
    out = out_dir / "reel.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined)]
    if has_voice:
        cmd += ["-i", str(audio), "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{target:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
                "-map", "1:a", "-c:a", "aac"]
    cmd += ["-filter_complex", graph, "-map", "[v]", "-t", f"{target:.2f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-s", f"{w}x{h}", "-movflags", "+faststart", str(out)]
    run(cmd)
    log(f"Rendered {out} ({target:.1f}s, {'with' if has_voice else 'without'} narration)")
    return out


# ---------- qa ----------

def qa(project: pathlib.Path, cfg: dict | None = None) -> list[str]:
    """Automatic gates. Returns failures (empty = pass). Also writes a contact sheet."""
    cfg = cfg or load_config()
    reel = project / "out" / "reel.mp4"
    if not reel.exists():
        return ["no out/reel.mp4 - render first"]
    failures: list[str] = []

    info = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height,r_frame_rate",
                           "-of", "json", str(reel)], capture=True))["streams"][0]
    if (info["width"], info["height"]) != (cfg["video"]["width"], cfg["video"]["height"]):
        failures.append(f"wrong size {info['width']}x{info['height']}")

    dur = ffprobe_duration(reel)
    lo, hi = cfg["video"]["min_seconds"], cfg["video"]["max_seconds"]
    if not lo <= dur <= hi:
        failures.append(f"duration {dur:.1f}s outside {lo}-{hi}s")

    # Static-looking reels fail: a reel that freezes most of the time is not worth posting.
    stderr = subprocess.run(
        ["ffmpeg", "-i", str(reel), "-vf", "freezedetect=n=0.003:d=1", "-map", "0:v:0",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    frozen = sum(float(m) for m in re.findall(r"freeze_duration: ([\d.]+)", stderr))
    ratio = frozen / dur if dur else 1
    if ratio > cfg["qa"]["max_freeze_ratio"]:
        failures.append(f"{ratio:.0%} of the reel is frozen (max {cfg['qa']['max_freeze_ratio']:.0%})")

    # 18 evenly spaced frames fill a 6x3 grid, whatever the reel length.
    sheet = project / "out" / "contact_sheet.jpg"
    rate = 18 / max(dur, 1)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(reel),
         "-vf", f"fps={rate:.4f},scale=270:-2,tile=6x3", "-frames:v", "1", str(sheet)])
    log(f"QA sheet: {sheet}")
    return failures
