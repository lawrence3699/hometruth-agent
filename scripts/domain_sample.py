#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真房源样本（data/real/domain/*.json，9 套 Domain 挂牌）→ 语音导览矩阵（src/voice/mock_matrix.json）里的房源，和 5 套合成房源并排参与查找。

真房源只带真事实（data/real/README.md）：挂牌文字（租金、户型、可入住日、特征标签、朝向词、quiet 这种营销词只算推断 R-A2）、看图模型读照片
（C2 家具、C3 炉灶、D1 新旧）、读户型图（朝向、K2–K4）、按经纬度算的日照（E2，src/sun/solar.py）、Domain 的本区两房中位租金（A1 那行多一条
public_rent 证据）、按直线距离估的通勤（G1，标 estimate，状态只到"推断"）。没有的东西就是未知（押金以外的文件、法定披露、水电），变成该问中介的问题；
绝不给真地址配合成的投诉 / 石棉 / NCAT / 检查报告。

步骤（可单跑）：
  fetch    按 slides 里的 CDN 链接重新下载照片到 data/real/photos/<id>/NN.webp（不进 git）
  prepare  缩成能内联上传的 JPEG：data/real/photos/<id>/prep/NN.jpg（页面也直接用这份，/real/<id>/prep/NN.jpg）
  read     每张照片问一次 Nemotron VL（src/photo/facts.py 的提示词和路由：先 Nightshift 视觉路由、没有就直连 NVIDIA，如实记录）
           → runs/photo_facts.jsonl（listing = L-D<Domain 编号>）；已读过的文件跳过（--force 重读）；--max-photos 限每套张数
  plans    有户型图的几套问一次（src/photo/floorplan.py）→ runs/floorplan_facts.jsonl
  build    合成矩阵房源并写进 mock_matrix.json（替换旧的 L-D*，合成房源不动，只给它们补 sun 几何和 E2 未知格）；--dry 只打印
跑：python3 scripts/domain_sample.py all            python3 scripts/domain_sample.py read --only 17153470 --max-photos 4
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from llm import provider as llm  # noqa: E402
from photo import facts  # noqa: E402
from photo import floorplan as fp  # noqa: E402
from sun import solar  # noqa: E402

REAL = ROOT / "data" / "real"
DOMAIN = REAL / "domain"
PHOTOS = REAL / "photos"
MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"
URL_BASE = "/real/"
ANCHORS = {"central": (-33.8832, 151.2063, "Central Station"), "unsw": (-33.9173, 151.2313, "UNSW"), "cbd": (-33.8688, 151.2093, "the CBD")}
SUBURB_LL = {"Kensington": (-33.9100, 151.2240), "Zetland": (-33.9075, 151.2090), "Kingsford": (-33.9245, 151.2270), "Randwick": (-33.9140, 151.2410),
             "Redfern": (-33.8930, 151.2040)}
DIMS_NEW = {"D1": {"label": "Condition", "hard": False},
            "K1": {"label": "Numbers", "hard": False, "pack": "fengshui"}, "K2": {"label": "Through-line", "hard": False, "pack": "fengshui"},
            "K3": {"label": "Doors", "hard": False, "pack": "fengshui"}, "K4": {"label": "Outline", "hard": False, "pack": "fengshui"}}
TODAY = dt.date.today()


# ---------------------------------------------------------------- 读入
def load(only: Optional[str] = None) -> List[dict]:
    out = []
    for f in sorted(DOMAIN.glob("*.json")):
        if only and f.stem != str(only):
            continue
        out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def lid(o: dict) -> str:
    return f"L-D{o['id']}"


def text_of(o: dict) -> str:
    return " ".join([o.get("headline") or ""] + list(o.get("description") or []) + list(o.get("features") or [])).lower()


def slide_file(o: dict, i: int, prep: bool = False) -> Path:
    d = PHOTOS / str(o["id"])
    return d / "prep" / f"{i:02d}.jpg" if prep else d / f"{i:02d}.webp"


def file_key(o: dict, i: int) -> str:
    return f"{o['id']}/prep/{i:02d}.jpg"


def url_of(o: dict, i: int) -> str:
    return URL_BASE + file_key(o, i)


# ---------------------------------------------------------------- fetch / prepare
def fetch(o: dict) -> int:
    n = 0
    for i, s in enumerate(o["slides"], 1):
        dst = slide_file(o, i)
        if dst.exists() or not s.get("url"):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(s["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            dst.write_bytes(r.read())
        n += 1
    print(f"fetch {o['id']}: {n} new files")
    return n


def prepare(o: dict) -> List[Tuple[int, dict, Path]]:
    from PIL import Image
    out = []
    for i, s in enumerate(o["slides"], 1):
        src, dst = slide_file(o, i), slide_file(o, i, prep=True)
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            img = Image.open(src).convert("RGB")
            side = 1400 if s["type"] == "floorplan" else facts.MAX_SIDE
            img.thumbnail((side, side))
            data = b""
            for q in (88, 85, 80, 75, 70, 62, 55):
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=q, optimize=True)
                data = buf.getvalue()
                if len(data) <= facts.MAX_BYTES:
                    break
            dst.write_bytes(data)
        out.append((i, s, dst))
    print(f"prepare {o['id']}: {len(out)} files → {PHOTOS.relative_to(ROOT)}/{o['id']}/prep/")
    return out


# ---------------------------------------------------------------- read / plans（问模型）
def read(o: dict, provider: Optional[str], max_photos: int, force: bool) -> List[dict]:
    done = facts.readings_by_file().get(lid(o), {})
    rows = []
    images = [(i, s) for i, s in enumerate(o["slides"], 1) if s["type"] == "image" and slide_file(o, i, prep=True).exists()][:max_photos]
    for i, s in images:
        key = file_key(o, i)
        if key in done and not force:
            print(f"read {lid(o)} {key}: already read on {done[key]['ts'][:10]} (--force to redo)")
            continue
        data = slide_file(o, i, prep=True).read_bytes()
        caption = f"photo {i} of {len(o['slides'])}; the listing is a {o['beds']}-bedroom {o['type'].split(' /')[0].lower()}"
        t0 = time.time()
        try:
            obj, res, route, reason = facts.ask_model(data, caption, provider)
        except Exception as e:  # noqa: BLE001
            print(f"read {lid(o)} {key}: FAILED {type(e).__name__}: {str(e)[:160]}")
            continue
        row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "listing": lid(o), "file": key, "slide": i, "sha256": facts.sha256(data),
               "bytes": len(data), "route": route, "nightshift": reason or None, "provider": res.provider, "model": res.model,
               "served_model": res.served_model or res.model, "ms": res.ms, "wall_ms": round((time.time() - t0) * 1000), "reading": obj, "raw": res.text[:800]}
        facts.LOG.parent.mkdir(parents=True, exist_ok=True)
        with facts.LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
        print(f"read {lid(o)} {key}: via {route} {row['served_model']} in {res.ms} ms → {json.dumps(obj, ensure_ascii=False)[:160]}")
        time.sleep(1.0)
    return rows


def plans(o: dict, provider: Optional[str], force: bool) -> Optional[dict]:
    done = fp.latest().get(lid(o))
    for i, s in enumerate(o["slides"], 1):
        if s["type"] != "floorplan" or not slide_file(o, i, prep=True).exists():
            continue
        if done and done.get("file") == file_key(o, i) and not force:
            print(f"plan {lid(o)}: already read on {done['ts'][:10]}")
            return done
        try:
            row = fp.read(lid(o), file_key(o, i), slide_file(o, i, prep=True).read_bytes(), f"{o['beds']}-bedroom apartment", provider)
        except Exception as e:  # noqa: BLE001
            print(f"plan {lid(o)}: FAILED {type(e).__name__}: {str(e)[:160]}")
            return None
        row["slide"] = i
        return row
    return None


# ---------------------------------------------------------------- build：真事实 → 矩阵房源
def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def commute_estimate(o: dict) -> Dict[str, dict]:
    """直线距离 → 分钟（8 分钟走路等车 + 每公里 3.75 分钟，约 16 km/h 门到门）。标 estimate，G1 只给"推断"。"""
    out = {}
    mode = "train" if o["suburb"] in ("Redfern",) else "light rail"
    for key, (lat, lng, _label) in ANCHORS.items():
        km = haversine_km((o["lat"], o["lng"]), (lat, lng))
        out[key] = {"min": int(round(8 + km * 3.75)), "mode": mode, "estimate": True, "km": round(km, 1)}
    return out


def _ev(table: str, row: str, material: Optional[str], text: str, **kw) -> dict:
    return dict({"table": table, "row": row, "material_id": material, "text": text}, **kw)


def special_line(o: dict) -> str:
    pat = re.compile(r"balcon|outlook|view|top floor|park|renovat|updated|art deco|sunroom|garden|courtyard|lift", re.I)
    for ln in o.get("description") or []:
        t = ln.strip().lstrip("•-– ").strip()
        if t and len(t) <= 110 and pat.search(t) and not t.lower().startswith(("located", "positioned", "enjoy", "disclaimer")):
            return f"the listing's own words: '{t.rstrip('. ')}'"
    return f"the listing's own words: '{(o.get('headline') or '').strip().rstrip('. ')}'"


def plan_slide(plan: dict) -> int:
    """户型图是第几张（日志行里 file = <id>/prep/NN.jpg）。"""
    return int(plan.get("slide") or re.sub(r"\D", "", plan["file"][-6:]) or 0)


def build_one(o: dict, readings: Dict[str, dict], plan: Optional[dict]) -> dict:
    if plan is not None:
        plan = dict(plan, slide=plan_slide(plan))
    L: dict = {"id": lid(o), "unit": str(o["unit"] or ""), "street": f"{o['streetNumber']} {o['street']}", "suburb": o["suburb"], "postcode": str(o["postcode"]),
               "rent": int(re.sub(r"[^\d]", "", o["price"].split("per")[0]) or 0), "bedrooms": int(o["beds"] or 0), "bathrooms": int(o["baths"] or 0),
               "parking": o.get("parking"), "available_from": (o["stats"].get("availableFrom") or "")[:10] or TODAY.isoformat(),
               "commute": commute_estimate(o), "special": special_line(o), "headline": o.get("headline") or "",
               "description": [ln for ln in (o.get("description") or []) if ln.strip() and not ln.lower().startswith("disclaimer")][:2],
               "lat": o["lat"], "lng": o["lng"],
               "source": {"site": "domain.com.au", "listing_id": o["id"], "url": o["url"], "agency": o.get("agency"), "fetched_at": o.get("fetched_at"),
                          "modified": o.get("modified")}}
    n = facts.num_of(L["id"])
    row_l = L["id"]
    mat = f"M-{n}-listing"
    text = text_of(o)
    bond = o["stats"].get("bond")
    F: Dict[str, dict] = {}
    median = o.get("medianRent")
    pct = int(round((L["rent"] - median) / median * 100)) if median else None
    F["A1"] = {"evidence": [_ev("listings", row_l, mat, f"Rent {o['price']}" + (f", bond ${bond:,}" if bond else ""))],
               "median": {"rent": median, "beds": o.get("medianBeds"), "suburb": o["suburb"], "pct": pct} if median else None}
    if median:
        F["A1"]["evidence"].append(_ev("public_rent", f"domain-median/{o['suburb'].lower()}/{o.get('medianBeds') or 2}-bed", None,
                                       f"Domain: median asking rent for {o.get('medianBeds') or 2}-bedroom places in {o['suburb']} is ${median} a week; this one asks ${L['rent']} "
                                       f"({'about the same' if abs(pct) < 2 else f'{abs(pct)}% ' + ('above' if pct > 0 else 'below')})"))
    F["B1"] = {"evidence": [_ev("listings", row_l, mat, f"{L['bedrooms']} bed, {L['bathrooms']} bath" + (f", {o['parking']} car" if o.get("parking") else ""))]}
    av = dt.date.fromisoformat(L["available_from"])
    F["A4"] = {"evidence": [_ev("listings", row_l, mat, f"Available {av.day} {av:%b %Y}" + (" (already vacant)" if av <= TODAY else ""))]}
    not_asked = _ev("documents", f"agent_replies/{L['id']}", None, "Not asked yet")
    if re.search(r"pets? (allowed|welcome|considered|ok|friendly)|pet[- ]friendly", text):
        F["J1"] = {"status": "inferred", "why": "The listing's features say 'Pets Allowed'. That's the agent's word; NSW rules want the landlord's consent in writing, so get it into the lease.",
                   "evidence": [_ev("listings", row_l, mat, "features: 'Pets Allowed'"), not_asked]}
    elif re.search(r"no pets|pets? not (allowed|permitted)", text):
        F["J1"] = {"status": "conflict", "why": "The listing says no pets. Under NSW rules that still needs a set ground, so it's a conflict to push on.",
                   "evidence": [_ev("listings", row_l, mat, "'No pets'"), not_asked]}
    else:
        F["J1"] = {"status": "unknown", "why": "The listing says nothing about pets and the agent has not been asked. Under NSW rules a landlord can only refuse a pet on set grounds, so ask.",
                   "evidence": [_ev("listings", row_l, mat, "no mention of pets"), not_asked]}
    if re.search(r"split[- ]system air[- ]?con[^.]{0,30}(living|lounge)|air[- ]?con[^.]{0,20}(living|lounge) (area|room) only", text):
        F["C1"] = {"status": "inferred", "value": "Living room only", "why": "The listing says split-system air conditioning in the living area and nothing about the bedrooms, so probably living room only.",
                   "evidence": [_ev("listings", row_l, mat, "'Split-system air conditioning in the living area'")]}
    elif re.search(r"air[- ]?con|split system|ducted", text):
        F["C1"] = {"status": "inferred", "value": "Somewhere", "why": "The listing lists air conditioning but not which rooms; ask whether it reaches the bedrooms.",
                   "evidence": [_ev("listings", row_l, mat, "features: 'Air conditioning' (no room named)")]}
    else:
        F["C1"] = {"status": "unknown", "why": "The listing doesn't mention air conditioning" + (" (ceiling fans only)" if "ceiling fan" in text else "") + ", so unknown until the agent answers.",
                   "evidence": [_ev("listings", row_l, mat, "no mention of air conditioning" + ("; 'ceiling fans'" if "ceiling fan" in text else ""))]}
    m = re.search(r"(water|bills|utilities|electricity|internet)[^.]{0,30}\b(included|inclusive)", text)
    if m:
        F["A6"] = {"status": "supported", "why": f"The listing says {m.group(1)} is included.", "evidence": [_ev("listings", row_l, mat, f"'{m.group(0)}'")]}
    else:
        F["A6"] = {"status": "unknown", "why": "The listing doesn't say which bills are included; ask.", "evidence": [_ev("listings", row_l, mat, "no mention of bills")]}
    # 照片：C2 / C3 / D1
    photo_rows = sorted(readings.values(), key=lambda r: r.get("slide") or 0)
    photos = []
    for r in photo_rows:
        i = r.get("slide") or int(re.sub(r"\D", "", r["file"][-6:]) or 0)
        room = str(r["reading"].get("room") or "").lower()
        photos.append(({"url": url_of(o, i), "caption": facts.VIEW_LABELS.get(room, "Photo"), "row": f"{i:02d}", "slide": i}, r["reading"], r["served_model"]))
    furnished = bool(re.search(r"\bfurnished\b", text)) and not re.search(r"\bunfurnished\b", text)
    furn_seen = [(p, r, m_) for p, r, m_ in photos if facts._list(r.get("furniture")) and not r.get("virtual_staging")]
    staged = [(p, r, m_) for p, r, m_ in photos if r.get("virtual_staging") or re.search(r"stag|render|virtual", str(r.get("watermark_text") or ""), re.I)]
    if staged:
        p, r, m_ = staged[0]
        F["C2"] = facts.facts_from_reading(L, p, r, m_)["C2"]
    elif furnished:
        F["C2"] = {"status": "supported", "value": "Furnished", "short": "furnished", "notable": False, "if_wanted": "supported", "why": "The listing says furnished.",
                   "evidence": [_ev("listings", row_l, mat, "'furnished'")]}
    elif furn_seen:
        p, r, m_ = furn_seen[0]
        F["C2"] = facts.facts_from_reading(L, p, r, m_)["C2"]
    else:
        F["C2"] = {"status": "unknown", "value": None, "notable": False, "if_wanted": "unknown", "why": "Nothing in the listing says it comes furnished.",
                   "evidence": [_ev("listings", row_l, mat, "features: no 'Furnished'")]}
    gas_text = re.search(r"gas (cooking|cooktop|stove|appliances)", text)
    kitchen = [(p, r, m_) for p, r, m_ in photos if str(r.get("cooktop") or "") in ("gas", "flat_electric")]
    if gas_text:
        ev = [_ev("listings", row_l, mat, f"'{gas_text.group(0)}'")]
        why = "The listing says gas cooking"
        if kitchen:
            p, r, m_ = kitchen[0]
            ev.append(_ev("photo_facts", f"{L['id']}-photo-{p['row']}", f"M-{n}-photo-{p['row']}", facts.photo_line(r, p["caption"]), read_by=m_, image=p["url"]))
            why += " and the kitchen photo shows " + ("gas burners" if r.get("cooktop") == "gas" else "a flat cooktop, which doesn't match; ask")
        F["C3"] = {"status": "inferred", "value": "Gas", "short": "gas", "want": "gas", "why": why + ".", "evidence": ev}
    elif kitchen:
        p, r, m_ = kitchen[0]
        F["C3"] = facts.facts_from_reading(L, p, r, m_)["C3"]
    else:
        F["C3"] = {"status": "unknown", "why": "Neither the listing nor the photos show the cooktop; ask.", "evidence": [_ev("listings", row_l, mat, "no mention of the cooktop")]}
    d1 = facts.condition_fact(L, photos)
    if d1:
        F["D1"] = d1
    # 安静：营销词只算推断（R-A2）；大马路是地址本身的事实
    if o["street"].lower() in ("anzac parade",):
        F["E4"] = {"status": "conflict", "value": "Main road", "short": "main road", "why": f"The address fronts {o['street']}, a main road, and the listing doesn't mention noise; expect traffic noise unless the unit faces the back. Ask which side it's on.",
                   "evidence": [_ev("listings", row_l, mat, f"address on {o['street']}")]}
    elif re.search(r"\bquiet\b|peaceful", text):
        F["E4"] = {"status": "inferred", "value": "Listing says quiet", "short": "quiet", "why": "The listing calls it quiet. That's the agent's word, nothing measured, so inferred.",
                   "evidence": [_ev("listings", row_l, mat, "'quiet'")]}
    else:
        F["E4"] = {"status": "unknown", "why": "Nothing in the listing covers noise.", "evidence": [_ev("listings", row_l, mat, "no mention of noise")]}
    # 朝向 + 日照
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
        F["E2"] = {"status": "unknown", "why": why + (" The floor plan has no north arrow." if plan else " There is no floor plan on the listing."),
                   "evidence": [_ev("listings", row_l, mat, "no facing stated"), _ev("floorplan_facts" if plan else "listings", f"{L['id']}-plan" if plan else row_l, None,
                                                                                    "floor plan: no north arrow" if plan else "no floor plan among the photos")]}
    F["H1"] = {"status": "unknown", "why": "Nobody has asked the agent about serious violent crime in the last five years.", "evidence": [not_asked]}
    # 风水包（K1–K4；默认不进清单，R-H0）
    F["K1"] = fp.k1_fact(L, floor, floor_how)
    if plan:
        F.update(fp.k_facts(L, {"url": url_of(o, plan["slide"]), "row": "plan"}, plan["reading"], plan["served_model"]))
    else:
        for d, label in (("K2", "through-line from the entry"), ("K3", "doors facing the kitchen or bathroom"), ("K4", "the outline")):
            F[d] = {"status": "unknown", "why": f"No floor plan on the listing, so {label} can't be checked. Ask the agent for the plan.",
                    "evidence": [_ev("listings", row_l, mat, "no floor plan among the photos")]}
    L["facts"] = F
    # 照片：卡片用的主图（客厅 / 厨房优先）、整套相册、户型图
    lead = next((p for p, r, m_ in photos if str(r.get("room")) in ("living room", "kitchen")), None) or (photos[0][0] if photos else None)
    if lead:
        r = readings[file_key(o, lead["slide"])]
        L["photo"] = {"file": file_key(o, lead["slide"]), "url": lead["url"], "set": None, "caption": lead["caption"], "stamp": None,
                      "source": f"domain.com.au listing {o['id']}", "read_by": r["served_model"], "read_at": r["ts"], "route": r["route"], "sha256": r["sha256"]}
    L["images"] = []
    for i, s in enumerate(o["slides"], 1):
        if s["type"] != "image" or not slide_file(o, i, prep=True).exists():
            continue
        r = readings.get(file_key(o, i))
        L["images"].append({"url": url_of(o, i), "slide": i, "caption": facts.VIEW_LABELS.get(str((r or {}).get("reading", {}).get("room") or "").lower(), f"Photo {i}"),
                            "read_by": (r or {}).get("served_model"), "condition": ((r or {}).get("reading") or {}).get("condition")})
    if plan:
        L["floorplan"] = {"url": url_of(o, plan["slide"]), "slide": plan["slide"], "read_by": plan["served_model"], "read_at": plan["ts"], "route": plan["route"],
                          "aspect": aspect if asp_src != "listing text" else None, "confidence": (plan["reading"].get("confidence") or {})}
    else:
        pf = next((i for i, s in enumerate(o["slides"], 1) if s["type"] == "floorplan" and slide_file(o, i, prep=True).exists()), None)
        if pf:
            L["floorplan"] = {"url": url_of(o, pf), "slide": pf, "read_by": None}
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


def build(only: Optional[str], dry: bool) -> int:
    matrix = facts.load_json(MATRIX)
    for d, v in DIMS_NEW.items():
        matrix["dims"].setdefault(d, v)
    by_file = facts.readings_by_file()
    plans_ = fp.latest()
    built = []
    for o in load(only):
        L = build_one(o, by_file.get(lid(o), {}), plans_.get(lid(o)))
        built.append(L)
        f = L["facts"]
        print(f"build {L['id']} {L['unit']}/{L['street']}, {L['suburb']} ${L['rent']}: " +
              "; ".join(f"{d} {f[d]['status']}" + (f" ({f[d].get('value')})" if f[d].get("value") else "") for d in ("J1", "C1", "C3", "D1", "E2", "E4", "K1", "K2") if d in f) +
              f"; photos {len(L.get('images', []))}" + (" + plan" if L.get("floorplan") else ""))
        if dry:
            for d in ("D1", "E2", "K2", "K3", "K4"):
                if d in f:
                    print(f"   {d}: {f[d]['why'][:220]}")
    if dry:
        return len(built)
    keep = [L for L in matrix["listings"] if not L["id"].startswith("L-D") or (only and L["id"] != f"L-D{only}")]
    for L in keep:
        if not L["id"].startswith("L-D"):
            synthetic_sun(L)
    matrix["listings"] = keep + built
    for s in matrix["sources"]:
        if s["name"] == "listings":
            s["rows"] = 50 + len([L for L in matrix["listings"] if L["id"].startswith("L-D")])
    names = {s["name"] for s in matrix["sources"]}
    for name, label, table in (("sun_geometry", "Sun geometry (computed)", "sun_geometry"), ("floorplan_facts", "Floor plans read by the vision model", "floorplan_facts")):
        if name not in names:
            matrix["sources"].append({"name": name, "label": label, "table": table, "rows": len(built)})
    MATRIX.write_text(json.dumps(matrix, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(built)} real + {len(keep)} other listings into {MATRIX.relative_to(ROOT)}")
    return len(built)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["fetch", "prepare", "read", "plans", "build", "all"])
    ap.add_argument("--only", help="只处理这一套（Domain 编号）")
    ap.add_argument("--provider", choices=["meterless", "nvidia"])
    ap.add_argument("--max-photos", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="read / plans：已读过的也重读")
    ap.add_argument("--dry", action="store_true", help="build：只打印")
    a = ap.parse_args()
    llm.load_env()
    items = load(a.only)
    if not items:
        raise SystemExit("no listing json found")
    for o in items:
        if a.step in ("fetch", "all"):
            fetch(o)
        if a.step in ("prepare", "all"):
            prepare(o)
        if a.step in ("read", "all"):
            read(o, a.provider, a.max_photos, a.force)
        if a.step in ("plans", "all"):
            plans(o, a.provider, a.force)
    if a.step in ("build", "all"):
        build(a.only, a.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
