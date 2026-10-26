#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""嘴可切换（Magpie 默认 / ElevenLabs）：eleven.py 对着假服务器跑，pipecat_app 的配置、问题清单、描述和合成器选择。
跑：.venv/bin/python -m unittest tests/test_elevenlabs.py -v"""
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
from mock_elevenlabs import Mock  # noqa: E402

KEYS = ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE", "ELEVENLABS_MODEL", "ELEVENLABS_BASE_URL", "TTS_PROVIDER", "HOMETRUTH_ENV_FILE", "NVIDIA_API_KEY",
        "ELEVENLABS_TAGS", "ELEVENLABS_STABILITY", "ELEVENLABS_SIMILARITY", "ELEVENLABS_STYLE", "ELEVENLABS_SPEED", "ELEVENLABS_SPEAKER_BOOST"]


class ElevenCase(unittest.TestCase):
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
        os.environ.update({"HOMETRUTH_ENV_FILE": "", "ELEVENLABS_BASE_URL": f"http://127.0.0.1:{self.port}", "ELEVENLABS_API_KEY": "mock-eleven-key"})
        self.tmp = tempfile.TemporaryDirectory()
        self._cache = eleven.CACHE
        eleven.CACHE = Path(self.tmp.name) / "voices.json"
        eleven._MEM.clear()
        self.mock.calls.clear()
        self.mock.bodies.clear()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        eleven.CACHE = self._cache
        eleven._MEM.clear()
        self.tmp.cleanup()

    def test_voice_name_resolves_and_caches(self):
        key = eleven.api_key()
        self.assertEqual(eleven.voice_id("Charlie", key), "IKne3meq5aSn9XLyUdCD")
        self.assertEqual(eleven.voice_id("sarah", key), "EXAVITQu4vr4xnSDxMaL")  # 大小写不管
        self.assertEqual(eleven.voice_id("JBFqnCBsd6RMkjVDRZzb", key), "JBFqnCBsd6RMkjVDRZzb")  # id 原样
        self.assertTrue(eleven.CACHE.exists())
        gets = [p for m, p in self.mock.calls if m == "GET"]
        self.assertEqual(len(gets), 1, gets)  # 三次解析只查了一次网
        with self.assertRaises(eleven.ElevenError) as cm:
            eleven.voice_id("Nobody", key)
        self.assertIn("Charlie", str(cm.exception))  # 报错里列出能用的名字
        self.assertEqual(eleven.voice_id("Zz9AbCdEfGhIjKlMnOpQ", key), "Zz9AbCdEfGhIjKlMnOpQ")  # 长得像 id 又查不到：当 id 用
        self.assertEqual(eleven.short_name("Charlie - Deep, Confident, Energetic"), "Charlie")  # 账户里自带声音是长名

    def test_synth_returns_pcm_and_bad_key_is_clear(self):
        key = eleven.api_key()
        pcm = eleven.synth("Hello there.", "Charlie", key, sample_rate=22050)
        self.assertEqual(len(pcm), len("Hello there.") * 200 * 2)
        self.assertIn("output_format=pcm_22050", self.mock.calls[-1][1])
        self.assertNotIn("voice_settings", self.mock.bodies[-1])  # 没填参数就不发
        eleven.synth("[happy] Hi there.", "Charlie", key, "eleven_v4_turbo", voice_settings={"stability": 0.5})
        self.assertEqual(self.mock.bodies[-1], {"text": "[happy] Hi there.", "model_id": "eleven_v4_turbo", "voice_settings": {"stability": 0.5}})
        with self.assertRaises(eleven.ElevenError) as cm:
            eleven.synth("Hello", "Charlie", "wrong-key")
        self.assertIn("401", str(cm.exception))
        with self.assertRaises(eleven.ElevenError):
            eleven._request("/v1/voices", key="")
        self.assertEqual(eleven.subscription(key)["tier"], "free")
        self.assertEqual([m["model_id"] for m in eleven.list_models(key)], ["eleven_flash_v2_5", "eleven_multilingual_v2", "eleven_v4_turbo"])
        self.assertEqual(eleven.list_voices(key)[0]["labels"]["accent"], "Australian")

    def test_model_families_settings_and_tags(self):
        self.assertTrue(eleven.supports_tags("eleven_v4_turbo") and eleven.supports_tags("eleven_v3_conversational"))
        self.assertFalse(eleven.supports_tags("eleven_flash_v2_5") or eleven.supports_tags("eleven_multilingual_v2"))
        self.assertFalse(eleven.streams_over_websocket("eleven_v4_turbo"))  # v3 / v4 走 HTTP 流式
        self.assertTrue(eleven.streams_over_websocket("eleven_flash_v2_5"))
        self.assertFalse(eleven.accepts_context("eleven_v3_conversational"))
        self.assertTrue(eleven.accepts_context("eleven_v4_turbo"))
        self.assertEqual(eleven.model(), "eleven_v4_turbo")  # 默认模型
        self.assertTrue(eleven.tags_enabled())  # auto + v4 → 开
        self.assertFalse(eleven.tags_enabled("eleven_flash_v2_5"))
        os.environ["ELEVENLABS_TAGS"] = "0"
        self.assertFalse(eleven.tags_enabled("eleven_v4_turbo"))
        os.environ["ELEVENLABS_TAGS"] = "1"
        self.assertTrue(eleven.tags_enabled("eleven_flash_v2_5"))
        self.assertEqual(eleven.voice_settings_from_env(), {})
        os.environ.update({"ELEVENLABS_STABILITY": "0.5", "ELEVENLABS_SPEED": "1.1", "ELEVENLABS_SPEAKER_BOOST": "1"})
        self.assertEqual(eleven.voice_settings_from_env(), {"stability": 0.5, "speed": 1.1, "use_speaker_boost": True})
        os.environ["ELEVENLABS_STYLE"] = "2"
        with self.assertRaises(eleven.ElevenError) as cm:
            eleven.voice_settings_from_env()
        self.assertIn("ELEVENLABS_STYLE", str(cm.exception))
        os.environ["ELEVENLABS_STYLE"] = "abc"
        with self.assertRaises(eleven.ElevenError):
            eleven.voice_settings_from_env()

    def test_pipecat_config_switch(self):
        try:
            import pipecat_app as app
        except SystemExit:
            self.skipTest("pipecat not importable here")
        os.environ["TTS_PROVIDER"] = "magpie"
        cfg = app.Config.load()
        self.assertEqual(cfg.tts_provider, "magpie")
        self.assertIn("NVIDIA", app.tts_label(cfg))
        self.assertFalse([p for p in cfg.problems() if "ELEVENLABS" in p])

        os.environ["TTS_PROVIDER"] = "elevenlabs"
        os.environ.pop("ELEVENLABS_API_KEY", None)
        cfg = app.Config.load()
        self.assertTrue(any("ELEVENLABS_API_KEY" in p for p in cfg.problems()), cfg.problems())

        os.environ["ELEVENLABS_API_KEY"] = "mock-eleven-key"
        os.environ["ELEVENLABS_VOICE"] = "George"
        os.environ["ELEVENLABS_MODEL"] = "eleven_flash_v2_5"  # 老路：WebSocket 服务、不加标签
        cfg = app.Config.load()
        self.assertFalse(cfg.eleven_tags)
        self.assertFalse([p for p in cfg.problems() if "ELEVENLABS" in p], cfg.problems())
        self.assertIn("ElevenLabs", app.tts_label(cfg))
        self.assertIn("George", app.tts_label(cfg))
        self.assertEqual(cfg.describe()["tts"], app.tts_label(cfg))
        speaker = app.make_speaker(cfg)
        self.assertEqual(type(speaker).__name__, "ElevenLabsTTSService")
        self.assertEqual(speaker._settings.voice, "JBFqnCBsd6RMkjVDRZzb")
        self.assertEqual(speaker._settings.model, "eleven_flash_v2_5")
        self.assertNotIn("tags on", app.tts_label(cfg))

        os.environ["ELEVENLABS_MODEL"] = "eleven_v4_turbo"  # 新默认：HTTP 流式服务 + 情绪标签 + 声音参数
        os.environ["ELEVENLABS_STABILITY"] = "0.5"
        cfg = app.Config.load()
        self.assertTrue(cfg.eleven_tags)
        self.assertEqual(cfg.eleven_settings, {"stability": 0.5})
        self.assertFalse([p for p in cfg.problems() if "ELEVENLABS" in p], cfg.problems())
        self.assertIn("tags on", app.tts_label(cfg))
        self.assertIn("HTTP stream", app.tts_label(cfg))
        speaker = app.make_speaker(cfg)
        self.assertEqual(type(speaker).__name__, "HttpElevenLabsTTSService")
        self.assertEqual(speaker._settings.voice, "JBFqnCBsd6RMkjVDRZzb")
        self.assertEqual(speaker._settings.model, "eleven_v4_turbo")
        self.assertEqual(speaker._settings.stability, 0.5)
        self.assertIsNone(speaker._session)  # 会话到管线 start 时才建
        os.environ["ELEVENLABS_TAGS"] = "0"
        self.assertFalse(app.Config.load().eleven_tags)
        os.environ["ELEVENLABS_STABILITY"] = "7"
        self.assertTrue(any("ELEVENLABS_STABILITY" in p for p in app.Config.load().problems()))
        with self.assertRaises(eleven.ElevenError):
            app.make_speaker(app.Config.load())

        os.environ["TTS_PROVIDER"] = "nope"
        self.assertTrue(any("TTS_PROVIDER" in p for p in app.Config.load().problems()))


if __name__ == "__main__":
    unittest.main()
