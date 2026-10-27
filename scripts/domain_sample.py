#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真房源（data/real/domain/*.json 的 Domain 挂牌、data/real/rea/*.json 的 realestate.com.au 挂牌；来自单套挂牌页或搜索结果卡片）
→ 语音导览矩阵（src/voice/mock_matrix.json）里的房源，和 5 套合成房源并排参与查找。

真房源只带真事实（data/real/README.md）：挂牌文字（租金、户型、可入住日、特征标签、朝向词、quiet 这种营销词只算推断 R-A2）、看图模型读照片
（C2 家具、C3 炉灶、D1 新旧）、读户型图（朝向、K2–K4）、按经纬度算的日照（E2，src/sun/solar.py）、Domain 的本区两房中位租金和 NSW Fair Trading
押金登记的邮编中位租金（A1 那行多 public_rent 证据，src/evidence/bond_rents.py）、按直线距离 + 走得到的站估的通勤（G1，标 estimate，状态只到"推断"；
到 UNSW 火车不到，离火车站近也写 train and light rail）。挂牌文字的引文都是规则真对上的那一句、带出处（设施清单 / 标题 / 正文），不套固定的话。
没有的东西就是未知（押金以外的文件、法定披露、水电），变成该问中介的问题；绝不给真地址配合成的投诉 / 石棉 / NCAT / 检查报告。
搜索结果卡片（JSON 里 card_only: true）只有价格、地址、经纬度、户型、类型、中介和几张照片，没有正文、可入住日、押金、户型图：A4 是未知
（硬条件待确认，不算满足），"没提到"的格子都说"搜索卡片没提到"，不说"挂牌没说"——我们只看到了卡片；照片还没读过就不说"没有户型图"。
进不了矩阵的（unusable，打印原因、不下图不问模型）：没坐标 / 地址、没周租、不是住的地方（车位、车库、仓储……）、没卧室数（Studio 算 0）、
角标是 Deposit taken / Leased。卫生间数没写就不说（bathrooms = None），不写成 0。

编号：Domain → L-D<编号>、照片 data/real/photos/<编号>/；REA → L-R<编号>、照片 data/real/photos/R<编号>/；页面 /real/<同样的相对路径>。

步骤（可单跑）：
  fetch    按 slides 里的 CDN 链接下载照片到 data/real/photos/<目录>/NN.webp（不进 git）：单线程，两次下载至少隔 0.6 s，已有的跳过，
           某张失败记一行接着下；搜索卡片每套最多 --max-photos 张照片（卡片带的户型图另外下、不占名额）；挂牌网站本身的页面地址一律不抓
  prepare  缩成能内联上传的 JPEG：data/real/photos/<目录>/prep/NN.jpg（页面也直接用这份）
  read     每张照片问一次 Nemotron VL（src/photo/facts.py 的提示词和路由：先 Nightshift 视觉路由、没有就直连 NVIDIA，如实记录）
           → runs/photo_facts.jsonl（listing = L-D<编号> / L-R<编号>）；已读过的跳过（--force 重读）；--max-photos 限每套张数；
           --workers N 几套房同时读（每套内部仍逐张、每次之间隔 1 s）
  plans    有户型图的几套问一次（src/photo/floorplan.py）→ runs/floorplan_facts.jsonl；搜索卡片没有户型图 slide，读图结果说哪张是户型图就读那张
  build    合成矩阵房源并写进 mock_matrix.json（替换旧的 L-D* / L-R*，合成房源不动，只给它们补 sun 几何和 E2 未知格）；--dry 只打印
跑：python3 scripts/domain_sample.py all            python3 scripts/domain_sample.py read --only 17153470 --max-photos 4
    --only 收裸编号（两个站都找）或 L-D<编号> / L-R<编号>
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from llm import provider as llm  # noqa: E402
from photo import facts  # noqa: E402
from photo import floorplan as fp  # noqa: E402
from sun import solar  # noqa: E402

try:  # NSW Fair Trading 押金登记的邮编中位租金（另一条线写的 src/evidence/bond_rents.py）；模块不在就安静跳过
    from evidence import bond_rents  # noqa: E402
except Exception:  # noqa: BLE001
    bond_rents = None

REAL = ROOT / "data" / "real"
DOMAIN = REAL / "domain"
REA = REAL / "rea"
PHOTOS = REAL / "photos"
MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"
URL_BASE = "/real/"
SITES = {"domain": ("D", "domain.com.au"), "rea": ("R", "realestate.com.au")}  # site → (编号前缀字母, 来源站名)
PAGE_HOSTS = ("domain.com.au", "www.domain.com.au", "realestate.com.au", "www.realestate.com.au")  # 挂牌网站本身的页面：fetch 一律不碰（只下 CDN 图片）
FETCH_GAP = 0.6  # 两次下载之间至少隔几秒
SYNTH_LISTING_ROWS = 50  # 矩阵 sources 里 listings 表的合成行数（50 套合成房源），真房源加在上面
SYNTH_PUBLIC_RENT_ROWS = 96  # public_rent 表原有的合成 DCJ 中位数行数，NSW 押金登记用到的行加在上面
ANCHORS = {"central": (-33.8832, 151.2063, "Central Station"), "unsw": (-33.9173, 151.2313, "UNSW"), "cbd": (-33.8688, 151.2093, "the CBD")}
SUBURB_LL = {"Kensington": (-33.9100, 151.2240), "Zetland": (-33.9075, 151.2090), "Kingsford": (-33.9245, 151.2270), "Randwick": (-33.9140, 151.2410),
             "Redfern": (-33.8930, 151.2040)}
# 通勤方式按"走得到的最近一个站"定。坐标是凭常识记的近似值（不是测绘 / Transport for NSW 数据），只够判断 1 km / 0.8 km 这种粗粒度；
# 通勤分钟数本身仍是直线距离估的（estimate: true，G1 最多"推断"）。
RAIL_STOPS = {"Central": (-33.8832, 151.2063), "Redfern": (-33.8917, 151.1986), "Green Square": (-33.9056, 151.2025),
              "Erskineville": (-33.8999, 151.1856), "Macdonaldtown": (-33.8965, 151.1867), "St Peters": (-33.9073, 151.1803),
              "Waterloo Metro": (-33.8995, 151.2060), "Mascot": (-33.9234, 151.1874)}
LIGHT_RAIL_STOPS = {  # L2 / L3 共用段（Central Chalmers Street → Surry Hills → Moore Park）+ L3（Anzac Parade 到 Juniors Kingsford）+ L2（Alison Road / Wansey Road / High Street 到 Randwick）
    "Central Chalmers Street": (-33.8838, 151.2071), "Surry Hills": (-33.8869, 151.2128), "Moore Park": (-33.8956, 151.2205), "ES Marks": (-33.9036, 151.2238), "Kensington": (-33.9087, 151.2241), "UNSW Anzac Parade": (-33.9166, 151.2262),
    "Kingsford": (-33.9203, 151.2272), "Juniors Kingsford": (-33.9246, 151.2275), "Royal Randwick": (-33.9066, 151.2335), "Wansey Road": (-33.9117, 151.2347),
    "UNSW High Street": (-33.9160, 151.2358), "Randwick": (-33.9165, 151.2398)}
RAIL_KM, LIGHT_RAIL_KM = 1.0, 0.8
LIGHT_RAIL_ONLY = {"unsw"}  # 火车不到的目的地（UNSW 只有 L2 / L3 轻轨）：离火车站近也得换轻轨
# 不是住的地方（车位、车库、仓储、空地、商铺）：卡片上有价格也不进矩阵，免得给真地址编出"0 卧 0 卫"
NOT_A_HOME = re.compile(r"car ?space|car ?park|parking|garage|storage|\bland\b|commercial|office|retail|warehouse|industrial|\bshop\b", re.I)
GONE_TAG = re.compile(r"deposit taken|\bleased\b|\blet agreed\b|\brented\b", re.I)  # 卡片角标说已经定出去了
# 明显的干道（地址本身的事实：门牌就在这条路上）。值 = 只在这些 suburb 算干道（别处的同名小街不算），None = 整条都算。
MAIN_ROADS: Dict[str, Optional[set]] = {
    "anzac parade": None, "botany road": None, "gardeners road": None, "alison road": None, "cleveland street": None, "south dowling street": None,
    "southern cross drive": None, "o'riordan street": None, "maroubra road": None, "bunnerong road": None, "mcevoy street": None, "euston road": None,
    "elizabeth street": {"redfern", "surry hills", "waterloo", "zetland", "sydney", "haymarket"},
    "regent street": {"redfern", "chippendale", "sydney", "haymarket"},
    "avoca street": {"randwick"},
    "oxford street": {"paddington", "darlinghurst", "woollahra", "bondi junction", "surry hills", "sydney"},
}
ROAD_ABBR = {"pde": "parade", "rd": "road", "st": "street", "dr": "drive", "ave": "avenue", "av": "avenue", "hwy": "highway"}
DIMS_NEW = {"D1": {"label": "Condition", "hard": False},
            "K1": {"label": "Numbers", "hard": False, "pack": "fengshui"}, "K2": {"label": "Through-line", "hard": False, "pack": "fengshui"},
            "K3": {"label": "Doors", "hard": False, "pack": "fengshui"}, "K4": {"label": "Outline", "hard": False, "pack": "fengshui"}}
ROOMS = set(facts.VIEW_LABELS) - {"other"}  # 照片提示词里的房间枚举（没有"户型图"这一项）
TODAY = dt.date.today()
_PRINT = threading.Lock()  # read 多线程：打印和追加 jsonl 各上一把锁
_LOG = threading.Lock()
_LAST_GET = [0.0]


def say(*a) -> None:
    with _PRINT:
        print(*a, flush=True)


# ---------------------------------------------------------------- 读入
def site(o: dict) -> str:
    return o.get("site", "domain")


def is_real(listing_id: str) -> bool:
    return listing_id.startswith(("L-D", "L-R"))


def lid(o: dict) -> str:
    return f"L-{SITES[site(o)][0]}{o['id']}"


def matches(o: dict, only: Optional[str]) -> bool:
    """--only：裸编号两个站都找；L-D<编号> / L-R<编号> 只找那个站。"""
    if not only:
        return True
    only = str(only).strip()
    return lid(o) == only if only.startswith("L-") else str(o["id"]) == only


def load(only: Optional[str] = None) -> List[dict]:
    out = []
    for folder, default_site in ((DOMAIN, "domain"), (REA, "rea")):
        for f in sorted(folder.glob("*.json")):
            o = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(o, dict) or "id" not in o:
                continue
            o.setdefault("site", default_site)
            if o["site"] not in SITES:
                say(f"skip {f.relative_to(ROOT)}: unknown site {o['site']!r}")
                continue
            if matches(o, only):
                out.append(o)
    return out


def card_only(o: dict) -> bool:
    return bool(o.get("card_only"))


def text_of(o: dict) -> str:
    return " ".join([o.get("headline") or ""] + list(o.get("description") or []) + list(o.get("features") or [])).lower()


def folder_of(o: dict) -> str:
    return f"R{o['id']}" if site(o) == "rea" else str(o["id"])


def slide_file(o: dict, i: int, prep: bool = False) -> Path:
    d = PHOTOS / folder_of(o)
    return d / "prep" / f"{i:02d}.jpg" if prep else d / f"{i:02d}.webp"


def file_key(o: dict, i: int) -> str:
    return f"{folder_of(o)}/prep/{i:02d}.jpg"


def url_of(o: dict, i: int) -> str:
    return URL_BASE + file_key(o, i)


def home_word(o: dict) -> str:
    t = str(o.get("type") or "").lower()
    for w in ("townhouse", "terrace", "villa", "duplex", "semi", "house", "studio"):
        if w in t:
            return {"semi": "semi-detached house"}.get(w, w)
    return "apartment"


def parse_rent(price) -> int:
    """'$850 per week' / '$850 pw' / '$1,050.00 per week' / '$800 - $850' → 850 / 850 / 1050 / 800（第一个金额）；没金额或按月报价 → 0（不猜）。"""
    s = str(price or "")
    if re.search(r"per month|monthly|\bpcm\b|p\.c\.m", s, re.I):
        return 0
    m = re.search(r"\$\s*([\d,]+)(?:\.\d+)?", s) or re.search(r"\b(\d{3,4})\b", s)
    return int(m.group(1).replace(",", "")) if m else 0


def iso_date(v) -> Optional[str]:
    s = str(v or "")[:10]
    try:
        return dt.date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def unusable(o: dict) -> Optional[str]:
    """进不了矩阵的原因（缺了就没法不编造地放进去）；能用返回 None。"""
    if o.get("lat") is None or o.get("lng") is None:
        return "no coordinates"
    if not (o.get("street") and o.get("suburb") and o.get("postcode")):
        return "no street / suburb / postcode"
    if not parse_rent(o.get("price")):
        return f"no weekly rent in the price {o.get('price')!r}"
    if o.get("type") and NOT_A_HOME.search(str(o["type"])):
        return f"not a home: the property type is {o['type']!r}"
    if beds_of(o) is None:
        return "no bedroom count on the card"
    if o.get("tag") and GONE_TAG.search(str(o["tag"])):
        return f"the card is tagged {o['tag']!r}"
    return None


def beds_of(o: dict) -> Optional[int]:
    """卧室数：卡片写了就用；没写但房型是 Studio 就是 0（导入时一般已经填好）；别的没写 → None（不当 0，unusable 会跳过）。"""
    b = o.get("beds")
    if b is None:
        return 0 if "studio" in str(o.get("type") or "").lower() else None
    return int(b)


def baths_of(o: dict) -> Optional[int]:
    """卫生间数：没写就是 None（不写"0 bath"）。"""
    return None if o.get("baths") is None else int(o["baths"])


# ---------------------------------------------------------------- fetch / prepare
def image_url_ok(url: str) -> bool:
    """只下 CDN 图片：挂牌网站本身的页面（domain.com.au / realestate.com.au 及 www.）不抓。"""
    u = urllib.parse.urlsplit(url)
    return u.scheme in ("http", "https") and (u.hostname or "").lower() not in PAGE_HOSTS


def fetch(o: dict, max_photos: int = 6) -> int:
    n = bad = 0
    slides = list(enumerate(o.get("slides") or [], 1))
    if card_only(o):  # 搜索卡片：每套最多 max_photos 张图；卡片带的户型图（REA 的 media.floorplans）另外全下，不占名额
        slides = [(i, s) for i, s in slides if s.get("type") == "image"][:max_photos] + [(i, s) for i, s in slides if s.get("type") == "floorplan"]
    for i, s in slides:
        dst, url = slide_file(o, i), s.get("url")
        if dst.exists() or not url:
            continue
        if not image_url_ok(url):
            say(f"fetch {lid(o)} slide {i}: skipped, not an image CDN address")
            continue
        wait = FETCH_GAP - (time.time() - _LAST_GET[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_GET[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)  # 整张读完再写：断掉的下载不留半个文件
            n += 1
        except Exception as e:  # noqa: BLE001
            bad += 1
            say(f"fetch {lid(o)} slide {i}: FAILED {type(e).__name__}: {str(e)[:120]}")
    say(f"fetch {lid(o)}: {n} new files" + (f", {bad} failed" if bad else ""))
    return n


def prepare(o: dict) -> List[Tuple[int, dict, Path]]:
    from PIL import Image
    out = []
    for i, s in enumerate(o.get("slides") or [], 1):
        src, dst = slide_file(o, i), slide_file(o, i, prep=True)
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            img = Image.open(src).convert("RGB")
            # 搜索卡片的照片本身就是网页低画质图（Domain 1440 宽 quality 35 的 webp、REA 800 宽），再按 88 存 JPEG 只会把体积撑大：
            # 卡片房源缩到 800、从 72 起步、渐进式（每张约 50 KB；300 套进私有仓库约 32 MB，10-27 实测），详情页抓的 9 套照旧
            side = 1400 if s.get("type") == "floorplan" else (800 if card_only(o) else facts.MAX_SIDE)
            img.thumbnail((side, side))
            data = b""
            for q in ((72, 66, 60, 55) if card_only(o) else (88, 85, 80, 75, 70, 62, 55)):
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=q, optimize=True, progressive=card_only(o))
                data = buf.getvalue()
                if len(data) <= facts.MAX_BYTES:
                    break
            dst.write_bytes(data)
        out.append((i, s, dst))
    say(f"prepare {lid(o)}: {len(out)} files → {PHOTOS.relative_to(ROOT)}/{folder_of(o)}/prep/")
    return out


# ---------------------------------------------------------------- read / plans（问模型）
def read(o: dict, provider: Optional[str], max_photos: int, force: bool, done: Optional[Dict[str, dict]] = None) -> List[dict]:
    done = facts.readings_by_file().get(lid(o), {}) if done is None else done
    rows = []
    images = [(i, s) for i, s in enumerate(o.get("slides") or [], 1) if s.get("type") == "image" and slide_file(o, i, prep=True).exists()][:max_photos]
    for i, s in images:
        key = file_key(o, i)
        if key in done and not force:
            say(f"read {lid(o)} {key}: already read on {done[key]['ts'][:10]} (--force to redo)")
            continue
        data = slide_file(o, i, prep=True).read_bytes()
        caption = f"photo {i} of {len(o['slides'])}; the listing is a {o.get('beds')}-bedroom {str(o.get('type') or 'home').split(' /')[0].lower()}"
        t0 = time.time()
        try:
            obj, res, route, reason = facts.ask_model(data, caption, provider)
        except Exception as e:  # noqa: BLE001
            say(f"read {lid(o)} {key}: FAILED {type(e).__name__}: {str(e)[:160]}")
            continue
        row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "listing": lid(o), "file": key, "slide": i, "sha256": facts.sha256(data),
               "bytes": len(data), "route": route, "nightshift": reason or None, "provider": res.provider, "model": res.model,
               "served_model": res.served_model or res.model, "ms": res.ms, "wall_ms": round((time.time() - t0) * 1000), "reading": obj, "raw": res.text[:800]}
        with _LOG:
            facts.LOG.parent.mkdir(parents=True, exist_ok=True)
            with facts.LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
        say(f"read {lid(o)} {key}: via {route} {row['served_model']} in {res.ms} ms → {json.dumps(obj, ensure_ascii=False)[:160]}")
        time.sleep(1.0)
    return rows


def read_all(items: List[dict], provider: Optional[str], max_photos: int, force: bool, workers: int) -> List[dict]:
    """几套房同时读（ThreadPool，每个线程一套；套内逐张、每次之间隔 1 s）。已读记录只在开头读一次，免得边写边读半行。"""
    done = facts.readings_by_file()
    rows: List[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [(o, ex.submit(read, o, provider, max_photos, force, done.get(lid(o), {}))) for o in items]
        for o, fu in futs:
            try:
                rows += fu.result()
            except Exception as e:  # noqa: BLE001
                say(f"read {lid(o)}: FAILED {type(e).__name__}: {str(e)[:160]}")
    return rows


def is_plan_reading(reading: dict) -> bool:
    """照片提示词的房间枚举里没有"户型图"：模型把它归到 other（或自己写 floor plan），一句话里说是户型图，才当户型图。"""
    room = str(reading.get("room") or "").lower().strip()
    if room in ROOMS:
        return False
    words = " ".join(str(reading.get(k) or "") for k in ("room", "one_line", "watermark_text"))
    return bool(re.search(r"floor ?plan|floorplan", words, re.I))


def floorplan_slides(o: dict, readings: Dict[str, dict]) -> List[int]:
    """户型图是哪几张：slides 里标 floorplan 的；没有的话（搜索卡片），读图结果说是户型图的那几张图。"""
    out = [i for i, s in enumerate(o.get("slides") or [], 1) if s.get("type") == "floorplan"]
    if not out:
        out = [i for i, s in enumerate(o.get("slides") or [], 1)
               if s.get("type") == "image" and is_plan_reading(((readings.get(file_key(o, i)) or {}).get("reading")) or {})]
    return out


def plans(o: dict, provider: Optional[str], force: bool, readings: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    readings = facts.readings_by_file().get(lid(o), {}) if readings is None else readings
    done = fp.latest().get(lid(o))
    for i in floorplan_slides(o, readings):
        if not slide_file(o, i, prep=True).exists():
            continue
        if done and done.get("file") == file_key(o, i) and not force:
            say(f"plan {lid(o)}: already read on {done['ts'][:10]}")
            return done
        if (o["slides"][i - 1].get("type") or "") != "floorplan":
            say(f"plan {lid(o)}: slide {i} reads as a floor plan in the photo reading, so it is read as the plan")
        try:
            row = fp.read(lid(o), file_key(o, i), slide_file(o, i, prep=True).read_bytes(), f"{o.get('beds')}-bedroom {home_word(o)}", provider)
        except Exception as e:  # noqa: BLE001
            say(f"plan {lid(o)}: FAILED {type(e).__name__}: {str(e)[:160]}")
            return None
        row["slide"] = i
        return row
    return None


# ---------------------------------------------------------------- build：真事实 → 矩阵房源
def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nearest_stop(lat: float, lng: float, anchor: str = "central") -> Tuple[str, Optional[str], Optional[float]]:
    """(方式, 站名, 公里)。到 Central / CBD：1 km 内有火车 / 地铁站 → train；否则 0.8 km 内有轻轨站 → light rail（L2 / L3 都到 Central 和城里）；
    都没有 → bus（不给站名）。到 UNSW（火车不到）：0.8 km 内有轻轨站 → light rail；否则 1 km 内有火车站 → train and light rail（在 Central 换）；都没有 → bus。"""
    pt = (lat, lng)
    rail = min((haversine_km(pt, ll), name) for name, ll in RAIL_STOPS.items())
    lr = min((haversine_km(pt, ll), name) for name, ll in LIGHT_RAIL_STOPS.items())
    if anchor in LIGHT_RAIL_ONLY:
        if lr[0] <= LIGHT_RAIL_KM:
            return "light rail", lr[1], round(lr[0], 1)
        if rail[0] <= RAIL_KM:
            return "train and light rail", rail[1], round(rail[0], 1)
        return "bus", None, None
    if rail[0] <= RAIL_KM:
        return "train", rail[1], round(rail[0], 1)
    if lr[0] <= LIGHT_RAIL_KM:
        return "light rail", lr[1], round(lr[0], 1)
    return "bus", None, None


def commute_estimate(o: dict) -> Dict[str, dict]:
    """直线距离 → 分钟（8 分钟走路等车 + 每公里 3.75 分钟，约 16 km/h 门到门）。方式看走得到的站和目的地。标 estimate，G1 只给"推断"。"""
    out = {}
    for key, (lat, lng, _label) in ANCHORS.items():
        mode, stop, stop_km = nearest_stop(o["lat"], o["lng"], key)
        km = haversine_km((o["lat"], o["lng"]), (lat, lng))
        row = {"min": int(round(8 + km * 3.75)), "mode": mode, "estimate": True, "km": round(km, 1)}
        if stop:
            row.update(stop=stop, stop_km=stop_km)
        out[key] = row
    return out


def road_key(street: str) -> str:
    s = re.sub(r"\s+", " ", str(street or "").replace("’", "'").replace("‘", "'").strip().lower())
    parts = s.split(" ")
    if parts and parts[-1].rstrip(".") in ROAD_ABBR:
        parts[-1] = ROAD_ABBR[parts[-1].rstrip(".")]
    return " ".join(parts)


def main_road(street: str, suburb: str) -> bool:
    k = road_key(street)
    if k not in MAIN_ROADS:
        return False
    where = MAIN_ROADS[k]
    return where is None or str(suburb or "").strip().lower() in where


def _ev(table: str, row: str, material: Optional[str], text: str, **kw) -> dict:
    return dict({"table": table, "row": row, "material_id": material, "text": text}, **kw)


def said(o: dict, pattern: str) -> Optional[dict]:
    """挂牌自己的话里第一处对上 pattern 的地方：按设施清单 → 标题 → 正文逐条找（不跨条拼接），返回 {where, quote, m}。
    引文照原样大小写：设施清单取整条；标题 / 正文取命中所在的那一小句（≤ 90 字符；太长就取命中前后各几个词，截断处加 …）。"""
    rx = re.compile(pattern, re.I)
    for where in ("features", "headline", "description"):
        items = o.get(where) or []
        for it in ([items] if isinstance(items, str) else items):
            t = str(it or "").strip()
            m = rx.search(t)
            if not m:
                continue
            q = t if where == "features" else _clause(t, m)
            return {"where": where, "quote": q, "m": m}
    return None


def _clause(t: str, m: "re.Match") -> str:
    a = max(t.rfind(c, 0, m.start()) for c in ".!?;•|") + 1
    ends = [k for k in (t.find(c, m.end()) for c in ".!?;•|") if k != -1]
    b = min(ends) if ends else len(t)
    q = t[a:b].strip(" *•-–,:")
    if len(q) <= 90:
        return q
    s0, e0 = m.start(), m.end()  # 命中扩到整词（"peaceful" 命中在 "Peacefully" 里时引整个词）
    while s0 > a and t[s0 - 1].isalnum():
        s0 -= 1
    while e0 < b and t[e0].isalnum():
        e0 += 1
    pre, post = t[a:s0].split(), t[e0:b].split()
    left, right = pre[-5:], post[:5]
    tail = " ".join(right).rstrip(",;:")
    return (("…" if len(pre) > 5 else "") + " ".join(left + [t[s0:e0]]) + (" " + tail if tail else "") + ("…" if len(post) > 5 else "")).strip(" *•-–,:")


def says(q: dict, card: bool) -> Tuple[str, str]:
    """(句子开头, 证据前缀)：'The listing's features say' / 'features'；搜索卡片 'The search card's headline says' / 'search card headline'。"""
    subj = {"features": "features", "headline": "headline", "description": "description"}[q["where"]]
    who = "The search card's" if card else "The listing's"
    head = f"{who} {subj} " + ("say" if subj == "features" else "says")
    if subj == "description" and not card:
        head = "The listing description says"
    return head, ("search card " if card else "") + subj


def street_line(o: dict) -> str:
    num = str(o.get("streetNumber") or "").strip()
    return f"{num} {o['street']}" if num else str(o["street"])


def special_line(o: dict) -> str:
    """"这套哪里特别"：挂牌自己的话（正文里带阳台 / 景观 / 翻新这类词的一行，没有就用标题）；搜索卡片没有字，就用真字段拼一句中性的。"""
    pat = re.compile(r"balcon|outlook|view|top floor|park|renovat|updated|art deco|sunroom|garden|courtyard|lift", re.I)
    for ln in o.get("description") or []:
        t = ln.strip().lstrip("•-– ").strip()
        if t and len(t) <= 110 and pat.search(t) and not t.lower().startswith(("located", "positioned", "enjoy", "disclaimer")):
            return f"the listing's own words: '{t.rstrip('. ')}'"
    head = (o.get("headline") or "").strip().rstrip(". ")
    if head:
        return f"the listing's own words: '{head}'"
    beds, baths = beds_of(o), baths_of(o)
    return ((f"{beds} bed" if beds else "studio") + (f", {baths} bath" if baths is not None else "") + (f", {o['parking']} car" if o.get("parking") else "")
            + f" on {street_line(o)}")


def plan_slide(plan: dict) -> int:
    """户型图是第几张（日志行里 file = <目录>/prep/NN.jpg）。"""
    return int(plan.get("slide") or re.sub(r"\D", "", plan["file"][-6:]) or 0)


def source_of(o: dict) -> dict:
    src = {"site": SITES[site(o)][1], "listing_id": o["id"], "url": o.get("url"), "agency": o.get("agency"), "fetched_at": o.get("fetched_at"),
           "modified": o.get("modified")}
    if o.get("also_on"):
        src["also_on"] = o["also_on"]  # 同一套房在另一个站也挂着（导入时去重留下的记录）
    if card_only(o):
        src["card_only"] = True  # 只看到了搜索结果卡片，没有挂牌正文
    return src


def bond_median(o: dict, L: dict) -> Optional[Tuple[dict, dict]]:
    """NSW Fair Trading 押金登记：本邮编、同户型、同卧室数新租约的中位租金 → (证据行, A1 的 median)。模块 / CSV 不在、行太少（n < 10）、
    没写房型 → None（不猜房型）。"""
    if bond_rents is None or not o.get("type") or not L["rent"]:
        return None
    try:
        rec = bond_rents.lookup(L["postcode"], L["bedrooms"], o["type"])
        if not rec or not rec.get("median"):
            return None
        text = bond_rents.evidence_text(L["rent"], rec)
    except Exception:  # noqa: BLE001  CSV 不在、格式不对：安静跳过
        return None
    med = int(round(rec["median"]))
    cmp_ = getattr(bond_rents, "compare", None)  # 和证据句同一个算法（半数进位），免得句子说 7% 而格子说 6%
    c = cmp_(L["rent"], rec["median"]) if cmp_ else None
    pct = (-c[0] if c[1] == "below" else c[0]) if c else int(round((L["rent"] - med) / med * 100))
    ev =_ev("public_rent", f"nsw-bonds/{rec.get('postcode', L['postcode'])}/{rec.get('beds', L['bedrooms'])}-bed-{rec.get('dwelling', 'F')}", None, text)
    return ev, {"rent": med, "beds": rec.get("beds"), "suburb": L["suburb"], "pct": pct, "source": "nsw-bonds", "n": rec.get("n"), "months": rec.get("months")}


def build_one(o: dict, readings: Dict[str, dict], plan: Optional[dict]) -> dict:
    if plan is not None:
        plan = dict(plan, slide=plan_slide(plan))
    card = card_only(o)
    who = "the search card" if card else "the listing"  # 说"没提到"时的主语：只看到卡片就别说挂牌什么都没写
    Who = who[0].upper() + who[1:]
    stats = o.get("stats") or {}
    L: dict = {"id": lid(o), "unit": str(o.get("unit") or ""), "street": street_line(o), "suburb": o["suburb"], "postcode": str(o["postcode"]),
               "rent": parse_rent(o.get("price")), "bedrooms": beds_of(o), "bathrooms": baths_of(o),  # 卫生间没写 = None，不写 0
               "parking": o.get("parking"), "available_from": iso_date(stats.get("availableFrom")),  # 没写日期就是 None（未知），不拿今天顶
               "commute": commute_estimate(o), "special": special_line(o), "headline": o.get("headline") or "",
               "description": [ln for ln in (o.get("description") or []) if ln.strip() and not ln.lower().startswith("disclaimer")][:2],
               "lat": o["lat"], "lng": o["lng"], "source": source_of(o)}
    n = facts.num_of(L["id"])
    row_l = L["id"]
    mat = f"M-{n}-listing"
    text = text_of(o)
    bond = stats.get("bond")
    F: Dict[str, dict] = {}
    median = o.get("medianRent")
    pct = int(round((L["rent"] - median) / median * 100)) if median else None
    F["A1"] = {"evidence": [_ev("listings", row_l, mat, f"Rent {o['price']}" + (f", bond ${bond:,}" if bond else ""))],
               "median": {"rent": median, "beds": o.get("medianBeds"), "suburb": o["suburb"], "pct": pct} if median else None}
    if median:
        F["A1"]["evidence"].append(_ev("public_rent", f"domain-median/{o['suburb'].lower()}/{o.get('medianBeds') or 2}-bed", None,
                                       f"Domain: median asking rent for {o.get('medianBeds') or 2}-bedroom places in {o['suburb']} is ${median} a week; this one asks ${L['rent']} "
                                       f"({'about the same' if abs(pct) < 2 else f'{abs(pct)}% ' + ('above' if pct > 0 else 'below')})"))
    bm = bond_median(o, L)
    if bm:  # Domain 的中位数在前（有的话），押金登记那行跟在后面；没有 Domain 中位数时 median 就用押金登记的
        F["A1"]["evidence"].append(bm[0])
        if not median:
            F["A1"]["median"] = bm[1]
    F["B1"] = {"evidence": [_ev("listings", row_l, mat, f"{L['bedrooms']} bed" + (f", {L['bathrooms']} bath" if L["bathrooms"] is not None else "") +
                                (f", {o['parking']} car" if o.get("parking") else ""))]}
    if L["available_from"]:
        av = dt.date.fromisoformat(L["available_from"])
        F["A4"] = {"evidence": [_ev("listings", row_l, mat, f"Available {av.day} {av:%b %Y}" + (" (already vacant)" if av <= TODAY else ""))]}
    else:  # 硬条件未知 = 待确认，不算满足（CLAUDE.md 第 4 节）；policy.evaluate 照这格出 unknown
        F["A4"] = {"status": "unknown", "why": "The listing card gives no move-in date; ask the agent." if card else "The listing gives no move-in date; ask the agent.",
                   "evidence": [_ev("listings", row_l, mat, f"{'search card' if card else 'listing'}: no move-in date")]}
    not_asked = _ev("documents", f"agent_replies/{L['id']}", None, "Not asked yet")
    nm = "search card: no mention of" if card else "no mention of"
    # 挂牌自己的话：引文都是 said() 真对上的那一句（原样大小写）+ 出处（设施清单 / 标题 / 正文），不套固定的话
    q_no = said(o, r"no pets|pets? not (allowed|permitted)|no animals")  # 先看"不许"：免得 "No pets allowed" 被当成 "pets allowed"
    q_pet = None if q_no else said(o, r"pets? (allowed|welcome|considered|ok|friendly)|pet[- ]friendly")
    if q_pet:
        head, lab = says(q_pet, card)
        F["J1"] = {"status": "inferred", "why": f"{head} '{q_pet['quote']}'. That's the agent's word; NSW rules want the landlord's consent in writing, so get it into the lease.",
                   "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_pet['quote']}'"), not_asked]}
    elif q_no:
        head, lab = says(q_no, card)
        F["J1"] = {"status": "conflict", "why": f"{head} '{q_no['quote']}'. Under NSW rules that still needs a set ground, so it's a conflict to push on.",
                   "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_no['quote']}'"), not_asked]}
    else:
        F["J1"] = {"status": "unknown", "why": ("The search card doesn't mention pets" if card else "The listing says nothing about pets") +
                   " and the agent has not been asked. Under NSW rules a landlord can only refuse a pet on set grounds, so ask.",
                   "evidence": [_ev("listings", row_l, mat, f"{nm} pets"), not_asked]}
    # 空调只说了客厅（同一句没提卧室）→ 多半只有客厅；说了空调没说哪间 → 有，但不知道在哪
    q_living = said(o, r"(split[- ]system|air[- ]?con\w*)[^.]{0,30}\b(living|lounge)")
    if q_living and re.search(r"bed", q_living["quote"], re.I):
        q_living = None
    q_air = None if q_living else said(o, r"air[- ]?con|split[- ]system|ducted (air|a/?c\b|cooling|reverse)|reverse[- ]cycle")  # "ducted heating" 不算空调
    if q_living:
        head, lab = says(q_living, card)
        F["C1"] = {"status": "inferred", "value": "Living room only", "why": f"{head} '{q_living['quote']}' and nothing about the bedrooms, so probably living room only.",
                   "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_living['quote']}'")]}
    elif q_air:
        head, lab = says(q_air, card)
        rooms = re.search(r"bed|living|lounge|room", q_air["quote"], re.I)  # 引文里点了房间就别说"没说哪间"
        F["C1"] = {"status": "inferred", "value": "Somewhere", "why": f"{head} '{q_air['quote']}'" + ("; ask which rooms it covers." if rooms else
                                                                                                    " but not which rooms; ask whether it reaches the bedrooms."),
                   "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_air['quote']}'" + ("" if rooms else " (no room named)"))]}
    else:
        F["C1"] = {"status": "unknown", "why": f"{Who} doesn't mention air conditioning" + (" (ceiling fans only)" if "ceiling fan" in text else "") + ", so unknown until the agent answers.",
                   "evidence": [_ev("listings", row_l, mat, f"{nm} air conditioning" + ("; 'ceiling fans'" if "ceiling fan" in text else ""))]}
    q_bills = said(o, r"(water|bills|utilities|electricity|internet)[^.]{0,30}\b(included|inclusive)")
    if q_bills and re.search(r"\bnot\b|n't\b|\bexcl", q_bills["m"].group(0), re.I):  # "water is not included"：别读成"包"
        head, lab = says(q_bills, card)
        F["A6"] = {"status": "conflict", "value": "Not included", "why": f"{head} '{q_bills['quote']}'.", "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_bills['quote']}'")]}
    elif q_bills:
        head, lab = says(q_bills, card)
        F["A6"] = {"status": "supported", "why": f"{head} '{q_bills['quote']}'.", "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_bills['quote']}'")]}
    else:
        F["A6"] = {"status": "unknown", "why": f"{Who} doesn't say which bills are included; ask.", "evidence": [_ev("listings", row_l, mat, f"{nm} bills")]}
    # 照片：C2 / C3 / D1（读成户型图的那张不算照片）
    photo_rows = sorted((r for r in readings.values() if not is_plan_reading(r.get("reading") or {})), key=lambda r: r.get("slide") or 0)
    photos = []
    for r in photo_rows:
        i = r.get("slide") or int(re.sub(r"\D", "", r["file"][-6:]) or 0)
        room = str(r["reading"].get("room") or "").lower()
        photos.append(({"url": url_of(o, i), "caption": facts.VIEW_LABELS.get(room, "Photo"), "row": f"{i:02d}", "slide": i}, r["reading"], r["served_model"]))
    q_furn = None if re.search(r"\bunfurnished\b", text) else said(o, r"\bfurnished\b")
    furn_seen = [(p, r, m_) for p, r, m_ in photos if facts._list(r.get("furniture")) and not r.get("virtual_staging")]
    staged = [(p, r, m_) for p, r, m_ in photos if r.get("virtual_staging") or re.search(r"stag|render|virtual", str(r.get("watermark_text") or ""), re.I)]
    if staged:
        p, r, m_ = staged[0]
        F["C2"] = facts.facts_from_reading(L, p, r, m_)["C2"]
    elif q_furn:
        head, lab = says(q_furn, card)
        F["C2"] = {"status": "supported", "value": "Furnished", "short": "furnished", "notable": False, "if_wanted": "supported", "why": f"{head} '{q_furn['quote']}'.",
                   "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_furn['quote']}'")]}
    elif furn_seen:
        p, r, m_ = furn_seen[0]
        F["C2"] = facts.facts_from_reading(L, p, r, m_)["C2"]
    else:
        F["C2"] = {"status": "unknown", "value": None, "notable": False, "if_wanted": "unknown",
                   "why": "Nothing on the search card says it comes furnished." if card else "Nothing in the listing says it comes furnished.",
                   "evidence": [_ev("listings", row_l, mat, "search card: no 'Furnished'" if card else "features: no 'Furnished'")]}
    q_gas = said(o, r"gas (cooking|cooktop|stove|appliances)")
    kitchen = [(p, r, m_) for p, r, m_ in photos if str(r.get("cooktop") or "") in ("gas", "flat_electric")]
    if q_gas:
        head, lab = says(q_gas, card)
        ev = [_ev("listings", row_l, mat, f"{lab}: '{q_gas['quote']}'")]
        why = f"{head} '{q_gas['quote']}'"
        if kitchen:
            p, r, m_ = kitchen[0]
            ev.append(_ev("photo_facts", f"{L['id']}-photo-{p['row']}", f"M-{n}-photo-{p['row']}", facts.photo_line(r, p["caption"]), read_by=m_, image=p["url"]))
            why += " and the kitchen photo shows " + ("gas burners" if r.get("cooktop") == "gas" else "a flat cooktop, which doesn't match; ask")
        F["C3"] = {"status": "inferred", "value": "Gas", "short": "gas", "want": "gas", "why": why + ".", "evidence": ev}
    elif kitchen:
        p, r, m_ = kitchen[0]
        F["C3"] = facts.facts_from_reading(L, p, r, m_)["C3"]
    else:
        F["C3"] = {"status": "unknown", "why": (f"Neither {who} nor the photos show the cooktop; ask." if photos else
                                                f"{Who} doesn't mention the cooktop and no photo has been read yet; ask."),
                   "evidence": [_ev("listings", row_l, mat, f"{nm} the cooktop")]}
    d1 = facts.condition_fact(L, photos)
    if d1:
        F["D1"] = d1
    # 安静：营销词只算推断（R-A2）；大马路是地址本身的事实
    q_quiet = said(o, r"\bquiet\b|peaceful")
    if main_road(o["street"], o["suburb"]):
        side = "the unit faces the back" if L["unit"] else "the main rooms face away from it"
        F["E4"] = {"status": "conflict", "value": "Main road", "short": "main road",
                   "why": f"The address fronts {o['street']}, a main road, and {who} doesn't mention noise; expect traffic noise unless {side}. Ask which side it's on.",
                   "evidence": [_ev("listings", row_l, mat, f"address on {o['street']}")]}
    elif q_quiet:
        head, lab = says(q_quiet, card)
        F["E4"] = {"status": "inferred", "value": "Listing says quiet", "short": "quiet", "why": f"{head} '{q_quiet['quote']}'. That's the agent's word, nothing measured, so inferred.",
                   "evidence": [_ev("listings", row_l, mat, f"{lab}: '{q_quiet['quote']}'")]}
    else:
        F["E4"] = {"status": "unknown", "why": "The search card doesn't mention noise." if card else "Nothing in the listing covers noise.",
                   "evidence": [_ev("listings", row_l, mat, f"{nm} noise")]}
    # 朝向 + 日照
    plan_listed = floorplan_slides(o, readings)  # 挂牌 / 卡片上标了户型图的 slide（卡片没标时：读图说是户型图的那张）
    plan_slides = [i for i in plan_listed if slide_file(o, i, prep=True).exists()]  # 有户型图文件但还没读的（plan 为 None）
    # 没有户型图时怎么说：挂牌页的 slides 是全的，没标就是"挂牌上没有"；搜索卡片只带几张图，图还没读过就是"还没查"，读过了才说"读过的照片里没有"
    if plan_listed:
        no_plan = ("The floor plan hasn't been read yet.", "floor plan not read yet", "The floor plan hasn't been read yet, so {label} can't be checked.")
    elif card and not readings:
        no_plan = ("The search card's photos haven't been checked for a floor plan yet.", "photos not checked for a floor plan yet",
                   "The search card's photos haven't been checked for a floor plan yet, so {label} can't be checked. Ask the agent for the plan.")
    elif card:
        no_plan = ("None of the search card's photos read so far is a floor plan.", "no floor plan among the photos read",
                   "No floor plan among the search card's photos read so far, so {label} can't be checked. Ask the agent for the plan.")
    else:
        no_plan = ("There is no floor plan on the listing.", "no floor plan among the photos",
                   "No floor plan on the listing, so {label} can't be checked. Ask the agent for the plan.")
    aspect, asp_src, asp_conf = solar.aspect_from_text(text), "listing text", "high"
    asp_ev = []
    quote = re.search(r"[^.•\-]*(north|south|east|west)[^.•]*(facing|aspect)[^.•]*", text)
    if aspect:
        asp_ev.append(_ev("listings", row_l, mat, f"'{quote.group(0).strip()}'" if quote else f"listing says {aspect}-facing"))
    elif plan:
        aspect, asp_src, asp_conf = fp.aspect_from_plan(plan["reading"])
        if aspect:
            asp_ev.append(_ev("floorplan_facts", f"{L['id']}-plan", f"M-{n}-plan", asp_src, read_by=plan["served_model"], image=url_of(o, plan["slide"]), confidence=asp_conf))
    floor, floor_how = solar.floor_from_unit(L["unit"], text)
    sun = solar.analyse(o["lat"], o["lng"], aspect, floor=floor)
    status, why = solar.verdict(sun)
    sun.update(aspect_source=asp_src if aspect else None, aspect_confidence=asp_conf if aspect else None, floor_source=floor_how)
    L["sun"] = sun
    if aspect:
        w, s_ = sun["direct"]["winter"], sun["direct"]["summer"]
        asp_ev.append(_ev("sun_geometry", f"{L['id']} 21 Jun / 21 Dec", None,
                          f"Facing {aspect} at {o['lat']:.3f}, {o['lng']:.3f}: direct sun on the main window " + (f"{w['spans'][0][0]}–{w['spans'][-1][1]} ({w['hours']} h)" if w["spans"] else "none") +
                          f" on 21 June and " + (f"{s_['spans'][0][0]}–{s_['spans'][-1][1]} ({s_['hours']} h)" if s_["spans"] else "none") + " on 21 December; neighbouring buildings not in the data"))
        if asp_src != "listing text":
            why += f" The facing comes off the floor plan's north arrow ({asp_conf} confidence)."
        F["E2"] = {"status": status, "value": f"{aspect}-facing", "short": f"{aspect.lower()} facing", "why": why, "evidence": asp_ev}
    else:
        if card:
            why = why.replace("The listing does not say", "The search card does not say")
        if plan:
            tail, plan_ev = " The floor plan has no north arrow.", "floor plan: no north arrow"
        else:
            tail, plan_ev = " " + no_plan[0], no_plan[1]
        F["E2"] = {"status": "unknown", "why": why + tail,
                   "evidence": [_ev("listings", row_l, mat, f"{'search card: ' if card else ''}no facing stated"),
                                _ev("floorplan_facts" if plan else "listings", f"{L['id']}-plan" if plan else row_l, None, plan_ev)]}
    F["H1"] = {"status": "unknown", "why": "Nobody has asked the agent about serious violent crime in the last five years.", "evidence": [not_asked]}
    # 风水包（K1–K4；默认不进清单，R-H0）
    F["K1"] = fp.k1_fact(L, floor, floor_how)
    if plan:
        F.update(fp.k_facts(L, {"url": url_of(o, plan["slide"]), "row": "plan"}, plan["reading"], plan["served_model"]))
    else:
        for d, label in (("K2", "through-line from the entry"), ("K3", "doors facing the kitchen or bathroom"), ("K4", "the outline")):
            F[d] = {"status": "unknown", "why": no_plan[2].format(label=label), "evidence": [_ev("listings", row_l, mat, no_plan[1])]}
    L["facts"] = F
    # 照片：整套相册（户型图那张除外）、卡片用的主图（客厅 / 厨房优先）、户型图
    skip = {plan["slide"]} if plan else set(plan_listed)
    images = []
    for i, s in enumerate(o.get("slides") or [], 1):
        if s.get("type") != "image" or i in skip or not slide_file(o, i, prep=True).exists():
            continue
        r = readings.get(file_key(o, i))
        images.append({"url": url_of(o, i), "slide": i, "caption": facts.VIEW_LABELS.get(str((r or {}).get("reading", {}).get("room") or "").lower(), f"Photo {i}"),
                       "read_by": (r or {}).get("served_model"), "condition": ((r or {}).get("reading") or {}).get("condition")})
    lead = next((p for p, r, m_ in photos if str(r.get("room")) in ("living room", "kitchen")), None) or (photos[0][0] if photos else None)
    if lead:
        r = readings[file_key(o, lead["slide"])]
        L["photo"] = {"file": file_key(o, lead["slide"]), "url": lead["url"], "set": None, "caption": lead["caption"], "stamp": None,
                      "source": f"{SITES[site(o)][1]} listing {o['id']}", "read_by": r["served_model"], "read_at": r["ts"], "route": r["route"], "sha256": r["sha256"]}
    elif images:  # 还没读过图（新导入的卡片）：主图就用它自己的第一张照片，不让界面轮配示意图
        im = images[0]
        L["photo"] = {"file": file_key(o, im["slide"]), "url": im["url"], "set": None, "caption": im["caption"], "stamp": None,
                      "source": f"{SITES[site(o)][1]} listing {o['id']}", "read_by": None, "read_at": None, "route": None, "sha256": None}
    L["images"] = images
    if plan:
        L["floorplan"] = {"url": url_of(o, plan["slide"]), "slide": plan["slide"], "read_by": plan["served_model"], "read_at": plan["ts"], "route": plan["route"],
                          "aspect": aspect if asp_src != "listing text" else None, "confidence": (plan["reading"].get("confidence") or {})}
    elif plan_slides:
        L["floorplan"] = {"url": url_of(o, plan_slides[0]), "slide": plan_slides[0], "read_by": None}
    return L


def synthetic_sun(L: dict) -> None:
    """合成房源：没经纬度、没指北针（R-C1 的坑）→ 用 suburb 中心点算太阳轨迹给详情页画图，E2 保持未知。"""
    lat, lng = SUBURB_LL.get(L["suburb"], SUBURB_LL["Kensington"])
    sun = solar.analyse(lat, lng, None)
    sun.update(aspect_source=None, aspect_confidence=None, floor_source="unknown", approx_location="suburb centre")
    L["sun"] = sun
    if not L["facts"].get("E2"):
        n = facts.num_of(L["id"])
        L["facts"]["E2"] = {"status": "unknown", "why": "The floor plan has no north arrow and the listing doesn't say which way it faces, so direct sun can't be worked out; ask the agent.",
                            "evidence": [{"table": "photo_facts", "row": f"M-{n}-plan", "material_id": f"M-{n}-plan", "text": "Floor plan: no north arrow"}]}


def _bond_rows(listings: List[dict]) -> set:
    return {e["row"] for L in listings for e in (L.get("facts", {}).get("A1") or {}).get("evidence", []) if str(e.get("row") or "").startswith("nsw-bonds/")}


def build(only: Optional[str], dry: bool) -> int:
    matrix = facts.load_json(MATRIX)
    for d, v in DIMS_NEW.items():
        matrix["dims"].setdefault(d, v)
    by_file = facts.readings_by_file()
    plans_ = fp.latest()
    built, skipped = [], []
    for o in load(only):
        bad = unusable(o)
        if bad:
            skipped.append((lid(o), bad))
            print(f"skip {lid(o)}: {bad}")
            continue
        L = build_one(o, by_file.get(lid(o), {}), plans_.get(lid(o)))
        built.append(L)
        f = L["facts"]
        print(f"build {L['id']} {L['unit'] + '/' if L['unit'] else ''}{L['street']}, {L['suburb']} ${L['rent']}: " +
              "; ".join(f"{d} {f[d]['status']}" + (f" ({f[d].get('value')})" if f[d].get("value") else "") for d in ("J1", "C1", "C3", "D1", "E2", "E4", "K1", "K2") if d in f) +
              f"; photos {len(L.get('images', []))}" + (" + plan" if L.get("floorplan") else ""))
        if dry:
            for d in ("D1", "E2", "K2", "K3", "K4"):
                if d in f:
                    print(f"   {d}: {f[d]['why'][:220]}")
    modes = Counter(L["commute"]["unsw"]["mode"] for L in built)
    print(f"{len(built)} real listings built ({sum(bool(L['source'].get('card_only')) for L in built)} from search cards, "
          f"{sum(L['id'].startswith('L-R') for L in built)} from realestate.com.au); move-in date unknown on {sum(not L['available_from'] for L in built)}; "
          f"NSW bond median on {sum(any(str(e.get('row')).startswith('nsw-bonds/') for e in L['facts']['A1']['evidence']) for L in built)}; "
          f"commute modes {dict(modes)}; skipped {len(skipped)}")
    if dry:
        return len(built)
    rebuilt = {L["id"] for L in built}
    keep = [L for L in matrix["listings"] if not is_real(L["id"]) or (only and L["id"] not in rebuilt)]
    for L in keep:
        if not is_real(L["id"]):
            synthetic_sun(L)
    matrix["listings"] = keep + built
    real = [L for L in matrix["listings"] if is_real(L["id"])]
    for s in matrix["sources"]:
        if s["name"] == "listings":
            s["rows"] = SYNTH_LISTING_ROWS + len(real)
        elif s["name"] == "public_rent":
            s["rows"] = SYNTH_PUBLIC_RENT_ROWS + len(_bond_rows(real))
            s["label"] = "DCJ rent medians + NSW bond lodgements" if _bond_rows(real) else "DCJ rent medians"
        elif s["name"] == "sun_geometry":
            s["rows"] = len(real)
        elif s["name"] == "floorplan_facts":
            s["rows"] = sum(bool((L.get("floorplan") or {}).get("read_by")) for L in real)  # 读过户型图的真房源套数
    names = {s["name"] for s in matrix["sources"]}
    for name, label, table in (("sun_geometry", "Sun geometry (computed)", "sun_geometry"), ("floorplan_facts", "Floor plans read by the vision model", "floorplan_facts")):
        if name not in names:
            matrix["sources"].append({"name": name, "label": label, "table": table,
                                      "rows": len(real) if name == "sun_geometry" else sum(bool((L.get("floorplan") or {}).get("read_by")) for L in real)})
    MATRIX.write_text(json.dumps(matrix, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(built)} real + {len(keep)} other listings into {MATRIX.relative_to(ROOT) if MATRIX.is_relative_to(ROOT) else MATRIX}")
    return len(built)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["fetch", "prepare", "read", "plans", "build", "all"])
    ap.add_argument("--only", help="只处理这一套：Domain / REA 编号，或 L-D<编号> / L-R<编号>")
    ap.add_argument("--provider", choices=["meterless", "nvidia"])
    ap.add_argument("--max-photos", type=int, default=6, help="read：每套最多读几张；fetch：搜索卡片每套最多下几张")
    ap.add_argument("--workers", type=int, default=4, help="read：几套房同时读（每套内部逐张）")
    ap.add_argument("--force", action="store_true", help="read / plans：已读过的也重读")
    ap.add_argument("--dry", action="store_true", help="build：只打印")
    a = ap.parse_args()
    llm.load_env()
    items = load(a.only)
    if not items:
        raise SystemExit("no listing json found")
    if a.step in ("fetch", "prepare", "read", "plans", "all"):  # 进不了矩阵的（没租金、车位、没卧室数、已定出）不下图、不问模型
        bad = [(o, unusable(o)) for o in items]
        for o, why in bad:
            if why:
                say(f"skip {lid(o)}: {why}")
        work = [o for o, why in bad if not why]
    else:
        work = items
    if a.step in ("fetch", "all"):
        for o in work:
            fetch(o, a.max_photos)
    if a.step in ("prepare", "all"):
        for o in work:
            prepare(o)
    if a.step in ("read", "all"):
        read_all(work, a.provider, a.max_photos, a.force, a.workers)
    if a.step in ("plans", "all"):
        by_file = facts.readings_by_file()
        for o in work:
            plans(o, a.provider, a.force, by_file.get(lid(o), {}))
    if a.step in ("build", "all"):
        build(a.only, a.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
