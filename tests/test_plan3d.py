#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""玩偶屋数据层（src/photo/plan3d.py）：程序画的合成户型图 → segment 分出正确数量的房间、背景被去掉、门洞（门弧 + 细缝）被合上、
文字不把房间掐断；rooms_from_reading 的归一和同类型合并；assign 的类型匹配（photo_facts 优先、没有的问假模型、卧室按顺序、对不上 null）；
scale 的尺寸文字校准；north_deg 的指北针换算。不调模型、不碰 runs/。
跑：.venv/bin/python -m unittest tests.test_plan3d -v"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["HOMETRUTH_ENV_FILE"] = ""

from photo import plan3d  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


def synthetic_plan(path: Path, with_text: bool = True) -> None:
    """900×600 白纸；外墙 14 px 黑；内墙把它分成 4 间：左上客厅（大）、右上卧室、左下卫生间、右下厨房；
    卧室和客厅之间开 50 px 门洞、画门弧（细灰线，末端离墙 8 px）；卫生间门洞画门弧；厨房和客厅之间 3 px 的细缝（JPEG 那种断点，膨胀后要合上）；
    页边有一行文字和一个指北针圆圈（都不是房间）。"""
    img = Image.new("L", (900, 600), 255)
    d = ImageDraw.Draw(img)
    T = 14
    x0, y0, x1, y1 = 100, 80, 800, 520  # 外墙外沿
    d.rectangle([x0, y0, x1, y1], outline=0, width=T)
    mx, my = 520, 330  # 内墙十字的中心线
    d.rectangle([mx - T // 2, y0, mx + T // 2, y1], fill=0)  # 竖内墙
    d.rectangle([x0, my - T // 2, x1, my + T // 2], fill=0)  # 横内墙
    # 卧室门（竖内墙上段）：门洞 50 px；铰链在上门框，门扇垂直于墙开进卧室，门弧（1 px 浅灰）从门扇末端扫到离下门框 8 px 处（真图上弧都不贴墙）
    d.rectangle([mx - T // 2, 160, mx + T // 2, 210], fill=255)
    hx, hy = mx + T // 2, 160
    d.line([(hx + 1, hy), (hx + 50, hy)], fill=200, width=1)
    d.arc([hx - 50, hy - 50, hx + 50, hy + 50], 0, 80, fill=200, width=1)
    # 卫生间门（横内墙左段）：铰链在右门框，开进卫生间
    d.rectangle([250, my - T // 2, 300, my + T // 2], fill=255)
    hx, hy = 300, my + T // 2
    d.line([(hx, hy + 1), (hx, hy + 50)], fill=200, width=1)
    d.arc([hx - 50, hy - 50, hx + 50, hy + 50], 90, 172, fill=200, width=1)
    # 厨房和客厅之间的细缝（3 px）
    d.rectangle([mx - T // 2, 420, mx + T // 2, 422], fill=255)
    if with_text:
        d.text((180, 150), "LIVING 5.0 x 3.5m", fill=0)
        d.text((600, 150), "BED 1 3.0 x 3.2m", fill=0)
        d.text((150, 400), "BATH", fill=0)
        d.text((620, 400), "KITCHEN", fill=0)
        d.text((120, 540), "Floor plan is indicative only", fill=0)
        d.ellipse([820, 540, 870, 590], outline=0, width=2)
    img.save(path)


@unittest.skipIf(Image is None, "Pillow not installed")
class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = Path(self.tmp.name) / "plan.png"
        synthetic_plan(self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def test_four_rooms_no_background(self):
        seg = plan3d.segment(self.plan, debug_png=Path(self.tmp.name) / "dbg.png")
        self.assertEqual(seg["width"], 900)
        self.assertEqual(len(seg["regions"]), 4, [r["bbox"] for r in seg["regions"]])
        for r in seg["regions"]:
            x, y, w, h = r["bbox"]
            self.assertGreater(x, 100)  # 没有碰到纸边的背景块
            self.assertGreater(y, 80)
            self.assertLess(x + w, 800)
            self.assertLess(y + h, 520)
            self.assertGreaterEqual(len(r["polygon"]), 4)
            self.assertTrue(all(len(p) == 2 for p in r["polygon"]))
        self.assertTrue((Path(self.tmp.name) / "dbg.png").exists())

    def test_doors_closed_and_order(self):
        seg = plan3d.segment(self.plan)
        by_pos = {}
        for r in seg["regions"]:
            cx, cy = r["centroid"]
            by_pos[("L" if cx < 520 else "R") + ("T" if cy < 330 else "B")] = r
        self.assertEqual(set(by_pos), {"LT", "RT", "LB", "RB"})  # 门弧把客厅 / 卧室、客厅 / 卫生间分开，细缝被合上
        living, bed = by_pos["LT"], by_pos["RT"]
        self.assertGreater(living["area_px"], bed["area_px"])
        self.assertEqual([r["id"] for r in seg["regions"]], [1, 2, 3, 4])  # 阅读顺序：上排左右，再下排
        self.assertEqual(by_pos["LT"]["id"], 1)
        self.assertEqual(by_pos["RT"]["id"], 2)
        # 盖章点在区域里（不是墙上）
        for r in seg["regions"]:
            ax, ay = r["anchor"]
            x, y, w, h = r["bbox"]
            self.assertTrue(x <= ax <= x + w and y <= ay <= y + h)

    def test_text_does_not_split_rooms(self):
        plain = Path(self.tmp.name) / "plain.png"
        synthetic_plan(plain, with_text=False)
        a = plan3d.segment(plain)
        b = plan3d.segment(self.plan)
        self.assertEqual(len(a["regions"]), len(b["regions"]))
        for ra, rb in zip(a["regions"], b["regions"]):
            self.assertLess(abs(ra["area_px"] - rb["area_px"]) / ra["area_px"], 0.05)

    def test_components_and_contour(self):
        import numpy as np
        m = np.zeros((10, 12), bool)
        m[1:4, 1:5] = True
        m[6:9, 7:11] = True
        m[6, 1] = True  # 单像素
        labels, st = plan3d.components(m)
        self.assertEqual(len(st), 3)
        areas = sorted(v["area"] for v in st.values())
        self.assertEqual(areas, [1, 12, 12])
        padded = np.zeros((12, 14), bool)
        padded[1:-1, 1:-1] = m[:, :] & (labels == labels[1, 1])
        contour = plan3d.trace_contour(padded)
        self.assertEqual(len(contour), 10)  # 4×3 的块外轮廓 10 个像素
        poly = plan3d.simplify([(float(x), float(y)) for x, y in contour], 0.5)
        self.assertEqual(len(poly), 4)


class RoomsTests(unittest.TestCase):
    REGIONS = [{"id": 1, "area_px": 5000, "bbox": [10, 10, 100, 50], "centroid": [60, 35], "anchor": [60, 35], "polygon": [[10, 10], [110, 10], [110, 60], [10, 60]]},
               {"id": 2, "area_px": 4000, "bbox": [120, 10, 80, 50], "centroid": [160, 35], "anchor": [160, 35], "polygon": [[120, 10], [200, 10], [200, 60], [120, 60]]},
               {"id": 3, "area_px": 3000, "bbox": [10, 70, 90, 40], "centroid": [55, 90], "anchor": [55, 90], "polygon": [[10, 70], [100, 70], [100, 110], [10, 110]]},
               {"id": 4, "area_px": 900, "bbox": [40, 80, 20, 20], "centroid": [50, 90], "anchor": [50, 90], "polygon": [[40, 80], [60, 80], [60, 100], [40, 100]]},
               {"id": 5, "area_px": 2000, "bbox": [120, 70, 80, 40], "centroid": [160, 90], "anchor": [160, 90], "polygon": [[120, 70], [200, 70], [200, 110], [120, 110]]}]
    READING = {"regions": [{"id": 1, "room": "Living/Dining", "label_text": "LIVING", "dims_text": "5.0 x 2.5m", "inside": True, "confidence": "high"},
                           {"id": 2, "room": "bed 1", "label_text": "BED 1", "dims_text": "4.0 x 2.5m", "inside": True, "confidence": "medium"},
                           {"id": 3, "room": "garage", "inside": False, "confidence": "high"},
                           {"id": 4, "room": "garage", "inside": False, "confidence": "low"},
                           {"id": 5, "room": "something odd", "inside": True, "confidence": "weird"}],
               "one_line": "A one-bed flat with a garage."}

    def test_normalise_and_merge(self):
        rooms = plan3d.rooms_from_reading(self.REGIONS, self.READING, "fake-vl")
        by_id = {r["id"]: r for r in rooms}
        self.assertEqual(by_id[1]["type"], "living")
        self.assertEqual(by_id[1]["label"], "Living")
        self.assertTrue(by_id[1]["inside"])
        self.assertEqual(by_id[2]["type"], "bedroom 1")
        self.assertEqual(by_id[2]["label"], "Bedroom 1")
        self.assertEqual(by_id[3]["type"], "garage")
        self.assertFalse(by_id[3]["inside"])
        self.assertNotIn(4, by_id)  # 车库里的小块并进车库
        self.assertEqual(by_id[3]["merged_ids"], [4])
        self.assertEqual(by_id[3]["area_px"], 3900)
        self.assertEqual(by_id[5]["type"], "unknown")
        self.assertEqual(by_id[5]["confidence"], "low")
        self.assertEqual(by_id[5]["read_by"], "fake-vl")

    def test_unanswered_region_is_unknown_low(self):
        rooms = plan3d.rooms_from_reading(self.REGIONS, {"regions": [{"id": 1, "room": "kitchen"}]}, "fake-vl")
        r2 = next(r for r in rooms if r["id"] == 2)
        self.assertEqual((r2["type"], r2["confidence"], r2["inside"]), ("unknown", "low", False))

    def test_adjacent_same_type_merge_uses_union_bbox(self):
        regions = [{"id": 1, "area_px": 5000, "bbox": [10, 10, 100, 50], "centroid": [60, 35], "anchor": [60, 35], "polygon": [[10, 10], [110, 10], [110, 60], [10, 60]]},
                   {"id": 2, "area_px": 4000, "bbox": [112, 10, 80, 50], "centroid": [152, 35], "anchor": [152, 35], "polygon": [[112, 10], [192, 10], [192, 60], [112, 60]]}]
        reading = {"regions": [{"id": 1, "room": "living", "inside": True}, {"id": 2, "room": "living", "inside": True}]}
        rooms = plan3d.rooms_from_reading(regions, reading, "fake-vl")
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["bbox"], [10, 10, 182, 50])
        self.assertEqual(rooms[0]["polygon"], [[10, 10], [192, 10], [192, 60], [10, 60]])

    def test_scale_from_dims_else_nominal(self):
        rooms = plan3d.rooms_from_reading(self.REGIONS, self.READING, "fake-vl")
        s, src = plan3d.scale_m_per_px(rooms)
        self.assertAlmostEqual(s, 0.05, places=3)  # 5.0 m / 100 px、2.5 m / 50 px
        self.assertIn("printed dimensions", src)
        for r in rooms:
            r["dims_text"] = None
        s2, src2 = plan3d.scale_m_per_px(rooms)
        self.assertIn("nominal", src2)
        self.assertAlmostEqual(s2, 12.0 / 190, places=4)  # 室内房间并集 x 10..200

    def test_north_deg(self):
        self.assertEqual(plan3d.north_deg("x", {"north_arrow": {"present": True, "points": "up"}}), 0.0)
        self.assertEqual(plan3d.north_deg("x", {"north_arrow": {"present": True, "points": "right"}}), 90.0)
        self.assertEqual(plan3d.north_deg("x", {"north_arrow": {"present": True, "points": "down-left"}}), 225.0)
        self.assertIsNone(plan3d.north_deg("x", {"north_arrow": {"present": False, "points": None}}))
        self.assertIsNone(plan3d.north_deg("x", {}))


class AssignTests(unittest.TestCase):
    ROOMS = [{"id": 1, "type": "living", "inside": True}, {"id": 2, "type": "kitchen", "inside": True}, {"id": 3, "type": "bedroom 1", "inside": True},
             {"id": 4, "type": "bedroom 2", "inside": True}, {"id": 5, "type": "bathroom", "inside": True}, {"id": 6, "type": "garage", "inside": False}]
    PHOTOS = [{"url": "/real/1/prep/01.jpg", "caption": "Living room"}, {"url": "/real/1/prep/02.jpg", "caption": "Kitchen"},
              {"url": "/real/1/prep/03.jpg", "caption": "Bedroom"}, {"url": "/real/1/prep/04.jpg", "caption": "Bedroom"},
              {"url": "/real/1/prep/05.jpg", "caption": "Bedroom"}, {"url": "/real/1/prep/06.jpg", "caption": "Photo 6"},
              {"url": "/real/1/prep/07.jpg", "caption": "Photo 7"}, {"url": "/real/1/prep/08.jpg", "caption": "Photo 8"}]
    FACTS = {"1/prep/01.jpg": {"served_model": "vl-a", "reading": {"room": "living room", "condition_confidence": "high"}},
             "1/prep/02.jpg": {"served_model": "vl-a", "reading": {"room": "kitchen", "condition_confidence": "medium"}},
             "1/prep/03.jpg": {"served_model": "vl-a", "reading": {"room": "bedroom"}},
             "1/prep/04.jpg": {"served_model": "vl-a", "reading": {"room": "bedroom"}},
             "1/prep/05.jpg": {"served_model": "vl-a", "reading": {"room": "bedroom"}}}

    def fake_ask(self, url, caption):
        self.asked.append(url)
        if url.endswith("06.jpg"):
            return {"served_model": "vl-b", "reading": {"room": "balcony", "features": ["glass balustrade", "outdoor chairs"], "confidence": "high"}}
        if url.endswith("07.jpg"):
            return {"served_model": "vl-b", "reading": {"room": "exterior", "features": ["brick facade"], "confidence": "high"}}
        return None  # 08：模型失败

    def test_assign(self):
        self.asked = []
        out = plan3d.assign("L-D1", self.ROOMS, self.PHOTOS, facts_by_file=self.FACTS, ask=self.fake_ask)
        self.assertEqual(self.asked, ["/real/1/prep/06.jpg", "/real/1/prep/07.jpg", "/real/1/prep/08.jpg"])  # photo_facts 有的不再问
        by = {plan3d.file_key(p["url"]): p for p in out}
        self.assertEqual((by["1/prep/01.jpg"]["room_id"], by["1/prep/01.jpg"]["source"], by["1/prep/01.jpg"]["confidence"]), (1, "photo_facts", "high"))
        self.assertEqual(by["1/prep/02.jpg"]["room_id"], 2)
        self.assertEqual([by[f"1/prep/0{i}.jpg"]["room_id"] for i in (3, 4, 5)], [3, 4, None])  # 卧室按顺序，第三张对不上
        self.assertEqual((by["1/prep/06.jpg"]["room"], by["1/prep/06.jpg"]["room_id"], by["1/prep/06.jpg"]["source"]), ("balcony", None, "model"))  # 没有阳台区域
        self.assertEqual(by["1/prep/06.jpg"]["features"], ["glass balustrade", "outdoor chairs"])
        self.assertEqual((by["1/prep/07.jpg"]["room"], by["1/prep/07.jpg"]["room_id"]), ("exterior", None))
        self.assertEqual((by["1/prep/08.jpg"]["room"], by["1/prep/08.jpg"]["room_id"], by["1/prep/08.jpg"]["source"]), ("other", None, "none"))

    def test_open_plan_fallback_and_single_bedroom(self):
        rooms = [{"id": 1, "type": "living", "inside": True}, {"id": 2, "type": "bedroom 1", "inside": True}]
        facts = {"1/prep/01.jpg": {"served_model": "vl-a", "reading": {"room": "kitchen"}},
                 "1/prep/02.jpg": {"served_model": "vl-a", "reading": {"room": "bedroom"}},
                 "1/prep/03.jpg": {"served_model": "vl-a", "reading": {"room": "bedroom"}}}
        out = plan3d.assign("L-D1", rooms, self.PHOTOS[:3], facts_by_file=facts, ask=lambda u, c: None)
        self.assertEqual((out[0]["room_id"], out[0]["confidence"]), (1, "low"))  # 没有厨房区域：放进客厅，置信度降到 low
        self.assertEqual([p["room_id"] for p in out[1:]], [2, 2])  # 只有一间卧室：两张都归它


if __name__ == "__main__":
    unittest.main()
