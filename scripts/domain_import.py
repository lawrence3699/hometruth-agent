#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户在自己浏览器里另存的 domain.com.au / realestate.com.au 页面（.html / .htm）→ 房源 JSON。

只解析本机文件，不联网：不请求 domain.com.au / realestate.com.au（照片 CDN 的下载在主会话另做）。
文件当不可信数据：只用 json / re / html.parser，绝不执行页面里的任何东西；编号只收纯数字（文件名用它），字符串截长。

认页面靠内容标记，不看文件名：
  Domain 搜索结果页  <script id="__NEXT_DATA__"> → props.pageProps.componentProps 里有 listingSearchResultIds / listingsMap / currentPage / totalPages；
                     每张卡片 listingsMap[id].listingModel = {url, images, retinaImages, price, address, features, branding, tags, inspection, …}
  Domain 单套挂牌页  同样是 __NEXT_DATA__，componentProps 有 listingId / listingSummary / gallery（data/real/domain 里原来 9 套就是这么来的）；
                     页面自带的 listingsMap（"相似房源"卡片）也按搜索卡片收
  REA 页面           window.ArgonautExchange = {...}，里面的值（urqlClientCache 等）是一层套一层的 JSON 字符串：递归 json.loads，
                     再找"像房源"的字典（有编号 + address + price / propertyType / generalFeatures）

输出（schema 和 data/real/domain 原来 9 个文件一致，另加 site / card_only / state / rentWeekly / tag / inspection / also_on / needs_geocode）：
  <out>/domain/<id>.json（site "domain"，矩阵编号 L-D<id>）    <out>/rea/<id>.json（site "rea"，矩阵编号 L-R<id>）
  搜索卡片没有正文、可入住日、押金、户型图标记：这些就留空（description []、stats {}），由 Agent 变成该问中介的问题，绝不补造。
  没写周租数字的卡片（项目盘、"Contact agent"、月租 / 售价）跳过并报原因。
  卡片 parking 字段 Domain 在 0 的时候干脆不给：这里记 None（来源没说），不替它写 0。

合并规则：
  - 已有的"富"文件（没有 card_only 键：原来 9 套或挂牌页导入的）永远不被覆盖，只补缺的字段（键不存在或值为 None）。
  - 已有卡片文件 + 新的挂牌页数据 → 升级成富文件（card_only 去掉），卡片独有的字段补回去。
  - 卡片 + 卡片 → 存档时间（文件 mtime）新的那份为准，旧的只补缺。
  - 同一批页面重复导入结果不变（内容没变就不写文件）。
  - 跨站重复（门牌号 / 单元 / 街名 / suburb 规范化后相同）：留 Domain 文件，REA 编号记进它的 also_on；
    之前单独导进来的 REA 文件（本脚本生成的）会删掉，保证先导 REA 还是先导 Domain 结果一样。

跑：.venv/bin/python scripts/domain_import.py                       # 默认扫 ~/Downloads
    .venv/bin/python scripts/domain_import.py ~/Downloads/rent --since 2026-10-27 --dry
    --out 换输出目录（默认 data/real，测试用临时目录）；-r 连子文件夹一起扫
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "data" / "real"
DOMAIN_BASE = "https://www.domain.com.au"
REA_BASE = "https://www.realestate.com.au"
REA_SIZE = "800x600"
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_TEXT = 4000
MAX_LINES = 300
MAX_SLIDES = 80
ID_RE = re.compile(r"^\d{4,12}$")

SRC_DOMAIN_SEARCH = "domain.com.au search results page saved by the user (__NEXT_DATA__), demo use only"
SRC_DOMAIN_LISTING = "domain.com.au listing page saved by the user (__NEXT_DATA__), demo use only"
SRC_DOMAIN_SIMILAR = "domain.com.au listing page saved by the user (similar-listings card, __NEXT_DATA__), demo use only"
SRC_REA_SEARCH = "realestate.com.au search results page saved by the user (ArgonautExchange), demo use only"
SRC_REA_LISTING = "realestate.com.au listing page saved by the user (ArgonautExchange), demo use only"

# 新记录的键顺序：前半段和原来 9 个文件一模一样，后面是这次加的
KEY_ORDER = ["id", "url", "address", "unit", "streetNumber", "street", "suburb", "postcode", "type", "beds", "baths", "parking", "price", "stats",
             "agency", "headline", "description", "features", "structured", "lat", "lng", "medianRent", "medianBeds", "created", "modified", "slides",
             "fetched_at", "source", "site", "card_only", "state", "rentWeekly", "tag", "inspection", "needs_geocode", "also_on"]
# 合并时永远不从别处抄过来的键（card_only 抄进富文件就等于降级）
NO_FILL = {"card_only", "also_on"}


# ---------------------------------------------------------------- 小工具
def _get(d: Any, *paths: str) -> Any:
    """按 a.b.c 的路径依次试，返回第一个非空值。"""
    for p in paths:
        cur = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, dict):
        return _int(_get(v, "value", "displayValue", "count"))
    m = re.search(r"\d+", str(v).replace(",", ""))
    return int(m.group(0)) if m else None


def _list(v: Any) -> list:
    """页面数据不可信：该是列表的地方不是列表就当空。"""
    return v if isinstance(v, list) else []


def _float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) <= 180 and f != 0 else None


def _text(v: Any, limit: int = 300) -> Optional[str]:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:limit] if s else None


def _title(s: Optional[str]) -> Optional[str]:
    if not s:
        return s
    return s.title() if s.isupper() or s.islower() else s


def _id(v: Any) -> Optional[str]:
    s = str(v).strip() if isinstance(v, (int, str)) and not isinstance(v, bool) else ""
    return s if ID_RE.match(s) else None


def _id_out(s: str) -> Any:
    """文件里的 id：原来 9 个文件是整数，这里也写整数。"""
    return int(s)


def sydney_iso(ts: float) -> str:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ts, ZoneInfo("Australia/Sydney")).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001  Windows 没装 tzdata 时退回本机时区
        return dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def sydney_date(ts: float) -> dt.date:
    return dt.date.fromisoformat(sydney_iso(ts)[:10])


# ---------------------------------------------------------------- 周租、户型、地址
_NOT_WEEKLY = re.compile(r"per\s*month|p\.?\s?c\.?\s?m\b|/\s*m(?:on)?th|monthly|calendar month|per\s*annum|\bp\.?a\.?\b|/\s*y(?:ea)?r|yearly|annually|"
                         r"per\s*night|nightly|/\s*night|per\s*day|daily", re.I)
_WEEK = re.compile(r"per\s*week|\bp\.?\s?w\.?\b|\bp\s*/\s*w\b|/\s*w(?:ee)?k|weekly|a\s+week", re.I)


def weekly_rent(price: Optional[str]) -> Optional[int]:
    """挂牌价字符串 → 周租整数；不是周租（月租、售价、Contact agent）返回 None。范围价取第一个数。"""
    if not price or not isinstance(price, str):
        return None
    s = price.replace(",", "")
    if _NOT_WEEKLY.search(s):
        return None
    weekly = bool(_WEEK.search(s))
    m = re.search(r"\$\s*(\d{2,6})(?:\.\d{1,2})?", s)
    if not m and weekly:
        m = re.search(r"\b(\d{3,5})(?:\.\d{1,2})?\b", s)
    if not m:
        return None
    v = int(m.group(1))
    hi = 20000 if weekly else 5000
    return v if 80 <= v <= hi else None


_TYPES = [(r"studio", "Studio"), (r"apartment|\bunit\b|\bflat\b|penthouse|block\s*of\s*units|apartmentunitflat", "Apartment / Unit / Flat"),
          (r"town\s*-?\s*house", "Townhouse"), (r"terrace", "Terrace"), (r"semi", "Semi-Detached"), (r"duplex", "Duplex"), (r"villa", "Villa"),
          (r"house|home", "House")]


def norm_type(v: Any) -> Optional[str]:
    s = _text(v, 80)
    if not s:
        return None
    if s == "Apartment / Unit / Flat":
        return s
    low = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).lower()
    for pat, out in _TYPES:
        if re.search(pat, low):
            return out
    return _title(s)


_STREET_ABBR = {"avenue": "ave", "av": "ave", "street": "st", "road": "rd", "parade": "pde", "place": "pl", "lane": "ln", "crescent": "cres",
                "cresent": "cres", "cr": "cres", "drive": "dr", "highway": "hwy", "terrace": "tce", "court": "ct", "close": "cl", "boulevard": "bvd",
                "boulevarde": "bvd", "blvd": "bvd", "circuit": "cct", "square": "sq", "grove": "gr", "esplanade": "esp", "parkway": "pkwy",
                "row": "row", "way": "way", "walk": "wlk", "mews": "mews", "circle": "cir"}


def parse_street(line: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """'5/18 Alder Lane' → ('5', '18', 'Alder Lane')；'407/438-448 Birchwood Street' → ('407', '438-448', 'Birchwood Street')；认不出门牌就只给街名或全 None。"""
    s = _text(line, 200)
    if not s or re.search(r"on request|available|undisclosed|contact|withheld", s, re.I):
        return None, None, None
    s = re.sub(r"^(?:level|lvl|floor)\s*\w+\s*,?\s*", "", s, flags=re.I)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        return None, None, None
    # 'Unit 5, 18 Alder Lane' 的逗号要留；'18 Alder Lane, Kensington NSW 2033' 只要第一段
    s = f"{parts[0]}, {parts[1]}" if len(parts) >= 2 and re.match(r"^(?:unit|apartment|apt|flat|suite)\s*\w+$", parts[0], re.I) else parts[0]
    num = r"\d+[A-Za-z]?(?:\s*-\s*\d+[A-Za-z]?)?"
    m = re.match(rf"^(?:(?:unit|apartment|apt|flat|suite|villa|townhouse|shop)\s*)?([A-Za-z]{{0,2}}\d+[A-Za-z]?)\s*/\s*({num})\s+([A-Za-z].*)$", s, re.I)
    if m:
        return m.group(1).upper() if m.group(1)[0].isalpha() else m.group(1), re.sub(r"\s+", "", m.group(2)).upper(), m.group(3).strip(" ,")
    m = re.match(rf"^(?:unit|apartment|apt|flat|suite)\s*([A-Za-z]{{0,2}}\d+[A-Za-z]?)\s*,\s*({num})\s+([A-Za-z].*)$", s, re.I)
    if m:
        return m.group(1), re.sub(r"\s+", "", m.group(2)).upper(), m.group(3).strip(" ,")
    m = re.match(rf"^({num})\s+([A-Za-z].*)$", s)
    if m:
        return None, re.sub(r"\s+", "", m.group(1)).upper(), m.group(2).strip(" ,")
    if not re.search(r"\d", s):
        return None, None, s.split(",")[0].strip()
    return None, None, None


def addr_key(rec: dict) -> Optional[str]:
    """跨站查重用的规范化地址：单元 / 门牌 / 街名（街道类型缩写统一）/ suburb。门牌或街名缺就不查重。"""
    num, street, suburb = rec.get("streetNumber"), rec.get("street"), rec.get("suburb")
    if not (num and street and suburb):
        return None
    unit = str(rec.get("unit") or "").lower()
    unit = re.sub(r"^(unit|apartment|apt|flat|suite)\s*", "", unit).lstrip("0") or ""
    words = re.sub(r"[^a-z0-9 ]", " ", str(street).lower()).split()
    if words:
        words[-1] = _STREET_ABBR.get(words[-1], words[-1])
    return "|".join([unit, str(num).lower().replace(" ", ""), " ".join(words), re.sub(r"[^a-z]", "", str(suburb).lower())])


def full_address(unit, num, street, suburb, state, postcode) -> Optional[str]:
    head = f"{unit}/{num} {street}" if unit and num and street else f"{num} {street}" if num and street else street
    tail = " ".join(x for x in (suburb, state, postcode) if x)
    return ", ".join(x for x in (head, tail) if x) or None


_PHONE = re.compile(r"(?:\+?61|\b0)[\s\-().]*[2-478](?:[\s\-().]*\d){8}\b|\b1[38]00[\s\-]?\d{3}[\s\-]?\d{3}\b|\b13[\s\-]?\d{2}[\s\-]?\d{2}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def clean_lines(text: Any, names: Iterable[str] = ()) -> List[str]:
    """正文 → 行列表：去掉 HTML 标签、电话行、邮箱行、带经纪人名字的行（和原来 9 个文件的处理一样）。"""
    if isinstance(text, list):
        raw = [str(x) for x in text if isinstance(x, (str, int, float))]
    elif isinstance(text, str):
        raw = re.split(r"<br\s*/?>|</p>|\r?\n", text, flags=re.I)
    else:
        return []
    pats = [re.compile(r"\b" + re.escape(n.strip()) + r"\b", re.I) for n in names if n and len(n.strip()) >= 3]
    out = []
    for ln in raw[:MAX_LINES]:
        t = re.sub(r"<[^>]{0,200}>", "", ln)
        t = t.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"').rstrip()[:MAX_TEXT]
        if _PHONE.search(t) or _EMAIL.search(t) or any(p.search(t) for p in pats):
            continue
        out.append(t)
    while out and not out[-1].strip():
        out.pop()
    return out


def _http(url: Any) -> Optional[str]:
    s = _text(url, 1000)
    return s if s and re.match(r"^https?://[^\s\"'<>]+$", s) else None


def _size_of(url: str) -> Tuple[Optional[int], Optional[int]]:
    m = re.search(r"/(?:fit-in/)?(\d{2,4})x(\d{2,4})/", url)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


# ---------------------------------------------------------------- HTML → 脚本
class _Page(HTMLParser):
    """只收 <script> 的属性和原文、canonical / og:url、Chrome 存档注释里的原网址。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: List[Tuple[Dict[str, str], str]] = []
        self.urls: List[str] = []
        self._cur: Optional[Tuple[Dict[str, str], List[str]]] = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            self._cur = (a, [])
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.urls.append(a.get("href", ""))
        elif tag == "meta" and a.get("property", "").lower() == "og:url":
            self.urls.append(a.get("content", ""))

    def handle_endtag(self, tag):
        if tag == "script" and self._cur is not None:
            self.scripts.append((self._cur[0], "".join(self._cur[1])))
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[1].append(data)

    def handle_comment(self, data):
        m = re.match(r"\s*saved from url=\(\d+\)(\S+)", data)
        if m:
            self.urls.insert(0, m.group(1))


def sniff(text: str) -> Optional[str]:
    if "__NEXT_DATA__" in text and re.search(r"domain\.com\.au|domainstatic\.com\.au", text):
        return "domain"
    if ("ArgonautExchange" in text or "__NEXT_DATA__" in text) and re.search(r"realestate\.com\.au|reastatic\.net", text):
        return "rea"
    return None


def parse_html(text: str) -> _Page:
    p = _Page()
    p.feed(text)
    p.close()
    return p


# ---------------------------------------------------------------- 记录
def make_record(**kw) -> dict:
    rec = {k: kw.get(k) for k in KEY_ORDER}
    for k in ("description", "features", "structured", "slides"):
        rec[k] = rec[k] or []
    rec["stats"] = rec["stats"] or {}
    for k in ("tag", "inspection", "needs_geocode", "also_on"):
        if not rec[k]:
            rec.pop(k)
    if not rec.get("card_only"):
        rec.pop("card_only")
    return rec


def _missing(rec: dict) -> List[str]:
    miss = [k for k in ("street", "streetNumber", "suburb", "postcode", "beds", "baths", "parking", "type", "agency") if rec.get(k) in (None, "")]
    if rec.get("lat") is None or rec.get("lng") is None:
        miss.append("lat/lng")
    if not any(s.get("type") == "image" and s.get("url") for s in rec.get("slides") or []):
        miss.append("photos")
    return miss


# ---------------------------------------------------------------- Domain
def _slug_parts(path: str) -> dict:
    """'/5-18-alder-lane-kensington-nsw-2033-90000001' → id / state / postcode / 前缀词。"""
    m = re.search(r"/([a-z0-9-]+)-(nsw|vic|qld|wa|sa|tas|act|nt)-(\d{4})-(\d{5,12})/?$", path or "", re.I)
    if not m:
        m2 = re.search(r"-(\d{5,12})/?$", path or "")
        return {"id": m2.group(1)} if m2 else {}
    return {"prefix": m.group(1).lower(), "state": m.group(2).upper(), "postcode": m.group(3), "id": m.group(4)}


def _slug_street(prefix: str, suburb: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """网址前缀里抠门牌和街名。只有一个数字才当门牌；两个以上分不清"单元/门牌"还是"门牌区间"，就不猜。"""
    if not prefix:
        return None, None, None
    sub = re.sub(r"[^a-z0-9]+", "-", (suburb or "").lower()).strip("-")
    if not sub or not prefix.endswith("-" + sub):
        return None, None, None  # 不知道 suburb 在网址里占几个词，就分不出街名
    prefix = prefix[: -len(sub) - 1]
    toks = prefix.split("-")
    nums = []
    while toks and re.match(r"^\d+[a-z]?$", toks[0]):
        nums.append(toks.pop(0))
    street = " ".join(t.capitalize() for t in toks) or None
    if len(nums) == 1:
        return None, nums[0].upper(), street
    return None, None, street


def domain_card(entry: Any, fetched_at: str, source: str) -> Tuple[Optional[dict], str]:
    """listingsMap 的一项 → (记录, "") 或 (None, 跳过原因)。"""
    if not isinstance(entry, dict):
        return None, "not an object"
    lm = entry.get("listingModel") if isinstance(entry.get("listingModel"), dict) else entry.get("listing") if isinstance(entry.get("listing"), dict) else entry
    ltype = str(entry.get("listingType") or lm.get("listingType") or "").lower()
    if "project" in ltype:
        return None, "project (not a single rental)"
    path = _text(_get(lm, "url", "listingUrl") or entry.get("domainWebsiteUrl"), 500) or ""
    slug = _slug_parts(path)
    lid = _id(entry.get("id")) or _id(lm.get("id")) or _id(lm.get("listingId")) or _id(slug.get("id"))
    if not lid:
        return None, "no listing id"
    price_v = _get(lm, "price", "priceDetails.displayPrice", "displayPrice", "priceDetails.price")
    price = _text(price_v if not isinstance(price_v, dict) else _get(price_v, "displayPrice", "display", "text"), 120)
    rent = weekly_rent(price)
    if rent is None:
        return None, f"no weekly price ({price!r})" if price else "no price"
    ad = lm.get("address") if isinstance(lm.get("address"), dict) else {}
    line = _text(_get(ad, "street", "streetAddress", "displayAddress", "address") or (lm.get("address") if isinstance(lm.get("address"), str) else None), 200)
    suburb = _title(_text(_get(ad, "suburb", "suburbName", "locality"), 60))
    state = (_text(_get(ad, "state", "stateAbbreviation"), 10) or slug.get("state") or "").upper() or None
    postcode = _text(_get(ad, "postcode", "postCode"), 10) or slug.get("postcode")
    unit, num, street = parse_street(line)
    from_slug = False
    if not street:
        unit, num, street = _slug_street(slug.get("prefix", ""), suburb)
        from_slug = bool(street)
    if not (suburb or postcode):
        return None, "no suburb or postcode"
    lat, lng = _float(_get(ad, "lat", "latitude")), _float(_get(ad, "lng", "lon", "longitude"))
    ft = lm.get("features") if isinstance(lm.get("features"), dict) else {}
    ptype = norm_type(_get(ft, "propertyTypeFormatted", "propertyType") or _get(lm, "propertyType") or entry.get("propertyType"))
    beds = _int(_get(ft, "beds", "bedrooms"))
    if beds is None and ptype == "Studio":
        beds = 0
    agency = _text(_get(lm, "branding.agencyName", "branding.agency.name", "branding.agency", "branding.brandName", "branding.name", "agencyName",
                        "agency.name"), 120)
    if not agency and isinstance(lm.get("branding"), dict):
        # 卡片 branding 的键名没抓到过：退一步找名字里带 agency + name 的字符串（agentNames 是经纪人个人名字，不收）
        agency = next((_text(v, 120) for k, v in lm["branding"].items() if isinstance(v, str) and "agency" in k.lower() and "name" in k.lower()), None)
    # 照片：retinaImages[].X1（720x540）优先；只留文件名以本房编号开头的（有一张以上时）
    urls: List[str] = []
    for r in _list(lm.get("retinaImages")):
        u = _http(r.get("X1") or r.get("x1")) if isinstance(r, dict) else _http(r)
        if u:
            urls.append(u)
    if not urls:
        for r in _list(lm.get("images")):
            u = _http(r.get("url") if isinstance(r, dict) else r)
            if u:
                urls.append(u)
    urls = list(dict.fromkeys(urls))
    own = [u for u in urls if u.rsplit("/", 1)[-1].startswith(f"{lid}_")]
    dropped = len(urls) - len(own) if own else 0
    urls = (own or urls)[:MAX_SLIDES]
    slides = [dict(type="image", url=u, w=_size_of(u)[0], h=_size_of(u)[1], caption=None) for u in urls]
    tags = lm.get("tags") if isinstance(lm.get("tags"), dict) else {}
    insp = lm.get("inspection") if isinstance(lm.get("inspection"), dict) else {}
    rec = make_record(
        id=_id_out(lid), url=(DOMAIN_BASE + path) if path.startswith("/") else _http(path) if "domain.com.au" in path else None,
        address=full_address(unit, num, street, suburb, state, postcode), unit=unit, streetNumber=num, street=street, suburb=suburb, postcode=postcode,
        type=ptype, beds=beds, baths=_int(_get(ft, "baths", "bathrooms")), parking=_int(_get(ft, "parking", "carspaces", "parkingSpaces", "cars")),
        price=price, stats={}, agency=agency, headline=_text(_get(lm, "headline", "title"), 300), lat=lat, lng=lng, slides=slides,
        fetched_at=fetched_at, source=source, site="domain", card_only=True, state=state, rentWeekly=rent,
        tag=_text(_get(tags, "tagText", "text"), 60),
        inspection={"open": insp.get("openTime"), "close": insp.get("closeTime")} if insp.get("openTime") else None,
        needs_geocode=lat is None or lng is None)
    rec["_notes"] = (["address from URL slug"] if from_slug else []) + ([f"dropped {dropped} image(s) of another listing"] if dropped else [])
    return rec, ""


def domain_listing(cp: dict, fetched_at: str) -> Tuple[Optional[dict], str]:
    """单套挂牌页的 componentProps → 富记录（和原来 9 个文件同一套字段）。"""
    lid = _id(cp.get("listingId")) or _id(cp.get("id")) or _id(_slug_parts(str(cp.get("listingUrl") or "")).get("id"))
    if not lid:
        return None, "no listing id"
    summ = cp.get("listingSummary") if isinstance(cp.get("listingSummary"), dict) else {}
    price = _text(_get(summ, "title") or _get(cp, "priceGuide.displayPrice", "price"), 120)
    rent = weekly_rent(price)
    if rent is None:
        return None, f"no weekly price ({price!r})" if price else "no price"
    st: Dict[str, Any] = {}
    for s in _list(summ.get("stats")):
        if isinstance(s, dict) and isinstance(s.get("key"), str):
            st[s["key"][:40]] = s.get("iso8601Value") or s.get("value")
    agents = [_text(_get(a, "name", "agentName", "fullName"), 80) for a in _list(cp.get("agents")) if isinstance(a, dict)]
    slides = []
    for s in _list(_get(cp, "gallery.slides"))[:MAX_SLIDES]:
        if not isinstance(s, dict):
            continue
        orig = _get(s, "images.original") or {}
        slides.append({"type": _text(s.get("mediaType"), 20) or "image", "url": _http(orig.get("url")) if isinstance(orig, dict) else None,
                       "w": _int(orig.get("width")) if isinstance(orig, dict) else None, "h": _int(orig.get("height")) if isinstance(orig, dict) else None,
                       "caption": _text(s.get("caption"), 200)})
    m = cp.get("map") if isinstance(cp.get("map"), dict) else {}
    ins = cp.get("suburbInsights") if isinstance(cp.get("suburbInsights"), dict) else {}
    url = _text(cp.get("listingUrl"), 500) or ""
    unit, num, street = _text(cp.get("unitNumber"), 20), _text(cp.get("streetNumber"), 20), _text(cp.get("street"), 120)
    suburb, postcode = _title(_text(cp.get("suburb"), 60)), _text(cp.get("postcode"), 10)
    state = (_text(cp.get("stateAbbreviation"), 10) or "").upper() or None
    lat, lng = _float(m.get("latitude")), _float(m.get("longitude"))
    rec = make_record(
        id=_id_out(lid), url=(DOMAIN_BASE + url) if url.startswith("/") else _http(url),
        address=_text(cp.get("address"), 200) or full_address(unit, num, street, suburb, state, postcode), unit=unit, streetNumber=num, street=street,
        suburb=suburb, postcode=postcode, type=norm_type(cp.get("propertyType")), beds=_int(summ.get("beds") if "beds" in summ else cp.get("beds")),
        baths=_int(summ.get("baths")), parking=_int(summ.get("parking")), price=price, stats=st, agency=_text(cp.get("agencyName"), 120),
        headline=_text(cp.get("headline"), 300), description=clean_lines(cp.get("description"), [a for a in agents if a]),
        features=[t for t in (_text(f, 80) for f in _list(cp.get("features"))) if t],
        structured=[t for t in (_text(f.get("name") if isinstance(f, dict) else f, 80) for f in _list(cp.get("structuredFeatures"))) if t],
        lat=lat, lng=lng, medianRent=_int(ins.get("medianRentPrice")), medianBeds=_int(ins.get("beds")),
        created=_text(cp.get("createdOn"), 40), modified=_text(cp.get("modifiedOn"), 40), slides=slides, fetched_at=fetched_at, source=SRC_DOMAIN_LISTING,
        site="domain", state=state, rentWeekly=rent, needs_geocode=lat is None or lng is None)
    rec["_notes"] = []
    return rec, ""


def parse_domain(page: _Page, fetched_at: str) -> dict:
    nd = None
    for a, t in page.scripts:
        if a.get("id") == "__NEXT_DATA__":
            try:
                nd = json.loads(t)
            except ValueError:
                return {"kind": "domain (bad __NEXT_DATA__)", "records": [], "skipped": Counter()}
            break
    pp = _get(nd, "props.pageProps") if isinstance(nd, dict) else None
    cp = pp.get("componentProps") if isinstance(pp, dict) and isinstance(pp.get("componentProps"), dict) else pp
    cp = cp if isinstance(cp, dict) else {}
    out = {"kind": "domain ?", "records": [], "skipped": Counter(), "page": None, "pages": None, "total": None}
    lm = cp.get("listingsMap") if isinstance(cp.get("listingsMap"), dict) else {}
    if "listingSearchResultIds" in cp or "currentPage" in cp or "totalListings" in cp:
        out.update(kind="domain search", page=_int(cp.get("currentPage")), pages=_int(cp.get("totalPages")), total=_int(cp.get("totalListings")))
        order = [str(i) for i in _list(cp.get("listingSearchResultIds")) if isinstance(i, (int, str))]
        keys = [k for k in order if k in lm] + [k for k in lm if k not in set(order)]
        for k in keys:
            rec, why = domain_card(lm[k], fetched_at, SRC_DOMAIN_SEARCH)
            if rec:
                out["records"].append(rec)
            else:
                out["skipped"].update([why.split(" (")[0]])
                out.setdefault("why", []).append(f"{k}: {why}")
        return out
    if cp.get("listingId") or cp.get("listingSummary") or cp.get("gallery"):
        out["kind"] = "domain listing"
        rec, why = domain_listing(cp, fetched_at)
        own = str(rec["id"]) if rec else str(cp.get("listingId") or "")
        if rec:
            out["records"].append(rec)
        else:
            out["skipped"].update([why.split(" (")[0]])
            out.setdefault("why", []).append(f"{own}: {why}")
        for k, v in lm.items():
            if str(k) == own:
                continue
            r2, why2 = domain_card(v, fetched_at, SRC_DOMAIN_SIMILAR)
            if r2 and str(r2["id"]) != own:
                out["records"].append(r2)
            elif not r2:
                out["skipped"].update([why2.split(" (")[0]])
                out.setdefault("why", []).append(f"{k}: {why2}")
        return out
    out["kind"] = "domain page without listings"
    return out


# ---------------------------------------------------------------- realestate.com.au
def deep_json(v: Any, layers: int = 0, depth: int = 0) -> Any:
    """值里像 JSON 的字符串一层层 json.loads（urqlClientCache → data → …）。字符串最多拆 8 层，结构最多走 200 层。"""
    if depth > 200:
        return v
    if isinstance(v, str):
        s = v.strip()
        if layers < 8 and len(s) >= 2 and s[0] in "{[" and s[-1] in "}]":
            try:
                return deep_json(json.loads(s), layers + 1, depth + 1)
            except (ValueError, RecursionError):
                return v
        return v
    if isinstance(v, dict):
        return {k: deep_json(x, layers, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        return [deep_json(x, layers, depth + 1) for x in v]
    return v


def rea_exchange(page: _Page) -> Optional[Any]:
    dec = json.JSONDecoder()
    for _a, t in page.scripts:
        i = t.find("ArgonautExchange")
        if i < 0:
            continue
        j = t.find("=", i)
        k = t.find("{", j if j >= 0 else i)
        if k < 0:
            continue
        try:
            obj, _end = dec.raw_decode(t, k)
        except ValueError:
            continue
        return deep_json(obj)
    for a, t in page.scripts:  # 万一 REA 换成 Next.js：退到 __NEXT_DATA__ 里同样找"像房源"的字典
        if a.get("id") == "__NEXT_DATA__":
            try:
                return deep_json(json.loads(t))
            except ValueError:
                return None
    return None


def _looks_rea_listing(d: dict) -> bool:
    lid = _id(d.get("id")) or _id(d.get("listingId"))
    return bool(lid) and isinstance(d.get("address"), (dict, str)) and any(k in d for k in ("price", "propertyType", "generalFeatures"))


def _walk(o: Any, out: List[dict], depth: int = 0) -> None:
    if depth > 80:
        return
    if isinstance(o, dict):
        if _looks_rea_listing(o):
            out.append(o)
        for v in o.values():
            _walk(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out, depth + 1)


def _find_first(o: Any, key: str, depth: int = 0) -> Any:
    if depth > 40:
        return None
    if isinstance(o, dict):
        if key in o and o[key] not in (None, "", {}):
            return o[key]
        for v in o.values():
            r = _find_first(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_first(v, key, depth + 1)
            if r is not None:
                return r
    return None


def _geo(d: Any, depth: int = 0) -> Tuple[Optional[float], Optional[float]]:
    """在地址子树里找 latitude / longitude（或 lat / lng）。"""
    if depth > 6 or not isinstance(d, dict):
        return None, None
    lat, lng = _float(_get(d, "latitude", "lat")), _float(_get(d, "longitude", "lng", "lon"))
    if lat is not None and lng is not None:
        return lat, lng
    for k in ("geocode", "location", "coordinates", "display", "map", "geo"):
        if isinstance(d.get(k), dict):
            r = _geo(d[k], depth + 1)
            if r[0] is not None:
                return r
    return None, None


def _rea_date(v: Any, fetched_at: str) -> Tuple[Optional[str], Optional[str]]:
    s = _text(v if not isinstance(v, dict) else _get(v, "display", "value", "date"), 80)
    if not s:
        return None, None
    if re.search(r"\bnow\b|immediate", s, re.I):
        return fetched_at[:10] + "T00:00:00", s
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(0)}T00:00:00", s
    t = re.sub(r"(?i)^available\s*(from\s*)?", "", s)
    t = re.sub(r"(?i)^(mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s*", "", t)
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t).replace(",", " ").strip()
    t = re.sub(r"\s+", " ", t)
    for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(t, fmt).strftime("%Y-%m-%dT00:00:00"), s
        except ValueError:
            pass
    # 没写年份（"Available 18 Nov"）：取存档那年；比存档日早两个月以上就是明年（挂牌上写的都是接下来的日子）。原文留在 availableText
    try:
        saved = dt.date.fromisoformat(fetched_at[:10])
    except ValueError:
        return None, s
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            d = dt.datetime.strptime(f"{t} {saved.year}", fmt).date()
        except ValueError:
            continue
        if d < saved - dt.timedelta(days=60):
            d = d.replace(year=d.year + 1)
        return f"{d.isoformat()}T00:00:00", s
    return None, s


def _rea_img(x: Any) -> Optional[str]:
    if isinstance(x, str):
        u = x
    elif isinstance(x, dict):
        u = _get(x, "templatedUrl", "url", "uri")
        if isinstance(u, str) and u.startswith("/") and isinstance(x.get("server"), str):
            u = x["server"].rstrip("/") + "/{size}" + u
    else:
        return None
    return _http(str(u).replace("{size}", REA_SIZE)) if u else None


def rea_listing(o: dict, fetched_at: str, source: str, card_only: bool) -> Tuple[Optional[dict], str]:
    lid = _id(o.get("id")) or _id(o.get("listingId"))
    if not lid:
        return None, "no listing id"
    pv = o.get("price")
    price = _text(pv if not isinstance(pv, dict) else _get(pv, "display", "displayPrice", "text", "value"), 120)
    rent = weekly_rent(price)
    if rent is None:
        return None, f"no weekly price ({price!r})" if price else "no price"
    ad = o.get("address") if isinstance(o.get("address"), dict) else {}
    line = _text(_get(ad, "display.shortAddress", "streetAddress", "street", "display.streetAddress", "shortAddress") or
                 (o.get("address") if isinstance(o.get("address"), str) else None), 200)
    suburb = _title(_text(_get(ad, "suburb", "locality", "display.suburb"), 60))
    state = (_text(_get(ad, "state", "stateAbbreviation"), 10) or "").upper() or None
    postcode = _text(_get(ad, "postcode", "postCode"), 10)
    full = _text(_get(ad, "display.fullAddress", "fullAddress"), 200)
    if full and not (suburb and postcode):
        m = re.search(r",\s*([A-Za-z' -]+?),?\s+(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+(\d{4})\s*$", full)
        if m:
            suburb, state, postcode = suburb or _title(m.group(1).strip()), state or m.group(2), postcode or m.group(3)
    unit, num, street = parse_street(line)
    if not (suburb or postcode):
        return None, "no suburb or postcode"
    lat, lng = _geo(ad)
    if lat is None:
        lat, lng = _geo({k: o.get(k) for k in ("geocode", "location", "map", "coordinates") if isinstance(o.get(k), dict)})
    gf = o.get("generalFeatures") if isinstance(o.get("generalFeatures"), dict) else _get(o, "features.general") or {}
    pt = o.get("propertyType")
    ptype = norm_type(_get(pt, "display", "id", "name") if isinstance(pt, dict) else pt)
    beds = _int(_get(gf, "bedrooms.value", "bedrooms") if isinstance(gf, dict) else None)
    if beds is None and ptype == "Studio":
        beds = 0
    media = o.get("media") if isinstance(o.get("media"), dict) else {}
    imgs = [u for u in (_rea_img(x) for x in ([media.get("mainImage")] if media.get("mainImage") else []) + _list(media.get("images"))) if u]
    if not imgs:
        imgs = [u for u in (_rea_img(x) for x in _list(o.get("images"))) if u]
    plans = [u for u in (_rea_img(x) for x in _list(media.get("floorplans"))) if u]
    slides = [{"type": "image", "url": u, "w": None, "h": None, "caption": None} for u in dict.fromkeys(imgs)][:MAX_SLIDES]
    slides += [{"type": "floorplan", "url": u, "w": None, "h": None, "caption": None} for u in dict.fromkeys(plans)][:10]
    href = _get(o, "_links.canonical.href", "_links.canonical.path", "_links.canonical", "canonicalUrl", "url", "listingUrl", "link")
    href = _text(href, 500) if isinstance(href, str) else None
    url = (REA_BASE + href) if href and href.startswith("/") else _http(href) if href and "realestate.com.au" in href else None
    names = [_text(_get(x, "name", "fullName"), 80) for x in _list(o.get("listers")) + _list(o.get("agents")) if isinstance(x, dict)]
    stats: Dict[str, Any] = {}
    av, av_text = _rea_date(o.get("availableDate") or o.get("dateAvailable"), fetched_at)
    if av:
        stats["availableFrom"] = av
    if av_text and av_text.lower() != (av or "").lower():
        stats["availableText"] = av_text
    bond = _int(_get(o, "bond.value", "bond.display", "bond") if not isinstance(o.get("bond"), (int, float)) else o.get("bond"))
    if bond:
        stats["bond"] = bond
    feats = []
    for f in _list(o.get("propertyFeatures")) + _list(o.get("features")):
        t = _text(_get(f, "displayLabel", "featureName", "name", "label") if isinstance(f, dict) else f, 80)
        if t and t not in feats:
            feats.append(t)
    rec = make_record(
        id=_id_out(lid), url=url, address=full_address(unit, num, street, suburb, state, postcode), unit=unit, streetNumber=num, street=street,
        suburb=suburb, postcode=postcode, type=ptype, beds=beds,
        baths=_int(_get(gf, "bathrooms.value", "bathrooms") if isinstance(gf, dict) else None),
        parking=_int(_get(gf, "parkingSpaces.value", "parkingSpaces", "carSpaces.value") if isinstance(gf, dict) else None),
        price=price, stats=stats, agency=_text(_get(o, "listingCompany.name", "agency.name", "agencyName"), 120),
        headline=_text(_get(o, "headline", "title"), 300), description=clean_lines(o.get("description"), [n for n in names if n]), features=feats,
        lat=lat, lng=lng, slides=slides, fetched_at=fetched_at, source=source, site="rea", card_only=card_only, state=state, rentWeekly=rent,
        needs_geocode=lat is None or lng is None)
    rec["_notes"] = []
    return rec, ""


def parse_rea(page: _Page, fetched_at: str) -> dict:
    out = {"kind": "rea ?", "records": [], "skipped": Counter(), "page": None, "pages": None, "total": None}
    ex = rea_exchange(page)
    if ex is None:
        out["kind"] = "rea page without ArgonautExchange data"
        return out
    found: List[dict] = []
    _walk(ex, found)
    merged: Dict[str, dict] = {}
    for d in sorted(found, key=lambda x: -len(x)):
        k = _id(d.get("id")) or _id(d.get("listingId"))
        if k in merged:
            for kk, vv in d.items():
                merged[k].setdefault(kk, vv)
        else:
            merged[k] = dict(d)
    main_id = None
    for u in page.urls:
        m = re.search(r"realestate\.com\.au/property-[a-z0-9+-]*?-(\d{6,12})\b", u or "", re.I)
        if m:
            main_id = m.group(1)
            break
    if main_id is None and len(merged) == 1:
        main_id = next(iter(merged))
    out["kind"] = "rea listing" if main_id else "rea search"
    pg = _find_first(ex, "pagination")
    out["page"] = _int(_get(pg, "page", "currentPage")) if isinstance(pg, dict) else None
    out["pages"] = _int(_get(pg, "maxPageNumberAvailable", "totalPages")) if isinstance(pg, dict) else None
    out["total"] = _int(_find_first(ex, "totalResultsCount"))
    for k, d in merged.items():
        is_main = k == main_id
        src = SRC_REA_LISTING if is_main else SRC_REA_SEARCH
        rec, why = rea_listing(d, fetched_at, src, card_only=not is_main)
        if rec:
            out["records"].append(rec)
        else:
            out["skipped"].update([why.split(" (")[0]])
            out.setdefault("why", []).append(f"{k}: {why}")
    return out


# ---------------------------------------------------------------- 合并、查重、写盘
def _dump(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, indent=1) + "\n"


def fill_missing(base: dict, extra: dict, skip: Iterable[str] = ()) -> dict:
    out = dict(base)
    skip = set(skip)
    for k, v in extra.items():
        if k in NO_FILL or k in skip or k.startswith("_"):
            continue
        if out.get(k) is None and v is not None:
            out[k] = v
    return out


def _union_also(a: dict, *others: dict) -> None:
    seen = {(x.get("site"), str(x.get("id"))) for x in _list(a.get("also_on")) if isinstance(x, dict)}
    for o in others:
        for x in _list(o.get("also_on")):
            if isinstance(x, dict) and (x.get("site"), str(x.get("id"))) not in seen:
                a.setdefault("also_on", []).append(x)
                seen.add((x.get("site"), str(x.get("id"))))


def _tidy(rec: dict) -> dict:
    """合并后的派生字段跟着记录自己的值走：周租从它自己的 price 算；有经纬度就去掉 needs_geocode。"""
    if "price" in rec:
        r = weekly_rent(rec.get("price"))
        if r is not None or "rentWeekly" in rec:
            rec["rentWeekly"] = r
    if rec.get("lat") is not None and rec.get("lng") is not None:
        rec.pop("needs_geocode", None)
    return rec


def merge(old: Optional[dict], new: dict) -> Tuple[dict, str]:
    """返回 (合并结果, 怎么合的)。富文件只补缺；卡片遇到挂牌页数据升级；卡片之间按存档时间新的为准。"""
    if old is None:
        return _tidy(dict(new)), "new"
    old_rich, new_rich = "card_only" not in old, "card_only" not in new
    if old_rich:
        out, why = fill_missing(old, new), "filled"
        _union_also(out, new)
    elif new_rich:
        out, why = fill_missing(new, old), "upgraded"
        _union_also(out, old, new)
    elif str(new.get("fetched_at") or "") >= str(old.get("fetched_at") or ""):
        # 新存档的卡片为准；角标和开放看房时间是"当时"的状态，旧的不抄回来
        out, why = fill_missing(new, old, skip=("tag", "inspection")), "refreshed"
        _union_also(out, old, new)
    else:
        out, why = fill_missing(old, new), "kept newer"
        _union_also(out, new)
    return _tidy(out), why


def _load_dir(d: Path, site: str) -> Dict[Tuple[str, str], Tuple[dict, str]]:
    out = {}
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        if not ID_RE.match(f.stem):
            continue
        try:
            txt = f.read_text(encoding="utf-8")
            obj = json.loads(txt)
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict):
            out[(site, f.stem)] = (obj, txt)
    return out


def collect(paths: Iterable[Path], since: Optional[dt.date], recursive: bool, log: Callable[[str], None] = print) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            files += [f for f in it if f.is_file() and f.suffix.lower() in (".html", ".htm")]
        elif p.is_file():
            files.append(p)
        else:
            log(f"{p}: not found")
    files = sorted(set(files), key=lambda f: (f.stat().st_mtime, str(f)))
    if since:
        files = [f for f in files if sydney_date(f.stat().st_mtime) >= since]
    return files


def _search_key(res: dict) -> Tuple[str, str]:
    """同一个搜索的不同页归一组：去掉网址里的页码；没网址就按"共几条 / 共几页"分。"""
    u = res.get("url") or ""
    u = re.sub(r"([?&])page=\d+&?", r"\1", u).rstrip("?&")
    u = re.sub(r"/list-\d+", "/list-N", u)
    return res["kind"], u or f"{res.get('total')} listings / {res.get('pages')} pages"


def coverage(pages: List[dict]) -> List[str]:
    """每个搜索存了哪几页、还缺哪几页（要凑够 100 套就照着补存）。"""
    groups: Dict[Tuple[str, str], dict] = {}
    for r in pages:
        if not r["kind"].endswith("search") or not r.get("page"):
            continue
        g = groups.setdefault(_search_key(r), {"pages": set(), "of": r.get("pages"), "total": r.get("total")})
        g["pages"].add(r["page"])
        g["of"] = g["of"] or r.get("pages")
    out = []
    for (kind, key), g in groups.items():
        have = sorted(g["pages"])
        miss = [i for i in range(1, (g["of"] or 0) + 1) if i not in g["pages"]]
        out.append(f"{kind} {key}: saved page(s) {', '.join(map(str, have))}" + (f" of {g['of']}" if g["of"] else "") +
                   (f" ({g['total']} listings on the site)" if g["total"] else "") + (f"; not saved yet: {_ranges(miss)}" if miss else ""))
    return out


def _ranges(nums: List[int]) -> str:
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(out)


_RANK = {"new": 5, "upgraded": 4, "refreshed": 3, "filled": 2, "kept newer": 1, "also_on": 0}


def run(paths: Iterable[Path], out_dir: Path = OUT_DEFAULT, dry: bool = False, since: Optional[dt.date] = None, recursive: bool = False,
        log: Callable[[str], None] = print) -> dict:
    """解析 → 合并 → 跨站查重 → 只写内容真变了的文件。返回汇总（测试用）。"""
    out_dir = Path(out_dir)
    disk = {**_load_dir(out_dir / "domain", "domain"), **_load_dir(out_dir / "rea", "rea")}
    state: Dict[Tuple[str, str], dict] = {k: v[0] for k, v in disk.items()}
    how: Dict[Tuple[str, str], str] = {}
    touched: List[Tuple[str, str]] = []
    notes: Counter = Counter()
    pages = []
    files = collect(paths, since, recursive, log)
    for f in files:
        try:
            if f.stat().st_size > MAX_FILE_BYTES:
                log(f"{f.name}: skipped, larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
                continue
            text = f.read_bytes().decode("utf-8", errors="replace")
        except OSError as e:
            log(f"{f.name}: cannot read ({type(e).__name__})")
            continue
        site = sniff(text)
        if not site:
            continue
        fetched_at = sydney_iso(f.stat().st_mtime)
        page = parse_html(text)
        res = parse_domain(page, fetched_at) if site == "domain" else parse_rea(page, fetched_at)
        res["file"] = f.name
        res["url"] = next((u for u in page.urls if u), None)
        pages.append(res)
        miss: Counter = Counter()
        for rec in res["records"]:
            for n in rec.pop("_notes", []):
                notes[n] += 1
            miss.update(_missing(rec))
            key = (rec["site"], str(rec["id"]))
            merged, why = merge(state.get(key), rec)
            state[key] = merged
            if key not in disk:
                why = "new"
            if _RANK.get(why, 0) >= _RANK.get(how.get(key, ""), -1):
                how[key] = why
            if key not in touched:
                touched.append(key)
        pg = f" page {res['page'] or '?'}/{res['pages'] or '?'}" if res.get("page") or res.get("pages") else ""
        tot = f" (site says {res['total']} listings)" if res.get("total") else ""
        sk = sum(res["skipped"].values())
        log(f"{f.name}: {res['kind']}{pg}{tot}: {len(res['records'])} parsed, {sk} skipped" +
            (" (" + ", ".join(f"{k} x{v}" for k, v in res["skipped"].most_common()) + ")" if sk else ""))
        for w in res.get("why", [])[:12]:
            log(f"   skipped {w}")
        if miss:
            log("   missing: " + ", ".join(f"{k} x{v}" for k, v in miss.most_common()))
    # 跨站查重：留 Domain，REA 编号记进 also_on；之前单独导进来的 REA 文件删掉
    dom_keys: Dict[str, Tuple[str, str]] = {}
    for key, rec in state.items():
        if key[0] == "domain":
            k = addr_key(rec)
            if k and k not in dom_keys:
                dom_keys[k] = key
    dupes: List[Tuple[Tuple[str, str], Tuple[str, str]]] = []
    for key, rec in list(state.items()):
        if key[0] != "rea":
            continue
        k = addr_key(rec)
        if k and k in dom_keys:
            dk = dom_keys[k]
            _union_also(state[dk], {"also_on": [{"site": "rea", "id": rec["id"], "url": rec.get("url")}]})
            dupes.append((key, dk))
            del state[key]
            if dk not in touched:
                touched.append(dk)
                how[dk] = "also_on"
    # 只写这次碰过、且内容真变了的文件（没碰过的旧文件原样不动，连格式都不动）
    written, removed, same = [], [], []
    for key in touched:
        rec = state.get(key)
        if rec is None:
            continue
        old = disk.get(key)
        if old is not None and old[0] == rec:
            same.append(key)
            continue
        if not dry:
            (out_dir / key[0]).mkdir(parents=True, exist_ok=True)
            (out_dir / key[0] / f"{key[1]}.json").write_text(_dump(rec), encoding="utf-8")
        written.append(key)
    for rk, _dk in dupes:
        old = disk.get(rk)
        if old is not None and old[0].get("site") == "rea":
            if not dry:
                (out_dir / "rea" / f"{rk[1]}.json").unlink(missing_ok=True)
            removed.append(rk)
    # 汇总
    recs = [state[k] for k in touched if k in state]
    log("")
    log(f"{len(files)} html file(s) looked at, {len(pages)} were Domain / REA pages; {len(recs)} distinct listings "
        f"({sum(1 for r in recs if r.get('site', 'domain') == 'domain')} Domain, {sum(1 for r in recs if r.get('site') == 'rea')} REA)")
    st = Counter(how.get(k, "") for k in written)
    log(f"   {'would write' if dry else 'wrote'} {len(written)} file(s)" + (" (" + ", ".join(f"{k} {v}" for k, v in st.most_common()) + ")" if written else "") +
        f", unchanged {len(same)}" + (f"; cross-site duplicates {len(dupes)} (kept Domain, REA id in also_on)" if dupes else "") +
        (f"; {'would remove' if dry else 'removed'} {len(removed)} older REA file(s)" if removed else ""))
    for n, c in notes.most_common():
        log(f"   note: {n} x{c}")
    for line in coverage(pages):
        log("   " + line)
    if recs:
        log("   by suburb: " + ", ".join(f"{k} {v}" for k, v in Counter(r.get("suburb") or "?" for r in recs).most_common()))
        log("   by bedrooms: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(str(r.get("beds")) for r in recs).items())))
        log(f"   with lat/lng {sum(1 for r in recs if r.get('lat') is not None and r.get('lng') is not None)}/{len(recs)}, "
            f"with photos {sum(1 for r in recs if any(s.get('type') == 'image' and s.get('url') for s in r.get('slides') or []))}/{len(recs)}, "
            f"card only {sum(1 for r in recs if r.get('card_only'))}, with description {sum(1 for r in recs if any(str(x).strip() for x in r.get('description') or []))}")
        tags = Counter(r.get("tag") for r in recs if r.get("tag"))
        if tags:
            log("   card tags: " + ", ".join(f"{k} {v}" for k, v in tags.most_common()))
    if not pages:
        log("   no Domain / realestate.com.au pages found: in the browser open a search results page and save it (Cmd/Ctrl+S, "
            "'Webpage, HTML Only' or 'Complete'), one file per results page, then run this again")
    on_disk = Counter(k[0] for k in state)
    log(f"   {'would be' if dry else 'now'} in {out_dir}: domain {on_disk.get('domain', 0)}, rea {on_disk.get('rea', 0)}" +
        ("  (dry run: nothing written)" if dry else ""))
    return {"files": len(files), "pages": pages, "listings": len(recs), "written": written, "unchanged": same, "removed": removed, "duplicates": dupes,
            "how": how, "state": state}


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # Windows 控制台编码兜底
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="saved .html/.htm files or folders (default ~/Downloads)")
    ap.add_argument("--dry", action="store_true", help="parse and report only; write nothing")
    ap.add_argument("--since", help="only files saved on or after this Sydney date (YYYY-MM-DD)")
    ap.add_argument("--out", default=str(OUT_DEFAULT), help="output root (default data/real)")
    ap.add_argument("-r", "--recursive", action="store_true", help="also scan sub-folders")
    a = ap.parse_args(argv)
    since = dt.date.fromisoformat(a.since) if a.since else None
    paths = [Path(p) for p in a.paths] or [Path.home() / "Downloads"]
    run(paths, Path(a.out), dry=a.dry, since=since, recursive=a.recursive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
