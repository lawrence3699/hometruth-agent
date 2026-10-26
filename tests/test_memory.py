#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""欢迎回来（src/voice/memory.py + policy.Session 的记忆开场）：存 / 读 / 忘、脏编号不认、预填 chip、机器先开口问、"Same again" 直接开查不再反问、
改一项其余照旧、needs 事件的 remembered、情绪标签。全部离线：规则解析、模板台词、记忆目录指到临时文件夹。
跑：.venv/bin/python -m unittest tests/test_memory.py -v"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))
os.environ["HOMETRUTH_ENV_FILE"] = ""
os.environ["NEEDS_PARSER"] = "rules"
os.environ["NARRATION_LLM"] = "0"
os.environ["VOICE_VARIETY"] = "0"

import memory  # noqa: E402
import policy  # noqa: E402
import tone  # noqa: E402

NEED = "Two bedrooms near Central, under 900 a week, I have a cat, moving mid November"
RID = "r-test-memory-0001"


def events(session: policy.Session, text: str) -> list:
    return list(session.handle_turn({"text": text}))


class MemoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._dir = memory.DIR
        memory.DIR = Path(self.tmp.name)

    def tearDown(self):
        memory.DIR = self._dir
        self.tmp.cleanup()

    def first_visit(self) -> policy.Session:
        s = policy.Session("mem-first")
        s.quick = True
        s.attach_renter(RID)
        self.assertIsNone(s.memory)
        ev = events(s, NEED)
        self.assertEqual(sum(e["type"] == "card" for e in ev), 3)
        return s

    def test_ids_are_cleaned_and_bad_ones_are_ignored(self):
        self.assertEqual(memory.clean_id(" r-abc_123 "), "r-abc_123")
        for bad in ("", None, "../x", "a/b", "x" * 65, "abc", "r.1"):
            self.assertIsNone(memory.clean_id(bad), bad)
        self.assertIsNone(memory.load("../etc"))
        self.assertIsNone(memory.save("../etc", policy.new_profile(), []))

    def test_search_saves_and_view_is_what_the_page_shows(self):
        self.first_visit()
        mem = memory.load(RID)
        self.assertIsNotNone(mem)
        self.assertEqual(mem["visits"], 1)
        self.assertEqual(mem["profile"]["budget"], 900)
        self.assertEqual(mem["profile"]["pets"]["has"], True)
        self.assertEqual(mem["top"][0], "L-0002")
        self.assertIn("with a cat", mem["summary"])
        v = memory.view(mem)
        self.assertEqual(v["profile"]["move_in"], "mid-November")
        self.assertEqual(v["remembered"], ["budget", "bedrooms", "anchor", "move_in", "pets"])
        self.assertEqual(v["ago"], "just now")
        self.assertTrue(memory.forget(RID))
        self.assertIsNone(memory.load(RID))
        self.assertFalse(memory.forget(RID))

    def test_second_visit_prefills_and_greets_first(self):
        self.first_visit()
        s = policy.Session("mem-second")
        s.quick = True
        self.assertIsNotNone(s.attach_renter(RID))
        self.assertEqual(s.profile["budget"], 900)
        self.assertEqual(s.remembered, ["budget", "bedrooms", "anchor", "move_in", "pets"])
        w = list(s.welcome())
        kinds = [e["type"] for e in w]
        self.assertEqual(kinds, ["state", "needs", "ask", "say", "done"])
        self.assertEqual(w[1]["remembered"], ["budget", "bedrooms", "anchor", "move_in", "pets"])
        self.assertTrue(w[3]["text"].startswith("Welcome back. Last time it was two bedrooms"))
        self.assertTrue(w[3]["text"].endswith("Same again, or has anything changed?"))
        self.assertEqual(w[3]["step"], "welcome")
        self.assertEqual(list(s.welcome()), [])  # only once
        # "Same again": no questions, straight to the sources and the tour
        ev = events(s, "Same again")
        says = [(e.get("step"), e["text"]) for e in ev if e["type"] == "say"]
        self.assertEqual(says[0], ("bridge", "Got it."))
        self.assertEqual(says[1], ("welcome", "Same as last time, then."))
        self.assertEqual(says[2], ("opening", f"Checking {len(policy.SOURCES)} sources now."))  # 10-26 起 7 个来源（多了日照几何、户型图）
        self.assertFalse(any(e["type"] == "ask" for e in ev))
        self.assertEqual(sum(e["type"] == "card" for e in ev), 3)
        self.assertEqual([e for e in ev if e["type"] == "needs"][0]["remembered"], ["budget", "bedrooms", "anchor", "move_in", "pets"])
        self.assertEqual(memory.load(RID)["visits"], 2)

    def test_second_visit_with_a_change_keeps_the_rest(self):
        self.first_visit()
        s = policy.Session("mem-change")
        s.quick = True
        s.attach_renter(RID)
        ev = events(s, "Make it under 800 this time")
        says = [(e.get("step"), e["text"]) for e in ev if e["type"] == "say"]
        self.assertEqual(says[1][0], "welcome")
        self.assertTrue(says[1][1].startswith("Welcome back. Last time it was two bedrooms, under 900 a week"), says[1][1])
        self.assertIn("this time budget under 800 a week, and the rest as before", says[1][1])
        self.assertEqual(s.profile["budget"], 800)
        self.assertEqual(s.profile["bedrooms"], 2)
        needs = [e for e in ev if e["type"] == "needs"][0]
        self.assertEqual(needs["remembered"], ["bedrooms", "anchor", "move_in", "pets"])  # budget was restated
        self.assertFalse(any(e["type"] == "ask" for e in ev))
        self.assertEqual(memory.load(RID)["profile"]["budget"], 800)  # the latest search wins

    def test_no_renter_means_no_memory_and_no_extra_keys(self):
        s = policy.Session("mem-none")
        s.quick = True
        ev = events(s, NEED)
        self.assertTrue(all("remembered" not in e for e in ev if e["type"] == "needs"))
        self.assertFalse(any(e.get("step") == "welcome" for e in ev))
        self.assertEqual(list(s.welcome()), [])

    def test_reset_style_attach_without_prefill_still_saves(self):
        self.first_visit()
        s = policy.Session("mem-reset")
        s.quick = True
        s.attach_renter(RID, prefill=False)
        self.assertIsNone(s.profile["budget"])
        ev = events(s, "One bedroom near UNSW, under 700, no pets, moving in December")
        self.assertEqual(sum(e["type"] == "card" for e in ev) + sum(e["type"] == "ask" for e in ev) > 0, True)
        self.assertFalse(any(e.get("step") == "welcome" and e["text"].startswith("Welcome back. Same") for e in ev if e["type"] == "say"))

    def test_ago_and_tone(self):
        now = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(memory.ago("2026-10-26T11:59:30+00:00", now), "just now")
        self.assertEqual(memory.ago("2026-10-26T11:30:00+00:00", now), "30 minutes ago")
        self.assertEqual(memory.ago("2026-10-26T09:00:00+00:00", now), "3 hours ago")
        self.assertEqual(memory.ago("2026-10-25T09:00:00+00:00", now), "yesterday")
        self.assertEqual(memory.ago("2026-10-20T09:00:00+00:00", now), "6 days ago")
        self.assertEqual(memory.ago("nonsense", now), "")
        self.assertEqual(tone.tag_for("welcome", "Welcome back. Last time it was two bedrooms near Central."), "[warmly]")


if __name__ == "__main__":
    unittest.main()
