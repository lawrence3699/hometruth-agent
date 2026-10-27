#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NSW Fair Trading 押金登记租金（src/evidence/bond_rents.py + scripts/nsw_bonds.py）：全部离线。
查找接口（形状、类型文字映射、4 房以上合并、n < 10 / 查不到 / 认不出 → None）、evidence_text 的措辞和百分比、
xlsx 解析（标准库，用测试里现造的小工作簿：标题行偏移、图例、U / O / 坏租金、文本日期）、来源页链接挑选，
以及真实 CSV 的一条常识检查（2033 两房 flat/unit）。
跑：.venv/bin/python -m unittest tests/test_bond_rents.py -v"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import nsw_bonds as nb  # noqa: E402
from evidence import bond_rents as br  # noqa: E402

MINI = ROOT / "tests" / "fixtures" / "bond_rents" / "mini.csv"
KEYS = {"postcode", "beds", "dwelling", "dwelling_label", "n", "median", "q1", "q3", "months", "source", "source_url"}


def q(postcode, beds, dwelling="F"):
    return br.lookup(postcode, beds, dwelling, path=MINI)


class Lookup(unittest.TestCase):
    def test_shape_matches_the_shared_interface(self):
        r = q("2033", 2)
        self.assertEqual(set(r), KEYS)
        self.assertEqual(r, {"postcode": "2033", "beds": 2, "dwelling": "F", "dwelling_label": "flat/unit", "n": 312, "median": 780, "q1": 700,
                             "q3": 850, "months": "Apr–Sep 2026", "source": "NSW Fair Trading rental bond lodgements",
                             "source_url": "https://www.fairtrading.nsw.gov.au/about-fair-trading/rental-bond-data"})

    def test_listing_type_strings_and_int_postcode(self):
        base = q("2033", 2, "F")
        self.assertEqual(q(2033, 2, "Apartment / Unit / Flat"), base)
        self.assertEqual(q(" 2033 ", "2", "apartment"), base)
        self.assertEqual(q(2033, 3, "Townhouse")["dwelling"], "T")
        self.assertEqual(q(2033, 3, "Terrace")["dwelling_label"], "terrace/townhouse")
        self.assertEqual(q(2033, 4, "House")["dwelling_label"], "house")

    def test_dwelling_mapping(self):
        cases = {"Apartment / Unit / Flat": "F", "House": "H", "Townhouse": "T", "Terrace": "T", "Semi-Detached": "T", "Duplex/Semi-detached": "T",
                 "duplex-semi-detached": "T", "Villa": "T", "Studio": "F", "Penthouse": "F", "New Apartments / Off the Plan": "F", "unit": "F",
                 "Free Standing": "H", "f": "F", "H": "H", "T": "T",
                 "O": None, "U": None, "": None, None: None, "Car Space": None, "Acreage / Semi-Rural": None, "Retirement Living": None,
                 "Community title": None}
        for text, code in cases.items():
            self.assertEqual(br.dwelling_code(text), code, text)

    def test_four_or_more_bedrooms_pool_as_four(self):
        for beds in (4, 5, 7, "6"):
            r = q(2033, beds, "House")
            self.assertIsNotNone(r, beds)
            self.assertEqual((r["beds"], r["n"], r["median"]), (4, 40, 1600))

    def test_none_cases(self):
        self.assertIsNone(q(2033, 1), "n = 9 is below the minimum of 10")
        self.assertIsNotNone(q(2034, 2), "n = 10 is enough")
        self.assertIsNone(q(2033, 2, "H"), "no row")
        self.assertIsNone(q(2999, 2), "no postcode")
        self.assertIsNone(q(2033, 2, "Car Space"), "unknown dwelling stays unknown")
        self.assertIsNone(q(2033, 2, None))
        self.assertIsNone(q(2033, None))
        self.assertIsNone(q(2033, -1))
        self.assertIsNone(q(2033, 2.5))
        self.assertIsNone(q("NSW 2033", 2))
        self.assertIsNone(q(2035, 2), "a broken CSV row is skipped, not guessed")
        self.assertIsNone(br.lookup(2033, 2, path=MINI.parent / "missing.csv"), "missing file → None, no crash")

    def test_month_labels(self):
        self.assertEqual(q(2034, 2)["months"], "Nov 2025–Apr 2026")
        self.assertEqual(q(2035, 1)["months"], "Sep 2026")
        self.assertEqual(q(2033, 0)["months"], "May–Sep 2026")

    def test_cache_rereads_a_changed_file(self):
        d = Path(tempfile.mkdtemp())
        try:
            p = d / "t.csv"
            shutil.copy(MINI, p)
            self.assertEqual(br.lookup(2033, 2, path=p)["median"], 780)
            p.write_text(MINI.read_text(encoding="utf-8").replace("2033,F,2,312,780", "2033,F,2,312,790"), encoding="utf-8")
            st = os.stat(p)
            os.utime(p, (st.st_atime, st.st_mtime + 5))
            self.assertEqual(br.lookup(2033, 2, path=p)["median"], 790)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class EvidenceText(unittest.TestCase):
    def test_wording_matches_the_spec_example(self):
        self.assertEqual(br.evidence_text(820, q(2033, 2)),
                         "NSW Fair Trading: 312 new 2-bedroom flat/unit leases in 2033 lodged Apr–Sep 2026, median $780 a week "
                         "(middle half $700–$850); this one asks $820 (5% above).")

    def test_percent_maths(self):
        rec = q(2033, 2)  # median 780
        self.assertTrue(br.evidence_text(741, rec).endswith("this one asks $741 (5% below)."), "-5.0%")
        self.assertTrue(br.evidence_text(780, rec).endswith("this one asks $780 (in line with the median)."))
        self.assertTrue(br.evidence_text(783, rec).endswith("(in line with the median)."), "+0.38% rounds to 0")
        self.assertTrue(br.evidence_text(1170, rec).endswith("this one asks $1,170 (50% above)."))
        h = q(2033, 4, "H")  # median 1600
        self.assertTrue(br.evidence_text(1608, h).endswith("(1% above)."), "+0.5% rounds half up")
        self.assertTrue(br.evidence_text(1592, h).endswith("(1% below)."), "-0.5% rounds half away from zero")
        self.assertEqual(br.compare(820, 780), (5, "above"))
        self.assertEqual(br.compare(None, 780), None)

    def test_labels_thousands_and_missing_rent(self):
        h = q(2033, 5, "House")
        s = br.evidence_text(None, h)
        self.assertEqual(s, "NSW Fair Trading: 40 new 4-or-more-bedroom house leases in 2033 lodged Apr–Sep 2026, median $1,600 a week "
                            "(middle half $1,400–$2,050).")
        self.assertIn("new studio/0-bedroom flat/unit leases", br.evidence_text(0, q(2033, 0)))
        self.assertNotIn("asks", br.evidence_text(0, q(2033, 0)), "rent 0 means unknown, so no comparison")
        self.assertIn("this one asks $820 (5% above)", br.evidence_text("$820 per week", q(2033, 2)), "Domain price text works too")
        big = dict(q(2033, 2), n=1234)
        self.assertIn(": 1,234 new", br.evidence_text(820, big))

    def test_no_demographic_words(self):
        s = br.evidence_text(820, q(2033, 2)).lower()
        for w in ("student", "ethnic", "national", "age group", "family", "young", "older"):
            self.assertNotIn(w, s)


# ---------------------------------------------------------------- xlsx 解析（测试里现造一个小工作簿）

def _cell(ref, v):
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'


def _sheet(rows):
    out = []
    for i, row in enumerate(rows, 1):
        cells = "".join(_cell(f"{'ABCDEFG'[j]}{i}", v) for j, v in enumerate(row))
        out.append(f'<row r="{i}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(out) + "</sheetData></worksheet>")


def make_xlsx(path: Path, data_rows, title="NSW Fair Trading\n\nResidential Rental Bond Lodgements\n\nSeptember  2026"):
    # 列顺序故意和真文件不同（按表头文字认列）；前两行是标题和空行（表头在第 3 行）
    header = ["Postcode", "Lodgement Date", "Weekly Rent", "Dwelling Type", "Bedrooms"]
    data = [[title], [], header] + data_rows
    legend = [["Description"], ["Column", "Definition"],
              ["Lodgement Date", "Date that the bond was lodged with Fair Trading."],
              ["Postcode", "Postcode of the rented premises address"],
              ["Dwelling Type", "Type of rented premises as provided by the agent of landlord. (F) Flat/unit; (H) House; "
                                "(T) Terrace/townhouse/semi-detached; (O) Other; (U) Unknown.\xa0A Dwelling Type of 'Other' may include rented rooms."],
              ["Bedrooms", "Number of bedrooms as provided by the agent or landlord; (U) unknown."],
              ["Weekly Rent", "Weekly rent amount as provided by the agent or landlord; (U) unknown"]]
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          '<sheet name="Sept26 Rental Bond Lodgments" sheetId="1" r:id="rId1"/><sheet name="Definitions" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", _sheet(data))
        z.writestr("xl/worksheets/sheet2.xml", _sheet(legend))


SEP15 = 46280  # Excel 序列号 = 2026-09-15


class Parser(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "rentalbond_lodgements_september_2026.xlsx"
        rows = [
            [2033, SEP15, 700, "F", 2], [2033, SEP15, "800", "F", "2"], [2033, SEP15, 900, "F", 2], [2033, "15/09/2026", 1000, "F", 2],
            [2033, SEP15, 650, "F", "U"],          # 卧室未知 → 丢
            [2033, SEP15, 300, "O", 1],            # Other（单间 / 车位）→ 丢
            [2033, SEP15, 640, "U", 2],            # 房型未知 → 丢
            [2033, SEP15, 640, "4", 2],            # 乱码房型 → 丢
            [2033, SEP15, "U", "F", 2],            # 租金未知 → 丢
            [2033, SEP15, 0, "F", 2],              # 租金 0 → 丢
            [2033, SEP15, 25000, "F", 2],          # 租金离谱 → 丢
            [2032, SEP15, 1500, "H", 6], [2032, SEP15, 1700, "H", 4],   # 4 房以上合成 4
            [2032, "sometime", 500, "F", 0],       # 日期认不出 → 用文件标题的月份
            [2032.0, SEP15, 1200.5, "T", 3.0],     # 数字带小数点
        ]
        make_xlsx(self.path, rows)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_read_file_filters_and_maps_columns(self):
        f = nb.read_file(self.path)
        self.assertEqual(f["header_row"], 3)
        self.assertEqual(f["sheet"], "Sept26 Rental Bond Lodgments")
        self.assertEqual(f["file_month"], "2026-09")
        self.assertEqual(f["legend"]["dwelling_codes"]["T"], "Terrace/townhouse/semi-detached")
        self.assertEqual(f["rows_read"], 15)
        self.assertEqual(f["rows_kept"], 8)
        sk = f["skipped"]
        self.assertEqual(sk["bedrooms U, blank or not a number"], 1)
        self.assertEqual(sk["dwelling O"], 1)
        self.assertEqual(sk["dwelling U"], 1)
        self.assertEqual(sk["dwelling code not in legend"], 1)
        self.assertEqual(sk["rent U, blank or not a number"], 1)
        self.assertEqual(sk[f"rent <= 0 or > {nb.MAX_RENT}"], 2)
        self.assertEqual(sk["date unreadable (kept, used the file month)"], 1)
        self.assertTrue(all(r[4] == "2026-09" for r in f["records"]))

    def test_aggregate_quartiles_and_pooling(self):
        rows = nb.aggregate(nb.read_file(self.path)["records"])
        by = {(r["postcode"], r["dwelling"], r["beds"]): r for r in rows}
        self.assertEqual(by[("2033", "F", 2)], {"postcode": "2033", "dwelling": "F", "beds": 2, "n": 4, "median": 850, "q1": 775, "q3": 925,
                                                "first_month": "2026-09", "last_month": "2026-09"})
        self.assertEqual(by[("2032", "H", 4)]["n"], 2)
        self.assertEqual(by[("2032", "H", 4)]["median"], 1600)
        self.assertEqual(by[("2032", "T", 3)]["median"], 1201, "1200.5 rounds half up")
        self.assertEqual(by[("2032", "F", 0)]["n"], 1)
        text = nb.csv_text(rows)
        self.assertTrue(text.startswith("postcode,dwelling,beds,n,median,q1,q3,first_month,last_month\n"))
        self.assertNotIn("\r", text)
        # 生成的 CSV 能被查找接口读回来（n 不够 10 → None，够了就有）
        p = self.dir / "agg.csv"
        p.write_text(text, encoding="utf-8")
        self.assertIsNone(br.lookup(2033, 2, path=p))

    def test_month_label_and_dates(self):
        self.assertEqual(nb.month_label("2026-04", "2026-09"), "Apr–Sep 2026")
        self.assertEqual(nb.month_label("2025-11", "2026-04"), "Nov 2025–Apr 2026")
        self.assertEqual(str(nb.excel_date(str(SEP15))), "2026-09-15")
        self.assertIsNone(nb.excel_date("U"))
        for name, ym in {"rentalbond_lodgements_september25.xlsx": (2025, 9), "rentalbond_lodgements_june_2025_0.xlsx": (2025, 6),
                         "Rental bond lodgement data - April 2026": (2026, 4), "rental-bond-lodgement-data-may-2025.xlsx": (2025, 5)}.items():
            self.assertEqual(nb.month_from_text(name), ym, name)

    def test_discover_picks_monthly_lodgement_files_only(self):
        page = """<ul>
        <li><a href="/sites/default/files/noindex/2026-10/rentalbond_lodgements_september_2026.xlsx" title="Rental bond lodgement data - September 2026">Rental bond lodgement data - September 2026 (XLSX 698KB)</a></li>
        <li><a href="/sites/default/files/noindex/2026-09/rentalbond_lodgements_august_2026.xlsx">Rental bond lodgement data - August 2026</a></li>
        <li><a href="/sites/default/files/noindex/2025-10/rentalbond_lodgements_september25.xlsx">Rental bond lodgement data - September 2025</a></li>
        <li><a href="/files/rentalbond_lodgements_year_2025.xlsx">Rental bond lodgement data - year 2025</a></li>
        <li><a href="/files/rentalbond_refunds_q3_2026.xlsx">Rental bond refund data - third quarter 2026</a></li>
        <li><a href="/files/holdings_september_2026.xlsx">Rental bond holdings - September 2026</a></li>
        <li><a href="/about">About</a></li></ul>"""
        items = nb.discover(page, "https://www.nsw.gov.au/housing-and-construction/rental-forms-surveys-and-data/rental-bond-data")
        self.assertEqual([(i["year"], i["month"]) for i in items], [(2026, 9), (2026, 8), (2025, 9)])
        self.assertEqual(items[0]["url"], "https://www.nsw.gov.au/sites/default/files/noindex/2026-10/rentalbond_lodgements_september_2026.xlsx",
                         "relative links resolve against the page we were redirected to")
        self.assertEqual(items[0]["file"], "rentalbond_lodgements_september_2026.xlsx")

    def test_html_instead_of_xlsx_is_refused_and_existing_files_are_skipped(self):
        # 10-27 真踩过：fairtrading 的文件链接 301 到一个网页，存下来是 HTML 不是 xlsx
        calls = []

        def fake_get(url, timeout=60):
            calls.append(url)
            return b"<html>NSW Fair Trading</html>", "https://www.nsw.gov.au/", "text/html"

        real_get = nb._get
        nb._get = fake_get
        try:
            item = {"url": "https://example.invalid/rentalbond_lodgements_august_2026.xlsx", "file": "rentalbond_lodgements_august_2026.xlsx"}
            with self.assertRaises(RuntimeError):
                nb.download(item, self.dir)
            self.assertFalse((self.dir / item["file"]).exists(), "nothing saved")
            have = {"url": "https://example.invalid/x.xlsx", "file": self.path.name}
            self.assertEqual(nb.download(have, self.dir), self.path)
            self.assertEqual(len(calls), 1, "an existing valid xlsx is not downloaded again")
        finally:
            nb._get = real_get


# ---------------------------------------------------------------- 真实 CSV（仓库里那份）

class RealCsv(unittest.TestCase):
    def test_kensington_two_bed_flats(self):
        r = br.lookup("2033", 2, "F")
        self.assertIsNotNone(r, "data/public/nsw_bond_rents.csv should have 2033 / 2 bed / F")
        self.assertGreaterEqual(r["n"], 10)
        self.assertTrue(400 <= r["median"] <= 1500, r)
        self.assertLessEqual(r["q1"], r["median"])
        self.assertLessEqual(r["median"], r["q3"])

    def test_meta_records_source_and_licence(self):
        meta = json.loads((ROOT / "data" / "public" / "nsw_bond_rents.meta.json").read_text(encoding="utf-8"))
        self.assertIn("CC BY 4.0", meta["licence"]["name"])
        self.assertEqual(meta["source_page"], br.SOURCE_URL)
        self.assertEqual(len(meta["files"]), 6)
        self.assertTrue(all(f["url"].endswith(".xlsx") for f in meta["files"]))


if __name__ == "__main__":
    unittest.main()
