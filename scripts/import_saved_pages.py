#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户自己在 Chrome 里存下来的租房搜索结果页（.mhtml 单文件网页）→ data/real/domain/<id>.json、data/real/rea/<id>.json + 页面里已经打包的照片。

为什么有这个脚本（10-27）：两家网站都不让程序抓（realestate.com.au 的 robots.txt 明文禁止任何自动访问，domain.com.au 拦非浏览器请求），
所以由超亮手动存搜索结果页，我们只解析这些文件。单文件网页里是渲染后的 DOM（没有 __NEXT_DATA__ / ArgonautExchange 数据块），
房源卡片靠 data-testid（Domain）和 residential-card 类名（realestate.com.au）认出来；照片只用文件里已经打包的那几张，
**不去两家的图片服务器下载任何东西**。

步骤（可单跑）：
  parse     读 mhtml（默认 ~/Downloads 里文件名带 "Domain" 或 "realestate.com.au" 的），每张卡片抽：编号、链接、周租、地址、卧室 / 卫生间 / 车位、
            房型、中介公司、相册张数、打包的照片 → runs/saved_pages/cards.jsonl（全部卡片，去重）
  select    从全部卡片里挑演示用的一批（默认 Domain 180 + realestate.com.au 70）：要有每周租金数字、门牌号、至少一张打包照片；
            按区 × 卧室数轮流挑，两站同一地址只留 Domain → runs/saved_pages/selected.json
  geocode   挑中的地址查坐标：OpenStreetMap Nominatim（公开服务，每秒一次，结果缓存在 data/real/geocode_cache.json）；查不到退到区中心，
            标 precision = suburb
  write     写房源 JSON（site、card_only = true、slides 只列打包了的照片）和照片原图 data/real/photos/<id>/NN.webp（realestate.com.au 是 R<id>）；
            已有的富数据（单套详情页抓的 9 套，没有 card_only）绝不被卡片数据覆盖
  all       parse → select → geocode → write
跑：.venv/bin/python scripts/import_saved_pages.py all [--domain 180 --rea 70] [--src ~/Downloads] [--dry]
之后照常：scripts/domain_sample.py prepare / read / build（fetch 对这些房源什么也不下：照片已经在本地）。
页面文件是外来数据：只用 email / re / html 解析，不执行任何东西。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import email
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from email import policy
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data" / "real"
PHOTOS = REAL / "photos"
OUT = ROOT / "runs" / "saved_pages"
GEO_CACHE = REAL / "geocode_cache.json"
SYD = dt.timezone(dt.timedelta(hours=11))  # 10–4 月悉尼夏令时；只用来给抓取时间标时区
UA = "HomeTruth/0.1 (Open Agent Hackathon 2026 demo; one-off geocode of ~250 rental listing addresses)"
SUBURB_LL = {"kensington": (-33.9100, 151.2240), "zetland": (-33.9075, 151.2090), "kingsford": (-33.9245, 151.2270), "randwick": (-33.9140, 151.2410),
             "redfern": (-33.8930, 151.2040)}
TYPE_MAP = {"apartment / unit / flat": "Apartment / Unit / Flat", "unit": "Apartment / Unit / Flat", "apartment": "Apartment / Unit / Flat", "flat": "Apartment / Unit / Flat",
            "studio": "Studio", "house": "House", "townhouse": "Townhouse", "terrace": "Terrace", "semi-detached": "Semi-Detached", "duplex": "Duplex/Semi-detached",
            "villa": "Villa", "penthouse": "Penthouse"}
SKIP_TAGS = re.compile(r"deposit taken|leased|under application", re.I)


# ---------------------------------------------------------------- mhtml
def read_mhtml(path: Path) -> Tuple[str, Dict[str, bytes], str]:
    """返回 (主 HTML, {Content-Location: 图片字节}, 页面原地址)。"""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    page, images, origin = "", {}, str(msg.get("Snapshot-Content-Location") or "")
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/html" and not page:
            page = re.sub(r"<!--.*?-->", "", part.get_content(), flags=re.S)  # React 在数字和单位之间插的 <!-- --> 会挡住正则
            origin = origin or str(part.get("Content-Location") or "")
        elif ct.startswith("image/"):
            loc = str(part.get("Content-Location") or "")
            data = part.get_payload(decode=True)
            if loc and data:
                images[loc] = data
    return page, images, origin


def site_of(path: Path, page: str, origin: str) -> Optional[str]:
    if "realestate.com.au" in origin or 'data-testid="ResidentialCard"' in page:
        return "rea"
    if "domain.com.au" in origin or 'data-testid="listing-card-price' in page:
        return "domain"
    return None


def text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip().strip(",").strip()


def weekly(price: str) -> Optional[int]:
    """'$1,050 per week' / '$820 pw' / '$700 - $750 per week'（取低值）→ 整数；'Contact agent' → None。"""
    p = (price or "").lower().replace(",", "")
    if not re.search(r"week|p\.?w\b|pw\b|/w\b|weekly", p) and not re.fullmatch(r"\s*\$\s*\d{3,4}\s*", p):
        return None
    m = re.search(r"\$\s*(\d{3,5})", p)
    return int(m.group(1)) if m and 150 <= int(m.group(1)) <= 20000 else None


def split_address(line1: str) -> Optional[Tuple[str, str, str]]:
    """'9/6 Bradley Street' → ('9', '6', 'Bradley Street')；'G05/1-3 Some Road' 也行；没有门牌号 → None。"""
    s = re.sub(r"^(?:level|lvl)\s*\d+\s*,?\s*", "", line1.strip(), flags=re.I)
    if re.search(r"wechat|furnish|car ?space|whatsapp|studio\s*/|^\D*:", s, re.I):
        return None  # 中介把广告词塞进地址行的（"WeChat: …"、"Fully Furnished-L1D/…"）：地址不可信，不要
    m = re.match(r"^(?:(?:unit|apt|apartment)\s*)?(?:(?P<unit>[A-Za-z]{0,2}\d+(?:\.\d+)?[A-Za-z]?|[A-Z]\d*)\s*/\s*)?(?P<num>\d+[A-Za-z]?(?:\s*-\s*\d+[A-Za-z]?)?)\s+(?P<street>[A-Za-z].+)$", s, re.I)
    if not m:
        return None
    return (m.group("unit") or "", m.group("num").replace(" ", ""), m.group("street").strip())


def norm_key(unit: str, num: str, street: str, suburb: str) -> str:
    st = re.sub(r"\b(street|st|road|rd|avenue|ave|parade|pde|lane|ln|place|pl|drive|dr|crescent|cres|way|close|court|ct)\b\.?", "", street.lower())
    return "|".join(re.sub(r"[^a-z0-9]", "", x.lower()) for x in (unit, num, st, suburb))


# ---------------------------------------------------------------- Domain 卡片
def domain_cards(page: str, images: Dict[str, bytes], src: Path) -> Iterable[dict]:
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'<li[^>]*data-testid="listing-(\d{6,10})"', page)]
    for k, (pos, lid) in enumerate(starts):
        chunk = page[pos: starts[k + 1][0] if k + 1 < len(starts) else len(page)]
        url = re.search(r'href="(https://www\.domain\.com\.au/[a-z0-9-]+-' + lid + r')"', chunk)
        price = re.search(r'data-testid="listing-card-price"[^>]*>(.*?)</p>', chunk, re.S)
        l1 = re.search(r'data-testid="address-line1"[^>]*>(.*?)</span>', chunk, re.S)
        l2 = re.search(r'data-testid="address-line2"[^>]*>(.*?)</span>\s*</span>|data-testid="address-line2"[^>]*>(.*?)</span>', chunk, re.S)
        feats = {}
        for n, label in re.findall(r'data-testid="property-features-text-container"[^>]*>\s*([\d−-]+|Studio)?\s*<span[^>]*data-testid="property-features-text"[^>]*>([^<]+)</span>', chunk):
            key = label.strip().lower()
            feats["beds" if key.startswith("bed") or key == "studio" else "baths" if key.startswith("bath") else "parking" if key.startswith("park") else key] = "0" if key == "studio" or n == "Studio" else n
        ptype = re.search(r'data-testid="listing-card-features-wrapper".*?</div>\s*</div>\s*<div[^>]*>\s*<span[^>]*>([^<]+)</span>', chunk, re.S)
        agency = re.search(r'data-testid="listing-card-brand-name"[^>]*>([^<]+)<', chunk)
        tags = [text(t) for t in re.findall(r'data-testid="listing-card-tag"[^>]*>(.*?)</', chunk, re.S)]
        count = re.search(r"<span[^>]*>\s*1\s*/\s*(\d+)\s*</span>", chunk)
        slug = url.group(1) if url else ""
        pc = re.search(r"-nsw-(\d{4})-" + lid + "$", slug)
        slides, seen = [], set()
        for m in re.finditer(r"https://rimh2\.domainstatic\.com\.au/[^\"' ]+?/" + lid + r"_(\d+)_\d+_\d+_\d+-w\d+-h\d+", chunk):
            n = int(m.group(1))
            if n in seen:
                continue
            seen.add(n)
            pool = [u for u in images if f"/{lid}_{n}_" in u]
            pool.sort(key=lambda u: ("1440x1080" not in u, len(u)))
            slides.append({"n": n, "url": m.group(0), "embedded": pool[0] if pool else None})
        slides.sort(key=lambda s: s["n"])
        line2 = text((l2.group(1) or l2.group(2)) if l2 else "")
        yield {"site": "domain", "id": int(lid), "url": slug, "price": text(price.group(1)) if price else "", "line1": text(l1.group(1)) if l1 else "",
               "suburb": re.sub(r"\s+NSW.*$", "", line2).strip(), "postcode": pc.group(1) if pc else "", "beds": feats.get("beds"), "baths": feats.get("baths"),
               "parking": feats.get("parking"), "type": text(ptype.group(1)) if ptype else "", "agency": text(agency.group(1)) if agency else "",
               "tags": tags, "gallery_count": int(count.group(1)) if count else None, "slides": slides, "saved_page": src.name}


# ---------------------------------------------------------------- realestate.com.au 卡片
def rea_cards(page: str, images: Dict[str, bytes], src: Path) -> Iterable[dict]:
    for m in re.finditer(r'<article[^>]*data-testid="ResidentialCard"[^>]*>.*?</article>', page, re.S):
        chunk = m.group(0)
        aria = re.search(r'aria-label="([^"]+)"', chunk)
        url = re.search(r'href="(https://www\.realestate\.com\.au/property-([a-z+]+)-nsw-([a-z+-]+)-(\d{6,12}))"', chunk)
        if not url:
            continue
        price = re.search(r'class="property-price[^"]*"[^>]*>(.*?)</span>', chunk, re.S)
        alt = re.search(r'class="property-image__img[^"]*"[^>]*alt="([^"]+)"|alt="([^"]+NSW \d{4})"', chunk)
        full = html.unescape((alt.group(1) or alt.group(2)) if alt else "")
        pc = re.search(r"NSW\s+(\d{4})", full)
        beds = re.search(r'aria-label="(\d+) bedrooms?"', chunk)
        baths = re.search(r'aria-label="(\d+) bathrooms?"', chunk)
        cars = re.search(r'aria-label="(\d+) (?:car spaces?|parking spaces?|garage spaces?)"', chunk)
        studio = re.search(r'aria-label="studio"', chunk, re.I)
        ptxt = re.findall(r'<p class="Text__Typography[^"]*"[^>]*>([A-Za-z][^<]{1,30})</p>', chunk)
        agency = re.search(r'class="branding__image"[^>]*alt="([^"]+)"|alt="([^"]+)"[^>]*class="branding__image"', chunk)
        slides, seen = [], set()
        for n, hm in enumerate(re.finditer(r'data-url="(https://i2\.au\.reastatic\.net/[^"]*?/([0-9a-f]{64})/image\.[a-z]+)"', chunk)):
            h = hm.group(2)
            if h in seen:
                continue
            seen.add(h)
            pool = sorted((u for u in images if h in u), key=lambda u: ("800x600" not in u, len(u)))
            slides.append({"n": n + 1, "url": hm.group(1), "embedded": pool[0] if pool else None})
        line1 = text(aria.group(1)).split(",")[0] if aria else ""
        yield {"site": "rea", "id": int(url.group(4)), "url": url.group(1), "price": text(price.group(1)) if price else "", "line1": line1,
               "suburb": url.group(3).replace("+", " ").title(), "postcode": pc.group(1) if pc else "", "beds": beds.group(1) if beds else ("0" if studio or "studio" in " ".join(ptxt).lower() or "studio" in url.group(2) else None),
               "baths": baths.group(1) if baths else None, "parking": cars.group(1) if cars else None, "type": (ptxt[-1] if ptxt else url.group(2).replace("+", " ")),
               "agency": html.unescape((agency.group(1) or agency.group(2)) if agency else ""), "tags": [], "gallery_count": None, "slides": slides, "saved_page": src.name}


# ---------------------------------------------------------------- parse / select
def source_files(src: List[Path]) -> List[Path]:
    out = []
    for p in src:
        p = p.expanduser()
        if p.is_dir():
            out += [f for f in sorted(p.glob("*.mhtml")) if re.search(r"domain|realestate", f.name, re.I)]
        elif p.suffix.lower() in (".mhtml", ".mht"):
            out.append(p)
    return out


def parse(src: List[Path]) -> Tuple[List[dict], Dict[Tuple[str, int], bytes]]:
    cards: Dict[Tuple[str, int], dict] = {}
    blobs: Dict[Tuple[str, int], bytes] = {}
    stats = collections.Counter()
    for f in source_files(src):
        page, images, origin = read_mhtml(f)
        site = site_of(f, page, origin)
        if not site:
            stats["not a listing page"] += 1
            continue
        got = list((domain_cards if site == "domain" else rea_cards)(page, images, f))
        stats[f"{site} pages"] += 1
        stats[f"{site} cards seen"] += len(got)
        mtime = dt.datetime.fromtimestamp(f.stat().st_mtime, tz=SYD).isoformat(timespec="seconds")
        for c in got:
            key = (c["site"], c["id"])
            c["fetched_at"] = mtime
            old = cards.get(key)
            emb = sum(1 for s in c["slides"] if s["embedded"])
            if old and sum(1 for s in old["slides"] if s["embedded"]) >= emb:
                continue  # 同一套在两页都出现：留打包照片多的那份
            cards[key] = c
            for s in c["slides"]:
                if s["embedded"]:
                    blobs[(c["site"], c["id"], s["n"])] = images[s["embedded"]]
    print("parse:", dict(stats), "unique cards:", collections.Counter(k[0] for k in cards))
    return list(cards.values()), blobs


def usable(c: dict) -> Optional[str]:
    """能进演示集吗？不能就返回原因。"""
    if any(SKIP_TAGS.search(t) for t in c.get("tags") or []):
        return "deposit taken / leased"
    if weekly(c["price"]) is None:
        return "no weekly price"
    if not split_address(c["line1"]):
        return "no street number"
    if not c.get("postcode"):
        return "no postcode"
    if c.get("beds") in (None, "") or not str(c["beds"]).isdigit():
        return "no bedroom count"
    if int(c["beds"]) > 4:
        return "more than 4 bedrooms (likely a share house)"
    if not any(s["embedded"] for s in c["slides"]):
        return "no photo in the saved page"
    return None


def select(cards: List[dict], n_domain: int, n_rea: int, existing: Dict[str, str]) -> List[dict]:
    why = collections.Counter()
    ok: Dict[str, List[dict]] = {"domain": [], "rea": []}
    for c in cards:
        r = usable(c)
        if r:
            why[f"{c['site']}: {r}"] += 1
            continue
        u, num, st = split_address(c["line1"])
        c["_key"] = norm_key(u, num, st, c["suburb"])
        ok[c["site"]].append(c)
    domain_keys = {c["_key"] for c in ok["domain"]} | set(existing)
    picked: List[dict] = []
    for site, n in (("domain", n_domain), ("rea", n_rea)):
        pool = [c for c in ok[site] if site == "domain" or c["_key"] not in domain_keys]
        if site == "rea":
            why["rea: same address already on Domain"] += len(ok[site]) - len(pool)
        # 区 × 卧室数轮流挑，打包照片多的、页面靠前的先
        groups: Dict[Tuple[str, str], List[dict]] = collections.defaultdict(list)
        for c in sorted(pool, key=lambda c: -sum(1 for s in c["slides"] if s["embedded"])):
            groups[(c["suburb"].lower(), str(min(int(c["beds"]), 3)))].append(c)
        order = sorted(groups)
        got = []
        while len(got) < n and any(groups[g] for g in order):
            for g in order:
                if groups[g] and len(got) < n:
                    got.append(groups[g].pop(0))
        picked += got
    print("select:", collections.Counter(c["site"] for c in picked), "skipped:", dict(why))
    print("        by suburb:", dict(collections.Counter(c["suburb"] for c in picked)), "by beds:", dict(collections.Counter(str(c["beds"]) for c in picked)))
    return picked


# ---------------------------------------------------------------- geocode
def geocode(cards: List[dict], dry: bool) -> None:
    cache = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
    asked = 0
    for c in cards:
        u, num, st = split_address(c["line1"])
        q = {"street": f"{num.split('-')[0]} {st}", "city": c["suburb"], "state": "NSW", "postalcode": c["postcode"], "country": "Australia"}
        key = f"{q['street']}|{q['city']}|{q['postalcode']}".lower()
        if key not in cache and not dry:
            url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(dict(q, format="jsonv2", limit=1, addressdetails=0))
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
                    hits = json.loads(r.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"geocode {key}: {type(e).__name__} {str(e)[:80]}")
                hits = None
            asked += 1
            if hits is not None:
                h = hits[0] if hits else None
                cache[key] = {"lat": float(h["lat"]), "lng": float(h["lon"]), "osm_type": h.get("type"), "class": h.get("category") or h.get("class"),
                              "addresstype": h.get("addresstype"), "display": h.get("display_name")} if h else {"miss": True}
                cache[key]["asked_at"] = dt.datetime.now(SYD).isoformat(timespec="seconds")
                GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            time.sleep(1.1)  # Nominatim 用法规定：每秒最多一次
        hit = cache.get(key) or {}
        if hit.get("lat"):
            precise = hit.get("class") != "highway"  # 落在门牌（building / place / 某个店）= 门牌级；只对上路名（class highway）= 街道级
            c["lat"], c["lng"] = hit["lat"], hit["lng"]
            c["geocode"] = {"source": "OpenStreetMap Nominatim", "precision": "address" if precise else "street", "query": q["street"] + ", " + q["city"] + " " + q["postalcode"]}
        else:
            lat, lng = SUBURB_LL.get(c["suburb"].lower(), (None, None))
            c["lat"], c["lng"] = lat, lng
            c["geocode"] = {"source": "suburb centre (address not found)", "precision": "suburb" if lat else "none", "query": q["street"] + ", " + q["city"]}
    prec = collections.Counter(c["geocode"]["precision"] for c in cards)
    print(f"geocode: asked Nominatim {asked} times; precision {dict(prec)}")


# ---------------------------------------------------------------- write
def norm_type(t: str) -> str:
    return TYPE_MAP.get((t or "").strip().lower(), (t or "").strip().title() or "Apartment / Unit / Flat")


def to_listing(c: dict) -> dict:
    u, num, st = split_address(c["line1"])
    files = []
    for s in c["slides"]:
        if s["embedded"]:
            files.append({"type": "image", "url": s["url"], "embedded": True})
    site_name = "domain.com.au" if c["site"] == "domain" else "realestate.com.au"
    beds = int(c["beds"])
    return {"id": c["id"], "site": c["site"], "card_only": True, "url": c["url"],
            "address": f"{c['line1']}, {c['suburb']} NSW {c['postcode']}", "unit": u, "streetNumber": num, "street": st, "suburb": c["suburb"], "postcode": c["postcode"],
            "type": norm_type(c["type"]), "beds": beds, "baths": int(c["baths"]) if str(c.get("baths") or "").isdigit() else None,
            "parking": int(c["parking"]) if str(c.get("parking") or "").isdigit() else None, "price": c["price"], "stats": {}, "agency": c["agency"],
            "headline": "", "description": [], "features": [], "structured": [], "tags": c.get("tags") or [],
            "lat": c.get("lat"), "lng": c.get("lng"), "geocode": c.get("geocode"), "medianRent": None, "medianBeds": None, "created": None, "modified": None,
            "slides": files, "gallery_count": c.get("gallery_count"), "fetched_at": c["fetched_at"], "saved_page": c["saved_page"],
            "source": f"{site_name} search results page saved by the user in their own browser (single-file page, card only), demo use only"}


def photo_dir(L: dict) -> Path:
    return PHOTOS / (str(L["id"]) if L["site"] == "domain" else f"R{L['id']}")


def write(cards: List[dict], blobs: Dict[Tuple[str, int, int], bytes], dry: bool) -> int:
    n = 0
    for c in cards:
        if c.get("lat") is None:  # 坐标查不到、也不在区中心表里：通勤和日照都没法算，不进演示集（不拿别的点冒充）
            print(f"write: skip {c['site']} {c['id']} ({c['line1']}, {c['suburb']}): no coordinates")
            continue
        L = to_listing(c)
        folder = REAL / ("domain" if c["site"] == "domain" else "rea")
        dst = folder / f"{c['id']}.json"
        if dst.exists():
            old = json.loads(dst.read_text(encoding="utf-8"))
            if not old.get("card_only"):
                print(f"write: keep the richer {dst.relative_to(ROOT)} (single listing page), not overwritten by card data")
                continue
        if dry:
            n += 1
            continue
        folder.mkdir(parents=True, exist_ok=True)
        pdir = photo_dir(L)
        pdir.mkdir(parents=True, exist_ok=True)
        i = 0
        for s in c["slides"]:
            if not s["embedded"]:
                continue
            i += 1
            out = pdir / f"{i:02d}.webp"  # 原图（webp 字节，不进 git），prep 再缩成 JPEG
            if not out.exists():
                out.write_bytes(blobs[(c["site"], c["id"], s["n"])])
        dst.write_text(json.dumps(L, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n += 1
    print(f"write: {n} listing files {'(dry)' if dry else ''}")
    return n


def existing_keys() -> Dict[str, str]:
    out = {}
    for f in (REAL / "domain").glob("*.json"):
        o = json.loads(f.read_text(encoding="utf-8"))
        if not o.get("card_only"):
            out[norm_key(str(o.get("unit") or ""), str(o.get("streetNumber") or ""), o.get("street") or "", o.get("suburb") or "")] = f.stem
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["parse", "select", "geocode", "write", "all"])
    ap.add_argument("--src", nargs="*", default=["~/Downloads"], help="mhtml 文件或文件夹")
    ap.add_argument("--domain", type=int, default=180)
    ap.add_argument("--rea", type=int, default=70)
    ap.add_argument("--dry", action="store_true", help="不查坐标、不写文件")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cards, blobs = parse([Path(p) for p in a.src])
    with (OUT / "cards.jsonl").open("w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    if a.step == "parse":
        return 0
    picked = select(cards, a.domain, a.rea, existing_keys())
    if a.step in ("geocode", "all"):
        geocode(picked, a.dry)
    (OUT / "selected.json").write_text(json.dumps([{k: v for k, v in c.items() if k != "_key"} for c in picked], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.step in ("write", "all"):
        if a.step == "write":
            geocode(picked, dry=True)  # 只读缓存
        write(picked, blobs, a.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
