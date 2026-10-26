#!/usr/bin/env python3
"""假的 Meterless Runtime（只依赖标准库），没装 Nightshift 时测 src/llm/provider.py 和需求解析的模型路径用。
不是 Nightshift，不连任何模型；回答里的 served model 一律带 "mock" 字样，免得被当成真证据。

单独跑：python3 tests/mock_meterless.py --port 8099 --token mock-token
行为：
  GET  /healthz                 200（不验 token）
  GET  /v1/models               token 对 → 200 + meterless/* 列表；不对或没带 → 401；--plain 时返回没有 meterless id 的列表（像 Ollama）
  POST /v1/chat/completions     验 token、meterless-app 头、chat 的 meterless-scope: user；未知路由 → 404 model_not_found
最后一条用户消息里的暗号：RATE_LIMIT → 429；REFUSE → 400 class_carrier_unsupported + fix[]；SLOW → 睡 3 s；
STREAM_AS_JSON → 请求 stream 也回整个 JSON；PARTS → content 用分段数组；THINK → 回答前带 <think> 块。
系统提示里有 HOMETRUTH_NEEDS_V1 时按需求解析的格式回 JSON（见 NEEDS 表；BADJSON 回非 JSON；HALLUCINATE 回不在原话里的数字）。
系统提示里有 HOMETRUTH_NARRATE_V1（台词交给模型写）时：facts 列表里每条事实原样加 "Mock says: " 前缀，按 key 回 JSON；
租客原话里有 BADNUMBER → 每行后面多一句 "Costs 999."（多出来的数字，该被校验拒掉）；NOJSON → 回一句普通话（不是 JSON）；SLOW 照旧睡 3 s（测超时）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional

ROUTES = ["meterless/auto", "meterless/fast", "meterless/deep", "meterless/cheap", "meterless/local", "meterless/text.fast",
          "meterless/vision", "meterless/experimental-thing"]
SERVED = "mock/nemotron-3.5-lightning-30b-a3b"

# 需求解析的假回答（模拟模型比规则多认出来的东西）。键是小写原话。
NEEDS: Dict[str, dict] = {
    "two bedrooms near central, i have a cat, and i'd like air con in the bedroom.": {
        "budget": None, "bedrooms": 2, "anchor": "Central Station", "move_in": None, "pets": {"has": True, "kind": "cat"},
        "extras": [{"dim": "C1", "label": "Air con in the bedroom"}], "max_commute": None},
    "under 900, mid-november.": {
        "budget": 900, "bedrooms": None, "anchor": None, "move_in": {"month": 11, "day": 15, "text": "mid-November"}, "pets": None,
        "extras": [], "max_commute": None},
    "somewhere close to newtown for my partner and me, we've got a little dog.": {
        "budget": None, "bedrooms": None, "anchor": "Newtown", "move_in": None, "pets": {"has": True, "kind": "dog"}, "extras": [],
        "max_commute": None},
    "nine hundred tops, and we need it in about two weeks.": {  # move_in 在 _needs_answer 里按今天 + 14 天算
        "budget": 900, "bedrooms": None, "anchor": None, "move_in": None, "pets": None, "extras": [], "max_commute": None},
    "actually make it under 850 a week.": {
        "budget": 850, "bedrooms": None, "anchor": None, "move_in": None, "pets": None, "extras": [], "max_commute": None},
}


def _needs_answer(utterance: str) -> str:
    u = re.sub(r"\b(BADNUMBER|NOJSON|SLOW|THINK)\b", "", utterance).strip().lower()  # 台词层的暗号不影响需求表查找
    if "badjson" in u:
        return "Sure! The user wants a nice flat."
    if "hallucinate" in u:
        return json.dumps({"budget": 1234, "bedrooms": 3, "anchor": "Bondi Beach", "move_in": None, "pets": None, "extras": [],
                           "max_commute": None})
    ans = dict(NEEDS.get(u) or {"budget": None, "bedrooms": None, "anchor": None, "move_in": None, "pets": None, "extras": [],
                                  "max_commute": None})
    if u.startswith("nine hundred tops"):
        d = dt.date.today() + dt.timedelta(days=14)
        ans["move_in"] = {"month": d.month, "day": d.day, "text": "in about two weeks"}
    return "```json\n" + json.dumps(ans) + "\n```"


def _narrate_answer(user: str) -> str:
    try:
        obj = json.loads(user)
    except ValueError:
        return "I cannot help with that."
    renter = str(obj.get("renter_said", ""))
    if "NOJSON" in renter:
        return "Sure! Here is what I would say about this place."
    bad = "BADNUMBER" in renter

    def tag(t):
        t = "Mock says: " + str(t)
        return t + " Costs 999." if bad else t

    facts = obj.get("facts") or []
    if isinstance(facts, dict):  # 老格式兜底
        facts = [{"key": k, "fact": v} for k, v in facts.items()]
    return json.dumps({str(f.get("key")): tag(f.get("fact", "")) for f in facts if isinstance(f, dict)})


class Mock:
    def __init__(self, token: str = "mock-token", plain: bool = False, nvidia: bool = False):
        """nvidia=True 时装成 integrate.api.nvidia.com（不要 meterless 头，只认 nvidia/* 模型），测回退用。"""
        self.token = token
        self.plain = plain
        self.nvidia = nvidia
        self.requests: List[dict] = []  # 记录收到的请求头（测试用）
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # 安静
                pass

            def _send(self, code: int, obj, ctype: str = "application/json") -> None:
                body = json.dumps(obj).encode("utf-8") if not isinstance(obj, bytes) else obj
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):  # 客户端等不及先挂了（超时测试）
                    pass

            def _authed(self) -> bool:
                return self.headers.get("Authorization", "") == f"Bearer {mock.token}"

            def _record(self, body: Optional[dict] = None) -> None:
                mock.requests.append({"path": self.path, "method": self.command,
                                      "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})

            def do_GET(self):
                self._record()
                if self.path == "/healthz":
                    return self._send(200, {"ok": True})
                if self.path == "/v1/models":
                    if not self._authed():
                        return self._send(401, {"error": {"message": "invalid runtime token", "type": "auth", "code": "unauthorized"}})
                    ids = ["llama3:8b", "qwen3:4b"] if mock.plain else ROUTES
                    return self._send(200, {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})
                return self._send(404, {"error": {"message": "not found"}})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._send(400, {"error": {"message": "bad json"}})
                self._record(body)
                if self.path != "/v1/chat/completions":
                    return self._send(404, {"error": {"message": "not found"}})
                if not self._authed():
                    return self._send(401, {"error": {"message": "invalid runtime token", "code": "unauthorized"}})
                model = body.get("model", "")
                if mock.nvidia:
                    if not model.startswith("nvidia/"):
                        return self._send(404, {"status": 404, "title": "Not Found", "detail": f"Function '{model}': Not found for account"})
                else:
                    if not self.headers.get("meterless-app"):
                        return self._send(400, {"error": {"message": "missing meterless-app header", "code": "bad_request"}})
                    if self.headers.get("meterless-scope") != "user":
                        return self._send(400, {"error": {"message": "chat needs meterless-scope: user", "code": "bad_request"}})
                    if model not in ROUTES:
                        return self._send(404, {"error": {"message": f"model '{model}' not found", "code": "model_not_found"}})
                msgs = body.get("messages") or []
                user = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
                system = next((m.get("content", "") for m in msgs if m.get("role") == "system"), "")
                if not isinstance(user, str):
                    return self._send(400, {"error": {"message": "plain text requests must stay a string"}})
                if "RATE_LIMIT" in user:
                    return self._send(429, {"error": {"message": "lane busy", "code": "rate_limited"}})
                if "REFUSE" in user:
                    return self._send(400, {"error": {"message": "this route can't carry that class", "code": "class_carrier_unsupported"},
                                            "meterless": {"fix": ["Use the jobs route for media."], "chat_carrier": False}})
                if "SLOW" in user:
                    time.sleep(3)
                if "HOMETRUTH_NEEDS_V1" in system:
                    m = re.search(r"Utterance:\s*(.*)", user)
                    answer = _needs_answer(m.group(1) if m else user)
                elif "HOMETRUTH_NARRATE_V1" in system:
                    answer = _narrate_answer(user)
                else:
                    answer = "Connection works. This is the mock runtime, not a real model."
                if "THINK" in user:
                    answer = "<think>planning the reply</think>" + answer
                usage = {"prompt_tokens": 42, "completion_tokens": len(answer.split()), "total_tokens": 42 + len(answer.split())}
                meta = None if mock.nvidia else {"route": model, "lane": "lane-1", "provider": "mock"}
                served = f"mock/{model}" if mock.nvidia else SERVED
                if body.get("stream") and "STREAM_AS_JSON" not in user:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b'data: {"meterless": {"progress": {"stage": "loading"}}}\n\n')
                    for w in re.findall(r"\S+\s*", answer):
                        chunk = {"model": served, "choices": [{"index": 0, "delta": {"content": w}}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    tail = {"model": served, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}
                    if meta:
                        tail["meterless"] = meta
                    self.wfile.write(f"data: {json.dumps(tail)}\n\ndata: [DONE]\n\n".encode("utf-8"))
                    return
                content = [{"type": "text", "text": answer}] if "PARTS" in user else answer
                out = {"id": "mock-1", "object": "chat.completion", "model": served,
                       "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}], "usage": usage}
                if meta:
                    out["meterless"] = meta
                return self._send(200, out)

        self.server = ThreadingHTTPServer((host, port), H)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_address[1]

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--token", default="mock-token")
    ap.add_argument("--plain", action="store_true", help="answer /v1/models without meterless ids")
    a = ap.parse_args()
    m = Mock(a.token, a.plain)
    port = m.start(a.host, a.port)
    print(f"mock Meterless Runtime on http://{a.host}:{port}/v1 (token {a.token!r}) — not Nightshift, answers are fake", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        m.stop()


if __name__ == "__main__":
    main()
