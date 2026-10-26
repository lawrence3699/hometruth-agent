#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装修风格匹配（src/photo/style.py + server.py 的 /api/style）：参考照片的 profile 合并（多数、平手取第一张、unknown 不参与、style_words 并集）、
带 unknown 的评分和权重重新归一、可比属性不足返回 None、路由的请求校验（张数、大小、base64 坏、不是图）、模型失败 502、结果落盘 / 读回 /
Forget me 删掉、真 server.py 的两条路由。模型函数是假的（monkeypatch style.ask_model），不连网、不碰 runs/。
跑：.venv/bin/python -m unittest tests.test_style_match -v"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))
os.environ["HOMETRUTH_ENV_FILE"] = ""
os.environ["NEEDS_PARSER"] = "rules"
os.environ["NARRATION_LLM"] = "0"
os.environ["VOICE_VARIETY"] = "0"

from llm import provider as llm  # noqa: E402
from photo import style  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

# 假模型按图的宽度认图：参考照片 10 / 11 px 宽，挂牌照片 20 / 30 px 宽（thumb 不改小图的尺寸）
READINGS = {
    10: {"floor": "timber", "palette": "light", "kitchen": "modern", "light": "bright", "era": "new", "style_words": ["scandi", "minimalist"], "one_line": "Pale timber floors and white walls."},
    11: {"floor": "carpet", "palette": "light", "kitchen": "unknown", "light": "bright", "era": "recent", "style_words": ["minimalist", "warm timber"], "one_line": "A carpeted bedroom."},
    20: {"floor": "timber", "palette": "light", "kitchen": "dated", "light": "unknown", "era": "new", "style_words": ["classic"], "one_line": "Timber floors."},
    30: {"floor": "unknown", "palette": "unknown", "kitchen": "unknown", "light": "dim", "era": "unknown", "style_words": [], "one_line": "A dim hallway."},
}


def jpeg(width: int, color=(200, 180, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, width), color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def png(width: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, width), (10, 20, 30, 128)).save(buf, "PNG")
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class FakeModel:
    """style.ask_model 的替身：按图宽回预设 JSON，记下每次的 task。"""

    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail

    def __call__(self, image: bytes, task: str, user_text: str, timeout: float = 60.0):
        self.calls.append(task)
        if self.fail:
            raise llm.LLMError("server_error", "boom", status=500)
        w = Image.open(io.BytesIO(image)).size[0]
        reading = READINGS[w]
        res = llm.ChatResult(text=json.dumps(reading), provider="nvidia", model="nvidia/nemotron-3.5-super-vl-120b-a12b",
                             served_model="private/nvidia/nemotron-3.5-super-120b-a12b", ms=12)
        return reading, res, "nvidia-direct", "refused: this box cannot serve vision"


class PureLogic(unittest.TestCase):
    def test_normalize_maps_synonyms_and_unknowns(self):
        n = style.normalize({"floor": "Hardwood", "palette": "WHITE", "kitchen": "contemporary", "light": "sunny", "era": "period",
                             "style_words": "Scandi, Minimalist , scandi", "one_line": "  Pale   timber. "})
        self.assertEqual({a: n[a] for a in style.ATTRS}, {"floor": "timber", "palette": "light", "kitchen": "modern", "light": "bright", "era": "older"})
        self.assertEqual(n["style_words"], ["scandi", "minimalist"])
        self.assertEqual(n["one_line"], "Pale timber.")
        n = style.normalize({"floor": "lava", "palette": None, "kitchen": 3, "style_words": None})
        self.assertEqual({a: n[a] for a in style.ATTRS}, {a: "unknown" for a in style.ATTRS})
        self.assertEqual(style.normalize("not a dict")["style_words"], [])

    def test_merge_majority_tie_first_unknown_excluded_words_union(self):
        a = {"floor": "timber", "palette": "light", "kitchen": "modern", "light": "bright", "era": "new", "style_words": ["scandi", "minimalist"]}
        b = {"floor": "carpet", "palette": "light", "kitchen": "unknown", "light": "dim", "era": "recent", "style_words": ["minimalist", "warm timber", "coastal"]}
        c = {"floor": "carpet", "palette": "unknown", "kitchen": "unknown", "light": "dim", "era": "older", "style_words": ["industrial", "loft", "brick", "x"]}
        p = style.merge_profiles([a, b, c])
        self.assertEqual(p["floor"], "carpet")  # 2 against 1
        self.assertEqual(p["palette"], "light")  # unknown does not vote
        self.assertEqual(p["kitchen"], "modern")  # only one photo shows a kitchen
        self.assertEqual(p["light"], "dim")
        self.assertEqual(p["era"], "new")  # three-way tie → the first photo
        self.assertEqual(p["style_words"], ["scandi", "minimalist", "warm timber", "coastal", "industrial", "loft"])  # union, deduped, first 6
        self.assertEqual((p["photos"], p["status"]), (3, "inferred"))
        p = style.merge_profiles([{"floor": "unknown"}, {"floor": "tile"}, {"floor": "stone"}])
        self.assertEqual(p["floor"], "tile")  # tie between photos 2 and 3 → the earlier one
        self.assertEqual(style.merge_profiles([])["floor"], "unknown")

    def test_match_renormalises_around_unknowns(self):
        ref = {"floor": "timber", "palette": "light", "kitchen": "modern", "light": "bright", "era": "new", "photos": 2}
        lp = {"floor": "timber", "palette": "light", "kitchen": "dated", "light": "unknown", "era": "new"}
        m = style.match(ref, lp)
        self.assertEqual(m["score"], 76)  # (30 + 25 + 10) / (30 + 25 + 20 + 10)
        self.assertEqual(m["status"], "inferred")
        self.assertEqual(m["reasons"], ["timber floors", "light palette", "new finishes"])
        self.assertEqual(m["misses"], ["kitchen looks dated, your reference is modern"])
        self.assertEqual(m["basis"], "from 2 reference photos and the listing's lead photo")
        self.assertEqual(m["compared"], 4)
        ref1 = dict(ref, photos=1, kitchen="unknown")
        m = style.match(ref1, dict(lp, light="dim"))
        self.assertEqual(m["score"], 81)  # kitchen unknown on the reference side: (30 + 25 + 10) / (30 + 25 + 15 + 10) = 81.25
        self.assertEqual(m["basis"], "from 1 reference photo and the listing's lead photo")
        self.assertIn("light looks dim, your reference is bright", m["misses"])

    def test_match_needs_two_comparable_attributes(self):
        ref = {"floor": "timber", "palette": "light", "kitchen": "modern", "light": "bright", "era": "new"}
        self.assertIsNone(style.match(ref, {"floor": "timber"}))
        self.assertIsNone(style.match(ref, {a: "unknown" for a in style.ATTRS}))
        self.assertIsNone(style.match(None, ref))
        self.assertIsNone(style.match(ref, None))
        two = style.match(ref, {"floor": "carpet", "era": "new"})
        self.assertEqual((two["score"], two["compared"]), (25, 2))  # 10 / 40

    def test_match_full_and_zero(self):
        ref = {"floor": "tile", "palette": "cool", "kitchen": "classic", "light": "moderate", "era": "recent"}
        self.assertEqual(style.match(ref, dict(ref))["score"], 100)
        zero = style.match(ref, {"floor": "carpet", "palette": "warm", "kitchen": "dated", "light": "dim", "era": "older"})
        self.assertEqual((zero["score"], zero["reasons"], len(zero["misses"])), (0, [], 5))
        self.assertEqual(style.chips(ref), ["tiled floors", "cool palette", "classic kitchen", "moderate light", "recent finishes"])


@unittest.skipUnless(Image, "Pillow is needed to make the test photos")
class Routes(unittest.TestCase):
    """api_post / api_get / forget 对着临时目录跑：两套假房源的挂牌照片放在临时的 assets/photos 下。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ht-style-"))
        photos = self.tmp / "photos"
        photos.mkdir()
        (photos / "L-0001-01.jpg").write_bytes(jpeg(20))
        (photos / "L-0002-01.jpg").write_bytes(jpeg(30, (40, 40, 40)))
        listings = [{"id": "L-0001", "street": "1 Test St", "suburb": "Zetland", "photo": {"url": "/static/qi/assets/photos/L-0001-01.jpg", "caption": "Living room"}},
                    {"id": "L-0002", "street": "2 Test St", "suburb": "Redfern", "photo": {"url": "/static/qi/assets/photos/L-0002-01.jpg"}},
                    {"id": "L-0003", "street": "3 Test St", "suburb": "Redfern", "photo": {"url": "/real/999/prep/01.jpg"}}]  # photo not on disk → skipped
        self.model = FakeModel()
        for name, value in (("STYLE_DIR", self.tmp / "style"), ("LOG", self.tmp / "style_facts.jsonl"), ("STATIC_PHOTOS", photos),
                            ("REAL_PHOTOS", self.tmp / "real"), ("ask_model", self.model), ("load_listings", lambda: listings)):
            p = mock.patch.object(style, name, value)
            p.start()
            self.addCleanup(p.stop)

    def post(self, **over):
        body = {"renter": "r-abc123", "images": [{"name": "kitchen.jpg", "data": b64(jpeg(10))}, {"name": "bedroom.png", "data": "data:image/png;base64," + b64(png(11))}]}
        body.update(over)
        return style.api_post(body)

    def test_rejects_bad_requests(self):
        code, out = style.api_post({"images": [{"name": "a.jpg", "data": b64(jpeg(10))}]})
        self.assertEqual(code, 400)
        self.assertIn("renter", out["error"])
        self.assertEqual(style.api_post({"renter": "../x", "images": []})[0], 400)
        self.assertEqual(self.post(images=[])[0], 400)
        code, out = self.post(images=[{"name": "a.jpg", "data": b64(jpeg(10))}] * 4)
        self.assertEqual((code, out["error"]), (400, "At most 3 photos per upload."))
        code, out = self.post(images=[{"name": "a.jpg", "data": "not*base64!!"}])
        self.assertEqual((code, out["error"]), (400, "Photo 1 is not valid base64."))
        big = b"\xff\xd8\xff" + b"\0" * (3 * 1024 * 1024)
        code, out = self.post(images=[{"name": "a.jpg", "data": b64(jpeg(10))}, {"name": "big.jpg", "data": b64(big)}])
        self.assertEqual(code, 400)
        self.assertIn("Photo 2 is larger than 3 MB", out["error"])
        code, out = self.post(images=[{"name": "notes.txt", "data": b64(b"hello there, not a picture")}])
        self.assertEqual((code, out["error"]), (400, "Photo 1 must be a JPEG or PNG."))
        self.assertEqual(self.post(images=[{"name": "a.jpg"}])[0], 400)
        self.assertEqual(self.post(images="nope")[0], 400)
        self.assertEqual(style.api_post(None)[0], 400)
        self.assertEqual(self.model.calls, [])  # nothing reached the model
        self.assertEqual(style.api_get({"renter": [""]})[0], 400)

    def test_reads_reference_scores_listings_and_stores(self):
        code, out = self.post()
        self.assertEqual(code, 200, out)
        self.assertEqual(sorted(out), ["matches", "model", "ms", "profile", "route"])
        p = out["profile"]
        self.assertEqual({a: p[a] for a in style.ATTRS}, {"floor": "timber", "palette": "light", "kitchen": "modern", "light": "bright", "era": "new"})
        self.assertEqual(p["style_words"], ["scandi", "minimalist", "warm timber"])
        self.assertEqual((p["photos"], p["failed"], p["status"]), (2, 0, "inferred"))
        self.assertEqual((out["model"], out["route"]), ("private/nvidia/nemotron-3.5-super-120b-a12b", "nvidia-direct"))
        self.assertEqual(list(out["matches"]), ["L-0001"])  # L-0002 has one comparable attribute, L-0003 no photo on disk
        m = out["matches"]["L-0001"]
        self.assertEqual((m["score"], m["status"], m["reasons"], m["misses"]), (76, "inferred", ["timber floors", "light palette", "new finishes"], ["kitchen looks dated, your reference is modern"]))
        self.assertEqual(m["listing_photo"], "/static/qi/assets/photos/L-0001-01.jpg")
        self.assertEqual(sorted(self.model.calls), ["style_facts", "style_facts", "style_profile", "style_profile"])
        # stored: result + uploads, and the listing readings are cached by sha256
        stored = json.loads((self.tmp / "style" / "r-abc123.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["renter"], stored["uploads"]), ("r-abc123", ["01-kitchen.jpg", "02-bedroom.png"]))
        self.assertEqual(sorted(f.name for f in (self.tmp / "style" / "uploads" / "r-abc123").iterdir()), ["01-kitchen.jpg", "02-bedroom.png"])
        rows = [json.loads(l) for l in (self.tmp / "style_facts.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(r["listing"] for r in rows), ["L-0001", "L-0002"])
        self.assertEqual(sorted(rows[0]), sorted(["ts", "listing", "file", "sha256", "bytes", "route", "nightshift", "provider", "model", "served_model", "ms", "wall_ms", "reading", "raw"]))
        code, got = style.api_get({"renter": ["r-abc123"]})
        self.assertEqual((code, got["profile"]["floor"], got["matches"]["L-0001"]["score"], got["route"]), (200, "timber", 76, "nvidia-direct"))
        # a second upload re-reads the reference photos but not the listings (cache by sha256)
        self.model.calls.clear()
        code, out = self.post(images=[{"name": "one.jpg", "data": b64(jpeg(11))}])
        self.assertEqual((code, out["profile"]["floor"], out["profile"]["photos"]), (200, "carpet", 1))
        self.assertEqual(self.model.calls, ["style_profile"])
        self.assertEqual(out["matches"]["L-0001"]["basis"], "from 1 reference photo and the listing's lead photo")
        self.assertEqual(sorted(f.name for f in (self.tmp / "style" / "uploads" / "r-abc123").iterdir()), ["01-one.jpg"])  # the new set replaces the old

    def test_model_failure_is_502_and_logged(self):
        self.model.fail = True
        code, out = self.post()
        self.assertEqual(code, 502)
        self.assertIn("photo reader", out["error"])
        self.assertFalse((self.tmp / "style" / "r-abc123.json").exists())
        errors = (self.tmp / "style" / "errors.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(errors), 2)  # one per reference photo
        self.assertEqual(style.api_get({"renter": "r-abc123"}), (200, {"profile": None, "matches": {}}))

    def test_forget_removes_result_and_uploads(self):
        self.assertEqual(self.post()[0], 200)
        self.assertEqual(style.forget("r-abc123"), {"style": True, "uploads": 2})
        self.assertFalse((self.tmp / "style" / "uploads" / "r-abc123").exists())
        self.assertEqual(style.api_get({"renter": "r-abc123"}), (200, {"profile": None, "matches": {}}))
        self.assertEqual(style.forget("r-abc123"), {"style": False, "uploads": 0})
        self.assertEqual(style.forget("../etc"), {"style": False, "uploads": 0})
        self.assertEqual(style.forget(None), {"style": False, "uploads": 0})


@unittest.skipUnless(Image, "Pillow is needed to make the test photos")
class HttpRoutes(Routes):
    """同样的用例走真的 server.py（标准库 http.server）：POST / GET /api/style、/api/forget 顺手删。"""

    def setUp(self):
        super().setUp()
        import server  # noqa: E402  src/voice/server.py（导入便宜，不起 TTS）
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_routes_end_to_end(self):
        self.assertEqual(self.call("GET", "/api/style?renter=r-abc123"), (200, {"profile": None, "matches": {}}))
        self.assertEqual(self.call("GET", "/api/style")[0], 400)
        code, out = self.call("POST", "/api/style", {"renter": "r-abc123", "images": [{"name": "a.jpg", "data": b64(jpeg(10))}] * 4})
        self.assertEqual((code, out["error"]), (400, "At most 3 photos per upload."))
        code, out = self.call("POST", "/api/style", {"renter": "r-abc123", "images": [{"name": "a.jpg", "data": b64(jpeg(10))}, {"name": "b.png", "data": b64(png(11))}]})
        self.assertEqual(code, 200, out)
        self.assertEqual((out["profile"]["floor"], out["matches"]["L-0001"]["score"], out["route"]), ("timber", 76, "nvidia-direct"))
        code, got = self.call("GET", "/api/style?renter=r-abc123")
        self.assertEqual((code, got["matches"]["L-0001"]["reasons"]), (200, ["timber floors", "light palette", "new finishes"]))
        self.assertEqual(self.call("POST", "/api/forget", {"renter": "r-abc123"})[0], 204)
        self.assertEqual(self.call("GET", "/api/style?renter=r-abc123"), (200, {"profile": None, "matches": {}}))
        self.assertFalse((self.tmp / "style" / "uploads" / "r-abc123").exists())
        self.model.fail = True
        code, out = self.call("POST", "/api/style", {"renter": "r-abc123", "images": [{"name": "a.jpg", "data": b64(jpeg(10))}]})
        self.assertEqual(code, 502)


if __name__ == "__main__":
    unittest.main()
