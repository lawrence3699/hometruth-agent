#!/usr/bin/env python3
"""src/llm/provider.py 的单测：按 Power Prompt 合同逐条测，对着 tests/mock_meterless.py（假 runtime）跑，不连真服务。
跑：python3 -m unittest tests/test_provider.py -v     （/usr/bin/python3 3.9 和 .venv 的 3.12 都能跑）"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from llm import provider as P  # noqa: E402
from mock_meterless import Mock  # noqa: E402

KEYS = ["METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN", "meterless_runtime_token", "METERLESS_API_KEY", "METERLESS_MODEL",
        "METERLESS_CONNECT_LINK", "METERLESS_TOKEN_FILE", "METERLESS_APP", "NVIDIA_API_KEY", "NVIDIA_TEXT_MODEL", "NVIDIA_VL_MODEL",
        "LLM_PROVIDER", "HOMETRUTH_ENV_FILE"]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_free(port: int) -> bool:
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # 上一轮测试留下的 TIME_WAIT 不算占用（假 Runtime 也开了 reuse）
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class EnvCase(unittest.TestCase):
    """每个用例前清掉相关环境变量、不读 .env、日志写到临时文件。"""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in KEYS}
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ["HOMETRUTH_ENV_FILE"] = ""
        P._env_loaded = False
        P.invalidate()
        self.tmp = tempfile.TemporaryDirectory()
        self._log, self._nv, self._delays = P.LOG, P.NV_BASE, P.RETRY_DELAYS
        P.LOG = Path(self.tmp.name) / "llm_log.jsonl"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        P.LOG, P.NV_BASE, P.RETRY_DELAYS = self._log, self._nv, self._delays
        P._env_loaded = False
        P.invalidate()
        self.tmp.cleanup()

    def use(self, mock_port: int, token: str = "mock-token") -> str:
        base = f"http://127.0.0.1:{mock_port}/v1"
        os.environ["METERLESS_BASE_URL"] = base
        os.environ["METERLESS_RUNTIME_TOKEN"] = token
        P.invalidate()
        return base


class TestHelpers(unittest.TestCase):
    def test_normalize(self):
        cases = {"": "http://127.0.0.1:8088/v1", "127.0.0.1:8088": "http://127.0.0.1:8088/v1",
                 "http://127.0.0.1:8088/v1/": "http://127.0.0.1:8088/v1", "http://localhost:8090/v1/chat/completions": "http://localhost:8090/v1",
                 "http://[::1]:8787/v1/models": "http://[::1]:8787/v1", "http://127.0.0.1:8088/healthz": "http://127.0.0.1:8088/v1",
                 "https://x.example/v1/v1": "https://x.example/v1", "x.example:9000/v1/v1/chat/completions": "http://x.example:9000/v1"}
        for raw, want in cases.items():
            self.assertEqual(P.normalize_base_url(raw), want, raw)
            self.assertNotIn("/v1/v1", P.normalize_base_url(raw))

    def test_connect_link(self):  # quick-connect 卡里列的八种
        full = P.parse_connect_link("http://127.0.0.1:8088/connect#k=abc")
        self.assertEqual((full["base_url"], full["api_key"], full["model"]), ("http://127.0.0.1:8088/v1", "abc", "meterless/auto"))
        mn = P.parse_connect_link("http://10.0.0.5:8088/connect#k=abc&m=meterless/fast&n=demo")
        self.assertEqual((mn["model"], mn["app"]), ("meterless/fast", "demo"))
        self.assertIsNotNone(P.parse_connect_link("http://127.0.0.1:8088/connect/#k=abc"))
        self.assertEqual(P.parse_connect_link("https://h.example/connect#k=abc")["base_url"], "https://h.example/v1")
        self.assertEqual(P.parse_connect_link("http://127.0.0.1:8088/connect#k=a%2Bb%20c")["api_key"], "a+b c")
        self.assertIsNone(P.parse_connect_link("http://127.0.0.1:8088/v1"))
        self.assertIsNone(P.parse_connect_link("http://127.0.0.1:8088/connect"))
        self.assertIsNone(P.parse_connect_link("http://127.0.0.1:8088/other#k=abc"))

    def test_strip_think_and_parts(self):
        self.assertEqual(P.strip_think("<think>x</think> hello"), "hello")
        text, parts = P.extract_text({"choices": [{"message": {"content": [{"type": "text", "text": "hi"},
                                                                           {"type": "image_url", "image_url": {"url": "http://x/a.png"}}]}}]})
        self.assertEqual(text, "hi\nImage: http://x/a.png")
        self.assertEqual(len(parts), 1)


class TestRuntime(EnvCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = Mock("mock-token")
        cls.port = cls.mock.start()
        cls.plain = Mock("mock-token", plain=True)
        cls.plain_port = cls.plain.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.plain.stop()

    def setUp(self):
        super().setUp()
        self.mock.requests.clear()

    def test_online_and_unknown_ids_kept(self):
        base = self.use(self.port)
        p = P.probe()
        self.assertEqual(p.state, "online")
        self.assertIn("meterless/experimental-thing", p.meterless_ids)
        self.assertEqual(p.base_url, base)

    def test_wrong_token_is_unauthorized_not_offline(self):
        self.use(self.port, token="wrong-token")
        self.assertEqual(P.probe().state, "unauthorized")
        self.assertEqual(P.probe(token="").state, "unauthorized")

    def test_closed_port_is_offline(self):
        p = P.probe(f"http://127.0.0.1:{free_port()}/v1", "x", timeout=1)
        self.assertEqual((p.state, p.status), ("offline", 0))

    def test_200_without_meterless_ids_is_offline(self):
        p = P.probe(f"http://127.0.0.1:{self.plain_port}/v1", "mock-token")
        self.assertEqual(p.state, "offline")
        self.assertIn("no meterless", p.error)

    def test_healthz_only_proves_process(self):
        self.use(self.port, token="wrong-token")
        ok, status, _, _ = P.healthz()
        self.assertTrue(ok)
        self.assertEqual(P.probe().state, "unauthorized")

    def test_headers_on_every_request(self):
        self.use(self.port)
        P.probe()
        P.complete("Reply with one sentence confirming this connection works.")
        get = next(r for r in self.mock.requests if r["method"] == "GET")
        post = next(r for r in self.mock.requests if r["method"] == "POST")
        for r in (get, post):
            self.assertEqual(r["headers"].get("authorization"), "Bearer mock-token")
            self.assertEqual(r["headers"].get("meterless-app"), "hometruth")
        self.assertNotIn("meterless-scope", get["headers"])
        self.assertEqual(post["headers"].get("meterless-scope"), "user")
        self.assertIsInstance(post["body"]["messages"][-1]["content"], str)
        self.assertEqual(post["body"]["model"], "meterless/auto")

    def test_plain_text_on_meterless_auto_returns_string(self):
        self.use(self.port)
        res = P.complete("Reply with one sentence confirming this connection works.")
        self.assertIsInstance(res.text, str)
        self.assertTrue(res.text)
        self.assertEqual((res.provider, res.model), ("meterless", "meterless/auto"))
        self.assertIn("mock", res.served_model)
        self.assertEqual(res.usage.get("total_tokens"), res.usage["prompt_tokens"] + res.usage["completion_tokens"])

    def test_stream_sse_and_progress(self):
        self.use(self.port)
        deltas, prog = [], []
        res = P.complete("hello", stream=True, on_delta=deltas.append, on_progress=prog.append)
        self.assertEqual("".join(deltas).strip(), res.text)
        self.assertTrue(prog)
        self.assertIsNotNone(res.first_token_ms)
        post = [r for r in self.mock.requests if r["method"] == "POST"][-1]
        self.assertEqual(post["headers"].get("meterless-trace"), "on")

    def test_stream_answered_as_json(self):
        self.use(self.port)
        res = P.complete("STREAM_AS_JSON please", stream=True)
        self.assertIn("Connection works", res.text)

    def test_parts_and_think(self):
        self.use(self.port)
        self.assertIn("Connection works", P.complete("PARTS please").text)
        self.assertFalse(P.complete("THINK first").text.startswith("<think>"))

    def test_model_not_found(self):
        self.use(self.port)
        with self.assertRaises(P.LLMError) as cm:
            P.complete("hi", model="meterless/nope")
        self.assertEqual(cm.exception.kind, "model_not_found")
        self.assertIn("not found", str(cm.exception))

    def test_rate_limit_retries_then_surfaces(self):
        self.use(self.port)
        P.RETRY_DELAYS = (0.01, 0.01, 0.01)
        with self.assertRaises(P.LLMError) as cm:
            P.complete("RATE_LIMIT", retries=2)
        self.assertEqual(cm.exception.kind, "rate_limited")
        self.assertEqual(len([r for r in self.mock.requests if r["method"] == "POST"]), 3)
        self.mock.requests.clear()
        with self.assertRaises(P.LLMError):
            P.complete("RATE_LIMIT", retries=0)
        self.assertEqual(len([r for r in self.mock.requests if r["method"] == "POST"]), 1)

    def test_refusal_keeps_server_fix(self):
        self.use(self.port)
        with self.assertRaises(P.LLMError) as cm:
            P.complete("REFUSE this")
        e = cm.exception
        self.assertEqual(e.kind, "refused")
        self.assertIn("Use the jobs route", str(e))
        self.assertIs(e.chat_carrier, False)
        self.assertNotIn("machine", str(e).lower())

    def test_timeout_is_transport(self):
        self.use(self.port)
        with self.assertRaises(P.LLMError) as cm:
            P.complete("SLOW", timeout=1, provider="meterless")
        self.assertEqual(cm.exception.kind, "timeout")
        self.assertTrue(cm.exception.transport)

    def test_rt_local_and_token_file(self):
        self.use(self.port, token="rt-local")
        cfg = P.meterless_config()
        self.assertEqual(cfg.token, "")
        self.assertTrue(any("rt-local" in n for n in cfg.notes))
        f = Path(self.tmp.name) / "proxy-token"
        f.write_text("mock-token\n")
        os.environ["METERLESS_TOKEN_FILE"] = str(f)
        self.assertEqual((P.meterless_config().token, P.meterless_config().token_source), ("mock-token", "token_file"))
        self.assertEqual(P.probe().state, "online")

    def test_connect_link_in_base_url_field(self):
        os.environ["METERLESS_BASE_URL"] = f"http://127.0.0.1:{self.port}/connect#k=mock-token&m=meterless/fast"
        cfg = P.meterless_config()
        self.assertEqual((cfg.base_url, cfg.token_source, cfg.model), (f"http://127.0.0.1:{self.port}/v1", "connect_link", "meterless/fast"))
        self.assertEqual(P.select(refresh=True).name, "meterless")

    def test_log_line_without_secrets(self):
        self.use(self.port)
        P.complete("hello there", task="unit")
        lines = P.LOG.read_text().splitlines()
        self.assertTrue(lines)
        e = json.loads(lines[-1])
        for k in ("provider", "model", "prompt_sha256", "ms", "tokens", "served_model", "status"):
            self.assertIn(k, e)
        self.assertEqual((e["provider"], e["status"], e["task"]), ("meterless", "ok", "unit"))
        self.assertNotIn("mock-token", P.LOG.read_text())


class TestSelection(EnvCase):
    @classmethod
    def setUpClass(cls):
        cls.nv = Mock("nvapi-test-key", nvidia=True)
        cls.nv_port = cls.nv.start()

    @classmethod
    def tearDownClass(cls):
        cls.nv.stop()

    def setUp(self):
        super().setUp()
        self.nv.requests.clear()
        P.NV_BASE = f"http://127.0.0.1:{self.nv_port}/v1"

    def test_none_without_token_or_key_makes_no_requests(self):
        m = Mock()
        port = m.start()
        try:
            os.environ["METERLESS_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
            sel = P.select(refresh=True)
            self.assertEqual((sel.name, sel.meterless_state, sel.nvidia_state), ("none", "no_token", "no_key"))
            self.assertEqual(m.requests, [])
            with self.assertRaises(P.LLMError) as cm:
                P.complete("hi")
            self.assertEqual(cm.exception.kind, "no_provider")
        finally:
            m.stop()

    def test_nvidia_direct_when_no_nightshift(self):
        os.environ["NVIDIA_API_KEY"] = "nvapi-test-key"
        sel = P.select(refresh=True)
        self.assertEqual((sel.name, sel.model), ("nvidia", P.NV_TEXT_DEFAULT))
        res = P.complete("hello")
        self.assertEqual(res.provider, "nvidia")
        post = [r for r in self.nv.requests if r["method"] == "POST"][-1]
        self.assertNotIn("meterless-app", post["headers"])

    def test_transport_failure_falls_back_typed_refusal_does_not(self):
        m = Mock()
        port = m.start()
        self.use(port)
        os.environ["NVIDIA_API_KEY"] = "nvapi-test-key"
        self.assertEqual(P.select(refresh=True).name, "meterless")
        with self.assertRaises(P.LLMError) as cm:  # 带类型的拒绝：不回退
            P.complete("REFUSE this")
        self.assertEqual(cm.exception.kind, "refused")
        self.assertEqual([r for r in self.nv.requests if r["method"] == "POST"], [])
        m.stop()  # Nightshift 突然没了：传输失败 → 回退直连
        res = P.complete("hello again")
        self.assertEqual((res.provider, res.fallback_from, res.fallback_reason), ("nvidia", "meterless", "unreachable"))
        log = [json.loads(x) for x in P.LOG.read_text().splitlines()]
        self.assertTrue(any(e.get("status") == "unreachable" and e.get("fallback") == "nvidia" for e in log))

    def test_wrong_token_selects_nvidia_but_explicit_meterless_says_unauthorized(self):
        m = Mock()
        port = m.start()
        try:
            self.use(port, token="wrong")
            os.environ["NVIDIA_API_KEY"] = "nvapi-test-key"
            sel = P.select(refresh=True)
            self.assertEqual((sel.name, sel.meterless_state), ("nvidia", "unauthorized"))
            with self.assertRaises(P.LLMError) as cm:
                P.complete("hi", provider="meterless")
            self.assertEqual(cm.exception.kind, "unauthorized")
            self.assertIn("METERLESS_RUNTIME_TOKEN", str(cm.exception))
            os.environ["LLM_PROVIDER"] = "meterless"
            self.assertEqual(P.select(refresh=True).name, "none")
        finally:
            m.stop()

    @unittest.skipUnless(port_free(8787) and port_free(8088) and port_free(8090), "8787/8088/8090 not free")
    def test_auto_detect_finds_runtime(self):
        m = Mock()
        m.start(port=8787)
        try:
            hit = P.auto_detect("mock-token", timeout=0.5)
            self.assertEqual((hit.state, hit.base_url), ("online", "http://127.0.0.1:8787/v1"))
            self.assertEqual(P.auto_detect("", timeout=0.5).state, "unauthorized")  # 没 token 也算找到
            self.use(free_port())  # 配置的地址是死的 → 选择时自动探测
            sel = P.select(refresh=True)
            self.assertEqual((sel.name, sel.base_url, sel.detected), ("meterless", "http://127.0.0.1:8787/v1", True))
            env = Path(self.tmp.name) / "env"
            env.write_text("METERLESS_RUNTIME_TOKEN=\nMETERLESS_BASE_URL=http://127.0.0.1:9/v1\nOTHER=1\n")
            os.environ["HOMETRUTH_ENV_FILE"] = str(env)
            P.save_base_url(hit.base_url)
            self.assertEqual(env.read_text(), "METERLESS_RUNTIME_TOKEN=\nMETERLESS_BASE_URL=http://127.0.0.1:8787/v1\nOTHER=1\n")
        finally:
            m.stop()


if __name__ == "__main__":
    unittest.main()
