#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台词交给模型写（src/voice/narrator.py）的单测：校验器本身，以及整轮对话对着 tests/mock_meterless.py 跑（假模型把事实加前缀回来）。
跑：.venv/bin/python -m unittest tests/test_narrator.py -v"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))

from llm import provider as P  # noqa: E402
import narrator  # noqa: E402
import phraser  # noqa: E402
import policy  # noqa: E402
from mock_meterless import Mock  # noqa: E402

KEYS = ["VOICE_TOUR", "METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN", "METERLESS_API_KEY", "METERLESS_MODEL", "METERLESS_CONNECT_LINK", "NVIDIA_API_KEY",
        "LLM_PROVIDER", "HOMETRUTH_ENV_FILE", "NEEDS_PARSER", "NEEDS_LLM_TIMEOUT", "POLISH_LLM", "NARRATION_LLM", "NARRATION_LLM_TIMEOUT", "VOICE_VARIETY"]
NEED = "Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom."
ANSWER = "Under 900, mid-November."


class CheckLineCase(unittest.TestCase):
    """校验器：数字不能多不能少、状态词要在、维度词要在、不要 markdown。"""

    def test_accepts_a_faithful_rewrite(self):
        t, why = narrator.check_line("Rent's 890 a week, so you're inside the 900 budget.", required={"890", "900"}, allowed={"890", "900"},
                                     status="supported", words=narrator.DIM_WORDS["A1"])
        self.assertEqual(why, "")
        self.assertTrue(t.startswith("Rent's 890"))

    def test_rejects_invented_number(self):
        t, why = narrator.check_line("Rent is 890 a week, 50 under your 900 budget.", required={"890", "900"}, allowed={"890", "900"}, status="supported")
        self.assertIsNone(t)
        self.assertIn("invented number", why)

    def test_rejects_missing_required_number(self):
        t, why = narrator.check_line("Rent fits your budget.", required={"890", "900"}, allowed={"890", "900"}, status="supported", words=narrator.DIM_WORDS["A1"])
        self.assertIsNone(t)
        self.assertIn("missing number", why)

    def test_unknown_must_say_so_and_supported_must_not_hedge(self):
        self.assertIsNone(narrator.check_line("Bedroom air con: looks fine.", status="unknown", words=narrator.DIM_WORDS["C1"])[0])
        self.assertIsNotNone(narrator.check_line("Bedroom air con I can't confirm; nothing in the report mentions it, so ask the agent.",
                                                 status="unknown", words=narrator.DIM_WORDS["C1"])[0])
        self.assertIsNone(narrator.check_line("Pets are probably fine, supported.", status="supported", words=narrator.DIM_WORDS["J1"])[0])

    def test_rejects_copies_labels_and_echoes(self):
        self.assertEqual(narrator.check_line("Rent is 890 a week, inside your 900 budget.", allowed={"890", "900"},
                                             fact="Rent is 890 a week, inside your 900 budget.")[1], "copied the fact")
        self.assertEqual(narrator.check_line("Supported: pets allowed with written consent.", status="supported")[1], "starts with a status label")
        self.assertEqual(narrator.check_line("Is the first one close to the station? It's 14 minutes by bus.", allowed={"14"},
                                             avoid=["Is the first one close to the station?"])[1], "repeats the renter's words")
        self.assertEqual(narrator.check_line("it's the only one with vents in both bedrooms.")[0], "It's the only one with vents in both bedrooms.")

    def test_rejects_markdown_questions_and_long_handovers(self):
        self.assertIsNone(narrator.check_line("**Rent** is 890", allowed={"890"})[0])
        self.assertIsNone(narrator.check_line("Ask the agent about pets.", question=True)[0])
        self.assertIsNotNone(narrator.check_line("Are pets allowed, in writing?", question=True, words=narrator.DIM_WORDS["J1"])[0])
        self.assertIsNotNone(narrator.check_line("Worth asking: are pets allowed, in writing? A yes settles it.", question=True, words=narrator.DIM_WORDS["J1"])[0])
        self.assertIsNone(narrator.check_line("And now let us move along to the very next place on the list.", max_words=8)[0])

    def test_number_words_count_as_digits(self):
        self.assertEqual(narrator.words_to_digits("Fourteen minutes, seven hundred a week, the twenty-fourth of November, November first, one of the grounds, First up"),
                         "14 minutes, 700 a week, 24 November, November 1, one of the grounds, First up")
        self.assertEqual(narrator.words_to_digits("eight hundred and ninety a week, twenty-four minutes, ten days"), "890 a week, 24 minutes, 10 days")
        t, why = narrator.check_line("Fourteen minutes to Central Station by bus, and that checks out.", required={"14"}, allowed={"14"},
                                     status="supported", words=narrator.DIM_WORDS["G1"])
        self.assertEqual(why, "")
        self.assertTrue(t.startswith("Fourteen"))  # 说出来的还是模型的原话

    def test_rejects_lines_that_drift_from_the_fact(self):
        fact = ("Pets: I can only infer. The by-laws excerpt says nothing about animals, and the agent has not been asked. "
                "Under NSW rules a landlord can only refuse a pet on set grounds, so I lean yes, but nobody has confirmed it.")
        bad = "On pets: the photos show a bed and a couch, but with no inventory I'm only inferring they stay. Worth asking the agent in writing."
        self.assertIn("drifts", narrator.check_line(bad, fact=fact, status="inferred", words=narrator.DIM_WORDS["J1"], overlap=0.34)[1])
        good = "Pets I can only infer: the by-laws say nothing about animals and the agent hasn't been asked, though NSW rules only allow refusal on set grounds."
        self.assertEqual(narrator.check_line(good, fact=fact, status="inferred", words=narrator.DIM_WORDS["J1"], overlap=0.34)[1], "")
        self.assertIsNone(narrator.check_line("Rent's fine, it checks out.", must=[r"rent", r"fenwick"])[0])  # must 可以是一列
        fact2 = "Pets: supported. The by-laws allow pets with the owners corporation's written consent, not to be unreasonably withheld."
        self.assertIn("drops the source (owners corporation)", narrator.check_line(
            "Pets are allowed with the owner's written consent, and the by-laws say they can't refuse unreasonably.", fact=fact2, status="supported",
            words=narrator.DIM_WORDS["J1"], overlap=0.3)[1])
        self.assertEqual(narrator.check_line("Pets are fine here: the by-laws allow them once the owners corporation gives written consent, which can't be unreasonably withheld.",
                                             fact=fact2, status="supported", words=narrator.DIM_WORDS["J1"], overlap=0.3)[1], "")

    def test_bridges_fixed_when_variety_off(self):
        before = os.environ.get("VOICE_VARIETY")
        try:
            os.environ["VOICE_VARIETY"] = "0"
            self.assertEqual(phraser.bridge([], variety=True), "Got it.")
            self.assertEqual(phraser.bridge(["A1"], variety=True), "Thanks.")
            self.assertEqual(phraser.bridge([], interrupted=True, variety=True), "Okay.")
            os.environ["VOICE_VARIETY"] = "1"
            self.assertIn(phraser.bridge([], variety=True), phraser.BRIDGES["first"])
            self.assertEqual(phraser.bridge([], variety=False), "Got it.")
        finally:
            if before is None:
                os.environ.pop("VOICE_VARIETY", None)
            else:
                os.environ["VOICE_VARIETY"] = before


class SessionNarrationCase(unittest.TestCase):
    """整轮对话：模型（假的）写台词，规则审；回归模式（deterministic）不碰模型。"""

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
                           "VOICE_VARIETY": "0", "VOICE_TOUR": "full"})  # 模型写台词只在逐格讲法里用（简短播报是模板，见 test_voice_brief.py）
        P._env_loaded = False
        P.invalidate()
        self.tmp = tempfile.TemporaryDirectory()
        self._log = P.LOG
        P.LOG = Path(self.tmp.name) / "llm_log.jsonl"
        for k in narrator.STATS:
            narrator.STATS[k] = 0

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

    @staticmethod
    def tour_lines(events):
        return [e for e in events if e["type"] == "say" and (re.match(r"L\d", e.get("step") or "") or e.get("step") == "wrap")]

    @staticmethod
    def turns(texts, deterministic=False):
        s = policy.Session("t-narr")
        s.quick = True
        out = []
        for t in texts:
            out.append(list(s.handle_turn({"text": t, "deterministic": deterministic})))
        return s, out

    def test_model_lines_are_used_and_marked(self):
        self.assertTrue(narrator.enabled())
        s, (first, tour) = self.turns([NEED, ANSWER])
        steps = [e.get("step") for e in first if e["type"] == "say"]
        self.assertEqual(steps, ["bridge", "heard", "ask"])  # 复述先说，反问由模型写
        ask = next(e for e in first if e["type"] == "say" and e["step"] == "ask")
        self.assertEqual(ask.get("by"), "llm")
        self.assertTrue(ask["text"].startswith("Mock says:") and ask["text"].endswith("?"))
        self.assertEqual(next(e for e in first if e["type"] == "ask")["text"], ask["text"])
        says = self.tour_lines(tour)
        self.assertGreater(len(says), 10)
        self.assertTrue(all(e.get("by") == "llm" and e["text"].startswith("Mock says:") for e in says), [e["text"][:60] for e in says if e.get("by") != "llm"])
        self.assertNotIn("_nar", says[0])
        self.assertEqual(narrator.STATS["rejected"], 0)
        self.assertEqual(narrator.STATS["copied"], 0)

    def test_conversational_glue_only_on_the_model_path(self):
        s, (first, tour) = self.turns([NEED, ANSWER])
        self.assertEqual(next(e["text"] for e in first if e.get("step") == "heard"),
                         "So: two bedrooms, commuting to Central Station, with a cat, and air con in the bedroom.")
        steps = [e.get("step") for e in tour if e["type"] == "say"][:4]
        self.assertEqual(steps, ["bridge", "opening", "opening", "shortlist"])
        opening = [e["text"] for e in tour if e.get("step") == "opening"]
        self.assertEqual(opening, ["Okay, let me see what fits that near Central Station.", f"Checking {len(policy.SOURCES)} sources now."])  # 复述过了就不再复述
        self.assertEqual(next(e["text"] for e in tour if e.get("step") == "shortlist"),
                         phraser.found(len(s.ranked), min(3, len(s.ranked)), False))  # 10-26 起真房源进池子，过硬条件的不止三套
        q = list(s.handle_turn({"text": "Are the bills included?", "listing_id": s.current,
                                "interrupted": {"active": True, "spoken_idx": 3, "listing_id": next(e["listing"]["id"] for e in tour if e["type"] == "card"), "cut_sentence": "x"}}))
        self.assertEqual(next(e["text"] for e in q if e.get("step") == "back"), "Back to the first place.")  # VOICE_VARIETY=0 → 第一个
        # 一次说全需求（没有反问那轮）：开场先复述再"让我看看"。假模型的需求表里没有五项全的句子，这一句走规则解析
        os.environ["NEEDS_PARSER"] = "rules"
        s2 = policy.Session("t-glue2"); s2.quick = True
        ev = list(s2.handle_turn({"text": "Two bedrooms under 900 a week near Central Station, moving mid-November, and I have a cat."}))
        opening = [e["text"] for e in ev if e.get("step") == "opening"]
        self.assertTrue(opening[0].startswith("So: two bedrooms, under 900 a week"), opening)
        self.assertTrue(opening[1].startswith("Okay, let me see what fits that"), opening)
        self.assertTrue(opening[-1].endswith("sources now."), opening)
        self.assertTrue(all(t in phraser.all_glue() for t in [phraser.thinking(None, False), phraser.found(3, 3, False), phraser.back(2, False)]))

    def test_deterministic_turn_keeps_the_template_stream(self):
        s, (first, tour) = self.turns([NEED, ANSWER], deterministic=True)
        self.assertEqual([e.get("step") for e in first if e["type"] == "say"], ["bridge", "ask"])
        self.assertEqual([e["text"] for e in tour if e.get("step") == "opening"],
                         ["Two bedrooms, under 900 a week, commuting to Central Station, moving mid-November, with a cat, and air con in the bedroom.", f"Checking {len(policy.SOURCES)} sources now."])
        self.assertEqual(next(e["text"] for e in tour if e.get("step") == "shortlist"), phraser.shortlist(len(s.ranked), 3))
        self.assertTrue(all("by" not in e for e in first + tour if e["type"] == "say"))
        self.assertEqual(next(e["text"] for e in first if e["type"] == "say"), "Got it.")
        self.assertEqual(narrator.STATS["calls"], 0)

    def test_bad_numbers_fall_back_to_templates(self):
        s, (first, tour) = self.turns([NEED + " BADNUMBER", ANSWER])
        says = self.tour_lines(tour)
        self.assertTrue(says)
        self.assertTrue(all("by" not in e and not e["text"].startswith("Mock") for e in says))
        self.assertGreater(narrator.STATS["rejected"], 0)
        plain = policy.Session("t-plain"); plain.quick = True
        list(plain.handle_turn({"text": NEED, "deterministic": True}))
        ref = self.tour_lines(list(plain.handle_turn({"text": ANSWER, "deterministic": True})))
        self.assertEqual([e["text"] for e in says], [e["text"] for e in ref])  # 和纯模板逐字一样

    def test_non_json_and_timeout_fall_back_to_templates(self):
        s, (first, tour) = self.turns([NEED + " NOJSON", ANSWER])
        says = self.tour_lines(tour)
        self.assertTrue(says and all("by" not in e for e in says))
        self.assertGreater(narrator.STATS["failed"], 0)
        os.environ["NARRATION_LLM_TIMEOUT"] = "1"
        s, (first, tour) = self.turns([NEED + " SLOW", ANSWER])
        says = self.tour_lines(tour)
        self.assertTrue(says and all("by" not in e for e in says))
        self.assertGreater(narrator.STATS["timeouts"], 0)  # 假模型睡 3 s，1 s 预算到了就用模板

    def test_answer_and_agent_reply_lines(self):
        s, (first, tour) = self.turns([NEED, ANSWER])
        cut = self.tour_lines(tour)
        q = list(s.handle_turn({"text": "Is the first one close to the station?", "listing_id": s.current,
                                "interrupted": {"active": True, "spoken_idx": 3, "listing_id": s.current, "cut_sentence": cut[4]["text"]}}))
        steps = [e.get("step") for e in q if e["type"] == "say"][:2]
        self.assertEqual(steps, ["answer", "back"])  # 10-28 起答问用模板（先说结论再给依据，不等模型、不说内部词）
        ans = next(e for e in q if e.get("step") == "answer")
        self.assertIsNone(ans.get("by"))
        self.assertNotIn("close to the station?", ans["text"])  # 不许把租客的问题原样复述
        r = list(s.handle_turn({"text": "The agent said the split system is in the living room only."}))
        self.assertEqual([e.get("step") for e in r if e["type"] == "say"][:2], ["bridge", "change"])
        self.assertEqual(next(e for e in r if e.get("step") == "change").get("by"), "llm")
        self.assertEqual([e["type"] for e in r][-1], "done")


class SmartTurnCase(unittest.TestCase):
    def test_turn_strategy_follows_the_flag(self):
        try:
            import pipecat_app as app
        except SystemExit:
            self.skipTest("pipecat not importable here")
        os.environ["HOMETRUTH_ENV_FILE"] = ""
        os.environ["SMART_TURN"] = "1"
        cfg = app.Config.load(fake_speech=True)
        self.assertIn("smart-turn", app.turn_label(cfg))
        self.assertEqual([type(x).__name__ for x in app.turn_stop_strategies(cfg)], ["TurnAnalyzerUserTurnStopStrategy"])
        os.environ["SMART_TURN"] = "0"
        cfg = app.Config.load(fake_speech=True)
        self.assertIn("speech timeout", app.turn_label(cfg))
        self.assertEqual([type(x).__name__ for x in app.turn_stop_strategies(cfg)], ["SpeechTimeoutUserTurnStopStrategy"])
        os.environ.pop("SMART_TURN", None)


if __name__ == "__main__":
    unittest.main()
