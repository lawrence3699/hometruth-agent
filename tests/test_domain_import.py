#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/domain_import.py：用户另存的 Domain / REA 页面 → data/real/{domain,rea}/<id>.json。全部离线，只用 tests/fixtures/domain_import 的假页面
（街名取自 data/streets.json，suburb / 邮编真实，编号和图片签名是假的），输出写进临时目录。
覆盖：搜索页三张卡片（一张没周租、一张混了别家照片）、单套挂牌页（富数据 + 相似房源卡片）、REA 套娃 JSON 字符串、重复导入不变、
富文件只补缺不降级、卡片升级、新存档为准、跨站查重（两种导入顺序结果一样）、按内容认页面、--since / --dry、几个解析小函数。
跑：.venv/bin/python -m unittest tests/test_domain_import.py -v"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import domain_import as di  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "domain_import"
T0 = dt.datetime(2026, 10, 27, 2, 0, tzinfo=dt.timezone.utc).timestamp()  # 悉尼 2026-10-27 13:00 AEDT


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.saved = self.tmp / "saved"
        self.saved.mkdir()
        self.out = self.tmp / "out"
        self.lines = []

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, name: str, as_name: str = None, ts: float = T0, edit=None) -> Path:
        dst = self.saved / (as_name or name)
        text = (FIX / name).read_text(encoding="utf-8")
        if edit:
            text = edit(text)
        dst.write_text(text, encoding="utf-8")
        os.utime(dst, (ts, ts))
        return dst

    def run_import(self, *paths, **kw):
        return di.run(list(paths), self.out, log=self.lines.append, **kw)

    def read(self, site: str, lid) -> dict:
        return json.loads((self.out / site / f"{lid}.json").read_text(encoding="utf-8"))


class SearchPage(_Base):
    def test_three_cards_two_kept(self):
        res = self.run_import(self.put("domain_search_p1.html"))
        files = sorted(p.name for p in (self.out / "domain").glob("*.json"))
        self.assertEqual(files, ["90000001.json", "90000003.json"], "the card without a weekly price is skipped")
        page = res["pages"][0]
        self.assertEqual((page["kind"], page["page"], page["pages"], page["total"]), ("domain search", 1, 4, 61))
        self.assertEqual(page["skipped"]["no weekly price"], 1)
        self.assertTrue(any("90000002" in ln and "Contact agent" in ln for ln in self.lines), "the skip reason is printed")

    def test_card_fields(self):
        self.run_import(self.put("domain_search_p1.html"))
        o = self.read("domain", 90000001)
        self.assertEqual(o["id"], 90000001)
        self.assertEqual(o["url"], "https://www.domain.com.au/5-18-alder-lane-kensington-nsw-2033-90000001")
        self.assertEqual((o["unit"], o["streetNumber"], o["street"], o["suburb"], o["postcode"], o["state"]),
                         ("5", "18", "Alder Lane", "Kensington", "2033", "NSW"))
        self.assertEqual(o["address"], "5/18 Alder Lane, Kensington NSW 2033")
        self.assertEqual((o["type"], o["beds"], o["baths"]), ("Apartment / Unit / Flat", 2, 1))
        self.assertIsNone(o["parking"], "Domain leaves parking off the card at 0: we record 'not stated', never invent 0")
        self.assertEqual((o["price"], o["rentWeekly"]), ("$820 per week", 820))
        self.assertEqual((o["lat"], o["lng"]), (-33.9161, 151.2201))
        self.assertEqual(o["agency"], "Fictional Realty Kensington")
        self.assertEqual((o["site"], o["card_only"]), ("domain", True))
        self.assertEqual((o["stats"], o["description"], o["headline"]), ({}, [], None), "no description / available date / bond on a card")
        self.assertEqual(o["tag"], "New")
        self.assertEqual(o["inspection"], {"open": "2026-10-30T10:00:00", "close": "2026-10-30T10:15:00"})
        self.assertEqual(o["fetched_at"], "2026-10-27T13:00:00+11:00", "file mtime as Sydney time")
        self.assertIn("search results page saved by the user", o["source"])
        self.assertNotIn("needs_geocode", o)
        self.assertEqual(list(o)[:28], di.KEY_ORDER[:28], "same key order as the 9 original files")

    def test_foreign_image_dropped_and_x1_used(self):
        self.run_import(self.put("domain_search_p1.html"))
        slides = self.read("domain", 90000001)["slides"]
        self.assertEqual(len(slides), 3)
        for s in slides:
            self.assertEqual((s["type"], s["w"], s["h"]), ("image", 720, 540))
            self.assertIn("/720x540/", s["url"])
            self.assertTrue(s["url"].rsplit("/", 1)[-1].startswith("90000001_"))
        self.assertTrue(any("another listing" in ln for ln in self.lines))

    def test_house_without_coordinates(self):
        self.run_import(self.put("domain_search_p1.html"))
        o = self.read("domain", 90000003)
        self.assertEqual((o["unit"], o["streetNumber"], o["street"], o["type"], o["beds"], o["parking"]), (None, "24B", "Caldera Avenue", "House", 3, 1))
        self.assertEqual((o["price"], o["rentWeekly"]), ("$1,150 pw", 1150))
        self.assertIsNone(o["lat"])
        self.assertTrue(o["needs_geocode"])
        self.assertEqual(o["tag"], "DEPOSIT TAKEN")
        self.assertEqual(len(o["slides"]), 2, "no retinaImages: falls back to images[]")

    def test_project_and_bad_id_cards_are_skipped(self):
        rec, why = di.domain_card({"id": 90000099, "listingType": "project", "listingModel": {"price": "$800 per week"}}, "x", "s")
        self.assertIsNone(rec)
        self.assertIn("project", why)
        rec, why = di.domain_card({"id": "../../etc", "listingModel": {"url": "/x", "price": "$800 per week"}}, "x", "s")
        self.assertIsNone(rec, "ids end up in file names: digits only")
        self.assertEqual(why, "no listing id")

    def test_address_from_slug_only_when_street_missing(self):
        entry = {"id": 90000031, "listingType": "listing",
                 "listingModel": {"url": "/7-marlow-place-kensington-nsw-2033-90000031", "price": "$700 per week",
                                  "address": {"suburb": "Kensington", "state": "NSW", "postcode": "2033"}, "features": {"beds": 1}}}
        rec, _ = di.domain_card(entry, "2026-10-27T13:00:00+11:00", "s")
        self.assertEqual((rec["streetNumber"], rec["street"], rec["suburb"]), ("7", "Marlow Place", "Kensington"))
        entry["listingModel"]["url"] = "/5-18-marlow-place-kensington-nsw-2033-90000031"
        rec, _ = di.domain_card(entry, "2026-10-27T13:00:00+11:00", "s")
        self.assertEqual((rec["unit"], rec["streetNumber"], rec["street"]), (None, None, "Marlow Place"),
                         "two numbers in a slug could be unit/number or a range: don't guess")


class ListingPage(_Base):
    def test_rich_listing(self):
        res = self.run_import(self.put("domain_listing_90000011.htm"))
        self.assertEqual(res["pages"][0]["kind"], "domain listing")
        o = self.read("domain", 90000011)
        self.assertNotIn("card_only", o)
        self.assertEqual((o["unit"], o["streetNumber"], o["street"], o["suburb"], o["postcode"]), ("3", "7", "Fenwick Street", "Zetland", "2017"))
        self.assertEqual((o["beds"], o["baths"], o["parking"], o["price"]), (2, 1, 1, "$905 per week"))
        self.assertEqual(o["stats"], {"availableFrom": "2026-11-18T00:00:00", "bond": 3620})
        self.assertEqual((o["medianRent"], o["medianBeds"], o["lat"], o["lng"]), (950, 2, -33.9065, 151.2085))
        self.assertEqual(o["structured"], ["Balcony", "Dishwasher", "Built in wardrobes"])
        self.assertEqual([s["type"] for s in o["slides"]], ["image", "image", "floorplan", "video"])
        text = " ".join(o["description"])
        for bad in ("0412", "Jane Fictitious", "@"):
            self.assertNotIn(bad, text, "phone lines, agent names and emails are stripped like the original 9 files")
        self.assertIn("North-facing balcony", text)

    def test_similar_listing_cards_are_kept_as_cards(self):
        self.run_import(self.put("domain_listing_90000011.htm"))
        o = self.read("domain", 90000012)
        self.assertTrue(o["card_only"])
        self.assertIn("similar-listings card", o["source"])
        self.assertEqual((o["streetNumber"], o["street"], o["beds"]), ("9", "Glasshouse Lane", 1))
        self.assertNotIn("card_only", self.read("domain", 90000011), "the page's own listing is not downgraded by its own card")


class ReaPage(_Base):
    def test_nested_json_strings(self):
        res = self.run_import(self.put("rea_search_p1.html"))
        page = res["pages"][0]
        self.assertEqual((page["kind"], page["page"], page["pages"], page["total"]), ("rea search", 1, 3, 45))
        self.assertEqual(sorted(p.name for p in (self.out / "rea").glob("*.json")), ["990000001.json", "990000002.json"])
        self.assertEqual(page["skipped"]["no weekly price"], 1, "monthly price is not a weekly rent")
        o = self.read("rea", 990000001)
        self.assertEqual((o["site"], o["card_only"], o["unit"], o["streetNumber"], o["street"], o["state"]), ("rea", True, "5", "18", "Alder Ln", "NSW"))
        self.assertEqual((o["lat"], o["lng"]), (-33.9161, 151.2201))
        self.assertEqual(o["url"], "https://www.realestate.com.au/property-apartment-nsw-kensington-990000001")
        self.assertEqual(o["agency"], "Fictional Agents Eastern Suburbs")
        self.assertTrue(all("/800x600/" in s["url"] and "{size}" not in s["url"] for s in o["slides"]))
        self.assertEqual(len(o["slides"]), 2, "mainImage repeated in images[] is kept once")

    def test_studio_without_geocode(self):
        self.run_import(self.put("rea_search_p1.html"))
        o = self.read("rea", 990000002)
        self.assertEqual((o["type"], o["beds"], o["rentWeekly"]), ("Studio", 0, 650))
        self.assertIsNone(o["lat"])
        self.assertTrue(o["needs_geocode"])
        self.assertEqual(o["stats"]["availableFrom"], "2026-11-05T00:00:00")
        self.assertEqual(o["stats"]["bond"], 2600)

    def test_listing_page(self):
        res = self.run_import(self.put("rea_listing_990000021.html"))
        self.assertEqual(res["pages"][0]["kind"], "rea listing")
        o = self.read("rea", 990000021)
        self.assertNotIn("card_only", o)
        self.assertEqual(o["headline"], "Leafy two bedroom unit")
        self.assertEqual(o["description"], ["A fictional unit for tests.", "", "Two bedrooms, one bathroom."])
        self.assertEqual(o["stats"], {"availableFrom": "2026-10-27T00:00:00", "availableText": "Available Now", "bond": 3120},
                         "'Available now' = the day the page was saved")
        self.assertEqual(o["features"], ["Built-in wardrobes", "Dishwasher"])


class MergeRules(_Base):
    def test_reimport_is_idempotent(self):
        paths = [self.put(n) for n in ("domain_search_p1.html", "domain_listing_90000011.htm", "rea_search_p1.html", "rea_listing_990000021.html")]
        first = self.run_import(*paths)
        self.assertEqual(len(first["written"]), 6)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.out.rglob("*.json")}
        second = self.run_import(*paths)
        self.assertEqual(second["written"], [])
        self.assertEqual(len(second["unchanged"]), 6)
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.out.rglob("*.json")}
        self.assertEqual(before, after, "same pages again: not a byte or a timestamp changes")

    def test_rich_file_is_never_downgraded(self):
        rich = {"id": 90000001, "url": "https://www.domain.com.au/5-18-alder-lane-kensington-nsw-2033-90000001", "address": "5/18 Alder Lane, Kensington NSW 2033",
                "unit": "5", "streetNumber": "18", "street": "Alder Lane", "suburb": "Kensington", "postcode": "2033", "type": "Apartment / Unit / Flat",
                "beds": 2, "baths": 1, "parking": 0, "price": "$800 per week", "stats": {"availableFrom": "2026-11-18T00:00:00", "bond": 3200},
                "agency": "Fictional Realty Kensington", "headline": "Kept headline", "description": ["Kept text."], "features": [], "structured": [],
                "lat": -33.9, "lng": 151.2, "medianRent": 870, "medianBeds": 2, "created": None, "modified": None,
                "slides": [{"type": "image", "url": "https://rimh2.domainstatic.com.au/KEEP=/fit-in/1920x1080/x/90000001_9_1-w1-h1", "w": 1, "h": 1, "caption": None}],
                "fetched_at": "2026-10-26T10:50:00+11:00", "source": "domain.com.au public listing page (__NEXT_DATA__), demo use only"}
        (self.out / "domain").mkdir(parents=True)
        (self.out / "domain" / "90000001.json").write_text(di._dump(rich), encoding="utf-8")
        res = self.run_import(self.put("domain_search_p1.html", ts=T0 + 86400))
        o = self.read("domain", 90000001)
        for k, v in rich.items():
            if k != "created" and k != "modified":
                self.assertEqual(o[k], v, f"{k} must not change")
        self.assertNotIn("card_only", o)
        self.assertEqual((o["site"], o["state"], o["tag"]), ("domain", "NSW", "New"), "only missing fields are added")
        self.assertEqual(o["rentWeekly"], 800, "derived from the file's own price, not the card's $820")
        self.assertEqual(res["how"][("domain", "90000001")], "filled")
        self.assertEqual(self.run_import(self.put("domain_search_p1.html", ts=T0 + 86400))["written"], [], "and stays put on re-import")

    def test_card_upgrades_to_listing_page(self):
        self.run_import(self.put("domain_search_p1.html"))
        card = di.make_record(id=90000011, address="3/7 Fenwick Street, Zetland NSW 2017", unit="3", streetNumber="7", street="Fenwick Street", suburb="Zetland",
                              postcode="2017", price="$905 per week", fetched_at="2026-10-26T10:00:00+11:00", source=di.SRC_DOMAIN_SEARCH, site="domain",
                              card_only=True, tag="New", rentWeekly=905)
        (self.out / "domain" / "90000011.json").write_text(di._dump(card), encoding="utf-8")
        res = self.run_import(self.put("domain_listing_90000011.htm"))
        o = self.read("domain", 90000011)
        self.assertNotIn("card_only", o)
        self.assertTrue(o["description"])
        self.assertEqual(o["tag"], "New", "card-only extras survive the upgrade")
        self.assertEqual(res["how"][("domain", "90000011")], "upgraded")

    def test_newer_saved_card_wins_in_any_order(self):
        newer = self.put("domain_search_p1.html", as_name="later.html", ts=T0 + 3600, edit=lambda t: t.replace("$820 per week", "$840 per week"))
        older = self.put("domain_search_p1.html", as_name="earlier.html", ts=T0)
        self.run_import(newer)
        self.run_import(older)
        o = self.read("domain", 90000001)
        self.assertEqual((o["price"], o["rentWeekly"]), ("$840 per week", 840), "an older page imported later does not roll the price back")
        self.assertEqual(o["fetched_at"], "2026-10-27T14:00:00+11:00")

    def test_newer_card_drops_stale_tag(self):
        self.run_import(self.put("domain_search_p1.html", as_name="earlier.html", ts=T0))
        self.assertEqual(self.read("domain", 90000003)["tag"], "DEPOSIT TAKEN")
        self.run_import(self.put("domain_search_p1.html", as_name="later.html", ts=T0 + 3600,
                                 edit=lambda t: t.replace('"tagText": "DEPOSIT TAKEN"', '"tagText": null')))
        self.assertNotIn("tag", self.read("domain", 90000003), "a tag from an older page is a past state, not copied forward")


class Duplicates(_Base):
    def test_same_flat_on_both_sites_keeps_domain(self):
        res = self.run_import(self.put("domain_search_p1.html"), self.put("rea_search_p1.html"))
        self.assertFalse((self.out / "rea" / "990000001.json").exists())
        self.assertTrue((self.out / "rea" / "990000002.json").exists())
        o = self.read("domain", 90000001)
        self.assertEqual(o["also_on"], [{"site": "rea", "id": 990000001, "url": "https://www.realestate.com.au/property-apartment-nsw-kensington-990000001"}])
        self.assertEqual(len(res["duplicates"]), 1)

    def test_order_does_not_matter(self):
        d, r = self.put("domain_search_p1.html"), self.put("rea_search_p1.html")
        self.run_import(r)
        self.assertTrue((self.out / "rea" / "990000001.json").exists())
        res = self.run_import(d)
        self.assertEqual(res["removed"], [("rea", "990000001")])
        self.assertFalse((self.out / "rea" / "990000001.json").exists())
        one_go = {p.relative_to(self.out): p.read_text(encoding="utf-8") for p in self.out.rglob("*.json")}
        shutil.rmtree(self.out)
        self.run_import(d, r)
        both = {p.relative_to(self.out): p.read_text(encoding="utf-8") for p in self.out.rglob("*.json")}
        self.assertEqual(one_go, both)

    def test_address_key_normalises_street_types(self):
        a = {"unit": "5", "streetNumber": "18", "street": "Alder Lane", "suburb": "Kensington"}
        self.assertEqual(di.addr_key(a), di.addr_key({"unit": "05", "streetNumber": "18", "street": "Alder Ln", "suburb": "KENSINGTON"}))
        self.assertNotEqual(di.addr_key(a), di.addr_key(dict(a, unit="6")))
        self.assertIsNone(di.addr_key({"street": "Alder Lane", "suburb": "Kensington"}), "no house number: no duplicate matching")


class FilesAndCli(_Base):
    def test_pages_are_found_by_content_not_name(self):
        self.put("not_a_listing.html")
        self.put("domain_search_p1.html", as_name="page (3).htm")
        (self.saved / "notes.txt").write_text("<script id=\"__NEXT_DATA__\">domain.com.au</script>", encoding="utf-8")
        res = self.run_import(self.saved)
        self.assertEqual(res["files"], 2, "only .html / .htm are opened")
        self.assertEqual([p["file"] for p in res["pages"]], ["page (3).htm"])

    def test_since_and_dry(self):
        self.put("domain_search_p1.html", ts=T0 - 3 * 86400)
        self.put("rea_search_p1.html", ts=T0)
        res = self.run_import(self.saved, since=dt.date(2026, 10, 26), dry=True)
        self.assertEqual([p["file"] for p in res["pages"]], ["rea_search_p1.html"])
        self.assertEqual(len(res["written"]), 2)
        self.assertFalse(self.out.exists(), "--dry writes nothing")

    def test_page_coverage_is_reported(self):
        self.put("domain_search_p1.html")
        self.put("domain_search_p1.html", as_name="p3.html", edit=lambda t: t.replace('"currentPage": 1', '"currentPage": 3')
                 .replace("?page=1", "?page=3"))
        self.run_import(self.saved)
        line = next(ln for ln in self.lines if "saved page(s)" in ln)
        self.assertIn("saved page(s) 1, 3 of 4", line)
        self.assertIn("not saved yet: 2, 4", line)

    def test_cli(self):
        self.put("domain_search_p1.html")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = di.main([str(self.saved), "--out", str(self.out)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "domain" / "90000001.json").exists())
        self.assertIn("by suburb", buf.getvalue())


class Helpers(unittest.TestCase):
    def test_weekly_rent(self):
        cases = {"$820 per week": 820, "$1,150 pw": 1150, "$850": 850, "From $700 p/w": 700, "$800 - $850 per week": 800, "$650.00 weekly": 650,
                 "Contact agent": None, "Deposit Taken": None, "$3,100 per month": None, "$1,250,000": None, "$850pcm": None, None: None,
                 "850 per week": 850}
        for s, want in cases.items():
            self.assertEqual(di.weekly_rent(s), want, s)

    def test_parse_street(self):
        cases = {"5/18 Alder Lane": ("5", "18", "Alder Lane"), "407/438-448 Birchwood Street": ("407", "438-448", "Birchwood Street"),
                 "G01/12 Caldera Avenue": ("G01", "12", "Caldera Avenue"), "2/24B Dunmore Row": ("2", "24B", "Dunmore Row"),
                 "Unit 5, 18 Ellery Place": ("5", "18", "Ellery Place"), "Level 3, 12/5 Fenwick Street": ("12", "5", "Fenwick Street"),
                 "18 Ingram Street, Kensington NSW 2033": (None, "18", "Ingram Street"), "Juniper Avenue": (None, None, "Juniper Avenue"),
                 "Address available on request": (None, None, None), "": (None, None, None)}
        for s, want in cases.items():
            self.assertEqual(di.parse_street(s), want, s)

    def test_norm_type(self):
        self.assertEqual(di.norm_type("ApartmentUnitFlat"), "Apartment / Unit / Flat")
        self.assertEqual(di.norm_type("Apartment"), "Apartment / Unit / Flat")
        self.assertEqual(di.norm_type("unit"), "Apartment / Unit / Flat")
        self.assertEqual(di.norm_type("Studio"), "Studio")
        self.assertEqual(di.norm_type("Townhouse"), "Townhouse")
        self.assertEqual(di.norm_type("Duplex/Semi-detached"), "Semi-Detached")
        self.assertEqual(di.norm_type("House"), "House")

    def test_deep_json_unwraps_strings(self):
        inner = json.dumps({"listing": {"id": "990000009"}})
        outer = json.dumps({"k": {"data": inner}})
        self.assertEqual(di.deep_json({"cache": outer}), {"cache": {"k": {"data": {"listing": {"id": "990000009"}}}}})

    def test_rea_available_dates(self):
        saved = "2026-12-20T10:00:00+11:00"
        self.assertEqual(di._rea_date({"display": "Available 5 Nov 2026"}, saved)[0], "2026-11-05T00:00:00")
        self.assertEqual(di._rea_date({"display": "Available from Tuesday, 18th November 2026"}, saved)[0], "2026-11-18T00:00:00")
        self.assertEqual(di._rea_date({"display": "Available 18 Nov"}, saved)[0], "2026-11-18T00:00:00", "no year: the year it was saved")
        self.assertEqual(di._rea_date({"display": "Available 6 Jan"}, saved)[0], "2027-01-06T00:00:00", "early next year, not 11 months ago")
        self.assertEqual(di._rea_date({"display": "Available Now"}, saved), ("2026-12-20T00:00:00", "Available Now"))
        self.assertEqual(di._rea_date({"display": "Ask the agent"}, saved), (None, "Ask the agent"))

    def test_sydney_time(self):
        self.assertEqual(di.sydney_iso(T0), "2026-10-27T13:00:00+11:00")


if __name__ == "__main__":
    unittest.main()
