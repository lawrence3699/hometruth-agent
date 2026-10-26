# -*- coding: utf-8 -*-
"""假 ElevenLabs（单测用，不上网）：/v1/voices、/v1/models、/v1/user/subscription、/v1/text-to-speech/<id>?output_format=pcm_<rate>。
key 不对回 401；id 不存在回 404；text 里有 SLOW 睡 3 s。合成返回 len(text) × 200 个采样的 PCM（听不了，只够量长度）。"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

VOICES = [
    {"voice_id": "IKne3meq5aSn9XLyUdCD", "name": "Charlie", "category": "premade", "labels": {"accent": "Australian", "gender": "male", "age": "middle_aged", "use_case": "conversational"}},
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "category": "premade", "labels": {"accent": "american", "gender": "female", "age": "young"}},
    {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "George", "category": "premade", "labels": {"accent": "British", "gender": "male", "age": "middle_aged"}},
]
MODELS = [{"model_id": "eleven_flash_v2_5", "name": "Eleven Flash v2.5", "can_do_text_to_speech": True, "languages": [{"language_id": "en"}] * 32},
          {"model_id": "eleven_multilingual_v2", "name": "Eleven Multilingual v2", "can_do_text_to_speech": True, "languages": [{"language_id": "en"}] * 29},
          {"model_id": "eleven_v4_turbo", "name": "Eleven v4 Turbo", "can_do_text_to_speech": True, "languages": [{"language_id": "en"}] * 94}]


class Mock:
    def __init__(self, key: str = "mock-eleven-key"):
        self.key = key
        self.calls = []
        self.bodies = []  # 每次合成请求的 JSON（text / model_id / voice_settings），测试里检查发了什么
        self._srv: Optional[ThreadingHTTPServer] = None

    def start(self) -> int:
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D102
                pass

            def _send(self, code, body, ctype="application/json"):
                data = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _authed(self):
                if self.headers.get("xi-api-key") != mock.key:
                    self._send(401, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
                    return False
                return True

            def do_GET(self):
                mock.calls.append(("GET", self.path))
                if not self._authed():
                    return
                if self.path.startswith("/v1/voices"):
                    return self._send(200, {"voices": VOICES})
                if self.path.startswith("/v1/models"):
                    return self._send(200, MODELS)
                if self.path.startswith("/v1/user/subscription"):
                    return self._send(200, {"tier": "free", "character_count": 1234, "character_limit": 10000})
                self._send(404, {"detail": "no such route"})

            def do_POST(self):
                mock.calls.append(("POST", self.path))
                if not self._authed():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                mock.bodies.append(body)
                if not self.path.startswith("/v1/text-to-speech/"):
                    return self._send(404, {"detail": "no such route"})
                vid = self.path.split("/v1/text-to-speech/", 1)[1].split("?")[0]
                if vid not in {v["voice_id"] for v in VOICES}:
                    return self._send(404, {"detail": {"status": "voice_not_found", "message": f"A voice for the voice_id {vid} was not found."}})
                text = str(body.get("text", ""))
                if "SLOW" in text:
                    time.sleep(3)
                pcm = (b"\x10\x00\xf0\xff" * (len(text) * 100))[: len(text) * 200 * 2]
                self._send(200, pcm, ctype="audio/pcm")

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self._srv.server_address[1]

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
