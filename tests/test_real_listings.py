#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真房源样本 + 照片新旧 + 日照 + 文化偏好核对包（10-26）：全部离线。
solar.py（朝向词、楼层、太阳几何的常识性检查）、floorplan.py 的规则（指北针 + 主开口 → 朝向；K2–K4；K1 数字）、facts.condition_fact 的合成规则、
scripts/domain_sample.build_one 用保存下来的 Domain JSON + 假读图结果组出矩阵房源、policy 把 D1 / K 包 / 估算通勤 / 中位租金算进格子、phraser 的句子。
10-27 加：搜索结果卡片（card_only，没有正文 / 可入住日）和 realestate.com.au 房源（L-R<编号>、照片目录 R<编号>）、最近站定通勤方式、干道表、
NSW 押金登记中位租金（bond_rents 用假的 lookup 代替，不读 CSV）、可入住日为空时 policy 当未知（硬条件待确认，不崩）。
审查后补：没卧室数 / 车位 / 已定出的卡片不进矩阵、没卫生间数不写 0、引文只引规则真对上的那句并说出处、卡片的户型图另外下载、
照片没读过不说"没有户型图"、到 UNSW 离火车站近写 train and light rail、build 写的来源行数（假矩阵副本，不碰真文件）。
卡片样本的街名取 data/streets.json（虚构），suburb / 邮编真实，不用真实完整地址。
跑：.venv/bin/python -m unittest tests/test_real_listings.py -v"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

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
STREETS = json.loads((ROOT / "data" / "streets.json").read_text(encoding="utf-8"))["streets"]


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
        self.assertTrue(phraser.cell_sentence("D1", cells["D1"], L, self.profile("")).startswith("Condition: doesn't match what you asked."))
        self.assertIn("floor plan", phraser.best_question("K2", cells["K2"], self.profile("")))
        card = policy.card_payload(L, cells, 1)
        d1 = next(c for c in card["cells"] if c["dim"] == "D1")
        self.assertTrue(d1["photo"])
        self.assertEqual(card["source"]["listing_id"], 17153470)
        summ = policy.listing_summary(L)
        self.assertEqual(summ["source"]["site"], "domain.com.au")
        self.assertIn("sun", summ)
        self.assertTrue(summ["images"])


def card(**kw):
    """搜索结果卡片样本：价格、地址、坐标、户型、类型、中介、几张图；没有标题、正文、可入住日、押金。街名虚构，坐标在 Kensington 轻轨站旁。"""
    o = {"id": 90000001, "url": "https://example.test/listing/90000001", "unit": "3", "streetNumber": "12", "street": STREETS[5], "suburb": "Kensington",
         "postcode": "2033", "type": "Apartment / Unit / Flat", "beds": 2, "baths": 1, "parking": 1, "price": "$820 per week", "agency": "Test Agency",
         "headline": "", "description": [], "features": [], "lat": -33.9088, "lng": 151.2236, "fetched_at": "2026-10-27T10:00:00+11:00",
         "slides": [{"type": "image", "url": "https://cdn.example.test/1.jpg"}, {"type": "image", "url": "https://cdn.example.test/2.jpg"}],
         "site": "domain", "card_only": True}
    o.update(kw)
    return o


FAKE_REC = {"postcode": "2033", "beds": 2, "dwelling": "F", "dwelling_label": "flat/unit", "n": 212, "median": 780, "q1": 700, "q3": 850,
            "months": "Apr–Sep 2026", "source": "NSW Fair Trading rental bond lodgements", "source_url": "https://www.fairtrading.nsw.gov.au/about-fair-trading/rental-bond-data"}


def fake_bonds(rec=FAKE_REC, calls=None, boom=None):
    def lookup(postcode, beds, dwelling="F"):
        if calls is not None:
            calls.append((postcode, beds, dwelling))
        if boom:
            raise boom
        return rec
    return types.SimpleNamespace(lookup=lookup, evidence_text=lambda rent, r: f"NSW Fair Trading: {r['n']} new leases, median ${r['median']}; this one asks ${rent}.")


class CardOnlyListing(unittest.TestCase):
    def test_card_is_honest_about_what_it_does_not_know(self):
        calls = []
        with mock.patch.object(ds, "bond_rents", fake_bonds(calls=calls)):
            L = ds.build_one(card(), {}, None)
        F = L["facts"]
        self.assertEqual(L["id"], "L-D90000001")
        self.assertIsNone(L["available_from"], "no date on the card: not today, not anything")
        self.assertEqual(F["A4"]["status"], "unknown")
        self.assertIn("no move-in date", F["A4"]["why"])
        for d in ("J1", "C1", "A6", "E4", "C2", "C3", "E2", "K2", "K3", "K4"):
            self.assertEqual(F[d]["status"], "unknown", d)
            self.assertIn("search card", F[d]["why"], f"{d} must say we only saw a search card")
            self.assertNotIn("says nothing", F[d]["why"], d)
            self.assertFalse(F[d]["why"].startswith(("The listing", "Nothing in the listing")), d)
        self.assertIn("no photo has been read yet", F["C3"]["why"])
        self.assertEqual(calls, [("2033", 2, "Apartment / Unit / Flat")])
        bond = F["A1"]["evidence"][-1]
        self.assertEqual((bond["table"], bond["row"], bond["material_id"]), ("public_rent", "nsw-bonds/2033/2-bed-F", None))
        self.assertIn("NSW Fair Trading", bond["text"])
        self.assertEqual(F["A1"]["median"], {"rent": 780, "beds": 2, "suburb": "Kensington", "pct": 5, "source": "nsw-bonds", "n": 212, "months": "Apr–Sep 2026"})
        self.assertNotIn("own words", L["special"], "no words on the card, so nothing is quoted")
        self.assertEqual(L["special"], f"2 bed, 1 bath, 1 car on 12 {STREETS[5]}")
        self.assertEqual((L["headline"], L["description"]), ("", []))
        self.assertTrue(L["source"]["card_only"])
        self.assertEqual(L["source"]["site"], "domain.com.au")
        self.assertEqual(F["H1"]["status"], "unknown")
        self.assertTrue(all(e["table"] != "documents" or e["text"] == "Not asked yet" for f in F.values() for e in f["evidence"]), "no synthetic documents on a real address")

    def test_bond_line_follows_the_domain_median_and_is_skipped_quietly_without_data(self):
        o = card(card_only=False, headline="Bright flat", description=["A bright flat."], medianRent=800, medianBeds=2, stats={"availableFrom": "2026-11-02T00:00:00", "bond": 3280})
        with mock.patch.object(ds, "bond_rents", fake_bonds()):
            L = ds.build_one(o, {}, None)
        ev = L["facts"]["A1"]["evidence"]
        self.assertEqual([e["table"] for e in ev], ["listings", "public_rent", "public_rent"])
        self.assertTrue(ev[1]["row"].startswith("domain-median/") and ev[2]["row"].startswith("nsw-bonds/"), "Domain first, the bond line after it")
        self.assertEqual(L["facts"]["A1"]["median"], {"rent": 800, "beds": 2, "suburb": "Kensington", "pct": 2}, "the Domain median stays the cell's median")
        self.assertEqual(L["available_from"], "2026-11-02")
        self.assertNotIn("status", L["facts"]["A4"])
        for bonds in (None, fake_bonds(rec=None), fake_bonds(boom=FileNotFoundError("no csv"))):
            with mock.patch.object(ds, "bond_rents", bonds):
                L = ds.build_one(card(), {}, None)
            self.assertEqual([e["table"] for e in L["facts"]["A1"]["evidence"]], ["listings"])
            self.assertIsNone(L["facts"]["A1"]["median"])
        with mock.patch.object(ds, "bond_rents", fake_bonds()):
            self.assertEqual(len(ds.build_one(card(type=None), {}, None)["facts"]["A1"]["evidence"]), 1, "no property type: don't guess flat or house")

    def test_rea_listing_gets_its_own_id_and_photo_folder(self):
        o = card(id=4123456, site="rea", also_on=[{"site": "domain.com.au", "listing_id": 90000001}])
        key = ds.file_key(o, 1)
        rd = {key: row("L-R4123456", key, 1, reading("living room", "good", ["fresh paint"]))}
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(o, rd, None)
        self.assertEqual((L["id"], key), ("L-R4123456", "R4123456/prep/01.jpg"))
        self.assertEqual(ds.slide_file(o, 1, prep=True).parent.parent.name, "R4123456")
        self.assertEqual(L["photo"]["url"], "/real/R4123456/prep/01.jpg")
        self.assertEqual(L["photo"]["source"], "realestate.com.au listing 4123456")
        self.assertEqual(L["source"]["site"], "realestate.com.au")
        self.assertEqual(L["source"]["also_on"], [{"site": "domain.com.au", "listing_id": 90000001}])
        self.assertTrue(ds.matches(o, "4123456") and ds.matches(o, "L-R4123456"))
        self.assertFalse(ds.matches(o, "L-D4123456"))

    def test_a_photo_read_as_a_floor_plan_counts_as_the_plan(self):
        o = card()
        rd = {ds.file_key(o, 1): row("L-D90000001", ds.file_key(o, 1), 1, reading("living room", "good", one_line="An open floor plan living room.")),
              ds.file_key(o, 2): row("L-D90000001", ds.file_key(o, 2), 2, reading("other", "unknown", one_line="A floor plan of a two-bedroom unit."))}
        self.assertEqual(ds.floorplan_slides(o, rd), [2], "only the 'other' slide whose reading says floor plan; a living room photo is not a plan")
        self.assertEqual(ds.floorplan_slides(dict(o, slides=[{"type": "image"}, {"type": "floorplan"}]), {}), [2])
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(o, rd, None)
        self.assertEqual(L["photo"]["url"], "/real/90000001/prep/01.jpg", "the plan is never the lead photo")

    def test_load_reads_both_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            dom, rea = Path(tmp) / "domain", Path(tmp) / "rea"
            dom.mkdir()
            rea.mkdir()
            (dom / "90000001.json").write_text(json.dumps(card()), encoding="utf-8")
            (rea / "4123456.json").write_text(json.dumps({k: v for k, v in card(id=4123456).items() if k != "site"}), encoding="utf-8")
            with mock.patch.object(ds, "DOMAIN", dom), mock.patch.object(ds, "REA", rea):
                self.assertEqual([ds.lid(o) for o in ds.load()], ["L-D90000001", "L-R4123456"], "a file in rea/ without a site key is REA")
                self.assertEqual([ds.lid(o) for o in ds.load("L-R4123456")], ["L-R4123456"])

    def test_unusable_cards_and_prices(self):
        self.assertEqual(ds.parse_rent("$850 per week"), 850)
        self.assertEqual(ds.parse_rent("$1,050.00 per week"), 1050)
        self.assertEqual(ds.parse_rent("$800 - $850 pw"), 800)
        self.assertEqual(ds.parse_rent("Contact agent"), 0)
        self.assertEqual(ds.parse_rent("$3,500 per month"), 0, "monthly prices are not turned into a weekly rent")
        self.assertIsNone(ds.unusable(card()))
        self.assertIn("coordinates", ds.unusable(card(lat=None)))
        self.assertIn("rent", ds.unusable(card(price="Deposit taken")))
        self.assertFalse(ds.image_url_ok("https://www.domain.com.au/some-listing-1"), "listing pages are never fetched")
        self.assertFalse(ds.image_url_ok("https://www.realestate.com.au/property-x"))
        self.assertTrue(ds.image_url_ok("https://rimh2.domainstatic.com.au/abc/1.jpg"))


class CommuteAndRoads(unittest.TestCase):
    def test_mode_follows_the_nearest_stop(self):
        redfern = ds.commute_estimate(card(lat=-33.8925, lng=151.1995, suburb="Redfern", postcode="2016"))
        self.assertEqual((redfern["central"]["mode"], redfern["central"]["stop"]), ("train", "Redfern"))
        anzac = ds.commute_estimate(card(lat=-33.9210, lng=151.2268, suburb="Kingsford", postcode="2032"))
        self.assertEqual((anzac["unsw"]["mode"], anzac["unsw"]["stop"]), ("light rail", "Kingsford"))
        self.assertEqual((redfern["unsw"]["mode"], redfern["unsw"]["stop"]), ("train and light rail", "Redfern"), "no train reaches UNSW: change to the light rail")
        self.assertEqual(anzac["central"]["mode"], "light rail", "L3 runs up Anzac Parade to Central")
        far = ds.commute_estimate(card(lat=-33.9200, lng=151.2560, suburb="Randwick", postcode="2031"))
        self.assertEqual(far["unsw"]["mode"], "bus")
        self.assertNotIn("stop", far["unsw"])
        for c in (redfern, anzac, far):
            self.assertTrue(all(r["estimate"] for r in c.values()))
            self.assertLessEqual(abs(c["unsw"]["min"] - (8 + c["unsw"]["km"] * 3.75)), 1, "minutes still come from the straight-line distance")

    def test_main_roads(self):
        self.assertTrue(ds.main_road("Anzac Parade", "Kingsford"))
        self.assertTrue(ds.main_road("Anzac Pde", "Maroubra"))
        self.assertTrue(ds.main_road("Botany Road", "Rosebery"))
        self.assertTrue(ds.main_road("O’Riordan Street", "Alexandria"))
        self.assertTrue(ds.main_road("Regent Street", "Redfern"))
        self.assertFalse(ds.main_road("Regent Street", "Kensington"), "a small street with the same name elsewhere")
        self.assertFalse(ds.main_road("Botany Street", "Kingsford"))
        self.assertFalse(ds.main_road(STREETS[0], "Zetland"))
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(card(unit="", streetNumber="", street="Gardeners Road", suburb="Kingsford", postcode="2032"), {}, None)
        self.assertEqual((L["facts"]["E4"]["status"], L["facts"]["E4"]["value"]), ("conflict", "Main road"))
        self.assertIn("fronts Gardeners Road, a main road, and the search card doesn't mention noise", L["facts"]["E4"]["why"])


class MissingMoveInDate(unittest.TestCase):
    def test_policy_treats_no_date_as_unknown_not_a_yes(self):
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(card(), {}, None)
            dated = ds.build_one(card(id=90000002, card_only=False, stats={"availableFrom": "2026-10-20T00:00:00"}), {}, None)
        p = policy.new_profile()
        policy.parse_into(p, "two bedrooms")
        p.update(budget=900, bedrooms=2, anchor="UNSW", move_in={"month": 11, "day": 15, "text": "mid-November"}, pets={"has": False, "text": "no pets"})
        cells = policy.evaluate(L, p, {})
        a4 = cells["A4"]
        self.assertEqual((a4["status"], a4["value"], a4["fail"], a4["hard"]), ("unknown", None, False, True))
        self.assertEqual(a4["next"]["kind"], "ask_agent")
        self.assertIn("no move-in date", a4["why"])
        self.assertEqual(policy.evaluate(dated, p, {})["A4"]["status"], "supported")
        with mock.patch.object(policy, "LISTINGS", [L, dated]):
            ranked, excluded = policy.rank(p, {})
            self.assertEqual(excluded, 0, "unknown is not a reason to drop the place")
            got = {r["listing"]["id"]: r for r in ranked}
            self.assertEqual(got["L-D90000001"]["cells"]["A4"]["status"], "unknown")
            self.assertGreater(got["L-D90000001"]["counts"]["open"], got["L-D90000002"]["counts"]["open"], "the missing date stays open, it is not counted as a yes")
            self.assertLess(got["L-D90000001"]["score"], got["L-D90000002"]["score"])
            policy.build_tour(ranked, p, excluded)  # 不崩
        card_ = policy.card_payload(L, cells, 1)
        self.assertIsNone(card_["available_from"])
        self.assertEqual(next(c for c in card_["cells"] if c["dim"] == "A4")["short"], "no date")
        summ = policy.listing_summary(L)
        self.assertIsNone(summ["available_from"])
        self.assertEqual(next(f for f in summ["facts"] if f["dim"] == "A4")["status"], "unknown")


class ReviewFixes(unittest.TestCase):
    """10-27 审查：只写来源真说了的；说不准的留未知。"""

    def test_cards_without_a_bed_count_or_that_are_not_homes_are_skipped(self):
        self.assertEqual(ds.unusable(card(beds=None)), "no bedroom count on the card")
        self.assertIsNone(ds.unusable(card(beds=None, type="Studio")), "a studio is 0 bedrooms")
        self.assertEqual(ds.beds_of(card(beds=None, type="Studio")), 0)
        self.assertIn("not a home", ds.unusable(card(type="Car Space", beds=None)))
        self.assertIn("not a home", ds.unusable(card(type="Garage", beds=0)))
        self.assertIn("DEPOSIT TAKEN", ds.unusable(card(tag="DEPOSIT TAKEN")))
        self.assertIsNone(ds.unusable(card(tag="New")))

    def test_a_missing_bath_count_is_left_out_not_written_as_zero(self):
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(card(baths=None), {}, None)
        self.assertIsNone(L["bathrooms"])
        self.assertEqual(L["facts"]["B1"]["evidence"][0]["text"], "2 bed, 1 car")
        self.assertEqual(L["special"], f"2 bed, 1 car on 12 {STREETS[5]}")
        self.assertNotIn("0 bath", json.dumps(L))

    def test_quotes_are_the_words_that_matched_with_where_they_came_from(self):
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(card(headline="Pet friendly two bedroom with ducted air"), {}, None)
        F = L["facts"]
        self.assertEqual(F["J1"]["status"], "inferred")
        self.assertEqual(F["J1"]["evidence"][0]["text"], "search card headline: 'Pet friendly two bedroom with ducted air'")
        self.assertTrue(F["J1"]["why"].startswith("The search card's headline says 'Pet friendly"))
        self.assertEqual(F["C1"]["status"], "inferred")
        self.assertIn("search card headline: 'Pet friendly two bedroom with ducted air'", F["C1"]["evidence"][0]["text"])
        blob = json.dumps(F)
        self.assertNotIn("Pets Allowed", blob, "no feature quote the card never had")
        self.assertNotIn("features:", blob)
        with mock.patch.object(ds, "bond_rents", None):
            no = ds.build_one(card(headline="Two bedroom unit, no pets allowed"), {}, None)["facts"]["J1"]
            heat = ds.build_one(card(headline="Two bedroom unit with ducted heating"), {}, None)["facts"]["C1"]
            water = ds.build_one(card(card_only=False, description=["Water usage is not included in the rent."]), {}, None)["facts"]["A6"]
        self.assertEqual(no["status"], "conflict", "'No pets allowed' is not 'pets allowed'")
        self.assertIn("'Two bedroom unit, no pets allowed'", no["evidence"][0]["text"])
        self.assertEqual(heat["status"], "unknown", "ducted heating is not air conditioning")
        self.assertEqual((water["status"], water["value"]), ("conflict", "Not included"), "'not included' is never read as included")
        self.assertIn("The listing description says 'Water usage is not included in the rent'", water["why"])

    @unittest.skipUnless(BOTANY.exists(), "needs the saved Domain json")
    def test_saved_listing_quotes_its_own_sentence(self):
        o = json.loads(BOTANY.read_text(encoding="utf-8"))
        with mock.patch.object(ds, "bond_rents", None):
            F = ds.build_one(o, {}, None)["facts"]
        self.assertIn("quiet pocket", F["E4"]["evidence"][0]["text"])
        self.assertTrue(F["E4"]["evidence"][0]["text"].startswith("description: '"))
        self.assertTrue(F["E4"]["why"].startswith("The listing description says '"))
        self.assertEqual(ds.said(dict(o, description=["Peacefully located near the park."]), r"peaceful")["quote"], "Peacefully located near the park")

    def test_card_floor_plans_are_fetched_beyond_the_photo_cap(self):
        o = card(id=4123457, site="rea", slides=[{"type": "image", "url": f"https://cdn.example.test/{k}.jpg"} for k in range(8)] +
                 [{"type": "floorplan", "url": "https://cdn.example.test/plan.jpg"}])
        got = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"x"

        def urlopen(req, timeout=30):
            got.append(req.full_url)
            if req.full_url.endswith("/2.jpg"):
                raise OSError("boom")
            return Resp()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, "PHOTOS", Path(tmp)), mock.patch.object(ds, "FETCH_GAP", 0), \
                mock.patch.object(ds.urllib.request, "urlopen", urlopen), mock.patch.object(ds, "say", lambda *a: None):
            self.assertEqual(ds.fetch(o, 3), 3, "one image failed, the rest carried on")
            self.assertEqual(got, [f"https://cdn.example.test/{k}.jpg" for k in range(3)] + ["https://cdn.example.test/plan.jpg"])
            self.assertTrue(ds.slide_file(o, 9).exists())
            got.clear()
            ds.fetch(o, 3)
            self.assertEqual(got, ["https://cdn.example.test/2.jpg"], "files already on disk are skipped")

    def test_no_floor_plan_is_only_said_after_looking(self):
        with mock.patch.object(ds, "bond_rents", None):
            fresh = ds.build_one(card(), {}, None)["facts"]
            listed = ds.build_one(card(slides=card()["slides"] + [{"type": "floorplan", "url": "https://cdn.example.test/p.jpg"}]), {}, None)["facts"]
            key = ds.file_key(card(), 1)
            read_ = ds.build_one(card(), {key: row("L-D90000001", key, 1, reading("living room", "good"))}, None)["facts"]
        self.assertIn("haven't been checked for a floor plan yet", fresh["E2"]["why"])
        self.assertIn("haven't been checked for a floor plan yet", fresh["K2"]["why"])
        self.assertNotIn("no floor plan", fresh["E2"]["why"].lower())
        self.assertIn("The floor plan hasn't been read yet", listed["E2"]["why"])
        self.assertIn("The floor plan hasn't been read yet", listed["K3"]["why"])
        self.assertIn("None of the search card's photos read so far is a floor plan", read_["E2"]["why"])
        self.assertIn("No floor plan among the search card's photos read so far", read_["K4"]["why"])

    def test_agent_reply_settles_a_missing_move_in_date(self):
        with mock.patch.object(ds, "bond_rents", None):
            L = ds.build_one(card(), {}, None)
        p = policy.new_profile()
        policy.parse_into(p, "two bedrooms")
        p.update(budget=900, bedrooms=2, anchor="UNSW", move_in={"month": 11, "day": 15, "text": "mid-November"}, pets={"has": False, "text": "no pets"})
        ov = {"A4": {"status": "supported", "why": "The agent says it is free from 10 November.",
                     "evidence": [{"table": "documents", "row": "agent_replies/L-D90000001", "material_id": "M-D90000001-reply-01", "text": "free from 10 November"}]}}
        a4 = policy.evaluate(L, p, ov)["A4"]
        self.assertEqual((a4["status"], a4["short"], a4["fail"]), ("supported", "per agent", False))
        self.assertEqual(a4["evidence"][0]["table"], "documents")
        self.assertEqual(policy.evaluate(L, p, {})["A4"]["short"], "no date")

    def test_build_counts_rea_listings_and_bond_rows_in_the_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            dom, rea, mx = Path(tmp) / "domain", Path(tmp) / "rea", Path(tmp) / "matrix.json"
            dom.mkdir()
            rea.mkdir()
            mx.write_text(ds.MATRIX.read_text(encoding="utf-8"), encoding="utf-8")
            (dom / "90000001.json").write_text(json.dumps(card()), encoding="utf-8")
            (dom / "90000002.json").write_text(json.dumps(card(id=90000002, beds=None, type="Car Space")), encoding="utf-8")
            (rea / "4123456.json").write_text(json.dumps(card(id=4123456, site="rea", postcode="2032", suburb="Kingsford")), encoding="utf-8")
            with mock.patch.object(ds, "DOMAIN", dom), mock.patch.object(ds, "REA", rea), mock.patch.object(ds, "MATRIX", mx), \
                    mock.patch.object(ds, "bond_rents", fake_bonds()), mock.patch.object(ds.facts, "readings_by_file", lambda: {}), \
                    mock.patch.object(ds.fp, "latest", lambda: {}), mock.patch("builtins.print"):
                self.assertEqual(ds.build(None, False), 2, "the car space is skipped")
            m = json.loads(mx.read_text(encoding="utf-8"))
        real = [L["id"] for L in m["listings"] if ds.is_real(L["id"])]
        self.assertEqual(sorted(real), ["L-D90000001", "L-R4123456"])
        src = {s["name"]: s for s in m["sources"]}
        self.assertEqual(src["listings"]["rows"], ds.SYNTH_LISTING_ROWS + 2)
        self.assertEqual(src["public_rent"]["rows"], ds.SYNTH_PUBLIC_RENT_ROWS + 1, "both cards hit the same fake bond row")
        self.assertIn("NSW bond lodgements", src["public_rent"]["label"])
        self.assertEqual(src["floorplan_facts"]["rows"], 0, "no plan read yet")
        self.assertEqual(src["sun_geometry"]["rows"], 2)


if __name__ == "__main__":
    unittest.main()
