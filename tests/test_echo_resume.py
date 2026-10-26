# -*- coding: utf-8 -*-
"""误触发的打断（自己的回声、噪声）之后不能卡住：开查前被切断就重问 / 重新开查；机器说话时它自己的回声不算开口。"""
import os
import sys
import unittest
from unittest.mock import AsyncMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "voice"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import policy  # noqa: E402


def full_profile():
    p = policy.new_profile()
    p.update(budget=900, bedrooms=2, anchor="Central Station",
             move_in={"month": 11, "day": 15, "text": "mid-November"},
             pets={"has": True, "kind": "cat", "text": "a cat"})
    return p


def types(events):
    return [e["type"] for e in events]


class ResumeBeforePlan(unittest.TestCase):
    def session(self):
        s = policy.Session("t-echo")
        s.deterministic = True
        return s

    def test_cut_during_opening_reruns_the_search(self):
        s = self.session()
        s.profile = full_profile()
        s.request_text = "two bedrooms near Central, under 900, mid November, I have a cat"
        ev = list(s.resume_before_plan("Let me make sure I've got it: two bedrooms."))
        self.assertIn("source", types(ev))
        self.assertIn("card", types(ev))
        self.assertEqual(ev[-1]["type"], "done")
        self.assertTrue(s.plan, "the tour must be built again")
        self.assertEqual(types(ev).count("done"), 1)

    def test_cut_during_a_question_asks_it_again(self):
        s = self.session()
        s.pending = ["A1", "A4"]
        ev = list(s.resume_before_plan("Let me make sure I've got it: two bedrooms."))
        self.assertEqual(types(ev), ["ask", "say", "done"])
        self.assertEqual(ev[0]["fields"], ["A1", "A4"])
        self.assertEqual(ev[1]["step"], "repeat")
        self.assertTrue(ev[1].get("expects_answer"))

    def test_cut_during_welcome_question_repeats_it(self):
        s = self.session()
        s.memory = {"summary": "two bedrooms, under 900 a week"}
        s.profile = full_profile()
        s.awaiting = "welcome"
        ev = list(s.resume_before_plan("Welcome back. Same again?"))
        self.assertEqual(types(ev), ["ask", "say", "done"])
        self.assertEqual(ev[0]["fields"], [])
        self.assertEqual(ev[1]["text"], "Welcome back. Same again?")
        self.assertFalse(s.plan, "a welcome question must not start the search on its own")

    def test_answering_clears_awaiting(self):
        s = self.session()
        s.memory = {"summary": "two bedrooms"}
        s.awaiting = "welcome"
        list(s.handle_turn({"text": "Same again", "deterministic": True}))
        self.assertIsNone(s.awaiting)

    def test_nothing_said_yet_only_repeats_the_cut_sentence(self):
        s = self.session()
        self.assertEqual(types(list(s.resume_before_plan("Hello there."))), ["say", "done"])
        self.assertEqual(types(list(s.resume_before_plan(None))), ["done"])


class EchoDetection(unittest.TestCase):
    def setUp(self):
        try:
            import pipecat_app  # noqa: F401
        except Exception as e:  # pragma: no cover - pipecat not installed
            self.skipTest(f"pipecat app not importable: {e}")
        self.app = sys.modules["pipecat_app"]

    def test_echo_like_needs_two_words_and_overlap(self):
        said = "Let me make sure I've got it: two bedrooms, under 900 a week."
        self.assertTrue(self.app.echo_like("Let me", said))
        self.assertTrue(self.app.echo_like("let me make", said, ""))
        self.assertFalse(self.app.echo_like("Let", said))
        self.assertFalse(self.app.echo_like("wait, stop", said))
        self.assertFalse(self.app.is_echo("Let me", said), "the commit-stage check still wants three words")

    def test_strategy_ignores_own_echo_while_speaking(self):
        from pipecat.frames.frames import InterimTranscriptionFrame
        from pipecat.turns.types import ProcessFrameResult

        async def run():
            strategy = self.app.EchoAwareUserTurnStartStrategy(
                min_words=2, said=lambda: ("Let me make sure I've got it: two bedrooms.", "Got it."))
            strategy.trigger_user_turn_started = AsyncMock()
            strategy.trigger_reset_aggregation = AsyncMock()
            strategy._bot_speaking = True
            frame = lambda t: InterimTranscriptionFrame(text=t, user_id="u", timestamp="0")
            echo = await strategy._handle_transcription(frame("Let me make"))
            short = await strategy._handle_transcription(frame("Wait"))
            real = await strategy._handle_transcription(frame("wait stop"))
            strategy._bot_speaking = False
            silent = await strategy._handle_transcription(frame("Hi"))
            return echo, short, real, silent, strategy.trigger_user_turn_started.await_count

        import asyncio
        echo, short, real, silent, starts = asyncio.run(run())
        self.assertEqual(echo, ProcessFrameResult.CONTINUE)
        self.assertEqual(short, ProcessFrameResult.CONTINUE)
        self.assertEqual(real, ProcessFrameResult.STOP)
        self.assertEqual(silent, ProcessFrameResult.STOP, "when the bot is silent one word is enough")
        self.assertEqual(starts, 2)


if __name__ == "__main__":
    unittest.main()
