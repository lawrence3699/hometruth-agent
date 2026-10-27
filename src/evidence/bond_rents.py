# -*- coding: utf-8 -*-
"""真实市场租金：NSW Fair Trading 押金登记（rental bond lodgements，政府开放数据，CC BY 4.0）按 邮编 × 房型 × 卧室数 聚合的新签周租。

数据：data/public/nsw_bond_rents.csv（scripts/nsw_bonds.py 生成；列 postcode,dwelling,beds,n,median,q1,q3,first_month,last_month；
来源、许可、署名、过滤规则在旁边的 .meta.json）。只用标准库，第一次查找时读一遍 CSV 缓存在内存（文件改了自动重读），Mac 和 Windows 都能跑。

接口（别的模块按这个写，别改形状）：
  lookup(postcode, beds, dwelling="F") -> dict | None
      dwelling 收 F / H / T 代码，也收挂牌的类型文字（'Apartment / Unit / Flat' → F，'House' → H，'Townhouse' / 'Terrace' → T）；
      beds ≥ 4 合成 4；没有这一格、或样本 n < 10、或类型认不出（Other、车位、乡村地块……）都返回 None —— 认不出就是未知，不硬套。
  evidence_text(rent, rec) -> str   一行大白话英文，给证据抽屉 / 旁白用。
"""
from __future__ import annotations

import csv
import os
import re
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "data" / "public" / "nsw_bond_rents.csv"
SOURCE = "NSW Fair Trading rental bond lodgements"
SOURCE_URL = "https://www.fairtrading.nsw.gov.au/about-fair-trading/rental-bond-data"
MIN_N = 10
POOL_BEDS = 4
LABELS = {"F": "flat/unit", "H": "house", "T": "terrace/townhouse"}
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# 挂牌类型文字 → Fair Trading 房型代码。先认 T（"Townhouse" 里也有 house），再 F，再 H；Fair Trading 的 T 是 terrace/townhouse/semi-detached，
# duplex、villa 这种连体的也算 T。乡村地块、车位、养老村、空地认不出 → None（未知，不硬套成 house）。
_T = re.compile(r"town\s*-?\s*houses?|terraces?|semi[\s\-]*detached|duplex|villas?")
_F = re.compile(r"\b(?:apartments?|units?|flats?|studios?|pent\s*-?\s*houses?|bedsitters?)\b")
_H = re.compile(r"\b(?:houses?|cottages?|free\s*-?\s*standing)\b")
_NOT = re.compile(r"\b(?:car\s*space|garage|parking|land|acreage|rural|retirement|farm|vacant)\b")

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Dict[Tuple[str, str, int], dict]]] = {}


def dwelling_code(kind: Optional[str]) -> Optional[str]:
    """'F' / 'H' / 'T' 原样；挂牌类型文字按关键词映射；认不出（含 O 其他、U 未知）→ None。"""
    if kind is None:
        return None
    s = str(kind).strip()
    if s.upper() in LABELS:
        return s.upper()
    low = s.lower().replace("_", " ")
    if not low or _NOT.search(low):
        return None
    if _T.search(low):
        return "T"
    if _F.search(low):
        return "F"
    if _H.search(low):
        return "H"
    return None


def _postcode(p: Union[str, int, None]) -> Optional[str]:
    if p is None or isinstance(p, bool):
        return None
    s = str(p).strip()
    if isinstance(p, float):
        if p != int(p):
            return None
        s = str(int(p))
    if not s.isdigit() or not 1 <= len(s) <= 4:
        return None
    return s.zfill(4)


def _beds(b: Union[str, int, float, None]) -> Optional[int]:
    if b is None or isinstance(b, bool):
        return None
    try:
        x = float(str(b).strip())
    except ValueError:
        return None
    if x != int(x) or x < 0:
        return None
    return min(int(x), POOL_BEDS)


def months_label(first: str, last: str) -> str:
    """'2026-04', '2026-09' → 'Apr–Sep 2026'；跨年 'Nov 2025–Apr 2026'；同月 'Sep 2026'。"""
    fy, fm = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    if (fy, fm) == (ly, lm):
        return f"{_MON[fm - 1]} {fy}"
    if fy == ly:
        return f"{_MON[fm - 1]}–{_MON[lm - 1]} {ly}"
    return f"{_MON[fm - 1]} {fy}–{_MON[lm - 1]} {ly}"


def _load(path: Path) -> Dict[Tuple[str, str, int], dict]:
    key = str(path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        table: Dict[Tuple[str, str, int], dict] = {}
        with open(path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    k = (r["postcode"].strip().zfill(4), r["dwelling"].strip().upper(), int(r["beds"]))
                    table[k] = {"n": int(r["n"]), "median": int(float(r["median"])), "q1": int(float(r["q1"])), "q3": int(float(r["q3"])),
                                "first_month": r["first_month"].strip(), "last_month": r["last_month"].strip()}
                except (KeyError, ValueError, AttributeError):
                    continue
        _cache[key] = (mtime, table)
        return table


def lookup(postcode: Union[str, int], beds: int, dwelling: str = "F", *, path: Optional[Union[str, Path]] = None) -> Optional[dict]:
    """这个邮编、这种房型、这么多卧室，最近半年新签租约的周租中位数和中间一半区间；样本不够（n < 10）或查不到 → None。
    path 只给测试用（换成小的 fixture CSV）。"""
    pc, nb, dw = _postcode(postcode), _beds(beds), dwelling_code(dwelling)
    if pc is None or nb is None or dw is None:
        return None
    row = _load(Path(path) if path else CSV_PATH).get((pc, dw, nb))
    if not row or row["n"] < MIN_N:
        return None
    return {"postcode": pc, "beds": nb, "dwelling": dw, "dwelling_label": LABELS[dw], "n": row["n"], "median": row["median"],
            "q1": row["q1"], "q3": row["q3"], "months": months_label(row["first_month"], row["last_month"]),
            "source": SOURCE, "source_url": SOURCE_URL}


def _money(x: Union[int, float]) -> str:
    return f"${int(round(x)):,}"


def _rent(rent) -> Optional[int]:
    """挂牌租金：数字直接用；'$820 per week' 这种文字取第一个数。认不出 → None（那就不比）。"""
    if rent is None or isinstance(rent, bool):
        return None
    if isinstance(rent, (int, float)):
        return int(rent + 0.5) if rent > 0 else None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(rent))
    if not m:
        return None
    x = float(m.group(0).replace(",", ""))
    return int(x + 0.5) if x > 0 else None


def compare(rent, median: Union[int, float]) -> Optional[Tuple[int, str]]:
    """(百分比整数, 'above' / 'below' / 'in line')，四舍五入（半数进位）；挂牌租金认不出 → None。"""
    r = _rent(rent)
    if r is None or not median:
        return None
    pct = (r - median) * 100.0 / median  # 先乘后除：整数输入时 0.5% 这种边界是精确的
    k = int(abs(pct) + 0.5)
    if k == 0:
        return 0, "in line"
    return k, "above" if pct > 0 else "below"


def evidence_text(rent: int, rec: dict) -> str:
    """'NSW Fair Trading: 312 new 2-bedroom flat/unit leases in 2033 lodged Apr–Sep 2026, median $780 a week (middle half $700–$850);
    this one asks $820 (5% above).' —— 挂牌租金认不出时只说市场那半句。"""
    beds = int(rec["beds"])
    label = rec.get("dwelling_label") or LABELS.get(rec.get("dwelling", ""), "home")
    if beds == 0:
        kind = f"studio/0-bedroom {label}"
    elif beds >= POOL_BEDS:
        kind = f"{POOL_BEDS}-or-more-bedroom {label}"
    else:
        kind = f"{beds}-bedroom {label}"
    s = (f"NSW Fair Trading: {int(rec['n']):,} new {kind} leases in {rec['postcode']} lodged {rec['months']}, "
         f"median {_money(rec['median'])} a week (middle half {_money(rec['q1'])}–{_money(rec['q3'])})")
    cmp_ = compare(rent, rec["median"])
    if cmp_ is not None:
        pct, word = cmp_
        tail = "in line with the median" if word == "in line" else f"{pct}% {word}"
        s += f"; this one asks {_money(_rent(rent))} ({tail})"
    return s + "."
