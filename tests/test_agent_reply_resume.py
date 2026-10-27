#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导览中途转达中介回复后说 continue / go on：接着讲当前这套还没讲的格子，不从头再搜一遍；导览已经讲完时照旧（继续 = 重新来一遍）。
跑：.venv/bin/python -m unittest tests/test_agent_reply_resume.py -v"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))

ENV = {"NARRATION_LLM": "0", "NEEDS_PARSER": "rules", "HOMETRUTH_ENV_FILE": "", "VOICE_VARIETY": "0", "VOICE_TOUR": "full"}  # 逐格讲法（简短播报见 test_voice_brief.py）
NEED = "Two bedrooms under 900 a week near Central Station, moving mid-November, and I have a cat."
AGENT = "The Alder Lane agent said pets are fine as long as we clean the carpets when we leave."


class AgentReplyResumeCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        import policy  # noqa: WPS433
        self.policy = policy

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @staticmethod
    def says(events):
        return [e for e in events if e.get("type") == "say"]

    def test_go_on_after_mid_tour_agent_reply_continues_same_listing(self):
        s = self.policy.Session("t-agent-mid")
        tour = list(s.handle_turn({"text": NEED, "deterministic": True}))
        says = self.says(tour)
        alder = next(c["listing"]["id"] for c in tour if c.get("type") == "card" and "Alder" in json.dumps(c["listing"]))
        card = None
        pets = None
        for e in tour:  # Alder Lane 那套的宠物格
            if e.get("type") == "card":
                card = e["listing"]["id"]
            elif e.get("type") == "say" and card == alder and e["step"].endswith(".J1"):
                pets = e
        self.assertIsNotNone(pets)
        prefix = pets["step"].split(".")[0]  # 这套房是 L0 / L1 / L2 里的哪个
        cut = says[says.index(pets) + 1]  # 刚讲完宠物那格就被打断
        inter = {"active": True, "spoken_idx": pets["idx"], "listing_id": alder, "cut_sentence": cut["text"]}
        reply = list(s.handle_turn({"text": AGENT, "listing_id": alder, "interrupted": inter, "deterministic": True}))
        self.assertEqual([e["step"] for e in self.says(reply)][-1], "change")
        self.assertIn("confirmed", self.says(reply)[-1]["text"])  # 10-28 起不说 "goes from inferred to supported"
        self.assertLess(s.pos, len(s.plan), "导览没讲完，不该被标成讲完")

        # 翻格后重排，这套房的序号可能变（10-26 起 Alder Lane 的宠物一 supported 就追平第一名、按租金排到 L0）：按房源找它现在的序号
        new_prefix = next(f"L{i}" for i, e in enumerate([e for e in s.plan if e.get("type") == "card"]) if e["listing"]["id"] == alder)
        cont = self.says(list(s.handle_turn({"text": "Okay, go on.", "deterministic": True})))
        steps = [e["step"] for e in cont]
        self.assertTrue(steps, "continue 后得接着讲")
        self.assertTrue(steps[0].startswith(new_prefix + "."), (prefix, new_prefix, steps))  # 接着讲同一套房
        self.assertNotIn(new_prefix + ".J1", steps)  # 刚改过的那格不重复
        for bad in ("opening", "shortlist", "heard", new_prefix):  # 没有从头再搜一遍、没有重报这套房的开头
            self.assertNotIn(bad, steps, steps)
        self.assertEqual(steps[-1], "wrap")
        self.assertEqual(s.pos, len(s.plan))

    def test_agent_reply_after_finished_tour_stays_finished(self):
        s = self.policy.Session("t-agent-done")
        list(s.handle_turn({"text": NEED, "deterministic": True}))  # 整个导览一口气讲完
        self.assertEqual(s.pos, len(s.plan))
        reply = list(s.handle_turn({"text": AGENT, "deterministic": True}))
        self.assertEqual([e["step"] for e in self.says(reply)][-1], "change")
        self.assertEqual(s.pos, len(s.plan), "讲完了就还是讲完")
        again = [e["step"] for e in self.says(list(s.handle_turn({"text": "Okay, go on.", "deterministic": True})))]
        self.assertEqual(again, ["resume"])  # 10-28 起：讲完之后的 continue 不再从头查一遍，只说讲完了、问要不要细节或问题清单


if __name__ == "__main__":
    unittest.main()
