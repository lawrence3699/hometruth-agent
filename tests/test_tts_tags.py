#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""8630 浏览器版的嘴（src/voice/tts.py）：ElevenLabs 时句首加情绪标签（和 8631 同一套 tone.py）、带 .env 的声音参数、按加了标签的文本缓存；
别的后端原句。对着假 ElevenLabs 服务器跑，不出网。
跑：.venv/bin/python -m unittest tests/test_tts_tags.py -v"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))

import eleven  # noqa: E402
import tts  # noqa: E402
from mock_elevenlabs import Mock  # noqa: E402

KEYS = ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL", "ELEVENLABS_BASE_URL", "ELEVENLABS_TAGS", "ELEVENLABS_STABILITY",
        "ELEVENLABS_SIMILARITY", "TTS_BACKEND", "HOMETRUTH_ENV_FILE"]


class TtsTagsCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = Mock()
        cls.port = cls.mock.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in KEYS}
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update({"HOMETRUTH_ENV_FILE": "", "ELEVENLABS_BASE_URL": f"http://127.0.0.1:{self.port}", "ELEVENLABS_API_KEY": "mock-eleven-key",
                           "TTS_BACKEND": "elevenlabs", "ELEVENLABS_VOICE": "Sarah", "ELEVENLABS_STABILITY": "0.4"})
        self.tmp = tempfile.TemporaryDirectory()
        self._cache, tts.CACHE = tts.CACHE, Path(self.tmp.name)
        self._eleven_cache, eleven.CACHE = eleven.CACHE, Path(self.tmp.name) / "voices.json"
        eleven._MEM.clear()
        self.mock.bodies.clear()

    def tearDown(self):
        tts.CACHE, eleven.CACHE = self._cache, self._eleven_cache
        self.tmp.cleanup()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_tag_goes_in_front_only_for_tag_models(self):
        self.assertEqual(tts.speak_text("Welcome back. Last time it was two bedrooms.", "welcome"), "[warmly] Welcome back. Last time it was two bedrooms.")
        self.assertEqual(tts.speak_text("Pets: a conflict. The listing says no pets.", "L0.J1", "conflict"), "[concerned] Pets: a conflict. The listing says no pets.")
        self.assertEqual(tts.speak_text("Okay.", "bridge"), "Okay.")  # too short for a tag
        os.environ["ELEVENLABS_MODEL"] = "eleven_flash_v2_5"  # does not understand tags: none added
        self.assertEqual(tts.speak_text("Welcome back. Last time it was two bedrooms.", "welcome"), "Welcome back. Last time it was two bedrooms.")
        os.environ["TTS_BACKEND"] = "say"
        self.assertEqual(tts.speak_text("Welcome back. Last time it was two bedrooms.", "welcome"), "Welcome back. Last time it was two bedrooms.")

    def test_request_carries_tag_model_and_settings_and_is_cached_per_tag(self):
        data, ctype = tts.synthesize("Welcome back. Last time it was two bedrooms.", step="welcome")
        self.assertEqual(ctype, "audio/mpeg")
        self.assertTrue(data)
        body = self.mock.bodies[-1]
        self.assertEqual(body["text"], "[warmly] Welcome back. Last time it was two bedrooms.")
        self.assertEqual(body["model_id"], "eleven_v4_turbo")
        self.assertEqual(body["voice_settings"], {"stability": 0.4})
        n = len(self.mock.bodies)
        tts.synthesize("Welcome back. Last time it was two bedrooms.", step="welcome")
        self.assertEqual(len(self.mock.bodies), n)  # cached
        tts.synthesize("Welcome back. Last time it was two bedrooms.", step="answer")  # another tag → another request
        self.assertEqual(len(self.mock.bodies), n + 1)
        self.assertEqual(self.mock.bodies[-1]["text"], "[reassuring] Welcome back. Last time it was two bedrooms.")

    def test_voice_label_is_the_name_not_the_id(self):
        self.assertEqual(tts.voice_label(), "Sarah")
        self.assertNotEqual(tts.voice_name(), "Sarah")  # resolved to an id through the mock /v1/voices


if __name__ == "__main__":
    unittest.main()
