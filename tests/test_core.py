"""Offline tests: `python3 -m unittest discover -s tests -t .`"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from autopilot import engagement, media, queue, scoring, spec
from autopilot.config import load_config
from autopilot.util import ffmpeg_has_filter, iso, write_json

CFG = json.loads((pathlib.Path(__file__).resolve().parent.parent / "config.example.json").read_text())
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def repo(**overrides):
    base = {"name": "acme/neon-city", "description": "A 3D animation tool with shader demos",
            "topics": ["threejs"], "license": "MIT", "stars": 800, "homepage": "https://neon.example",
            "created_at": iso(NOW - timedelta(days=5))}
    base.update(overrides)
    return base


class ScoringTests(unittest.TestCase):
    def test_good_repo_scores_high(self):
        score, _ = scoring.score_idea(repo(), CFG, now=NOW)
        self.assertGreaterEqual(score, CFG["ideas"]["min_score"])

    def test_disallowed_licence_is_rejected(self):
        score, reasons = scoring.score_idea(repo(license="GPL-3.0"), CFG, now=NOW)
        self.assertEqual(score, 0)
        self.assertIn("not in allowed list", reasons[0])

    def test_reject_keyword_blocks_repo(self):
        score, reasons = scoring.score_idea(repo(description="3D animation keygen"), CFG, now=NOW)
        self.assertEqual(score, 0)
        self.assertIn("reject_keywords", reasons[0])

    def test_low_stars_cannot_reach_shortlist(self):
        score, _ = scoring.score_idea(repo(stars=3), CFG, now=NOW)
        self.assertLess(score, CFG["ideas"]["min_score"])


def make_project(root: pathlib.Path, **overrides) -> pathlib.Path:
    project = root / "demo"
    (project / "footage").mkdir(parents=True)
    (project / "footage" / "demo.mp4").write_bytes(b"x")
    data = {
        "title": "neon-city",
        "hook": ["Whole City In A Browser", "Built From One File"],
        "script": ("Here is a city you can walk through in your browser. It is called neon city. "
                   "Every building is drawn with three.js and runs at sixty frames. "
                   "The whole thing is free and open source on GitHub. "
                   "Comment NEON and I will send you the link."),
        "keyword": "NEON",
        "caption": "Neon city, free and open source.",
        "clips": [{"file": "footage/demo.mp4", "start": 0, "duration": 10}],
        "link": "https://github.com/acme/neon-city",
    }
    data.update(overrides)
    write_json(project / "spec.json", data)
    return project


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_spec_passes(self):
        project = make_project(self.tmp)
        self.assertEqual(spec.validate(json.loads((project / "spec.json").read_text()), project), [])

    def test_long_hook_line_fails(self):
        project = make_project(self.tmp, hook=["one two three four five six seven", "ok"])
        problems = spec.validate(json.loads((project / "spec.json").read_text()), project)
        self.assertTrue(any("hook line too long" in p for p in problems))

    def test_script_must_contain_keyword(self):
        project = make_project(self.tmp, keyword="TOKYO")
        problems = spec.validate(json.loads((project / "spec.json").read_text()), project)
        self.assertTrue(any("comment TOKYO" in p for p in problems))

    def test_missing_clip_file_fails(self):
        project = make_project(self.tmp, clips=[{"file": "footage/missing.mp4", "duration": 5}])
        problems = spec.validate(json.loads((project / "spec.json").read_text()), project)
        self.assertTrue(any("file not found" in p for p in problems))

    def test_sentence_split(self):
        self.assertEqual(len(spec.sentences("One. Two! Three?")), 3)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(queue, "QUEUE", self.tmp / "queue.json")
        self.patch.start()
        self.upload = mock.patch.object(queue, "upload_public", return_value="https://cdn.example/r.mp4")
        self.upload.start()
        self.project = make_project(self.tmp)
        (self.project / "out").mkdir()
        (self.project / "out" / "reel.mp4").write_bytes(b"x")

    def tearDown(self):
        self.patch.stop()
        self.upload.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_then_plan_assigns_slots(self):
        queue.add(self.project)
        self.assertEqual(queue.plan(days=1), 1)
        item = queue.list_items()[0]
        self.assertEqual(item["status"], "scheduled")
        self.assertIsNotNone(item["when"])

    def test_duplicate_add_is_refused(self):
        queue.add(self.project)
        with self.assertRaises(SystemExit):
            queue.add(self.project)

    def test_tick_publishes_due_item_once(self):
        queue.add(self.project)
        items = queue.list_items()
        items[0].update(status="scheduled", when=iso(NOW - timedelta(minutes=1)),
                        video_url="https://cdn.example/a.mp4", ig_media_id="123")
        write_json(queue.QUEUE, items)
        # ig_media_id already set, so nothing is sent to Meta.
        with mock.patch.object(queue, "load_config", return_value=CFG):
            result = queue.tick(now=NOW)
        self.assertEqual(result["published"], 1)
        self.assertEqual(queue.list_items()[0]["status"], "published")

    def test_tick_skips_future_items(self):
        queue.add(self.project)
        items = queue.list_items()
        items[0].update(status="scheduled", when=iso(NOW + timedelta(hours=2)))
        write_json(queue.QUEUE, items)
        with mock.patch.object(queue, "load_config", return_value=CFG):
            self.assertEqual(queue.tick(now=NOW)["published"], 0)

    def test_failing_item_gives_up_after_max_attempts(self):
        queue.add(self.project)
        items = queue.list_items()
        items[0].update(status="scheduled", when=iso(NOW - timedelta(minutes=1)), attempts=2,
                        video_url="https://cdn.example/a.mp4")
        write_json(queue.QUEUE, items)
        with mock.patch.object(queue, "load_config", return_value=CFG), \
                mock.patch.object(queue, "_publish_item", side_effect=RuntimeError("boom")):
            result = queue.tick(now=NOW)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(queue.list_items()[0]["status"], "failed")


class KeywordTests(unittest.TestCase):
    def test_whole_word_match_only(self):
        self.assertTrue(engagement._matches("comment neon please", "NEON"))
        self.assertTrue(engagement._matches("NEON!", "NEON"))
        self.assertFalse(engagement._matches("neonlight", "NEON"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe") and ffmpeg_has_filter("drawtext"),
                     "needs ffmpeg with drawtext (libfreetype)")
class RenderTests(unittest.TestCase):
    def test_render_and_qa_end_to_end(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            project = make_project(tmp)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=size=1440x1080:rate=30:duration=12",
                            str(project / "footage" / "demo.mp4")], check=True)
            cfg = load_config()
            cfg = json.loads(json.dumps(cfg))
            cfg["video"]["min_seconds"] = 5
            if not any(pathlib.Path(p).exists() for p in media.FONT_CANDIDATES) and not cfg["video"]["font"]:
                self.skipTest("no font available")
            media.render(project, cfg)
            reel = project / "out" / "reel.mp4"
            self.assertTrue(reel.exists())
            failures = media.qa(project, cfg)
            self.assertEqual(failures, [], failures)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
