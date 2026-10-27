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
import shutil
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
            raw = part.get_payload(decode=True) or b""  # Chrome 存的 HTML 部分不写 charset，按默认解码 é 会变 ��；页面本身是 UTF-8
            page = re.sub(r"<!--.*?-->", "", raw.decode(part.get_content_charset() or "utf-8", "replace"), flags=re.S)  # React 在数字和单位之间插的 <!-- --> 会挡住正则
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
    m = re.match(r"^(?:(?:unit|apt|apartment)\s*)?(?:(?P<unit>[A-Za-z]{0,2}\d+(?:\.\d+)?[A-Za-z]?(?:\+[A-Za-z]?\d+[A-Za-z]?)?|[A-Z]\d*)\s*/\s*)?(?P<num>\d+[A-Za-z]?(?:\s*-\s*\d+[A-Za-z]?)?)\s+(?P<street>[A-Za-z].+)$", s, re.I)
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


# ---------------------------------------------------------------- realestate.com.au 单套详情页（10-27 晚：超亮挑来演示的那几套）
AD_WORDS = re.compile(r"furnish|wechat|whatsapp|car ?space", re.I)
THUMB_SIDE = 600  # 长边不到这个数的图是缩略图（详情页只打包相册头一张大图，其余是 360x270 小图）：照片照读，户型图读不出尺寸


def clean_line1(line1: str) -> Tuple[str, Optional[str]]:
    """标题地址行 → (能拆的地址行, 改动说明)。'A-Fully Furnish-L6A/39-41 KENT RD' → 'L6A/39-41 Kent Rd'：
    广告词在单元号前面、用 '-' 隔开，去掉它；门牌和街名照原样，只把全大写改成首字母大写。拆不出来就原样返回（后面会被筛掉）。"""
    if split_address(line1) or "/" not in line1:
        return line1, None
    left, right = line1.split("/", 1)
    if re.fullmatch(r"\s*(?:\d\s*B\s*\d\s*B|studio|\d\s*-?\s*bed(?:room)?s?)\s*", left, re.I) and split_address(right.strip()):
        # '3B2B/6 Etherden Walk'、'Studio /5-11 Ewan St'、'1 - Bedroom /…'：单元号的位置写的是房型
        return right.strip(), f"the agent's title has {left.strip()!r} (the room type) where the unit number goes; unit number unknown"
    unit = left.split("-")[-1].strip()
    if not unit or AD_WORDS.search(unit) or not re.search(r"\d|^[A-Z]$", unit):
        return line1, None
    right = re.sub(r"\s+", " ", right).strip()
    if right.isupper():
        right = re.sub(r"[A-Za-z']+", lambda m: m.group(0).capitalize(), right.lower())
    right = re.sub(r"\b(st|rd|ave|pde|ln|pl|dr|cres|ct)\b\.?$", lambda m: m.group(1).capitalize(), right)  # 'Botany rd' → 'Botany Rd'
    if not split_address("1 " + right.split(" ", 1)[-1]) or not re.match(r"\d", right):
        return line1, None
    return f"{unit}/{right}", f"the agent's title has ad words before the unit number ({line1!r}); the address is the part after them"


CHAT_ID = re.compile(r"((?<![A-Za-z])(?:we ?chat|vx|wx|微信|whats ?app|qq|telegram)(?![A-Za-z])\s*(?:id)?\s*[:：]?\s*)(?!\[)([A-Za-z0-9_.+-]{3,})", re.I)
PHONE = re.compile(r"[+0]\(?\d[\d\s()-]{7,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
REDACTED = "[contact removed]"


def redact(s: str) -> str:
    """挂牌原文里中介留的手机号、微信 / WhatsApp 号、邮箱换成 [contact removed]：演示站是公开的，不转贴个人联系方式（中介公司名照留）。"""
    s = EMAIL.sub(REDACTED, s or "")
    s = PHONE.sub(lambda m: REDACTED if sum(ch.isdigit() for ch in m.group(0)) >= 9 else m.group(0), s)
    return CHAT_ID.sub(lambda m: m.group(1) + REDACTED, s)


def tidy_street(line1: str, note: Optional[str]) -> Tuple[str, Optional[str]]:
    """'2B/12 Church road' → '2B/12 Church Road'：中介手打的小写街名词首字母大写，其他不动。"""
    parts = split_address(line1)
    if not parts:
        return line1, note
    street = " ".join(w[:1].upper() + w[1:] if w.isalpha() and w.islower() else w for w in parts[2].split(" "))
    return line1[: len(line1) - len(parts[2])] + street if line1.endswith(parts[2]) else line1, note


def _largest(images: Dict[str, bytes], h: str) -> Optional[str]:
    """同一张图（64 位哈希）在页面里可能打包了几种尺寸 / 格式：挑字节最多的那份。"""
    pool = [u for u in images if h in u]
    return max(pool, key=lambda u: len(images[u])) if pool else None


def rea_detail(page: str, images: Dict[str, bytes], origin: str, src: Path) -> Optional[dict]:
    """单套详情页 → 一张"富"卡片：卡片字段 + 标题、描述、设施、入住日期、详情页打包的全部房源照片（头图大，其余缩略图）和户型图。"""
    lid = re.search(r"-(\d{6,12})/?$", origin) or re.search(r"Property ID:\s*(\d{6,12})", page)
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
    mt = re.match(r"^(?P<line1>.+?),\s*(?P<suburb>[^,]+),\s*NSW\s*(?P<pc>\d{4})\s*-\s*(?P<type>.+?)\s+for\s+Rent\b", text(title.group(1)) if title else "", re.I)
    if not (lid and mt):
        return None
    lid = lid.group(1)
    main = page.split('data-testid="enquiry-form"')[0]  # 后面是"相似房源"轮播：别把别人的价格 / 卧室数 / 中介读进来
    price = re.search(r'class="property-price[^"]*"[^>]*>(.*?)</span>', main, re.S)
    aria = re.search(r'aria-label="[A-Za-z /-]*\s+with\s+([^"]+)"', main)
    rooms = aria.group(1) if aria else ""
    beds = re.search(r"(\d+)\s+bedrooms?", rooms)
    baths = re.search(r"(\d+)\s+bathrooms?", rooms)
    cars = re.search(r"(\d+)\s+(?:car|parking|garage) spaces?", rooms)
    avail = re.search(r"<p[^>]*>\s*Available\s+(now|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*</p>", main, re.I)
    saved = dt.datetime.fromtimestamp(src.stat().st_mtime, tz=SYD)
    available_from, available_text = None, None
    if avail:
        available_text = "Available " + avail.group(1)
        if avail.group(1).lower() == "now":
            available_from = saved.date().isoformat()  # 页面在保存那天写"现在可入住"：日期就记保存那天
        else:
            for fmt in ("%d %b %Y", "%d %B %Y"):
                try:
                    available_from = dt.datetime.strptime(avail.group(1), fmt).date().isoformat()
                    break
                except ValueError:
                    pass
    desc_block = re.search(r'data-testid="PropertyDescription".*?<h2[^>]*>(.*?)</h2>', main, re.S)
    og = re.search(r'<meta property="og:description" content="([^"]*)"', page)
    body = html.unescape(og.group(1)) if og else ""
    description = [redact(re.sub(r"\s+", " ", html.unescape(ln)).strip()) for ln in re.split(r"<br\s*/?>", body)]
    while description and not description[-1]:
        description.pop()
    fsec = main.find('data-testid="all-property-features-section"')
    features = [text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", main[fsec: fsec + 20000].split("Show less")[0], re.S)] if fsec >= 0 else []
    agency = re.search(r'class="[^"]*styles__AgencyOrProject(?:NameLink|NonLink)[^"]*"[^>]*>([^<]+)<', main)
    count = re.search(r'data-testid="countIcon"[^>]*>(\d+)</span><span data-testid="countIcon"[^>]*>Images<', main)
    # 照片：头图 + 缩略图（img alt "…, image N of M" / "Preview property image N of M"），户型图（alt "Property floorplan"）
    slides, seen = [], set()
    for kind, pat in (("image", r'(?:aria-label="Preview property images?[^"]*"|data-testid="HeroMosaic")[^>]*>\s*<picture>(.*?)</picture>'),
                      ("floorplan", r'<picture>((?:(?!</picture>).)*?alt="Property floorplan"(?:(?!</picture>).)*)</picture>')):
        for pm in re.finditer(pat, main, re.S):
            hm = re.search(r"https://i\d\.au\.reastatic\.net/[^\"' ]*?/([0-9a-f]{64})/image\.[a-z]+", pm.group(1))
            if not hm or hm.group(1) in seen:
                continue
            seen.add(hm.group(1))
            emb = _largest(images, hm.group(1))
            size = re.search(r"reastatic\.net/(\d+)x(\d+)", emb or "")
            slides.append({"n": len(slides) + 1, "type": kind, "url": hm.group(0), "embedded": emb,
                           "w": int(size.group(1)) if size else None, "h": int(size.group(2)) if size else None})
    slides.sort(key=lambda s: s["type"] == "floorplan")  # 户型图放最后，和 Domain 详情页一样
    for k, s in enumerate(slides, 1):
        s["n"] = k
    line1, note = tidy_street(*clean_line1(re.sub(r"\s+" + re.escape(mt.group("suburb").strip()) + r"$", "", mt.group("line1").strip(), flags=re.I)))
    return {"site": "rea", "id": int(lid), "url": origin, "price": text(price.group(1)) if price else "", "line1": line1, "line1_note": note,
            "suburb": mt.group("suburb").strip(), "postcode": mt.group("pc"), "beds": beds.group(1) if beds else ("0" if re.search(r"studio", rooms + mt.group("type"), re.I) else None),
            "baths": baths.group(1) if baths else None, "parking": cars.group(1) if cars else None, "type": mt.group("type"),  # 页面没写车位 = 未知（REA 车位为 0 时不显示，但"没显示"不等于确认没有）
            "agency": text(agency.group(1)) if agency else "", "tags": [], "gallery_count": int(count.group(1)) if count else None,
            "slides": slides, "saved_page": src.name, "detail": True, "headline": redact(text(desc_block.group(1))) if desc_block else "",
            "description": description, "features": [f for f in features if f], "availableFrom": available_from, "availableText": available_text}


def detail_files(src: List[Path]) -> List[Path]:
    """单套详情页：文件名不像搜索结果页、页面里有 PropertyDescription 的。"""
    out = []
    for p in src:
        p = p.expanduser()
        for f in (sorted(p.glob("*.mhtml")) if p.is_dir() else [p]):
            if f.suffix.lower() in (".mhtml", ".mht") and not re.search(r"for Rent in|Rental Properties and Real Estate|oldest-first|page \d+|Pg\. \d+", f.name, re.I):
                out.append(f)
    return out


def parse_details(src: List[Path]) -> Tuple[List[dict], Dict[Tuple[str, int, int], bytes]]:
    cards, blobs, why = [], {}, collections.Counter()
    for f in detail_files(src):
        page, images, origin = read_mhtml(f)
        c = rea_detail(page, images, origin, f) if "realestate.com.au" in origin and 'data-testid="PropertyDescription"' in page else None
        if not c:
            r = "address available on request (no street address)" if "address available on request" in page[:3000].lower() else "not a realestate.com.au listing page"
            print(f"detail: skip {f.name}: {r}")
            why[r] += 1
            continue
        c["fetched_at"] = dt.datetime.fromtimestamp(f.stat().st_mtime, tz=SYD).isoformat(timespec="seconds")
        r = usable(c)
        if r:
            print(f"detail: skip {f.name}: {r}")
            why[r] += 1
            continue
        cards.append(c)
        for s in c["slides"]:
            if s["embedded"]:
                blobs[(c["site"], c["id"], s["n"])] = images[s["embedded"]]
    print(f"detail: {len(cards)} listing pages", dict(why) if why else "")
    return cards, blobs


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
ROAD_FULL = {"st": "Street", "rd": "Road", "ave": "Avenue", "av": "Avenue", "pde": "Parade", "ln": "Lane", "pl": "Place", "dr": "Drive", "cres": "Crescent",
             "ct": "Court", "hwy": "Highway", "tce": "Terrace", "cct": "Circuit", "blvd": "Boulevard"}


def geocode(cards: List[dict], dry: bool) -> None:
    cache = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
    asked = 0
    for c in cards:
        u, num, st = split_address(c["line1"])
        words = st.split(" ")
        full = " ".join(words[:-1] + [ROAD_FULL.get(words[-1].lower().rstrip("."), words[-1])])  # 'Church St' 查不到时再试 'Church Street'
        hit, q = {}, {}
        for street in dict.fromkeys([st, full]):
            q = {"street": f"{num.split('-')[0]} {street}", "city": c["suburb"], "state": "NSW", "postalcode": c["postcode"], "country": "Australia"}
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
                break
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
            row = {"type": s.get("type") or "image", "url": s["url"], "embedded": True}
            if s.get("w"):
                row.update(w=s["w"], h=s["h"], thumb=max(s["w"], s["h"]) < THUMB_SIDE)
            files.append(row)
    site_name = "domain.com.au" if c["site"] == "domain" else "realestate.com.au"
    beds = int(c["beds"])
    if c.get("detail"):  # 单套详情页：标题、描述、设施、入住日期都有，不是 card_only；照片只有页面打包的那几张（头图大、其余缩略图）
        stats = {k: v for k, v in (("availableFrom", c.get("availableFrom")), ("availableText", c.get("availableText"))) if v}
        return {"id": c["id"], "site": c["site"], "url": c["url"], "address": f"{c['line1']}, {c['suburb']} NSW {c['postcode']}", "address_note": c.get("line1_note"),
                "unit": u, "streetNumber": num, "street": st, "suburb": c["suburb"], "postcode": c["postcode"], "type": norm_type(c["type"]), "beds": beds,
                "baths": int(c["baths"]) if str(c.get("baths") or "").isdigit() else None, "parking": int(c["parking"]) if str(c.get("parking") or "").isdigit() else None,
                "price": c["price"], "stats": stats, "agency": c["agency"], "headline": c.get("headline") or "", "description": c.get("description") or [],
                "features": c.get("features") or [], "structured": [], "tags": [], "lat": c.get("lat"), "lng": c.get("lng"), "geocode": c.get("geocode"),
                "medianRent": None, "medianBeds": None, "created": None, "modified": None, "slides": files, "gallery_count": c.get("gallery_count"),
                "fetched_at": c["fetched_at"], "saved_page": c["saved_page"],
                "source": f"{site_name} listing page saved by the user in their own browser (single-file page; only the photos the page had loaded), demo use only"}
    return {"id": c["id"], "site": c["site"], "card_only": True, "url": c["url"],
            "address": f"{c['line1']}, {c['suburb']} NSW {c['postcode']}", "unit": u, "streetNumber": num, "street": st, "suburb": c["suburb"], "postcode": c["postcode"],
            "type": norm_type(c["type"]), "beds": beds, "baths": int(c["baths"]) if str(c.get("baths") or "").isdigit() else None,
            "parking": int(c["parking"]) if str(c.get("parking") or "").isdigit() else None, "price": c["price"], "stats": {}, "agency": c["agency"],
            "headline": "", "description": [], "features": [], "structured": [], "tags": c.get("tags") or [],
            "lat": c.get("lat"), "lng": c.get("lng"), "geocode": c.get("geocode"), "medianRent": None, "medianBeds": None, "created": None, "modified": None,
            "slides": files, "gallery_count": c.get("gallery_count"), "fetched_at": c["fetched_at"], "saved_page": c["saved_page"],
            "source": f"{site_name} search results page saved by the user in their own browser (single-file page, card only), demo use only"}


def as_webp(data: bytes) -> bytes:
    """详情页的缩略图是 avif / jpeg：转成 webp 存，文件名和内容对得上（卡片的图本来就是 webp，原样存）。"""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, "WEBP", quality=90)
    return buf.getvalue()


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
            if not old.get("card_only") and not (c.get("detail") and old.get("saved_page")):  # 详情页可以盖掉卡片、也可以盖掉旧的详情页存档
                print(f"write: keep the richer {dst.relative_to(ROOT)} (single listing page), not overwritten by card data")
                continue
        if dry:
            n += 1
            continue
        folder.mkdir(parents=True, exist_ok=True)
        pdir = photo_dir(L)
        if c.get("detail") and pdir.exists() and dst.exists() and json.loads(dst.read_text(encoding="utf-8")).get("card_only"):
            # 详情页盖掉卡片：张数和顺序都变了，旧照片（和它们的缩图）删掉重写，免得 NN 号对上别的图。
            # 读图记录按文件名记（runs/photo_facts.jsonl），不看内容：这套要 read --force 重读，否则会沿用卡片那几张的读法
            shutil.rmtree(pdir)
            print(f"write: {c['site']} {c['id']} had card photos; re-read them: scripts/domain_sample.py read --only {c['id']} --force")
        pdir.mkdir(parents=True, exist_ok=True)
        i = 0
        for s in c["slides"]:
            if not s["embedded"]:
                continue
            i += 1
            out = pdir / f"{i:02d}.webp"  # 原图（webp 字节，不进 git），prep 再缩成 JPEG
            if not out.exists():
                out.write_bytes(as_webp(blobs[(c["site"], c["id"], s["n"])]))
        dst.write_text(json.dumps(L, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n += 1
    print(f"write: {n} listing files {'(dry)' if dry else ''}")
    return n


def ALL_KEYS() -> Dict[str, str]:
    """已经写好的全部房源（卡片和详情页、两个站）：地址键 → 'domain/<id>' / 'rea/<id>'。"""
    out = {}
    for site in ("domain", "rea"):
        for f in (REAL / site).glob("*.json"):
            o = json.loads(f.read_text(encoding="utf-8"))
            out[norm_key(str(o.get("unit") or ""), str(o.get("streetNumber") or ""), o.get("street") or "", o.get("suburb") or "")] = f"{site}/{f.stem}"
    return out


def existing_keys() -> Dict[str, str]:
    out = {}
    for f in (REAL / "domain").glob("*.json"):
        o = json.loads(f.read_text(encoding="utf-8"))
        if not o.get("card_only"):
            out[norm_key(str(o.get("unit") or ""), str(o.get("streetNumber") or ""), o.get("street") or "", o.get("suburb") or "")] = f.stem
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["parse", "select", "geocode", "write", "all", "details"])
    ap.add_argument("--src", nargs="*", default=["~/Downloads"], help="mhtml 文件或文件夹")
    ap.add_argument("--domain", type=int, default=180)
    ap.add_argument("--rea", type=int, default=70)
    ap.add_argument("--dry", action="store_true", help="不查坐标、不写文件")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.step == "details":
        cards, blobs = parse_details([Path(p) for p in a.src])
        for c in cards:
            u, num, st = split_address(c["line1"])
            dup = ALL_KEYS().get(norm_key(u, num, st, c["suburb"]))
            if dup and dup != f"rea/{c['id']}":
                print(f"details: {c['id']} ({c['line1']}, {c['suburb']}) is the same address as data/real/{dup}.json; both stay (check the list)")
        geocode(cards, a.dry)
        with (OUT / "details.jsonl").open("w", encoding="utf-8") as f:
            for c in cards:
                f.write(json.dumps({k: v for k, v in c.items() if k != "slides"} | {"slides": [{k: v for k, v in s_.items()} for s_ in c["slides"]]}, ensure_ascii=False) + "\n")
        write(cards, blobs, a.dry)
        return 0
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
