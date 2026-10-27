"""10-28（docs/12）：简短播报和真人插话。每套房三句、不说内部词；插话按意思办（wait + 问题 = 答问题、"next one cheaper?" = 答、
带问号的改预算 = 改需求、too far = 划掉、sorry? = 重说、short version = 只说标题、比较、列问题、押金）；补条件不从头念。"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HOMETRUTH_ENV_FILE"] = ""
os.environ["NEEDS_PARSER"] = "rules"
os.environ["NARRATION_LLM"] = "0"
os.environ["VOICE_VARIETY"] = "0"
os.environ["HOMETRUTH_ZETARIS"] = "0"
sys.path.insert(0, str(ROOT / "src" / "voice"))
import memory  # noqa: E402
import policy  # noqa: E402

NEED = "Two bedrooms near UNSW, under 900 a week, moving mid-November. I've got a cat, and I want air con in the bedroom."
JARGON = re.compile(r"\b(supported|inferred|cells?|transit table|welcome)\b", re.I)


def says(events):
    return [e for e in events if e.get("type") == "say"]


class Base(unittest.TestCase):
    def setUp(self):
        self._tour = os.environ.get("VOICE_TOUR")
        os.environ["VOICE_TOUR"] = "brief"

    def tearDown(self):  # 放回去：别的测试模块（test_materials 等）固定用逐格讲法
        if self._tour is None:
            os.environ.pop("VOICE_TOUR", None)
        else:
            os.environ["VOICE_TOUR"] = self._tour

    def session(self, name="t-brief"):
        s = policy.Session(name)
        s.quick = True
        return s

    def turn(self, s, text, inter=None):
        body = {"text": text, "deterministic": True}
        if inter:
            body.update(interrupted=inter, listing_id=inter.get("listing_id"))
        return list(s.handle_turn(body))

    def cut_at(self, s, k):
        """租客在计划里第 k 句（带编号的导览句）播着的时候开口。"""
        n, last, cur = 0, None, None
        for ev in s.plan:
            if ev["type"] == "card":
                cur = ev["listing"]["id"]
            elif ev["type"] == "say" and ev.get("idx") is not None:
                if n == k:
                    return {"active": True, "spoken_idx": last, "listing_id": cur, "cut_sentence": ev["text"]}
                last = ev["idx"]
                n += 1
        raise AssertionError(f"plan has only {n} numbered lines")

    def tour(self, s=None):
        s = s or self.session()
        return s, self.turn(s, NEED)


class BriefTour(Base):
    def test_three_lines_per_place_and_a_beat_between(self):
        s, ev = self.tour()
        lines = says(ev)
        steps = [e["step"] for e in lines]
        self.assertEqual(steps[:3], ["bridge", "opening", "shortlist"])  # 不复述需求、不说 "let me see"
        self.assertEqual(steps[3], "L0")
        for i in range(3):
            self.assertLessEqual(sum(1 for x in steps if x == f"L{i}" or x.startswith(f"L{i}.")), 3)
        self.assertEqual(steps[-1], "wrap")
        self.assertEqual(sum(1 for e in ev if e["type"] == "beat"), 2)  # 套与套之间各停一下
        words = sum(len(e["text"].split()) for e in lines)
        self.assertLess(words, 160, words)  # 现在约 130 个词（≈ 60 秒）；改前 584–618 个
        self.assertLessEqual(max(len(e["text"].split()) for e in lines), 22)

    def test_plain_words_and_no_repeats(self):
        _, ev = self.tour()
        texts = [e["text"] for e in says(ev)]
        self.assertFalse([t for t in texts if JARGON.search(t)])
        self.assertEqual(len(texts), len(set(texts)), "no sentence said twice")
        self.assertIn("Same question for this agent: pets in writing.", texts)  # 第二次问同样的问题时说 same question

    def test_full_mode_still_available(self):
        os.environ["VOICE_TOUR"] = "full"
        s = self.session()
        ev = self.turn(s, NEED)
        self.assertTrue(any(e.get("step", "").endswith(".J1") for e in says(ev)))  # 逐格讲


class Interruptions(Base):
    def test_wait_plus_question_answers_instead_of_pausing(self):
        s, _ = self.tour()
        ev = self.turn(s, "Wait, does that one allow cats?", self.cut_at(s, 1))
        steps = [e["step"] for e in says(ev)]
        self.assertEqual(steps[0], "answer")
        self.assertNotIn("stop", steps)
        self.assertIn("Fenwick Street", says(ev)[0]["text"])
        self.assertEqual(steps[-1], "wrap")  # 答完接着讲到底

    def test_hang_on_per_week(self):
        s, _ = self.tour()
        ev = self.turn(s, "Hang on, is that per week?", self.cut_at(s, 0))
        self.assertRegex(says(ev)[0]["text"], r"890 a week")

    def test_next_one_cheaper_is_a_question(self):
        s, _ = self.tour()
        ev = self.turn(s, "Is the next one cheaper?", self.cut_at(s, 1))
        first = says(ev)[0]
        self.assertEqual(first["step"], "answer")
        self.assertRegex(first["text"], r"^Yes, Alder Lane is 760 a week, 130 less")

    def test_budget_change_phrased_as_a_question(self):
        s, _ = self.tour()
        ev = self.turn(s, "Actually, can we make it 800 max?", self.cut_at(s, 4))
        self.assertEqual(s.profile["budget"], 800)
        steps = [e["step"] for e in says(ev)]
        for bad in ("opening", "shortlist", "heard"):
            self.assertNotIn(bad, steps)  # 不复述、不报来源、不从头念
        self.assertIn("update", steps)
        self.assertIn("diff", steps)
        self.assertTrue(all(it["listing"]["rent"] <= 800 for it in s.ranked[:3]))

    def test_added_need_does_not_retell_what_was_heard(self):
        s, _ = self.tour()
        first = next(e["listing"]["id"] for e in s.plan if e["type"] == "card")
        ev = self.turn(s, "Oh, and it needs to be furnished.", self.cut_at(s, 4))  # 第一套已经听完，第二套讲到一半
        heard_intro = [e for e in says(ev) if e["step"] == "L0" and first in e["text"]]
        self.assertEqual(says(ev)[1]["text"], "Furnished, noted.")
        self.assertFalse(heard_intro or any("Fenwick" in e["text"] and re.fullmatch(r"L\d", e["step"]) for e in says(ev)), "already heard")
        self.assertTrue(any(e["step"] == "diff" and e["text"].startswith("On furniture") for e in says(ev)))
        self.assertLess(sum(len(e["text"].split()) for e in says(ev)), 110)

    def test_too_far_drops_the_place(self):
        s, _ = self.tour()
        inter = self.cut_at(s, 1)
        ev = self.turn(s, "That one's too far for me.", inter)
        self.assertEqual(says(ev)[0]["text"], "Okay, Fenwick Street is off the list.")
        self.assertIn(inter["listing_id"], s.rejected)
        self.assertNotIn(inter["listing_id"], [it["listing"]["id"] for it in s.ranked])
        self.assertTrue(any(e["step"] == "diff" and "comes in" in e["text"] for e in says(ev)))

    def test_sorry_repeats_the_last_line(self):
        s, _ = self.tour()
        inter = self.cut_at(s, 2)
        ev = self.turn(s, "Sorry, what was that?", inter)
        last_full = next(e["text"] for e in s.plan if e["type"] == "say" and e.get("idx") == inter["spoken_idx"])
        self.assertEqual(says(ev)[0]["text"], last_full)
        self.assertEqual(says(ev)[1]["text"], inter["cut_sentence"])

    def test_short_version_gives_headlines(self):
        s, _ = self.tour()
        ev = self.turn(s, "Can you just give me the short version?", self.cut_at(s, 2))
        lines = says(ev)
        self.assertEqual(lines[0]["text"], "Sure, just the headlines.")
        self.assertEqual([e["step"] for e in lines[1:]], ["L1", "L2", "wrap"])

    def test_compare_two_places(self):
        s, _ = self.tour()
        ev = self.turn(s, "What's the difference between the first and the second one?", self.cut_at(s, 4))
        a = " ".join(e["text"] for e in says(ev) if e["step"] == "answer")  # 一句一个 say（policy.sentences）
        self.assertIn("Fenwick Street", a)
        self.assertIn("130 cheaper", a)
        self.assertTrue(all(len(e["text"].split()) <= 24 for e in says(ev)))

    def test_go_back_to_the_first(self):
        s, _ = self.tour()
        ev = self.turn(s, "Go back to the first one.", self.cut_at(s, 4))
        steps = [e["step"] for e in says(ev)]
        self.assertEqual(steps[:4], ["L0", "L0.brief", "L0.question", "back"])

    def test_bond_and_questions_list(self):
        s, _ = self.tour()
        ev = self.turn(s, "How much is the bond?", self.cut_at(s, 1))
        self.assertEqual(says(ev)[0]["text"], "The listing doesn't say.")
        self.assertIn("four weeks' rent, so at most 3560", " ".join(e["text"] for e in says(ev) if e["step"] == "answer"))
        q = self.turn(s, "Yes please, draft the questions.")
        ql = next(e for e in q if e["type"] == "questions")
        self.assertEqual(len(ql["items"]), 3)
        self.assertTrue(ql["legal"])
        self.assertIn("the bond", " ".join(e["text"] for e in says(q) if e["step"] == "questions"))
        self.assertEqual(says(q)[0]["text"], "Here's what to ask.")  # 清单一句一个 say，句间能打断

    def test_tell_me_more_walks_every_line(self):
        s, _ = self.tour()
        ev = self.turn(s, "Tell me more about this one.", self.cut_at(s, 3))
        steps = [e["step"] for e in says(ev)]
        self.assertIn("L1.J1", steps)  # 逐格
        self.assertEqual(steps[-1], "wrap")
        self.assertEqual(steps.count("L1"), 1)

    def test_correction_that_matches_is_confirmed(self):
        s, _ = self.tour()
        ev = self.turn(s, "No, I said two bedrooms, not three.", self.cut_at(s, 0))
        self.assertEqual(says(ev)[1]["text"], "Yes, two bedrooms. That's what I'm searching for.")

    def test_after_the_tour(self):
        s, _ = self.tour()
        self.assertEqual([e["step"] for e in says(self.turn(s, "continue"))], ["resume"])  # 不再从头查一遍
        c = says(self.turn(s, "Compare them on the commute."))[0]["text"]
        self.assertTrue(c.startswith("Closest first: Alder Lane"), c)
        d = [e["step"] for e in says(self.turn(s, "the second one"))]
        self.assertIn("L1.A1", d)  # 收尾问 "details on one?" 之后只说是哪套 = 要细节

    def test_stop_and_next_still_work(self):
        s, _ = self.tour()
        self.assertEqual([e["step"] for e in says(self.turn(s, "Stop.", self.cut_at(s, 1)))], ["stop"])
        s, _ = self.tour()
        ev = self.turn(s, "next", self.cut_at(s, 1))
        self.assertEqual([e["step"] for e in says(ev)][:2], ["next", "L1"])

    def test_stale_line_number_restarts_the_new_plan(self):
        s, _ = self.tour()
        self.turn(s, "Oh, and it needs to be furnished.", self.cut_at(s, 4))
        old_idx = 2  # 客户端还没听完新计划的第一句，报回来的是旧计划的编号
        s.plan.insert(0, {"type": "say", "idx": None, "text": "x", "step": "pad"})  # 新计划里没有这个编号
        s._rewind_to(old_idx)
        self.assertEqual(s.pos, min(s.emit_from, len(s.plan)))


class Intents(unittest.TestCase):
    CASES = {
        "Oh, and it needs to be furnished.": "update", "Actually, can we make it 800 max?": "update", "What about three bedrooms?": "update",
        "Could you also look for furnished ones?": "update", "Wait, does that one allow cats?": "question", "Hang on, is that per week?": "question",
        "Is the next one cheaper?": "question", "Does it also have air con?": "question", "Is it furnished?": "question",
        "That one's too far for me.": "reject", "Skip this one, it's too far": "reject", "Sorry, what was that?": "repeat", "Sorry?": "repeat",
        "Can you just give me the short version?": "shorter", "What's the difference between the first and the second one?": "compare",
        "Compare them on the commute.": "compare", "Which one is cheapest?": "compare", "Which one would you pick?": "rank",
        "Go back to the first one.": "jump", "Tell me about the third one": "jump", "Tell me more about the second one": "detail",
        "Yes please, draft the questions.": "questions", "Stop.": "stop", "Wait.": "stop", "Next one please": "next", "skip": "next",
        "Okay, carry on": "resume", "yeah": "resume", "No thanks": "decline", "The agent said pets are fine": "agent_reply",
        "No, I said two bedrooms, not three.": "update",
    }

    def test_real_phrasings(self):
        wrong = {t: (policy.intent(t), k) for t, k in self.CASES.items() if policy.intent(t) != k}
        self.assertFalse(wrong)

    def test_places_and_people(self):
        f = policy.rules_fields
        self.assertEqual(f("near you and SW")["anchor"], "UNSW")
        self.assertEqual(f("it's just me")["bedrooms"], 1)
        self.assertEqual(f("can we make it 800 max?")["budget"], 800)


class VaguePlace(Base):
    def test_beach_gets_a_concrete_question(self):
        s = self.session()
        ev = self.turn(s, "Somewhere cheap near the beach, it's just me, under 600, no pets, moving mid-November.")
        ask = next(e for e in ev if e["type"] == "ask")
        self.assertIn("UNSW, the CBD or Central Station", ask["text"])


class DontKnowAndWording(Base):
    def test_dont_know_when_is_not_asked_again(self):  # 模拟顾客 P18：说了不知道哪天搬，下一轮不再追问
        s = self.session("t-dontknow")
        a = self.turn(s, "Two bedrooms near UNSW, I've got a cat.")
        self.assertTrue(any(e["type"] == "ask" for e in a))
        b = self.turn(s, "Not sure, maybe 900? I don't know when yet.")
        self.assertFalse(any(e["type"] == "ask" for e in b), [e["text"] for e in says(b)])
        self.assertTrue(any("any move-in date" in e["text"] for e in says(b)))
        self.assertEqual(sum(e["type"] == "card" for e in b), 3)

    def test_third_same_question_and_viewing_wording(self):
        import phraser
        self.assertEqual(phraser.brief_question("J1", {}, {}, {}, 1), "Same question for this agent: pets in writing.")
        self.assertEqual(phraser.brief_question("J1", {}, {}, {}, 2), "Same pets question here too.")
        self.assertEqual(phraser.brief_viewing("D1", {"next": {"hint": "benchtops, tiles, carpet"}}), "At the viewing, check the benchtops, tiles and carpet.")

    def test_need_added_mid_place_does_not_reread_its_opening(self):  # 模拟顾客 P03：第一套的开头刚听过，补条件后换成一句短的
        s, _ = self.tour()
        ev = self.turn(s, "Oh, and it needs to be furnished.", self.cut_at(s, 1))
        l0 = next(e["text"] for e in says(ev) if e["step"] == "L0")
        self.assertEqual(l0, "Fenwick Street is still the top pick.")

    def test_lower_budget_never_says_a_line_twice(self):  # 模拟顾客 P04：三套都要问宠物，以前 "Same question…" 原样说两遍
        s, _ = self.tour()
        ev = self.turn(s, "Actually, can we make it 800 max?", self.cut_at(s, 4))
        texts = [e["text"] for e in says(ev)]
        self.assertEqual(len(texts), len(set(texts)), texts)


class RememberRejected(Base):
    def test_rejected_place_stays_off_next_visit(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = memory.DIR
            memory.DIR = Path(tmp)
            try:
                s = self.session("t-rej-1")
                s.attach_renter("r-test-rejected")
                self.turn(s, NEED)
                inter = self.cut_at(s, 1)
                self.turn(s, "Not that one.", inter)
                s2 = self.session("t-rej-2")
                s2.attach_renter("r-test-rejected")
                self.assertIn(inter["listing_id"], s2.rejected)
            finally:
                memory.DIR = saved


if __name__ == "__main__":
    unittest.main()
