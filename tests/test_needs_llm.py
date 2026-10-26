#!/usr/bin/env python3
"""policy.parse_needs_llm 的单测：模型路径对着 tests/mock_meterless.py 跑（假模型按固定表回 JSON），不连真服务。
跑：python3 -m unittest tests/test_needs_llm.py -v"""
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
sys.path.insert(0, str(ROOT / "tests"))

from llm import provider as P  # noqa: E402
import policy  # noqa: E402
from mock_meterless import Mock  # noqa: E402

KEYS = ["METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN", "METERLESS_API_KEY", "METERLESS_MODEL", "METERLESS_CONNECT_LINK", "NVIDIA_API_KEY",
        "LLM_PROVIDER", "HOMETRUTH_ENV_FILE", "NEEDS_PARSER", "NEEDS_LLM_TIMEOUT", "POLISH_LLM", "NARRATION_LLM", "VOICE_VARIETY"]
NEED = "Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom."


class NeedsCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = Mock("mock-token")
        cls.port = cls.mock.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in KEYS}
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update({"HOMETRUTH_ENV_FILE": "", "METERLESS_BASE_URL": f"http://127.0.0.1:{self.port}/v1", "METERLESS_RUNTIME_TOKEN": "mock-token",
                           "NARRATION_LLM": "0", "VOICE_VARIETY": "0"})  # 这里只测需求解析；台词交给模型写在 test_narrator.py 测
        P._env_loaded = False
        P.invalidate()
        self.tmp = tempfile.TemporaryDirectory()
        self._log = P.LOG
        P.LOG = Path(self.tmp.name) / "llm_log.jsonl"
        self.mock.requests.clear()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        P.LOG = self._log
        P._env_loaded = False
        P.invalidate()
        self.tmp.cleanup()

    def both(self, text, pending=None):
        a, b = policy.new_profile(), policy.new_profile()
        ch_rules = policy.parse_into(a, text, pending)
        ch_llm, meta = policy.parse_needs_llm(text, b, pending)
        return (a, ch_rules), (b, ch_llm), meta

    def test_same_structure_as_rules(self):
        (a, ca), (b, cb), meta = self.both(NEED)
        self.assertEqual(meta["parser"], "llm")
        self.assertEqual((meta["provider"], meta["model"]), ("meterless", "meterless/auto"))
        self.assertEqual(a, b)
        self.assertEqual(ca, cb)
        self.assertEqual(b["pets"], {"has": True, "kind": "cat", "text": "a cat"})
        self.assertEqual(b["extras"], [{"dim": "C1", "label": "Air con in the bedroom"}])

    def test_short_answer_to_a_question(self):
        (a, _), (b, _), meta = self.both("Under 900, mid-November.", ["A1", "A4"])
        self.assertEqual(meta["parser"], "llm")
        self.assertEqual(a, b)
        self.assertEqual(b["move_in"], {"month": 11, "day": 15, "text": "mid-November"})

    def test_model_catches_what_rules_miss(self):
        (a, _), (b, ch), meta = self.both("Somewhere close to Newtown for my partner and me, we've got a little dog.")
        self.assertIsNone(a["anchor"])
        self.assertEqual(b["anchor"], "Newtown")
        self.assertEqual(b["pets"]["kind"], "dog")
        self.assertIn("anchor", ch)
        (a, _), (b, _), meta = self.both("Nine hundred tops, and we need it in about two weeks.")
        self.assertEqual((a["budget"], a["move_in"]), (None, None))
        d = dt.date.today() + dt.timedelta(days=14)
        self.assertEqual(b["budget"], 900)
        self.assertEqual((b["move_in"]["month"], b["move_in"]["day"]), (d.month, d.day))

    def test_invented_values_rejected_rules_fill_in(self):
        (a, _), (b, _), meta = self.both("HALLUCINATE two bedrooms please")
        self.assertEqual(meta["parser"], "llm")
        self.assertEqual(set(meta["rejected"]), {"budget", "bedrooms", "anchor"})
        self.assertEqual(meta["from_rules"], ["bedrooms"])
        self.assertEqual(b, a)  # 模型编的全被拒，结果和规则一样

    def test_omitted_keys_mean_null(self):
        out, bad = policy.validate_llm_fields({"bedrooms": 2}, "two bedrooms please", [])
        self.assertEqual((out["bedrooms"], out["budget"], out["anchor"], out["move_in"], out["pets"], out["extras"]), (2, None, None, None, None, []))
        self.assertEqual(bad, {})

    def test_bridge_then_model_result_second_round_says_thanks(self):
        s = policy.Session("t-bridge")
        list(s.handle_turn({"text": NEED}))
        evs = list(s.handle_turn({"text": "Under 900, mid-November."}))
        self.assertEqual(evs[1], {"type": "say", "idx": None, "text": "Thanks.", "step": "bridge"})
        needs = next(e for e in evs if e["type"] == "needs")
        self.assertEqual((needs["parser"], needs["missing"]), ("llm", []))
        says = [e["text"] for e in evs if e["type"] == "say"]
        self.assertTrue(says[1].startswith("Two bedrooms, under 900 a week"), says[1])  # 开场不再重复 "Got it"

    def test_not_json_falls_back_to_rules(self):
        (a, _), (b, _), meta = self.both("BADJSON two bedrooms please")
        self.assertEqual((meta["parser"], meta["reason"]), ("rules", "model answer was not a JSON object"))
        self.assertEqual(a, b)

    def test_timeout_falls_back_to_rules(self):
        os.environ["NEEDS_LLM_TIMEOUT"] = "1"
        (a, _), (b, _), meta = self.both("SLOW two bedrooms near Central")
        self.assertEqual(meta["parser"], "rules")
        self.assertTrue(meta["reason"].startswith("timeout"), meta["reason"])
        self.assertEqual(a, b)

    def test_no_provider_and_forced_rules_send_nothing(self):
        os.environ["METERLESS_RUNTIME_TOKEN"] = ""
        P.invalidate()
        (a, _), (b, _), meta = self.both(NEED)
        self.assertEqual(meta["parser"], "rules")
        self.assertIn("no provider", meta["reason"])
        os.environ["METERLESS_RUNTIME_TOKEN"] = "mock-token"
        os.environ["NEEDS_PARSER"] = "rules"
        P.invalidate()
        (_, _), (_, _), meta = self.both(NEED)
        self.assertEqual((meta["parser"], meta["reason"]), ("rules", "NEEDS_PARSER=rules"))
        self.assertEqual([r for r in self.mock.requests if r["method"] == "POST"], [])

    def test_session_marks_the_path_in_needs_event(self):
        s = policy.Session("t-llm")
        evs = list(s.handle_turn({"text": NEED}))
        self.assertEqual(evs[0], {"type": "state", "phase": "thinking", "label": "Analysing your request"})
        self.assertEqual(evs[1], {"type": "say", "idx": None, "text": "Got it.", "step": "bridge"})  # 过渡句先说，模型还在解析
        self.assertEqual([e["type"] for e in evs], ["state", "say", "needs", "ask", "say", "done"])
        needs = next(e for e in evs if e["type"] == "needs")
        self.assertEqual((needs["parser"], needs["parse"]["provider"]), ("llm", "meterless"))
        self.assertEqual(needs["asking"], ["A1", "A4"])
        ask = next(e for e in evs if e["type"] == "ask")
        self.assertEqual(ask["text"], "Two quick things before I search: what's your weekly budget, and when do you need to move in?")
        log = P.LOG.read_text()
        self.assertIn('"task": "needs_parse"', log)
        self.assertNotIn("mock-token", log)

    def test_polish_is_off_by_default_and_validated_when_on(self):
        q = "Two quick things before I search: what's your weekly budget, and when do you need to move in?"
        self.assertEqual(policy.polish_llm(q, ["A1", "A4"]), q)
        n = len([r for r in self.mock.requests if r["method"] == "POST"])
        self.assertEqual(n, 0)
        os.environ["POLISH_LLM"] = "1"
        self.assertEqual(policy.polish_llm(q, ["A1", "A4"]), q)  # 假模型回的不是问句 → 校验不过 → 用模板
        self.assertEqual(len([r for r in self.mock.requests if r["method"] == "POST"]), 1)


if __name__ == "__main__":
    unittest.main()
