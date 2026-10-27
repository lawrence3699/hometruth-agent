#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NSW Fair Trading 押金登记数据（rental bond lodgements，政府开放数据，CC BY）→ 每个邮编 × 房型 × 卧室数的真实新签租金。

产出（只有聚合结果，进仓库）：
  data/public/nsw_bond_rents.csv        postcode,dwelling,beds,n,median,q1,q3,first_month,last_month（全 NSW；beds ≥ 4 合成 4）
  data/public/nsw_bond_rents.meta.json  来源页、每个文件的链接和校验和、许可和署名原文、覆盖月份、生成时间、行数、过滤规则
原始 xlsx 只下到 --raw-dir（默认系统临时目录下的 hometruth_nsw_bonds），永远不进仓库。

步骤：
  1. 抓来源页（fairtrading 的地址会 301 到 www.nsw.gov.au，相对链接按跳转后的地址拼），挑出最新 N 个月的「lodgement 月度文件」
     （不要年度汇总、refund、holding）。
  2. 下载（已有且是合法 zip 的跳过；拿到的不是 xlsx —— 比如被重定向成网页 —— 直接报错，不当数据用）。
  3. 只用标准库读 xlsx（zipfile + xml.etree）：Definitions 表读图例（列名、房型代码），数据表按表头文字找列（标题行、空行的偏移不写死）；
     日期是 Excel 序列号（也认文本日期），解析不了就用文件标题里的月份。
  4. 过滤：房型只留 F / H / T（图例里 O = 其他，含出租单间、车库、车位；U = 未知；别的乱码也丢）；卧室 U / 空 丢；
     租金 U / 空 / ≤ 0 / > 20000 丢。0 卧室保留（图例：多半是 studio / bedsitter）。
  5. 聚合：n、中位数、四分位（statistics.quantiles inclusive，等同 Excel QUARTILE.INC），四舍五入到整数元；first / last_month 取这一格里的登记月份。
内容没变就不重写文件（generated_at 不跳），所以重复跑是幂等的。

跑：.venv/bin/python scripts/nsw_bonds.py                      （下载缺的 + 聚合 + 写文件）
    .venv/bin/python scripts/nsw_bonds.py --dry                （只列要下的文件；文件都在时再打印聚合摘要，不写）
    .venv/bin/python scripts/nsw_bonds.py --months 12 --raw-dir /path/to/raw
    .venv/bin/python scripts/nsw_bonds.py --offline            （不连网，只用 --raw-dir 里已有的 xlsx）
查找接口在 src/evidence/bond_rents.py。"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import statistics
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "public" / "nsw_bond_rents.csv"
OUT_META = ROOT / "data" / "public" / "nsw_bond_rents.meta.json"
DEFAULT_RAW = Path(tempfile.gettempdir()) / "hometruth_nsw_bonds"

SOURCE_PAGE = "https://www.fairtrading.nsw.gov.au/about-fair-trading/rental-bond-data"
DATA_NSW = "https://data.nsw.gov.au/data/dataset/rental-bond-lodgement"
UA = "Mozilla/5.0 (HomeTruth hackathon data script; NSW rental bond open data)"
# 许可和署名：2026-10-27 人工核过的原文（Data.NSW 数据集页的 license 字段 + 来源页页脚 Copyright 链接跳到的 NSW 政府版权页）
LICENCE = {
    "name": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
    "url": "https://creativecommons.org/licenses/by/4.0/",
    "data_nsw_dataset": DATA_NSW,
    "data_nsw_licence_field": "Creative Commons Attribution (cc-by), publisher: Fair Trading",
    "nsw_copyright_page": "https://www.nsw.gov.au/nsw-government/about-website/copyright",
    "nsw_copyright_statement": "All material on this website is licensed under the Creative Commons Attribution 4.0 licence, except as noted below.",
    "stated_attribution_form": "© State of New South Wales. For current information go to www.nsw.gov.au.",
    "attribution": ("Contains NSW Fair Trading rental bond lodgement data, © State of New South Wales, licensed under CC BY 4.0 "
                    "(https://creativecommons.org/licenses/by/4.0/). Aggregated by HomeTruth into medians and quartiles by postcode, "
                    "dwelling type and bedrooms; not endorsed by NSW Fair Trading."),
    "checked": "2026-10-27",
}
KEEP_DWELLINGS = ("F", "H", "T")
DWELLING_LABELS = {"F": "flat/unit", "H": "house", "T": "terrace/townhouse/semi-detached"}
MAX_RENT = 20000
POOL_BEDS = 4
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
FIELDS = {"date": "lodgement date", "postcode": "postcode", "dwelling": "dwelling type", "beds": "bedrooms", "rent": "weekly rent"}
CSV_COLUMNS = ["postcode", "dwelling", "beds", "n", "median", "q1", "q3", "first_month", "last_month"]

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


# ---------------------------------------------------------------- 来源页 → 月度文件链接

class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[Dict[str, str]] = []
        self._cur: Optional[Dict[str, str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            a = dict(attrs)
            self._cur = {"href": a.get("href") or "", "title": a.get("title") or "", "text": ""}

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._cur is not None:
            self.links.append(self._cur)
            self._cur = None


def month_from_text(s: str) -> Optional[Tuple[int, int]]:
    """'Rental bond lodgement data - September 2026' / 'rentalbond_lodgements_september25.xlsx' → (2026, 9)。"""
    s = (s or "").lower()
    mon = r"(?<![a-z])(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_\-]*"
    m = re.search(mon + r"((?:19|20)\d\d)(?!\d)", s) or re.search(mon + r"(\d\d)(?!\d)", s)
    if not m:
        return None
    year = int(m.group(2))
    if year < 100:
        year += 2000
    return year, MONTHS[m.group(1)]


def discover(page_html: str, base_url: str) -> List[Dict]:
    """来源页里所有「押金登记月度文件」，按月份新到旧。年度汇总、退款、持有量都不要。"""
    p = _Anchors()
    p.feed(page_html)
    out: Dict[Tuple[int, int], Dict] = {}
    for a in p.links:
        href = html.unescape(a["href"]).strip()
        label = " ".join((a["title"] or a["text"]).split())
        hay = f"{label} {href}".lower()
        if not href.lower().split("?")[0].endswith(".xlsx") or "lodg" not in hay:
            continue
        if any(w in hay for w in ("refund", "holding", "annual")) or re.search(r"\byear\b", hay):
            continue
        ym = month_from_text(label) or month_from_text(Path(urllib.parse.urlparse(href).path).name)
        if not ym or ym in out:
            continue
        url = urllib.parse.urljoin(base_url, href)
        out[ym] = {"year": ym[0], "month": ym[1], "title": label, "url": url, "file": Path(urllib.parse.urlparse(url).path).name}
    return [out[k] for k in sorted(out, reverse=True)]


def _get(url: str, timeout: float = 60) -> Tuple[bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.geturl(), r.headers.get("Content-Type", "")


def download(item: Dict, raw_dir: Path) -> Path:
    dest = raw_dir / item["file"]
    if dest.exists() and zipfile.is_zipfile(dest):
        return dest
    body, final, ctype = _get(item["url"], timeout=120)
    if not zipfile.is_zipfile(io.BytesIO(body)):
        raise RuntimeError(f"{item['url']} did not return an xlsx (got {ctype or 'unknown type'} from {final}); not using it")
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(body)
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------- 标准库读 xlsx

def _col(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(M + "t"))


class Workbook:
    """只读：工作表名 → 行迭代器（{列字母: 文本}），共享字符串、inlineStr、数字都转成字符串。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.z = zipfile.ZipFile(self.path)
        names = set(self.z.namelist())
        self.sst: List[str] = []
        if "xl/sharedStrings.xml" in names:
            self.sst = [_text(si) for si in ET.fromstring(self.z.read("xl/sharedStrings.xml")).findall(M + "si")]
        wb = ET.fromstring(self.z.read("xl/workbook.xml"))
        pr = wb.find(M + "workbookPr")
        self.date1904 = pr is not None and pr.get("date1904") in ("1", "true")
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ET.fromstring(self.z.read("xl/_rels/workbook.xml.rels")).iter(PKG_REL):
                t = rel.get("Target") or ""
                rels[rel.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        self.sheets: List[Tuple[str, str]] = []
        sheets_el = wb.find(M + "sheets")
        for i, s in enumerate(list(sheets_el) if sheets_el is not None else [], 1):
            self.sheets.append((s.get("name") or f"Sheet{i}", rels.get(s.get(R_ID), f"xl/worksheets/sheet{i}.xml")))

    def close(self) -> None:
        self.z.close()

    def _value(self, c) -> Optional[str]:
        t = c.get("t")
        if t == "inlineStr":
            is_ = c.find(M + "is")
            return _text(is_) if is_ is not None else None
        v = c.find(M + "v")
        if v is None or v.text is None:
            return None
        if t == "s":
            return self.sst[int(v.text)]
        return v.text

    def rows(self, part: str) -> Iterator[Tuple[int, Dict[str, Optional[str]]]]:
        with self.z.open(part) as f:
            for _, el in ET.iterparse(f):
                if el.tag == M + "row":
                    vals = {}
                    for c in el.findall(M + "c"):
                        v = self._value(c)
                        if v is not None and str(v).strip() != "":
                            vals[_col(c.get("r") or "")] = str(v).strip()
                    yield int(el.get("r") or 0), vals
                    el.clear()


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).lower()


def read_legend(wb: Workbook) -> Dict:
    """Definitions / Legend 表：{columns: {列名小写: 定义}, dwelling_codes: {F: 'Flat/unit', …}, sheet: 名字}。没有就给空。"""
    for name, part in wb.sheets:
        if not re.search(r"defin|legend|descr|notes", name, re.I):
            continue
        cols = {}
        for _, vals in wb.rows(part):
            cells = [vals[k] for k in sorted(vals, key=lambda x: (len(x), x))]
            if len(cells) >= 2 and _norm(cells[0]) in FIELDS.values():
                cols[_norm(cells[0])] = " ".join(cells[1].replace("\xa0", " ").split())
        codes = {}
        for code, label in re.findall(r"\(([A-Z])\)\s*([^;().]+)", cols.get(FIELDS["dwelling"], "")):
            codes[code] = label.strip()
        return {"sheet": name, "columns": cols, "dwelling_codes": codes}
    return {"sheet": None, "columns": {}, "dwelling_codes": {}}


def find_data_sheet(wb: Workbook, wanted: List[str]) -> Tuple[str, str, int, Dict[str, str], Optional[str]]:
    """哪张表的前 30 行里有一行表头包含全部列名 → (表名, 部件路径, 表头行号, {字段: 列字母}, 标题文字)。"""
    for name, part in wb.sheets:
        title = None
        for rn, vals in wb.rows(part):
            if rn > 30:
                break
            if title is None and vals:
                title = " ".join(next(iter(vals.values())).split())
            by_text = {_norm(v): col for col, v in vals.items()}
            if all(w in by_text for w in wanted):
                cols = {field: by_text[label] for field, label in FIELDS.items()}
                return name, part, rn, cols, title
    raise ValueError(f"{wb.path.name}: no sheet has a header row with {wanted}")


def excel_date(raw: Optional[str], date1904: bool = False) -> Optional[dt.date]:
    if not raw:
        return None
    s = raw.strip()
    try:
        x = float(s)
        if 20000 < x < 80000:  # 1954–2119 的序列号
            base = dt.date(1904, 1, 1) if date1904 else dt.date(1899, 12, 30)
            return base + dt.timedelta(days=int(x))
        return None
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    return None


def _postcode(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        x = float(raw)
    except ValueError:
        return None
    if x != int(x) or not 200 <= x <= 9999:
        return None
    return f"{int(x):04d}"


def _int_or_none(raw: Optional[str]) -> Optional[int]:
    try:
        x = float(raw or "")
    except ValueError:
        return None
    return int(x) if x == int(x) else None


def read_file(path: Path, fallback_month: Optional[Tuple[int, int]] = None) -> Dict:
    """一个月度文件 → {'records': [(postcode, dwelling, beds_bucket, rent, 'YYYY-MM')], 'skipped': Counter, 'legend': …, …}。"""
    wb = Workbook(path)
    try:
        legend = read_legend(wb)
        wanted = list(FIELDS.values())
        if legend["columns"]:
            missing = [w for w in wanted if w not in legend["columns"]]
            if missing:
                raise ValueError(f"{path.name}: legend has no definition for {missing}; the file layout changed")
        name, part, header_row, cols, title = find_data_sheet(wb, wanted)
        file_month = month_from_text(title or "") or fallback_month or month_from_text(path.name)
        codes = legend["dwelling_codes"] or {c: DWELLING_LABELS[c] for c in KEEP_DWELLINGS}
        keep = {c for c in KEEP_DWELLINGS if c in codes}
        records: List[Tuple[str, str, int, float, str]] = []
        skipped: Counter = Counter()
        months: Counter = Counter()
        read = 0
        for rn, vals in wb.rows(part):
            if rn <= header_row or not vals:
                continue
            read += 1
            pc = _postcode(vals.get(cols["postcode"]))
            if pc is None:
                skipped["postcode missing or not a postcode"] += 1
                continue
            dw = (vals.get(cols["dwelling"]) or "").strip().upper()
            if dw not in keep:
                skipped[f"dwelling {dw or 'blank'}" if dw in ("O", "U", "") else "dwelling code not in legend"] += 1
                continue
            beds = _int_or_none(vals.get(cols["beds"]))
            if beds is None or beds < 0:
                skipped["bedrooms U, blank or not a number"] += 1
                continue
            try:
                rent = float(vals.get(cols["rent"]) or "")
            except ValueError:
                skipped["rent U, blank or not a number"] += 1
                continue
            if rent <= 0 or rent > MAX_RENT:
                skipped[f"rent <= 0 or > {MAX_RENT}"] += 1
                continue
            d = excel_date(vals.get(cols["date"]), wb.date1904)
            if d is not None:
                ym = f"{d.year:04d}-{d.month:02d}"
            elif file_month:
                ym = f"{file_month[0]:04d}-{file_month[1]:02d}"
                skipped["date unreadable (kept, used the file month)"] += 1
            else:
                skipped["date unreadable and no file month"] += 1
                continue
            months[ym] += 1
            records.append((pc, dw, min(beds, POOL_BEDS), rent, ym))
        return {"file": path.name, "sheet": name, "header_row": header_row, "title": title,
                "file_month": f"{file_month[0]:04d}-{file_month[1]:02d}" if file_month else None,
                "legend": legend, "rows_read": read, "rows_kept": len(records), "skipped": skipped,
                "lodgement_months": dict(sorted(months.items())), "records": records}
    finally:
        wb.close()


# ---------------------------------------------------------------- 聚合

def _round(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def aggregate(records) -> List[Dict]:
    groups: Dict[Tuple[str, str, int], List[float]] = defaultdict(list)
    span: Dict[Tuple[str, str, int], List[str]] = {}
    for pc, dw, beds, rent, ym in records:
        k = (pc, dw, beds)
        groups[k].append(rent)
        s = span.get(k)
        span[k] = [min(s[0], ym), max(s[1], ym)] if s else [ym, ym]
    rows = []
    for k in sorted(groups):
        xs = sorted(groups[k])
        med = statistics.median(xs)
        if len(xs) >= 2:
            q1, _, q3 = statistics.quantiles(xs, n=4, method="inclusive")
        else:
            q1 = q3 = med
        rows.append({"postcode": k[0], "dwelling": k[1], "beds": k[2], "n": len(xs), "median": _round(med), "q1": _round(q1), "q3": _round(q3),
                     "first_month": span[k][0], "last_month": span[k][1]})
    return rows


def csv_text(rows: List[Dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def month_label(first: str, last: str) -> str:
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    fy, fm = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    if (fy, fm) == (ly, lm):
        return f"{names[fm - 1]} {fy}"
    if fy == ly:
        return f"{names[fm - 1]}–{names[lm - 1]} {ly}"
    return f"{names[fm - 1]} {fy}–{names[lm - 1]} {ly}"


def build_meta(items: List[Dict], per_file: List[Dict], rows: List[Dict], page_final: Optional[str]) -> Dict:
    skipped: Counter = Counter()
    for f in per_file:
        skipped.update(f["skipped"])
    months = sorted(f["file_month"] for f in per_file if f["file_month"])
    legend = next((f["legend"] for f in per_file if f["legend"]["columns"]), {"columns": {}, "dwelling_codes": {}})
    return {
        "dataset": "NSW Fair Trading residential rental bond lodgements (monthly files)",
        "what": "New residential tenancies whose bond was lodged with NSW Fair Trading; weekly rent, dwelling type and bedrooms as given by the agent or landlord at lodgement.",
        "source_page": SOURCE_PAGE,
        "source_page_resolved": page_final,
        "licence": LICENCE,
        "months": month_label(months[0], months[-1]) if months else None,
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "files": [{"month": f["file_month"], "title": it.get("title"), "url": it.get("url"), "file": f["file"], "bytes": it.get("bytes"),
                   "sha256": it.get("sha256"), "sheet": f["sheet"], "header_row": f["header_row"], "rows_read": f["rows_read"],
                   "rows_kept": f["rows_kept"], "lodgement_months": f["lodgement_months"], "skipped": dict(sorted(f["skipped"].items()))}
                  for it, f in zip(items, per_file)],
        "rows": {"read": sum(f["rows_read"] for f in per_file), "kept": sum(f["rows_kept"] for f in per_file),
                 "skipped": dict(sorted(skipped.items())), "csv_rows": len(rows),
                 "csv_rows_n_ge_10": sum(1 for r in rows if r["n"] >= 10), "postcodes": len({r["postcode"] for r in rows})},
        "legend": {"columns": legend["columns"], "dwelling_codes": legend["dwelling_codes"]},
        "filters": [
            "Dwelling type kept: F (flat/unit), H (house), T (terrace/townhouse/semi-detached). Dropped: O (other: rented rooms, garages, car spaces per the legend), U (unknown), blank and codes not in the legend.",
            "Bedrooms: U, blank or non-numeric dropped; 0 kept (studio or bedsitter per the legend); 4 or more pooled as 4.",
            f"Weekly rent: U, blank, non-numeric, <= 0 or > {MAX_RENT} dropped.",
            "Postcode: must be a whole number 0200-9999.",
            "Lodgement month comes from the lodgement date (Excel serial); if unreadable, the month in the file title.",
        ],
        "columns": {"postcode": "4-digit postcode of the rented premises", "dwelling": "F, H or T", "beds": "0-3, or 4 meaning 4 or more",
                    "n": "lodgements in the window", "median": "median weekly rent, AUD, rounded half up",
                    "q1": "25th percentile (statistics.quantiles inclusive = Excel QUARTILE.INC), rounded", "q3": "75th percentile, same method",
                    "first_month": "earliest lodgement month in this cell (YYYY-MM)", "last_month": "latest lodgement month in this cell"},
        "lookup_min_n": 10,
        "generated_by": "scripts/nsw_bonds.py",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def _offline_items(raw_dir: Path, months: int) -> List[Dict]:
    """不连网：用 raw 目录里已有的文件；链接从上一次的 meta 里按文件名找回来。"""
    old = {}
    if OUT_META.exists():
        try:
            for f in json.loads(OUT_META.read_text(encoding="utf-8")).get("files", []):
                old[f.get("file")] = f
        except (ValueError, OSError):
            pass
    found = {}
    for p in raw_dir.glob("*.xlsx"):
        ym = month_from_text(p.name)
        if ym and zipfile.is_zipfile(p) and ym not in found:
            o = old.get(p.name, {})
            found[ym] = {"year": ym[0], "month": ym[1], "title": o.get("title"), "url": o.get("url"), "file": p.name}
    return [found[k] for k in sorted(found, reverse=True)][:months]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="NSW rental bond lodgements -> data/public/nsw_bond_rents.csv")
    ap.add_argument("--months", type=int, default=6, help="latest N monthly files (default 6)")
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW, help=f"where raw xlsx files go (default {DEFAULT_RAW}); never inside the repo")
    ap.add_argument("--dry", action="store_true", help="list files; aggregate only if all are already downloaded; write nothing")
    ap.add_argument("--offline", action="store_true", help="no network: use the xlsx files already in --raw-dir")
    a = ap.parse_args(argv)
    raw_dir = a.raw_dir.expanduser().resolve()
    if raw_dir == ROOT or ROOT in raw_dir.parents:
        print(f"--raw-dir {raw_dir} is inside the repo; raw files must stay outside it", file=sys.stderr)
        return 2
    raw_dir.mkdir(parents=True, exist_ok=True)

    page_final = None
    if a.offline:
        items = _offline_items(raw_dir, a.months)
    else:
        body, page_final, _ = _get(SOURCE_PAGE)
        items = discover(body.decode("utf-8", "replace"), page_final)[: a.months]
    if len(items) < a.months:
        print(f"only {len(items)} monthly files available (wanted {a.months})", file=sys.stderr)
    if not items:
        return 1
    for it in items:
        have = (raw_dir / it["file"]).exists() and zipfile.is_zipfile(raw_dir / it["file"])
        print(f"{it['year']}-{it['month']:02d}  {'have' if have else 'get '}  {it['file']}  {it.get('url') or ''}")
    if a.dry:
        if not all(zipfile.is_zipfile(raw_dir / it["file"]) if (raw_dir / it["file"]).exists() else False for it in items):
            print("dry run: some files are not downloaded yet; nothing aggregated, nothing written")
            return 0
    else:
        for it in items:
            if not ((raw_dir / it["file"]).exists() and zipfile.is_zipfile(raw_dir / it["file"])):
                download(it, raw_dir)
                time.sleep(0.5)

    items = list(reversed(items))  # 旧到新
    per_file, records = [], []
    for it in items:
        p = raw_dir / it["file"]
        it["bytes"] = p.stat().st_size
        it["sha256"] = _sha256(p)
        f = read_file(p, (it["year"], it["month"]))
        records.extend(f.pop("records"))
        per_file.append(f)
        print(f"{f['file']}: sheet '{f['sheet']}' header row {f['header_row']}, read {f['rows_read']}, kept {f['rows_kept']}, "
              f"skipped {sum(f['skipped'].values())} {dict(f['skipped'])}")
    rows = aggregate(records)
    meta = build_meta(items, per_file, rows, page_final)
    text = csv_text(rows)
    print(f"{len(records)} lodgements -> {len(rows)} cells ({meta['rows']['csv_rows_n_ge_10']} with n >= 10), "
          f"{meta['rows']['postcodes']} postcodes, {meta['months']}, csv {len(text.encode('utf-8')) / 1024:.0f} KB")
    if a.dry:
        print("dry run: nothing written")
        return 0
    changed_csv = _write_if_changed(OUT_CSV, text)
    old_meta = None
    if OUT_META.exists():
        try:
            old_meta = json.loads(OUT_META.read_text(encoding="utf-8"))
        except ValueError:
            old_meta = None
    if old_meta and not changed_csv:
        same = {k: v for k, v in old_meta.items() if k not in ("generated_at", "source_page_resolved")} == \
               {k: v for k, v in meta.items() if k not in ("generated_at", "source_page_resolved")}
        if same:
            print(f"unchanged: {OUT_CSV.relative_to(ROOT)} and {OUT_META.relative_to(ROOT)}")
            return 0
    _write_if_changed(OUT_META, json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_CSV.relative_to(ROOT)} and {OUT_META.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
