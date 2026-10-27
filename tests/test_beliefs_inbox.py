#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考 Dot 的那层（10-26）：信念日志（beliefs.py，只追加、带版本、重放恢复）、收件箱（inbox.py，离开时到的中介回复）、读回复（replies.py 规则路 + 校验）、
policy.Session 把它们串起来：粘回复 → v1 → v2、同一条第二次不重做；回来时 "While you were away…" 在排名前折进来；导览中途 "Just in…"；
开场提还在等的问题；/api/hello 的视图；Forget me 全删。全部离线（规则解析、模板台词、三个目录指到临时文件夹）。
跑：.venv/bin/python -m unittest tests/test_beliefs_inbox.py -v"""
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
os.environ["HOMETRUTH_ENV_FILE"] = ""
os.environ["NEEDS_PARSER"] = "rules"
os.environ["NARRATION_LLM"] = "0"
os.environ["VOICE_VARIETY"] = "0"

import beliefs  # noqa: E402
import inbox  # noqa: E402
import memory  # noqa: E402
import policy  # noqa: E402
import replies  # noqa: E402

NEED = "Two bedrooms near Central, under 900 a week, I have a cat, moving mid November"
AGENT = "The Alder Lane agent said pets are fine as long as we clean the carpets when we leave."
HARROW = "L-0001"  # 12 Alder Lane（10-26 起真房源进了池子，Harrow 排不进前三：它有两个冲突，本就该靠后）
RID = "r-test-beliefs-0001"


_TOUR = os.environ.get("VOICE_TOUR")


def setUpModule():  # 逐格讲法（简短播报见 test_voice_brief.py）；开跑时设、跑完放回，不串到别的测试模块
    os.environ["VOICE_TOUR"] = "full"


def tearDownModule():
    if _TOUR is None:
        os.environ.pop("VOICE_TOUR", None)
    else:
        os.environ["VOICE_TOUR"] = _TOUR


class TmpDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._dirs = (memory.DIR, inbox.DIR, beliefs.DIR)
        memory.DIR, inbox.DIR, beliefs.DIR = root / "memory", root / "inbox", root / "beliefs"

    def tearDown(self):
        memory.DIR, inbox.DIR, beliefs.DIR = self._dirs
        self.tmp.cleanup()


class BeliefsModule(TmpDirs):
    def test_versions_dedupe_replay_forget(self):
        kw = dict(listing_id=HARROW, street="12 Alder Lane", dim="J1", label="Pets", source="agent_reply")
        row = beliefs.record("r-test-x", old="inferred", new="supported", text=AGENT, override={"status": "supported", "why": "w", "evidence": []}, **kw)
        self.assertEqual((row["from_version"], row["version"]), (1, 2))
        self.assertIsNone(beliefs.record("r-test-x", old="inferred", new="supported", text=AGENT, **kw), "same reply twice = one row")
        row2 = beliefs.record("r-test-x", old="supported", new="conflict", text="Actually, no pets after all.", override={"status": "conflict", "why": "", "evidence": []}, **kw)
        self.assertEqual((row2["from_version"], row2["version"]), (2, 3))
        self.assertEqual(beliefs.overrides("r-test-x")[HARROW]["J1"]["status"], "conflict", "replay = the latest flip wins")
        view = beliefs.view("r-test-x")
        self.assertEqual(view["flips"], 2)
        self.assertEqual(view["recent"][0]["version"], 3, "newest first")
        self.assertTrue(beliefs.forget("r-test-x"))
        self.assertEqual(beliefs.load("r-test-x"), [])

    def test_dirty_owner_is_ignored(self):
        self.assertIsNone(beliefs.record("../etc", listing_id=HARROW, street="s", dim="J1", label="Pets", old="a", new="b", source="x", text="t"))
        self.assertEqual(beliefs.load("../etc"), [])
        self.assertEqual(beliefs.versions(None), {})


class InboxModule(TmpDirs):
    def test_add_unread_mark_read(self):
        row = inbox.add(RID, HARROW, AGENT, "email")
        self.assertTrue(row["event_id"].startswith("in-"))
        self.assertEqual(inbox.add(RID, HARROW, AGENT, "email")["event_id"], row["event_id"], "same unread text is not queued twice")
        self.assertEqual(len(inbox.unread(RID)), 1)
        self.assertEqual(inbox.mark_read(RID, [row["event_id"]]), 1)
        self.assertEqual(inbox.unread(RID), [])
        self.assertEqual(inbox.view(RID)["unread"], 0)
        self.assertIsNone(inbox.add("bad id!", HARROW, AGENT))
        self.assertIsNone(inbox.add(RID, "", AGENT))


class RepliesModule(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(replies.read_rules("pets are fine, the owner said")["dim"], "J1")
        self.assertEqual(replies.read_rules("The split is in the living room only")["status"], "conflict")
        self.assertIsNone(replies.read_rules("The stove is gas."))

    def test_llm_answer_is_validated(self):
        text = "The stove is gas, sorry, not induction."
        ok, _ = replies.validate({"dim": "c3", "status": "conflict", "quote": "the stove is gas", "why": "Gas, not induction."}, text)
        self.assertEqual((ok["dim"], ok["status"], ok["quote"]), ("C3", "conflict", "the stove is gas"))
        self.assertIsNone(replies.validate({"dim": "C3", "status": "conflict", "quote": "it is electric"}, text)[0], "quote must be in the reply")
        self.assertIsNone(replies.validate({"dim": "C3", "status": "maybe"}, text)[0])
        self.assertIsNone(replies.validate({"dim": "C3", "status": "conflict", "why": "Installed in 2019."}, text)[0], "no new numbers")
        self.assertIsNone(replies.validate({"dim": None}, text)[0])
        self.assertIsNone(replies.validate({"dim": "H1", "status": "supported"}, text)[0], "legal disclosures are never flipped by an agent's reply")
        self.assertFalse(replies.ready(), "NEEDS_PARSER=rules keeps the tests offline")


class SessionReplies(TmpDirs):
    @staticmethod
    def tour(s: policy.Session, text: str = NEED):
        return list(s.handle_turn({"text": text, "renter": RID, "deterministic": True}))

    @staticmethod
    def cell(events, listing_id: str, dim: str):
        card = [c for c in events if c["type"] == "card" and c["listing"]["id"] == listing_id][-1]
        return next(c for c in card["listing"]["cells"] if c["dim"] == dim)

    def test_pasted_reply_records_a_version_and_is_not_applied_twice(self):
        s = policy.Session("t-b1")
        self.tour(s)
        ev = list(s.handle_turn({"text": AGENT, "listing_id": HARROW, "deterministic": True}))
        ch = next(e for e in ev if e["type"] == "change")
        self.assertEqual((ch["from_version"], ch["version"], ch["source"], ch["reader"]), (1, 2, "agent_reply", "rules"))
        self.assertTrue(ch["event_id"])
        self.assertEqual(len(beliefs.load(RID)), 1, "the belief log is kept under the renter, not the session")
        again = list(s.handle_turn({"text": AGENT, "listing_id": HARROW, "deterministic": True}))
        self.assertFalse([e for e in again if e["type"] == "change"])
        self.assertIn("already have that reply noted", " ".join(e["text"] for e in again if e["type"] == "say"))
        self.assertEqual(len(beliefs.load(RID)), 1)

    def test_beliefs_survive_into_the_next_visit(self):
        s = policy.Session("t-b2")
        self.tour(s)
        list(s.handle_turn({"text": AGENT, "listing_id": HARROW, "deterministic": True}))
        s2 = policy.Session("t-b3")
        s2.attach_renter(RID)
        self.assertEqual(s2.overrides[HARROW]["J1"]["status"], "supported", "replayed from beliefs.py")
        tour2 = list(s2.handle_turn({"text": "Same again", "renter": RID, "deterministic": True}))
        self.assertEqual(self.cell(tour2, HARROW, "J1")["status"], "supported")
        self.assertFalse([e for e in tour2 if e["type"] == "change"], "nothing new arrived, so nothing to announce")

    def test_reply_that_arrived_while_away_is_folded_in_before_ranking(self):
        self.tour(policy.Session("t-b4"))  # first visit: memory + open loops
        self.assertTrue(memory.load(RID)["open"])
        inbox.add(RID, HARROW, AGENT, "email")
        s2 = policy.Session("t-b5")
        s2.attach_renter(RID)
        ask = next(e for e in s2.welcome() if e["type"] == "ask")
        self.assertIn("While you were away, the agent for 12 Alder Lane replied.", ask["text"])
        ev = list(s2.handle_turn({"text": "Same again", "renter": RID, "deterministic": True}))
        types = [e["type"] for e in ev]
        ch = next(e for e in ev if e["type"] == "change")
        self.assertEqual((ch["source"], ch["channel"], ch["version"]), ("inbox", "email", 2))
        self.assertLess(types.index("change"), types.index("card"), "announced before the cards, so the cards already carry it")
        away = next(e for e in ev if e.get("step") == "away")
        self.assertRegex(away["text"], r"^By email, the agent for 12 Alder Lane says pets is now confirmed; I've folded that in before ranking\.$")
        self.assertEqual(self.cell(ev, HARROW, "J1")["status"], "supported")
        self.assertEqual(inbox.unread(RID), [], "read once, never again")
        self.assertEqual(types.count("done"), 1)
        self.assertEqual(ev[-1]["type"], "done")

    def test_reply_that_arrives_mid_tour_is_just_in(self):
        s = policy.Session("t-b6")
        self.tour(s)
        inbox.add(RID, HARROW, AGENT, "sms")
        ev = list(s.handle_turn({"text": "Is the Harrow place near a station?", "deterministic": True}))
        ch = next(e for e in ev if e["type"] == "change")
        self.assertEqual(ch["source"], "inbox_live")
        say = next(e for e in ev if e.get("step") == "away")
        self.assertRegex(say["text"], r"^Just in, by text: the agent for 12 Alder Lane says pets is now confirmed\.")
        self.assertIn("card_update", [e["type"] for e in ev])
        self.assertEqual(inbox.unread(RID), [])
        self.assertEqual([e["type"] for e in ev].count("done"), 1)

    def test_open_loops_are_mentioned_when_nothing_arrived(self):
        self.tour(policy.Session("t-b7"))
        s2 = policy.Session("t-b8")
        s2.attach_renter(RID)
        ask = next(e for e in s2.welcome() if e["type"] == "ask")
        self.assertRegex(ask["text"], r"You were still waiting on the agent about \w+ at \d+ \w+ \w+")

    def test_hello_view_and_forget_everything(self):
        self.tour(policy.Session("t-b9"))
        inbox.add(RID, HARROW, AGENT, "email")
        v = policy.hello_view(RID)
        self.assertEqual(v["away"]["unread"], 1)
        self.assertEqual(v["away"]["items"][0]["street"], "12 Alder Lane")
        self.assertTrue(v["open"])
        self.assertEqual(v["beliefs"]["flips"], 0)
        self.assertIsNone(policy.hello_view("nobody-here"))
        policy.forget_renter(RID)
        self.assertIsNone(policy.hello_view(RID))
        self.assertEqual(inbox.unread(RID), [])
        self.assertEqual(beliefs.load(RID), [])

    def test_street_word(self):
        self.assertEqual(policy.street_word("2 Harrow Crescent"), "harrow")
        self.assertEqual(policy.street_word("12 Alder Lane"), "alder")
        self.assertEqual(policy.street_word("Unit 3/12 Alder Lane"), "alder")


if __name__ == "__main__":
    unittest.main()
