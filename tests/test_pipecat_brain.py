#!/usr/bin/env python3
"""src/voice/pipecat_app.py 里"脑"的打断判断单测：不起管线、不连任何服务，直接喂它"听到了什么"，看它交给 policy 的是什么。
浏览器里只能打字，麦克风那条路（嗯、回声、噪声、真打断）靠这里测。
跑：.venv/bin/python -m unittest tests/test_pipecat_brain.py -v"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "voice"))
os.environ["HOMETRUTH_ENV_FILE"] = ""  # 不读真 .env
os.environ["NEEDS_PARSER"] = "rules"  # 不碰模型
os.environ["NARRATION_LLM"] = "0"  # 台词用模板
os.environ["VOICE_VARIETY"] = "0"  # 过渡句固定取第一个，句子才能逐字比

import pipecat_app as app  # noqa: E402
import policy  # noqa: E402

NEED = "Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom."


def toured_session() -> policy.Session:
    s = policy.Session("t-brain")
    s.quick = True  # 来源动画别等太久
    list(s.handle_turn({"text": NEED}))
    list(s.handle_turn({"text": "Under 900, mid-November."}))
    return s


class BrainCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.s = await asyncio.to_thread(toured_session)  # policy 开查时会 sleep，别卡事件循环
        self.b = app.Brain(self.s, "test")
        self.b.COMMIT_GRACE_S = self.b.LATE_FINAL_S = 0
        self.runs, self.pushed, self.broadcasts = [], [], 0

        async def fake_run(make_events, text, source, *, interrupted, kind="turn"):
            self.runs.append({"events": list(make_events()), "text": text, "source": source, "kind": kind, "interrupted": interrupted})

        async def fake_broadcast():
            self.broadcasts += 1

        async def fake_push(frame, direction=None):
            self.pushed.append(frame)

        self.b._run, self.b.broadcast_interruption, self.b.push_frame = fake_run, fake_broadcast, fake_push
        says = [e for e in self.s.plan if e["type"] == "say"]
        self.cut = says[3]
        # 模拟导览进行中：第 3 句说完、第 4 句说到一半，还有句子排着
        self.b.spoken_idx, self.b.current_say, self.b.queued, self.b.bot_speaking = says[2]["idx"], self.cut["text"], 5, True
        self.b.listing_id = next(e["listing"]["id"] for e in self.s.plan if e["type"] == "card")

    async def voice(self, *finals: str):
        """人声打断：InterruptionFrame 到 → 播音停 → 这段话的最终转写 → 提交。"""
        self.b._stop_current()
        self.b.bot_speaking = False
        self.b.heard = list(finals)
        await self.b._commit()

    def says(self, run):
        return [e["text"] for e in run["events"] if e["type"] == "say"]

    async def test_interruption_context_matches_what_was_played(self):
        self.b._stop_current()
        self.assertEqual(self.b.ictx, {"active": True, "spoken_idx": self.cut["idx"] - 1, "listing_id": self.b.listing_id,
                                       "cut_sentence": self.cut["text"]})
        self.assertEqual((self.b.queued, self.b.current_say), (0, None))

    async def test_filler_noise_and_echo_resume_silently_from_the_cut_sentence(self):
        for heard in (["yeah"], [], [self.cut["text"][:60]]):
            await self.asyncSetUp()
            await self.voice(*heard)
            run = self.runs[-1]
            self.assertEqual(run["kind"], "resume", heard)
            self.assertEqual(self.says(run)[0], self.cut["text"], heard)  # 不先说 "Sure."，直接重播被切断的那句

    async def test_real_question_goes_to_policy_with_the_context(self):
        await self.voice("Is the first one close to the station?")
        run = self.runs[-1]
        self.assertEqual((run["kind"], run["source"], run["interrupted"]), ("turn", "voice", True))
        self.assertEqual(run["events"][0], {"type": "state", "phase": "thinking", "label": "One sec"})
        self.assertIn(self.cut["text"], self.says(run))  # 答完回到被切断的那句
        self.assertEqual(self.broadcasts, 0)  # 已经停了，不用再广播打断

    async def test_typing_while_speaking_interrupts_first(self):
        await self.b._start_turn("skip", "text")
        run = self.runs[-1]
        self.assertEqual(self.broadcasts, 1)
        self.assertEqual((run["source"], run["interrupted"]), ("text", True))
        self.assertEqual(self.says(run)[0], "Sure, next one.")

    async def test_after_stop_noise_does_not_resume_but_continue_does(self):
        await self.b._pause()
        self.assertEqual(self.broadcasts, 1)
        self.assertEqual(self.pushed[-1].message["data"], {"type": "state", "phase": "idle", "label": "Paused"})
        self.b.heard = []
        await self.b._commit()  # 噪声
        self.assertEqual(self.runs, [])
        self.assertTrue(self.b.ictx["paused"])
        self.b.heard = ["continue"]
        await self.b._commit()
        run = self.runs[-1]
        self.assertEqual(self.says(run)[:2], ["Sure.", self.cut["text"]])

    async def test_idle_echo_is_ignored_and_idle_speech_is_a_normal_turn(self):
        self.b.queued, self.b.bot_speaking, self.b.current_say, self.b.last_said = 0, False, None, self.cut["text"]
        self.b.heard = [self.cut["text"]]
        await self.b._commit()
        self.assertEqual(self.runs, [])
        self.b.heard = ["Is the first one close to the station?"]
        await self.b._commit()
        self.assertEqual((self.runs[-1]["kind"], self.runs[-1]["interrupted"]), ("turn", False))

    async def test_resume_before_the_search_repeats_the_question(self):
        s = policy.Session("t-ask")
        list(s.handle_turn({"text": NEED}))
        b = app.Brain(s, "test")
        b.COMMIT_GRACE_S = b.LATE_FINAL_S = 0
        b._run = self.b._run
        q = "Two quick things before I search: what's your weekly budget, and when do you need to move in?"
        b.current_say, b.queued = q, 1
        b._stop_current()
        b.heard = ["mm"]
        await b._commit()
        self.assertEqual(self.says(self.runs[-1]), [q])


if __name__ == "__main__":
    unittest.main()
