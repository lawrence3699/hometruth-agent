#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中介回复不是租客的需求：转达 "the agent says no pets" 时，租客的猫不能被抹掉（10-27：需求被改成 no pets → J1 格没了 → KeyError 'J1'）。
翻成冲突后掉出前三要如实说谁补进来，不能说 "The order stays the same."
跑：.venv/bin/python -m unittest tests/test_agent_reply_needs.py -v"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))

ENV = {"NARRATION_LLM": "0", "NEEDS_PARSER": "rules", "HOMETRUTH_ENV_FILE": "", "VOICE_VARIETY": "0", "HOMETRUTH_ZETARIS": "0"}
NEED = "Two bedrooms under 900 a week near UNSW, moving mid-November, and I have a cat."
AGENT = "The agent at Alder Lane says no pets in that building, sorry."


class AgentReplyIsNotANeedCase(unittest.TestCase):
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

    def test_no_pets_reply_keeps_the_cat_and_flips_the_cell(self):
        s = self.policy.Session("t-agent-no-pets")
        list(s.handle_turn({"text": NEED, "deterministic": True}))
        self.assertTrue(s.profile["pets"]["has"])
        out = list(s.handle_turn({"text": AGENT, "deterministic": True}))
        self.assertFalse([e for e in out if e.get("type") == "error"], "the reply must not crash the turn")
        self.assertTrue(s.profile["pets"]["has"], "an agent's 'no pets' is not the renter's need")
        ch = next(e for e in out if e.get("type") == "change")
        self.assertEqual((ch["dim"], ch["to"]), ("J1", "conflict"))
        said = [e["text"] for e in out if e.get("type") == "say"][-1]
        if ch["rank_before"] != ch["rank_after"]:
            self.assertNotIn("order stays the same", said)


if __name__ == "__main__":
    unittest.main()
