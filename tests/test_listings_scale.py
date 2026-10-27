#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""房源从 14 套涨到 150 套左右（10-27，Domain / realestate.com.au 搜索结果页导入）时的规模检查，全部离线、只在内存里：
- 把矩阵里的真房源克隆成约 150 套（新编号 L-D9…，街名换成 data/streets.json 的虚构街名，suburb / 邮编真实；一半去掉正文模拟只有搜索卡片的 card_only），
  对几种需求跑 policy.rank：不抛错、每次 < 1 s、名次 + 被筛掉的 = 总数；listing_summary 全部能 JSON 序列化、编号不重；
- server.py 的 /api/listings 在 150 套时：浏览器说收 gzip 就压（解开后和原样一致），不说或 gzip;q=0 就原样；小 JSON 不压；
  /api/zetaris/<来源>（Zetaris REST 连接器取数的链路）永远不压；
- src/photo/style.py 的 warm --workers：真的 ask_model（闸门 + 预算都跑），只把 llm.chat 换成慢的假模型：看图调用默认一次一个、
  排队等闸门不占预算（一套都不丢）、缓存一行一套不交错、结果顺序和矩阵一致、第二遍全走缓存；STYLE_MODEL_SLOTS（含 .env 里的）能放开并发。
  不连网、不碰 runs/，临时目录测完删掉。
不改真矩阵文件（src/voice/mock_matrix.json）。
跑：.venv/bin/python -m unittest tests.test_listings_scale -v"""
from __future__ import annotations

import base64
import copy
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
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

import policy  # noqa: E402
from llm import provider as llm  # noqa: E402
from photo import style  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

TARGET = 150
STREETS = json.loads((ROOT / "data" / "streets.json").read_text(encoding="utf-8"))
NEEDS = [
    "",  # 还没说需求：只按矩阵登记的事实排
    "Two bedrooms near Central, under 900 a week, I have a cat, moving mid November",
    "A one-bedroom near UNSW under 700, moving early December, no pets",
    "Two bedrooms in Kensington with a dog, under 950 a week, moving 1 December, furnished and quiet",
]


def fat_listings(n: int = TARGET) -> list:
    """矩阵原有房源 + 真房源的克隆，凑够 n 套（只在内存里；矩阵本身已经够 n 套时也至少克隆 10 套，card_only 的用例要用）。
    克隆不带真地址：街名换成虚构街名表里的。"""
    base = list(policy.LISTINGS)
    n = max(n, len(base) + 10)
    real = [L for L in base if L["id"].startswith("L-D")] or base
    streets, subs = STREETS["streets"], STREETS["suburbs"]
    out, k = list(base), 0
    while len(out) < n:
        L = copy.deepcopy(real[k % len(real)])
        k += 1
        sub = subs[k % len(subs)]
        L.update(id=f"L-D{9000000 + k}", unit=str(k % 40 + 1), street=f"{k % 90 + 1} {streets[k % len(streets)]}", suburb=sub["suburb"], postcode=sub["postcode"],
                 rent=int(L["rent"]) + (k % 9 - 4) * 25)
        if isinstance(L.get("source"), dict):
            L["source"] = dict(L["source"], listing_id=9000000 + k, url=None)
        if k % 2 == 0:  # 只有搜索结果卡片：没有正文、标题、设施清单
            for key in ("description", "headline"):
                L.pop(key, None)
            L["features"] = []
            L["card_only"] = True
        out.append(L)
    return out


def profile_for(text: str) -> dict:
    p = policy.new_profile()
    if text:
        policy.parse_into(p, text)
    return p


class RankAtScale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fat = fat_listings()
        cls.patch = mock.patch.object(policy, "LISTINGS", cls.fat)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def test_rank_is_fast_and_complete(self):
        total = len(self.fat)
        self.assertGreaterEqual(total, TARGET)
        for text in NEEDS:
            with self.subTest(needs=text or "(none)"):
                prof = profile_for(text)
                t0 = time.perf_counter()
                ranked, excluded = policy.rank(prof, {})
                ms = (time.perf_counter() - t0) * 1000
                self.assertEqual(len(ranked) + excluded, total)
                self.assertLess(ms, 1000, f"rank over {total} listings took {ms:.0f} ms")
                scores = [r["score"] for r in ranked]
                self.assertEqual(scores, sorted(scores, reverse=True))
                for i, r in enumerate(ranked[:policy.TOP_N], 1):  # 卡片事件也能出
                    json.dumps(policy.card_payload(r["listing"], r["cells"], i), ensure_ascii=False)

    def test_summaries_serialise(self):
        t0 = time.perf_counter()
        rows = [policy.listing_summary(L) for L in self.fat]
        body = json.dumps({"listings": rows}, ensure_ascii=False)
        ms = (time.perf_counter() - t0) * 1000
        self.assertLess(ms, 1000)
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(json.loads(body)["listings"]), len(self.fat))
        card = next(r for r in rows if r["id"] == "L-D9000002")  # card_only 的克隆：没有正文也照样出摘要
        self.assertNotIn("description", card)
        self.assertEqual(card["features"], [])


class ListingsPayload(unittest.TestCase):
    """真的 server.py（标准库 http.server，端口 0）对着 150 套的内存矩阵。"""

    @classmethod
    def setUpClass(cls):
        import server  # noqa: E402
        cls.fat = fat_listings()
        cls.patch = mock.patch.object(server, "LISTINGS", cls.fat)
        cls.patch.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()

    def get(self, path: str, gz: bool):
        req = urllib.request.Request(self.base + path, headers={"Accept-Encoding": "gzip, deflate, br"} if gz else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_gzip_when_asked(self):
        code, h, raw = self.get("/api/listings", gz=False)
        self.assertEqual(code, 200)
        self.assertIsNone(h.get("Content-Encoding"))
        plain = json.loads(raw)
        self.assertEqual(len(plain["listings"]), len(self.fat))
        t0 = time.perf_counter()
        code, h, body = self.get("/api/listings", gz=True)
        ms = (time.perf_counter() - t0) * 1000
        self.assertEqual((code, h.get("Content-Encoding"), h.get("Vary")), (200, "gzip", "Accept-Encoding"))
        self.assertEqual(int(h["Content-Length"]), len(body))
        self.assertLess(len(body), len(raw) // 4, "gzip should shrink the listings JSON a lot")
        self.assertEqual(json.loads(gzip.decompress(body)), plain)
        self.assertLess(ms, 1000)

    def test_small_json_stays_plain(self):
        code, h, raw = self.get("/api/nothing-here", gz=True)
        self.assertEqual(code, 404)
        self.assertIsNone(h.get("Content-Encoding"))
        self.assertEqual(json.loads(raw), {"error": "not found"})

    def test_gzip_refused_with_q0(self):
        req = urllib.request.Request(self.base + "/api/listings", headers={"Accept-Encoding": "gzip;q=0, identity"})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.assertIsNone(r.headers.get("Content-Encoding"))
            self.assertEqual(len(json.loads(r.read())["listings"]), len(self.fat))

    def test_zetaris_rest_tables_never_gzipped(self):
        import server  # noqa: E402
        code, h, raw = self.get("/api/zetaris/listings", gz=True)
        self.assertEqual(code, 200)
        self.assertGreaterEqual(len(raw), server.GZIP_MIN, "big enough that it would have been compressed")
        self.assertIsNone(h.get("Content-Encoding"))
        self.assertEqual(json.loads(raw)["source"], "listings")

    def test_accepts_gzip_header_parsing(self):
        import server  # noqa: E402
        cases = {"gzip, deflate, br": True, "GZIP": True, "br;q=1.0, gzip;q=0.8, *;q=0.1": True, "*": True, "x-gzip": True,
                 "gzip;q=0": False, "gzip;q=0.0, br": False, "identity": False, "": False, None: False, "*;q=0": False,
                 "br, *;q=0.5": True, "gzip;q=0, *": False, "gzip;q=bad": False}
        for header, want in cases.items():
            with self.subTest(header=header):
                self.assertIs(server.accepts_gzip(header), want)


@unittest.skipUnless(Image, "Pillow is needed to make the test photos")
class StyleWarmWorkers(unittest.TestCase):
    """style.listing_profiles(workers=3) 走真的 ask_model（闸门 _model_gate + 每张图的预算都跑），只把 llm.chat 换成慢的假模型
    （按图的颜色回读数，记录同时在途的调用数）；缓存在临时目录。
    预算 TIMEOUT 只比 ask_model 的 10 s 下限多 0.5 s：要是排队等闸门也算进预算（10-27 评审抓到的 bug），排在两次调用后面的房子
    （等约 2 × DELAY = 0.6 s）一上来就 "no time left"，套数就对不上。"""

    N = 6
    DELAY = 0.3
    TIMEOUT = 10.5

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ht-scale-style-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        photos = self.tmp / "photos"
        photos.mkdir()
        listings = []
        for i in range(self.N):
            buf = io.BytesIO()
            Image.new("RGB", (24, 24), (40 * i, 100, 150)).save(buf, "JPEG", quality=95)
            (photos / f"S{i}.jpg").write_bytes(buf.getvalue())
            sub = STREETS["suburbs"][i % len(STREETS["suburbs"])]
            listings.append({"id": f"L-S{i:03d}", "street": f"{i + 1} {STREETS['streets'][i]}", "suburb": sub["suburb"],
                             "photo": {"url": f"/static/qi/assets/photos/S{i}.jpg", "caption": "Living room"}})
        listings.append({"id": "L-S999", "street": "9 Alder Lane", "suburb": "Zetland", "photo": {"url": "/real/none/prep/01.jpg"}})  # 照片不在盘上 → 跳过
        self.listings = listings
        self.lock = threading.Lock()
        self.in_flight = self.peak = self.calls = 0
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("STYLE_MODEL_SLOTS", None)
        for target, name, value in ((style, "STYLE_DIR", self.tmp / "style"), (style, "LOG", self.tmp / "style_facts.jsonl"),
                                    (style, "STATIC_PHOTOS", photos), (style, "REAL_PHOTOS", self.tmp / "real"),
                                    (style, "load_listings", lambda: listings),
                                    (style, "_model_lock", None),  # 闸门按这个测试的环境变量重建，测完恢复
                                    (llm, "chat", self.fake_chat)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def fake_chat(self, msgs, **kw):
        with self.lock:
            self.calls += 1
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            time.sleep(self.DELAY)
            url = msgs[-1]["content"][1]["image_url"]["url"]
            red = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB").getpixel((12, 12))[0]
            reading = {"floor": "timber" if red < 90 else "carpet", "palette": "light", "kitchen": "modern", "light": "bright", "era": "new",
                       "style_words": ["minimalist"], "one_line": f"Room {red}."}
            return llm.ChatResult(text=json.dumps(reading), provider="nvidia", model="nvidia/nemotron-3.5-super-vl-120b-a12b",
                                  served_model="nemotron-vl", ms=int(self.DELAY * 1000))
        finally:
            with self.lock:
                self.in_flight -= 1

    def warm(self, workers: int) -> dict:
        with mock.patch("builtins.print"):
            return style.listing_profiles(read_missing=True, workers=workers, verbose=True, timeout=self.TIMEOUT)

    def test_parallel_warm_is_serial_at_the_model_and_loses_nothing(self):
        got = self.warm(3)
        errors = self.tmp / "style" / "errors.jsonl"
        self.assertFalse(errors.exists(), errors.read_text(encoding="utf-8") if errors.exists() else "")
        self.assertEqual(list(got), [L["id"] for L in self.listings[:self.N]], "every listing with a photo, same order as the matrix")
        self.assertEqual(self.calls, self.N)
        self.assertEqual(self.peak, 1, "model calls stay one at a time unless STYLE_MODEL_SLOTS says otherwise")
        lines = (self.tmp / "style_facts.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), self.N)
        rows = [json.loads(x) for x in lines]  # 每行都是完整的 JSON（追加没交错）
        self.assertEqual(sorted(r["listing"] for r in rows), sorted(got))
        self.assertEqual({k: v["floor"] for k, v in got.items()}, {f"L-S{i:03d}": "timber" if 40 * i < 90 else "carpet" for i in range(self.N)})
        again = self.warm(1)  # 第二遍串行、全走缓存
        self.assertEqual(self.calls, self.N)
        self.assertEqual({k: v["floor"] for k, v in again.items()}, {k: v["floor"] for k, v in got.items()})

    def test_slots_env_opens_parallel_model_calls(self):
        os.environ["STYLE_MODEL_SLOTS"] = "3"
        got = self.warm(3)
        self.assertEqual(len(got), self.N)
        self.assertGreaterEqual(self.peak, 2)
        self.assertLessEqual(self.peak, 3)

    def test_slots_from_dotenv_after_import(self):
        """style 在 load_env 之前就 import 了（style.py main / server.main 都这样）；闸门第一次用时才建，所以 .env 里的值也算数。"""
        envf = self.tmp / "slots.env"
        envf.write_text("STYLE_MODEL_SLOTS=2\n", encoding="utf-8")
        os.environ["HOMETRUTH_ENV_FILE"] = str(envf)
        with mock.patch.object(llm, "_env_loaded", False):
            llm.load_env()
        self.assertEqual(os.environ.get("STYLE_MODEL_SLOTS"), "2")
        gate = style._model_gate()
        self.assertTrue(gate.acquire(blocking=False))
        self.assertTrue(gate.acquire(blocking=False))
        self.assertFalse(gate.acquire(blocking=False), "two slots, not one and not three")
        gate.release()
        gate.release()
        self.assertIs(style._model_gate(), gate, "built once per process")

    def test_slot_parsing(self):
        os.environ.pop("STYLE_MODEL_SLOTS", None)
        self.assertEqual(style._model_slots(), 1)
        os.environ["STYLE_MODEL_SLOTS"] = "three"
        self.assertEqual(style._model_slots(), 1)
        os.environ["STYLE_MODEL_SLOTS"] = "0"
        self.assertEqual(style._model_slots(), 1)
        os.environ["STYLE_MODEL_SLOTS"] = "3"
        self.assertEqual(style._model_slots(), 3)


if __name__ == "__main__":
    unittest.main()


class CardPayloadFields(unittest.TestCase):
    """10-27：card_payload 一行里插注释曾把 rent / bedrooms 吃掉（页面所有价格变空）。每套房的摘要都必须带这几样。"""

    def test_every_summary_has_rent_bedrooms_title(self):
        P = policy  # 文件头已经 import 过（src/voice 在 sys.path 上）
        for L in P.LISTINGS:
            s = P.listing_summary(L)
            for k in ("id", "title", "rent", "bedrooms", "bathrooms", "available_from"):
                self.assertIn(k, s, (L["id"], k))
            self.assertIsInstance(s["rent"], int, L["id"])
            self.assertFalse(s["title"].startswith("/"), s["title"])
