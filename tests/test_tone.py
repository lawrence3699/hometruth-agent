#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情绪标签（src/voice/tone.py）：按 step / 格子状态挑标签，只进嘴不进字幕；关着时永远没有。
跑：.venv/bin/python -m unittest tests/test_tone.py -v"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))

import tone  # noqa: E402


def feed(enabled, events):
    """按顺序喂每个事件（highlight 也要喂，它带格子状态），只收 say 的结果。"""
    m = tone.Mood(enabled)
    out = []
    for e in events:
        t = m.tag(e)
        if e.get("type") == "say":
            out.append((e.get("step"), t))
    return out, m


class ToneCase(unittest.TestCase):
    def test_tags_follow_step_and_cell_status(self):
        events = [
            {"type": "say", "step": "bridge", "text": "Okay."},
            {"type": "say", "step": "bridge", "text": "Let me check."},
            {"type": "say", "step": "bridge", "text": "Great, thanks a lot."},
            {"type": "say", "step": "heard", "text": "So: two bedrooms, under 900 a week."},
            {"type": "say", "step": "ask", "text": "First, what's your weekly budget?"},
            {"type": "say", "step": "opening", "text": "Okay, let me see what fits near Central."},
            {"type": "say", "step": "shortlist", "text": "Found some. Three places tick the basics."},
            {"type": "say", "step": "L0", "text": "First up: a two-bedroom on 31 Fenwick Street."},
            {"type": "highlight", "status": "supported"},
            {"type": "say", "step": "L0.A1", "text": "Rent is 890 a week, inside your 900 budget."},
            {"type": "highlight", "status": "inferred"},
            {"type": "say", "step": "L0.C1", "text": "Looks like there's a split system in the bedroom, going by the photos."},
            {"type": "highlight", "status": "conflict"},
            {"type": "say", "step": "L0.B1", "text": "One bedroom, where you asked for two."},
            {"type": "highlight", "status": "unknown"},
            {"type": "say", "step": "L0.F1", "text": "No checked fact on bills, so that goes to the agent."},
            {"type": "say", "step": "L0.special", "text": "There's a north-facing balcony off the living room."},
            {"type": "highlight", "status": "unknown", "question": True},
            {"type": "say", "step": "L0.question", "text": "Best thing to ask the agent: are bills included?"},
            {"type": "say", "step": "L0.next", "text": "Next one then, moving on."},
            {"type": "say", "step": "answer", "text": "The listing has no checked fact on whether bills are included."},
            {"type": "say", "step": "answer", "text": "Yes, the by-laws allow pets with written consent."},
            {"type": "say", "step": "back", "text": "Okay, where was I. The first place."},
            {"type": "say", "step": "next", "text": "Okay, moving on now."},
            {"type": "say", "step": "stop", "text": "Okay, I'll pause here. Say continue when you're ready."},
            {"type": "say", "step": "wrap", "text": "That's the three. Two left out for the cat rule."},
            {"type": "say", "step": "unclear", "text": "Sorry, I didn't catch that. I'll carry on."},
        ]
        got, m = feed(True, events)
        want = [("bridge", None), ("bridge", "[thoughtful]"), ("bridge", "[warmly]"), ("heard", "[thoughtful]"), ("ask", "[curious]"),
                ("opening", "[thoughtful]"), ("shortlist", "[happy]"), ("L0", "[upbeat]"), ("L0.A1", None), ("L0.C1", "[thoughtful]"),
                ("L0.B1", "[concerned]"), ("L0.F1", "[curious]"), ("L0.special", "[cheerful]"), ("L0.question", "[thoughtful]"), ("L0.next", "[cheerful]"),
                ("answer", "[thoughtful]"), ("answer", "[reassuring]"), ("back", "[thoughtful]"), ("next", "[cheerful]"), ("stop", "[calm]"),
                ("wrap", "[warmly]"), ("unclear", "[gentle]")]
        self.assertEqual(got, want)
        self.assertEqual(m.tagged, sum(1 for _, t in want if t))
        for e in events:  # 事件本身一个字没动
            if e.get("type") == "say":
                self.assertFalse(tone.TAG_RE.match(e["text"]), e["text"])

    def test_disabled_means_nothing_ever(self):
        events = [{"type": "highlight", "status": "conflict"}, {"type": "say", "step": "L0.B1", "text": "One bedroom, where you asked for two."},
                  {"type": "say", "step": "shortlist", "text": "Found some. Three places tick the basics."}]
        got, m = feed(False, events)
        self.assertEqual([t for _, t in got], [None, None])
        self.assertEqual(m.tagged, 0)
        self.assertEqual(tone.Mood(False).speak({"type": "say", "step": "shortlist", "text": "Found some. Three places tick."}), "Found some. Three places tick.")

    def test_speak_prefixes_tts_text_only(self):
        ev = {"type": "say", "step": "shortlist", "text": "Found some. Three places tick the basics."}
        spoken = tone.Mood(True).speak(ev)
        self.assertEqual(spoken, "[happy] Found some. Three places tick the basics.")
        self.assertEqual(ev["text"], "Found some. Three places tick the basics.")
        self.assertEqual(tone.strip_tags(spoken), ev["text"])
        self.assertEqual(tone.strip_tags("no tag here"), "no tag here")
        self.assertIsNone(tone.tag_for("shortlist", "Found."))  # 太短不加
        self.assertIsNone(tone.tag_for("nonsense-step", "Three words at least here."))

    def test_session_say_events_stay_clean(self):
        """整轮对话走一遍（规则解析、不叫模型）：say 文本里没有任何标签；Mood 开着时能给出标签。"""
        saved = {k: os.environ.get(k) for k in ("NARRATION_LLM", "NEEDS_PARSER", "VOICE_VARIETY", "HOMETRUTH_ENV_FILE")}
        os.environ.update({"NARRATION_LLM": "0", "NEEDS_PARSER": "rules", "HOMETRUTH_ENV_FILE": ""})
        try:
            import policy  # noqa: WPS433
            s = policy.Session("t-tone")
            events = []
            for text in ["Two bedrooms under 900 a week near Central Station, moving mid-November, and I have a cat.", "Skip.", "Stop."]:
                events += list(s.handle_turn({"text": text}))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        says = [e for e in events if e.get("type") == "say"]
        self.assertGreater(len(says), 10)
        for e in says:
            self.assertFalse(tone.TAG_RE.match(e["text"]), e["text"])
        m = tone.Mood(True)
        tags = [m.tag(e) for e in events]
        self.assertGreaterEqual(m.tagged, 5, tags)
        for e in says:  # 喂过 Mood 之后事件文本还是干净的
            self.assertFalse(tone.TAG_RE.match(e["text"]), e["text"])


if __name__ == "__main__":
    unittest.main()
