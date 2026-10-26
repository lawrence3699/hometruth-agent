#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真房源样本 + 照片新旧 + 日照 + 文化偏好核对包（10-26）：全部离线。
solar.py（朝向词、楼层、太阳几何的常识性检查）、floorplan.py 的规则（指北针 + 主开口 → 朝向；K2–K4；K1 数字）、facts.condition_fact 的合成规则、
scripts/domain_sample.build_one 用保存下来的 Domain JSON + 假读图结果组出矩阵房源、policy 把 D1 / K 包 / 估算通勤 / 中位租金算进格子、phraser 的句子。
跑：.venv/bin/python -m unittest tests/test_real_listings.py -v"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["HOMETRUTH_ENV_FILE"] = ""
os.environ["NEEDS_PARSER"] = "rules"
os.environ["NARRATION_LLM"] = "0"
os.environ["VOICE_VARIETY"] = "0"

import domain_sample as ds  # noqa: E402
import phraser  # noqa: E402
import policy  # noqa: E402
from photo import facts, floorplan as fp  # noqa: E402
from sun import solar  # noqa: E402

MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
BOTANY = ROOT / "data" / "real" / "domain" / "17153470.json"


def reading(room, cond, signs=(), **kw):
    r = {"room": room, "watermark_text": None, "virtual_staging": False, "furniture": [], "cooktop": "unknown", "air_con_unit_visible": False,
         "condition": cond, "condition_signs": list(signs), "condition_confidence": "medium"}
    r.update(kw)
    return r


def row(listing, file, slide, rd):
    return {"ts": "2026-10-26T01:00:00+00:00", "listing": listing, "file": file, "slide": slide, "sha256": "x", "route": "nvidia-direct", "served_model": MODEL, "reading": rd}


class Solar(unittest.TestCase):
    def test_words_and_floors(self):
        self.assertEqual(solar.aspect_from_text("Sunny north-east aspect with city glimpses"), "NE")
        self.assertEqual(solar.aspect_from_text("an easterly aspect and a park outlook"), "E")
        self.assertEqual(solar.aspect_from_text("faces north over the park"), "N")
        self.assertIsNone(solar.aspect_from_text("sun-drenched living room"), "marketing words are not a facing (R-A2)")
        self.assertEqual(solar.floor_from_unit("407"), (4, "unit number"))
        self.assertEqual(solar.floor_from_unit("6"), (None, "unknown"))
        self.assertEqual(solar.floor_from_unit("3", "positioned on the top floor")[0], None)
        self.assertEqual(solar.floor_from_unit("2", "ground floor apartment"), (0, "listing text"))

    def test_sydney_geometry_makes_sense(self):
        n = solar.analyse(-33.92, 151.23, "N", year=2026)
        s = solar.analyse(-33.92, 151.23, "S", year=2026)
        self.assertGreater(n["direct"]["winter"]["hours"], 8, "a north window in Sydney sees the sun nearly all of a winter day")
        self.assertEqual(s["direct"]["winter"]["hours"], 0, "a south window gets no direct winter sun")
        self.assertGreater(s["direct"]["summer"]["hours"], 1, "but some early and late summer sun")
        self.assertLess(max(p["elev"] for p in n["tracks"]["winter"]), 36)
        self.assertGreater(max(p["elev"] for p in n["tracks"]["summer"]), 75)
        st, why = solar.verdict(n)
        self.assertEqual(st, "inferred")
        self.assertIn("sky geometry only", why)
        self.assertEqual(solar.verdict(solar.analyse(-33.92, 151.23, None))[0], "unknown")


class FloorPlanRules(unittest.TestCase):
    PLAN = {"north_arrow": {"present": True, "points": "up"}, "entry_door": {"found": True, "wall": "left"}, "living_main_opening": {"found": True, "wall": "right", "kind": "balcony"},
            "entry_faces_main_opening": True, "bathroom_door_faces_entry": False, "stove_visible_from_entry": None, "kitchen_bathroom_doors_face_each_other": False,
            "outline": "l_shaped", "missing_corner": True, "rooms": ["living", "kitchen"], "confidence": {"north_arrow": "high", "entry": "medium", "opening": "high", "layout": "low"}, "one_line": "A two-bed plan."}

    def test_aspect_from_arrow_and_opening(self):
        self.assertEqual(solar.ASPECTS["E"], 90)
        self.assertEqual(fp.aspect_from_plan(self.PLAN)[0], "E")
        self.assertEqual(fp.aspect_from_plan(dict(self.PLAN, north_arrow={"present": True, "points": "left"}))[0], "S", "north to the left of the page: the right wall faces south")
        self.assertEqual(fp.aspect_from_plan(dict(self.PLAN, north_arrow={"present": False, "points": None}))[0], None)
        self.assertEqual(fp.aspect_from_plan(self.PLAN)[2], "high")

    def test_k_cells_follow_the_plan_with_confidence(self):
        L = {"id": "L-D1", "unit": "407", "street": "1 Test Street"}
        k = fp.k_facts(L, {"url": "/real/1/prep/09.jpg", "row": "plan"}, self.PLAN, MODEL)
        self.assertEqual((k["K2"]["status"], k["K2"]["if_wanted"], k["K2"]["confidence"]), ("inferred", "conflict", "low"))
        self.assertEqual((k["K3"]["status"], k["K3"]["if_wanted"]), ("inferred", "inferred"))
        self.assertEqual((k["K4"]["status"], k["K4"]["value"]), ("inferred", "Missing corner"))
        self.assertEqual(k["K2"]["evidence"][0]["table"], "floorplan_facts")
        blank = fp.k_facts(L, {"url": "/x", "row": "plan"}, {"outline": "unclear"}, MODEL)
        self.assertEqual({d: f["status"] for d, f in blank.items()}, {"K2": "unknown", "K3": "unknown", "K4": "unknown"})
        self.assertEqual((fp.k1_fact(L, 4, "unit number")["status"], fp.k1_fact(L, 4, "unit number")["if_wanted"]), ("inferred", "conflict"))
        self.assertEqual(fp.k1_fact({"id": "L-D2", "unit": "6", "street": "s"}, None, "unknown")["value"], "No 4")


class Condition(unittest.TestCase):
    def test_wet_room_dated_wins_and_is_notable(self):
        L = {"id": "L-0099", "street": "1 Test Street", "suburb": "Zetland"}
        photos = [({"url": "/a.jpg", "caption": "Living room", "row": "01"}, reading("living room", "new", ["fresh paint"]), MODEL),
                  ({"url": "/b.jpg", "caption": "Kitchen", "row": "03"}, reading("kitchen", "dated", ["laminate benchtop", "old tiles"]), MODEL)]
        f = facts.condition_fact(L, photos)
        self.assertEqual((f["status"], f["condition"], f["notable"], f["if_wanted"]), ("inferred", "dated", True, "conflict"))
        self.assertIn("the kitchen looks dated (laminate benchtop, old tiles)", f["why"])
        self.assertIn("condition report", f["why"])
        self.assertEqual([e["row"] for e in f["evidence"]], ["L-0099-photo-01", "L-0099-photo-03"])
        self.assertEqual(facts.condition_fact(L, [(photos[0][0], reading("living room", "new"), MODEL)])["condition"], "new")
        self.assertEqual(facts.condition_fact(L, [(photos[0][0], reading("bedroom", "worn", ["stained carpet"]), MODEL)])["condition"], "worn")
        self.assertIsNone(facts.condition_fact(L, [(photos[0][0], reading("exterior", "unknown"), MODEL)]))
        self.assertIn("finishes look dated (laminate benchtop, old tiles)", facts.photo_line(photos[1][1], "Kitchen"))


@unittest.skipUnless(BOTANY.exists(), "data/real/domain/17153470.json not on this machine")
class DomainSample(unittest.TestCase):
    def setUp(self):
        self.o = json.loads(BOTANY.read_text(encoding="utf-8"))
        lid = ds.lid(self.o)
        self.readings = {ds.file_key(self.o, 2): row(lid, ds.file_key(self.o, 2), 2, reading("living room", "good", ["timber floor"], furniture=["sofa", "dining table"])),
                         ds.file_key(self.o, 3): row(lid, ds.file_key(self.o, 3), 3, reading("kitchen", "dated", ["laminate benchtop"], cooktop="gas"))}

    def test_real_listing_carries_only_real_facts(self):
        L = ds.build_one(self.o, self.readings, None)
        F = L["facts"]
        self.assertEqual((L["id"], L["unit"], L["street"], L["suburb"], L["rent"], L["bedrooms"]), ("L-D17153470", "6", "104 Botany Street", "Kingsford", 850, 2))
        self.assertEqual(F["A1"]["median"], {"rent": 830, "beds": 2, "suburb": "Kingsford", "pct": 2})
        self.assertEqual(F["A1"]["evidence"][1]["table"], "public_rent")
        self.assertEqual((F["E2"]["status"], F["E2"]["value"]), ("inferred", "E-facing"))
        self.assertEqual(F["E2"]["evidence"][0]["table"], "listings")
        self.assertEqual(F["E2"]["evidence"][-1]["table"], "sun_geometry")
        self.assertIn("easterly aspect", F["E2"]["evidence"][0]["text"])
        self.assertGreater(L["sun"]["direct"]["winter"]["hours"], 3)
        self.assertEqual((F["D1"]["condition"], F["D1"]["notable"]), ("dated", True))
        self.assertEqual((F["C3"]["status"], F["C3"]["want"]), ("inferred", "gas"))
        self.assertEqual(F["C2"]["status"], "unknown", "furniture in a photo does not count")
        self.assertEqual(F["J1"]["status"], "unknown")
        self.assertEqual(F["C1"]["status"], "unknown", "ceiling fans, no air con mentioned")
        self.assertEqual(F["E4"]["status"], "inferred", "'quiet pocket' is the agent's word")
        self.assertEqual(F["H1"]["status"], "unknown")
        self.assertEqual((F["K1"]["value"], F["K2"]["status"], F["K4"]["status"]), ("No 4", "unknown", "unknown"))
        self.assertTrue(L["commute"]["unsw"]["estimate"])
        self.assertLess(L["commute"]["unsw"]["min"], 20)
        self.assertEqual(L["source"]["site"], "domain.com.au")
        self.assertEqual(L["photo"]["url"], "/real/17153470/prep/02.jpg", "the living room photo leads")
        self.assertTrue(all(e["table"] != "documents" or e["text"] == "Not asked yet" for f in F.values() for e in f["evidence"]), "no synthetic documents on a real address")

    def test_floor_plan_feeds_k_cells_and_the_aspect_when_the_text_is_silent(self):
        o = dict(self.o, description=["A bright apartment."], headline="Apartment", features=[])
        plan = {"ts": "2026-10-26T01:00:00+00:00", "listing": ds.lid(o), "file": ds.file_key(o, 7), "slide": 7, "route": "nvidia-direct", "served_model": MODEL,
                "reading": FloorPlanRules.PLAN}
        L = ds.build_one(o, self.readings, plan)
        self.assertEqual((L["facts"]["E2"]["status"], L["facts"]["E2"]["value"]), ("inferred", "E-facing"))
        self.assertIn("floor plan's north arrow", L["facts"]["E2"]["why"])
        self.assertEqual(L["facts"]["K2"]["status"], "inferred")
        self.assertEqual(L["floorplan"]["url"], "/real/17153470/prep/07.jpg")
        self.assertEqual(L["facts"]["E4"]["status"], "unknown")


class PolicyAndWords(unittest.TestCase):
    def profile(self, text):
        p = policy.new_profile()
        policy.parse_into(p, text)
        p.update(budget=900, bedrooms=2, anchor="UNSW", move_in={"month": 11, "day": 15, "text": "mid-November"}, pets={"has": True, "kind": "cat", "text": "a cat"})
        return p

    def listing(self):
        o = json.loads(BOTANY.read_text(encoding="utf-8"))
        lid = ds.lid(o)
        rd = {ds.file_key(o, 3): row(lid, ds.file_key(o, 3), 3, reading("kitchen", "dated", ["laminate benchtop"], cooktop="gas"))}
        return ds.build_one(o, rd, None)

    def test_extras_pick_up_condition_and_the_feng_shui_pack(self):
        ex = policy.parse_extras("renovated please, and I do care about feng shui")
        self.assertEqual([e["dim"] for e in ex], ["D1", "K1", "K2", "K3", "K4"])
        self.assertTrue(all(e.get("pack") == "fengshui" for e in ex[1:]))
        self.assertEqual([e["dim"] for e in policy.parse_extras("two bedrooms with a cat")], [], "the pack stays off until the renter asks (R-H0)")

    @unittest.skipUnless(BOTANY.exists(), "needs the saved Domain json")
    def test_cells_for_a_real_listing(self):
        L = self.listing()
        cells = policy.evaluate(L, self.profile("I want winter sun, renovated, feng shui matters"), {})
        self.assertEqual((cells["G1"]["status"], cells["G1"]["estimate"]), ("inferred", True))
        self.assertEqual(cells["A1"]["median"]["rent"], 830)
        self.assertEqual((cells["D1"]["status"], cells["D1"]["short"]), ("conflict", "dated"), "wanted renovated, the kitchen photo looks dated")
        self.assertEqual(cells["E2"]["status"], "inferred")
        self.assertEqual(cells["K1"]["status"], "supported")
        self.assertEqual(cells["K2"]["status"], "unknown")
        plain = policy.evaluate(L, self.profile("two bedrooms"), {})
        self.assertIn("D1", plain, "a dated kitchen is said even when nobody asked (notable)")
        self.assertEqual(plain["D1"]["status"], "inferred")
        self.assertNotIn("K2", plain)
        self.assertIn("Kingsford's median of 830", phraser.cell_sentence("A1", cells["A1"], L, self.profile("")))
        self.assertIn("estimated from the distance", phraser.cell_sentence("G1", cells["G1"], L, self.profile("")))
        self.assertTrue(phraser.cell_sentence("D1", cells["D1"], L, self.profile("")).startswith("Condition: a conflict."))
        self.assertIn("floor plan", phraser.best_question("K2", cells["K2"], self.profile("")))
        card = policy.card_payload(L, cells, 1)
        d1 = next(c for c in card["cells"] if c["dim"] == "D1")
        self.assertTrue(d1["photo"])
        self.assertEqual(card["source"]["listing_id"], 17153470)
        summ = policy.listing_summary(L)
        self.assertEqual(summ["source"]["site"], "domain.com.au")
        self.assertIn("sun", summ)
        self.assertTrue(summ["images"])


if __name__ == "__main__":
    unittest.main()
