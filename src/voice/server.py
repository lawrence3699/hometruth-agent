#!/usr/bin/env python3
"""HomeTruth 语音导览原型服务（只依赖标准库，Python 3.9 起）。

跑：python3 src/voice/server.py   →  http://127.0.0.1:8630 （语音要用 Chrome；文字框任何浏览器都行）
接口：
  GET  /                      页面
  GET  /api/hello?renter=ID   后端信息（TTS 后端、声音）+ 这位租客上次的需求（memory.py；没有就 null）
  POST /api/forget            {renter} 删掉记忆（连同收件箱、信念日志、风格匹配的上传和结果）
  POST /api/style             {renter, images:[{name, data(base64 jpeg/png)}]} 最多 3 张、每张 ≤ 3 MB → {profile, matches:{listing_id: match}, model, route, ms}（src/photo/style.py，软偏好）
  GET  /api/style?renter=ID   这位租客存的风格匹配，没有就 {profile: null, matches: {}}
  POST /api/inbox             {renter, listing_id, text, channel} 中介回复到了（inbox.py）：下一句话 "Just in…" / 下次开查 "While you were away…" 折进来
  GET  /api/listings          全部候选房源的只读摘要（背景卡片墙用；字段和 card 事件的 listing 一致，另加 suburb）
  POST /api/turn              {session, text, source, interrupted:{active, spoken_idx, listing_id, cut_sentence}} → SSE 事件流
  GET  /api/tts?text=...      一句话的音频（wav 或 mp3；browser 后端返回 204）
  POST /api/metric            浏览器上报的延迟，追加到 runs/voice_log.jsonl
  POST /api/reset             {session} 清掉会话
环境变量（可放项目根目录 .env）：TTS_BACKEND=auto|say|openai|elevenlabs|browser，TTS_VOICE，TTS_RATE，VOICE_PORT，VOICE_DEBUG。
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Optional
import mimetypes
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAL_PHOTOS = Path(__file__).resolve().parents[2] / "data" / "real" / "photos"
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import tts  # noqa: E402
from policy import LISTINGS, SESSIONS, card_payload, forget_renter, hello_view, listing_summary  # noqa: E402
import inbox  # noqa: E402
import memory  # noqa: E402
import narrator  # noqa: E402
import zetaris_live  # noqa: E402
from policy import SOURCES, zetaris_rows  # noqa: E402
from photo import style as style_match  # noqa: E402  装修风格匹配（软偏好；policy 已把 src 放进 sys.path）

LOG = ROOT / "runs" / "voice_log.jsonl"


def listings_view() -> list:
    """卡片墙、浏览网格和详情页用：每套候选房源一行（policy.listing_summary：card 事件的字段 + suburb / postcode / special / facts）。"""
    return [listing_summary(L) for L in LISTINGS]


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = dict({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, **entry)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "HomeTruthVoice/0.1"

    def log_message(self, fmt, *args):  # 安静一点
        if os.environ.get("VOICE_DEBUG"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str = "application/json", cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _file(self, p: Path) -> None:
        if not p.is_file():
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)

    def do_GET(self) -> None:
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):  # since 10-27 evening: the Notion-style page (static/notion); the qi shell stays at /qi, the first page at /classic
            return self._file(HERE / "static" / "notion" / "index.html")
        if u.path in ("/qi", "/qi.html"):
            return self._file(HERE / "static" / "qi" / "index.html")
        if u.path in ("/classic", "/classic.html"):
            return self._file(HERE / "static" / "index.html")
        if u.path.startswith("/static/"):
            p = (HERE / "static" / u.path[len("/static/"):]).resolve()
            if (HERE / "static") not in p.parents:
                return self._json(403, {"error": "forbidden"})
            return self._file(p)
        if u.path.startswith("/real/"):  # 真房源的照片和户型图（data/real/photos，本地缓存，不进 git；scripts/domain_sample.py）
            p = (REAL_PHOTOS / u.path[len("/real/"):]).resolve()
            if REAL_PHOTOS.resolve() not in p.parents:
                return self._json(403, {"error": "forbidden"})
            return self._file(p)
        if u.path == "/api/hello":  # ?renter=<id>：这位租客上次的需求（memory.py），没有就 null
            q = urllib.parse.parse_qs(u.query)
            return self._json(200, {"tts_backend": tts.backend(), "voice": tts.voice_label(), "voice_id": tts.voice_name(), "server_time": time.time(),
                                    "narration": "llm" if narrator.enabled() else "template",
                                    "deployed": deployed_info(),  # which commit is live (the box's auto-deploy writes deploy_info.json; null on a dev machine)
                                    "zetaris": zetaris_live.status(),  # live queries on? how many evidence ids came back through Zetaris
                                    "memory": hello_view((q.get("renter") or [""])[0])})
        if u.path == "/api/style":  # ?renter=<id>：这位租客存的风格匹配（src/photo/style.py），没有就 profile null
            return self._json(*style_match.api_get(urllib.parse.parse_qs(u.query)))
        if u.path == "/api/listings":
            return self._json(200, {"listings": listings_view()})
        if u.path.startswith("/api/zetaris/"):  # 证据表，Zetaris 把它注册成 REST 表来查（policy.zetaris_rows；scripts/zetaris/10_register_hometruth.sql）
            name = u.path[len("/api/zetaris/"):]
            rows = zetaris_rows(name)
            if rows is None:
                return self._json(404, {"error": f"unknown source {name!r}", "sources": [s["name"] for s in SOURCES]})
            return self._json(200, {"source": name, "count": len(rows), "items": rows})
        if u.path == "/api/tts":
            q = urllib.parse.parse_qs(u.query)
            text = (q.get("text") or [""])[0].strip()
            if not text:
                return self._json(400, {"error": "text required"})
            t0 = time.time()
            try:  # step / status：这句在流程里的位置和所讲格子的状态，ElevenLabs 按它加情绪标签（tone.py）
                data, ctype = tts.synthesize(text[:600], step=(q.get("step") or [""])[0][:40], status=(q.get("status") or [""])[0][:20])
            except Exception as e:  # 合成失败就让浏览器自己念
                log({"kind": "tts_error", "error": str(e), "text": text[:80]})
                return self._send(204, b"")
            if data is None:
                return self._send(204, b"")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("X-TTS-Ms", str(round((time.time() - t0) * 1000)))
            self.end_headers()
            self.wfile.write(data)
            return
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        if u.path == "/api/turn":
            return self._turn(body)
        if u.path == "/api/metric":
            if body.get("kind") == "client_error":  # the page reports a JavaScript error / a dropped event, so a stuck screen leaves a trace here
                log({"kind": "client_error", "session": str(body.get("session") or "")[:64], "where": str(body.get("where") or "")[:80], "error": str(body.get("error") or "")[:600]})
            else:
                log(dict({"kind": "client_metric"}, **{k: v for k, v in body.items() if k in ("session", "source", "first_event_ms", "first_audio_ms", "turn_text", "interrupted", "ua", "audio", "mic", "headphones")}))  # ua / audio / mic / headphones since 10-27: which browser, was the audio context running
            return self._send(204, b"")
        if u.path == "/api/reset":
            SESSIONS.reset(str(body.get("session") or "anon"))
            return self._send(204, b"")
        if u.path == "/api/forget":  # 界面上的 Forget me：记忆、收件箱、信念日志一起删
            forget_renter(body.get("renter"))
            style_match.forget(body.get("renter"))  # 风格匹配的上传和结果也删
            return self._send(204, b"")
        if u.path == "/api/style":  # {renter, images: [{name, data}]}：读参考照片、给每套房打风格分（软偏好：不进硬条件、不进排名）
            return self._json(*style_match.api_post(body))
        if u.path == "/api/inbox":  # 中介回复到了（邮件 / 短信的 webhook，或 scripts/agent_reply.py）：进这位租客的收件箱，下一句话或下次开查时折进来
            return self._inbox(body)
        return self._json(404, {"error": "not found"})

    def _inbox(self, body: dict) -> None:
        lid = str(body.get("listing_id") or "").strip()
        if not any(L["id"] == lid for L in LISTINGS):
            return self._json(404, {"error": f"unknown listing_id {lid!r}", "listings": [L["id"] for L in LISTINGS]})
        row = inbox.add(body.get("renter"), lid, str(body.get("text") or ""), str(body.get("channel") or "api"))
        if row is None:
            return self._json(400, {"error": "renter (the browser's ht_renter), listing_id and text are required"})
        log({"kind": "inbox", "renter": row["renter"], "listing_id": lid, "channel": row["channel"], "event_id": row["event_id"]})
        return self._json(200, {"status": "queued", "event": row, "unread": inbox.view(row["renter"])["unread"]})

    def _turn(self, body: dict) -> None:
        t0 = time.time()
        sess = SESSIONS.get(str(body.get("session") or "anon"))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        first_ms, n_events, status = None, 0, "ok"
        try:
            with sess.lock:
                for ev in sess.handle_turn(body):
                    if first_ms is None:
                        first_ms = round((time.time() - t0) * 1000)
                        ev = dict(ev, t_first_ms=first_ms)
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    n_events += 1
        except (BrokenPipeError, ConnectionResetError):
            status = "client_aborted"
        except Exception as e:  # 把异常也送到前端，便于调试
            status = f"error: {e}"
            try:
                self.wfile.write(f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n".encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass
        log({"kind": "turn", "session": sess.id, "text": (body.get("text") or "")[:200], "interrupted": bool((body.get("interrupted") or {}).get("active")),
             "first_event_ms": first_ms, "events": n_events, "total_ms": round((time.time() - t0) * 1000), "status": status})


def deployed_info() -> Optional[dict]:
    """deploy_info.json at the project root = {sha, time, by}, written by infra/windows/auto_deploy.ps1 after a successful deploy; None elsewhere."""
    p = ROOT / "deploy_info.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None
    return {"sha": str(d.get("sha") or "")[:40], "time": str(d.get("time") or "")[:40], "by": str(d.get("by") or "")[:20]} if isinstance(d, dict) else None


def main() -> None:
    load_env()
    port = int(os.environ.get("VOICE_PORT", "8630"))
    ThreadingHTTPServer.request_queue_size = 128  # listen backlog: Windows refuses connections beyond it (default 5), and a page load fires dozens at once through cloudflared → intermittent 502 on static files (10-27)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    zet = zetaris_live.enable()  # Zetaris keys in .env → every search queries the evidence through Zetaris (HOMETRUTH_ZETARIS=0 turns it off)
    if zet:
        zetaris_live.warm([s["name"] for s in SOURCES], [L["id"] for L in LISTINGS])
    print(f"HomeTruth voice prototype on http://127.0.0.1:{port}  (tts={tts.backend()}, voice={tts.voice_label()}, zetaris={'live' if zet else 'off'})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
