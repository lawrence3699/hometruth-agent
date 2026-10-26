#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""照片事实（docs/06 §4A；规则 docs/01 R-B1 / R-B2）：让 NVIDIA 的看图模型 Nemotron VL 读每套候选房的挂牌照片，只记"看得见的事"，
离线跑一次，结果写进 src/voice/mock_matrix.json（演示不实时调模型，稳）。界面上这一行的证据标 "Read by Nemotron VL"，带缩略图。

三步（每步可单跑）：
  prepare  按 manifest 把示意照片缩到能内联上传的大小（NVIDIA 直连 base64 上限约 180 KB），要盖章的盖 "VIRTUALLY STAGED"
           （R-B1：有虚拟软装水印的家具视为不存在）→ src/voice/static/qi/assets/photos/<listing>-01.jpg
  read     每张照片问一次模型：先走 Meterless Nightshift 的视觉路由（meterless/vision），它没有视觉 lane 就直连 NVIDIA，走了哪条路如实记
           → runs/photo_facts.jsonl（每行：房源、文件哈希、路由、served_model、毫秒、模型的 JSON 回答）
  write    把最近一次 read 的结果变成矩阵里的事实：C2 Furniture（盖章 → 家具不随租，推断，而且不管租客问没问都亮这一行；
           没盖章 → 照片里的家具不算数，未知）、C3 Stove（R-B2：明火炉架 = 燃气；平面炉 = 电，陶瓷还是电磁从照片分不出）、
           D1 Condition（10-26，docs/02 楼龄与新旧：模型只报看得见的迹象 —— 台面材质、瓷砖、地毯、漆面；规则把几张照片合成一格：
           有 worn 就 worn，厨房或卫生间 dated 就 dated，有 new 没 dated 就 new，其余 good；永远是"推断"，照片挑最好的时候拍（R-B3），
           看起来旧或破的那格不管问没问都亮，和盖章家具一样）
真房源（data/real）的多张照片走 scripts/domain_sample.py，它用这里的 ask_model / condition_fact，日志同一个文件（listing 是 L-D<Domain 编号>）。
跑：python3 src/photo/facts.py all            （prepare + read + write）
    python3 src/photo/facts.py read --listing L-0002 --provider nvidia
    python3 src/photo/facts.py write --dry     （只打印会写什么）
环境：.env 里的 NVIDIA_API_KEY（直连）/ METERLESS_*（Nightshift）；NVIDIA_VL_MODEL 默认 nvidia/nemotron-3.5-super-vl-120b-a12b。
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from llm import provider as llm  # noqa: E402

PHOTOS = ROOT / "src" / "voice" / "static" / "qi" / "assets" / "photos"
MANIFEST = PHOTOS / "manifest.json"
MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"
LOG = ROOT / "runs" / "photo_facts.jsonl"
URL_BASE = "/static/qi/assets/photos/"
MAX_BYTES = 170 * 1024  # NVIDIA 直连：内联 base64 的图大约 180 KB 封顶，留点余量
MAX_SIDE = 1024
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/Helvetica.ttc"]

SYSTEM = """HOMETRUTH_PHOTO_FACTS_V2
You read ONE photo from a Sydney rental listing on behalf of a renter. Report only what is visible in the photo itself. Never guess at anything the photo does not show, never describe people, and never estimate size, light or value.
Reply with ONE JSON object and nothing else:
{"room": "living room|kitchen|dining|bedroom|bathroom|balcony|exterior|other",
 "watermark_text": "the exact text of any stamp, label or watermark on the photo, else null",
 "virtual_staging": true or false (true only if a stamp or label says the photo is virtually staged or rendered, or the furniture is obviously computer-generated),
 "furniture": ["each piece of movable furniture in view, lower case, e.g. sofa, coffee table, dining table, chairs, bookshelf, bed"],
 "cooktop": "gas|flat_electric|none_visible|unknown" (gas only if burner grates or open flames are visible; flat_electric for a flat glass or ceramic surface),
 "air_con_unit_visible": true or false (a wall split unit or ducted vent in view),
 "window_view": "what is directly outside the window, in a few words, or null",
 "condition": "new|good|dated|worn|unknown" (new = recently built or fully renovated finishes; good = clean and intact, no obvious age; dated = older finishes such as laminate benchtops, old tiles or cabinetry, old carpet, but intact; worn = visible wear or damage such as stains, peeling paint, cracked tiles, mould; unknown = the photo does not show finishes),
 "condition_signs": ["each visible sign behind that condition, lower case, at most 4, e.g. laminate benchtop, new stone benchtop, old tiles, fresh paint, worn carpet"],
 "condition_confidence": "high|medium|low",
 "one_line": "one plain sentence (at most 25 words) telling the renter what this photo shows, nothing it does not show"}"""

USER = "Read this listing photo and fill the JSON. Caption from the listing: {caption}."

VIEW_LABELS = {"living room": "Living room", "kitchen": "Kitchen", "dining": "Dining area", "bedroom": "Bedroom", "bathroom": "Bathroom",
               "balcony": "Balcony", "exterior": "Exterior", "other": "Photo"}


# ---------------------------------------------------------------- 工具
def load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def manifest() -> dict:
    return load_json(MANIFEST)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def num_of(listing_id: str) -> str:
    """L-0002 → 0002（material_id 的编号段）。"""
    return listing_id.split("-", 1)[1] if "-" in listing_id else listing_id


def listing_items(m: dict, only: Optional[str] = None) -> List[dict]:
    return [it for it in m["photos"] if not only or it["listing"] == only]


# ---------------------------------------------------------------- prepare：缩图 + 盖章
def _font(size: int):
    from PIL import ImageFont
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def stamp(img, text: str):
    """右下角一块半透明深色底 + 白色大写字，像澳洲挂牌网站上 "VIRTUALLY STAGED" 那种角标。"""
    from PIL import Image, ImageDraw
    img = img.convert("RGBA")
    w, h = img.size
    size = max(18, int(min(w, h) * 0.045))
    font = _font(size)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = int(size * 0.6)
    x1, y1 = w - pad, h - pad
    x0, y0 = x1 - tw - 2 * pad, y1 - th - 2 * pad
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0, y0, x1, y1], radius=int(size * 0.35), fill=(20, 24, 30, 190))
    img = Image.alpha_composite(img, layer)
    ImageDraw.Draw(img).text((x0 + pad - bbox[0], y0 + pad - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
    return img.convert("RGB")


def prepare(only: Optional[str] = None) -> List[Tuple[str, Path, int]]:
    from PIL import Image
    m = manifest()
    out = []
    for it in listing_items(m, only):
        src = (PHOTOS / it["from"]).resolve()
        img = Image.open(src).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        if it.get("stamp"):
            img = stamp(img, it["stamp"])
        data = b""
        for q in (85, 80, 75, 70, 62, 55):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if len(data) <= MAX_BYTES:
                break
        dst = PHOTOS / it["file"]
        dst.write_bytes(data)
        out.append((it["listing"], dst, len(data)))
        print(f"prepare {it['listing']}: {src.name} → {dst.name} {img.size[0]}x{img.size[1]} {len(data) // 1024} KB" + (f" stamped {it['stamp']!r}" if it.get("stamp") else ""))
    return out


# ---------------------------------------------------------------- read：问模型
def _json_object(text: str) -> Optional[dict]:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(t[i:j + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def ask_model(image: bytes, caption: str, provider: Optional[str] = None, timeout: float = 90.0) -> Tuple[dict, llm.ChatResult, str, str]:
    """返回 (模型的 JSON, ChatResult, 路由, Nightshift 拒绝的原因)。provider=None 先试 Nightshift 视觉路由，被拒就直连 NVIDIA（如实记录）。"""
    b64 = base64.b64encode(image).decode("ascii")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": USER.format(caption=caption)},
                                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    kw = dict(task="photo_facts", vision=True, temperature=0.0, max_tokens=400, timeout=timeout, retries=1)

    def call(prov: Optional[str]) -> llm.ChatResult:
        """NVIDIA 的看图接口偶尔整段时间回 500（10-26 实测，同一张图几分钟后就好）：服务端错误等一会再试两次。"""
        for attempt in range(3):
            try:
                return llm.chat(msgs, provider=prov, **kw)
            except llm.LLMError as e:
                if e.kind != "server_error" or attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("unreachable")

    route, reason = "", ""
    if provider in (None, "meterless"):
        try:
            res = call(None if provider is None else "meterless")
            route = "nvidia-direct" if res.provider == "nvidia" else "meterless"
            if res.fallback_from:
                route, reason = "nvidia-direct (fallback)", res.fallback_reason
        except llm.LLMError as e:
            if provider == "meterless":
                raise
            reason = f"{e.kind}: {str(e)[:160]}"
            res = call("nvidia")
            route = "nvidia-direct"
    else:
        res = call(provider)
        route = "nvidia-direct" if provider == "nvidia" else provider
    obj = _json_object(res.text)
    if obj is None:
        raise RuntimeError(f"model answer was not JSON: {res.text[:200]!r}")
    return obj, res, route, reason


def read(only: Optional[str] = None, provider: Optional[str] = None) -> List[dict]:
    m = manifest()
    rows = []
    for it in listing_items(m, only):
        p = PHOTOS / it["file"]
        if not p.exists():
            raise SystemExit(f"{p} missing: run prepare first")
        data = p.read_bytes()
        t0 = time.time()
        obj, res, route, reason = ask_model(data, it.get("caption") or "", provider)
        row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "listing": it["listing"], "file": it["file"],
               "sha256": sha256(data), "bytes": len(data), "route": route, "nightshift": reason or None, "provider": res.provider, "model": res.model,
               "served_model": res.served_model or res.model, "ms": res.ms, "wall_ms": round((time.time() - t0) * 1000), "reading": obj,
               "raw": res.text[:800]}
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
        print(f"read {it['listing']} ({it['file']}): via {route} {row['served_model']} in {res.ms} ms → {json.dumps(obj, ensure_ascii=False)[:220]}")
    return rows


def _log_rows() -> List[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("listing") and isinstance(row.get("reading"), dict):
            out.append(row)
    return out


def latest_readings() -> Dict[str, dict]:
    """runs/photo_facts.jsonl 里每套房最近的一次读图（合成房源一套一张）。"""
    out: Dict[str, dict] = {}
    for row in _log_rows():
        out[row["listing"]] = row
    return out


def readings_by_file() -> Dict[str, Dict[str, dict]]:
    """每套房、每个文件最近的一次读图（真房源一套好几张）：{listing: {file: row}}。"""
    out: Dict[str, Dict[str, dict]] = {}
    for row in _log_rows():
        out.setdefault(row["listing"], {})[row.get("file") or ""] = row
    return out


# ---------------------------------------------------------------- write：读图结果 → 矩阵事实（规则在这里，模型只说看见了什么）
def _list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [x.strip().lower() for x in v.split(",") if x.strip()]
    return []


def furniture_phrase(items: List[str]) -> str:
    items = [x for x in items if x][:4]
    if not items:
        return "furniture"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def photo_line(reading: dict, caption: str) -> str:
    """photo_facts 表那一行的"原文"：照片编号、房间、水印、看见的家具 —— 全是模型报告里的字段，不是它的自由发挥。"""
    room = VIEW_LABELS.get(str(reading.get("room") or "").lower(), caption or "Photo")
    wm = reading.get("watermark_text")
    furn = _list(reading.get("furniture"))
    parts = [f"{room} photo"]
    parts.append(f"stamped '{wm}'" if wm else "no staging stamp")
    parts.append(f"furniture in view: {', '.join(furn)}" if furn else "no furniture in view")
    cook = str(reading.get("cooktop") or "").lower()
    if cook == "gas":
        parts.append("gas burners on the cooktop")
    elif cook == "flat_electric":
        parts.append("flat glass cooktop")
    if reading.get("air_con_unit_visible"):
        parts.append("air con unit in view")
    cond = str(reading.get("condition") or "").lower()
    if cond in CONDITION_WORDS:
        signs = _list(reading.get("condition_signs"))[:3]
        parts.append(f"finishes look {cond}" + (f" ({', '.join(signs)})" if signs else ""))
    return "; ".join(parts) + "."


CONDITION_WORDS = {"new": "Looks new", "good": "Looks well kept", "dated": "Looks dated", "worn": "Looks worn"}
WET_ROOMS = ("kitchen", "bathroom")


def condition_fact(listing: dict, photos: List[Tuple[dict, dict, str]]) -> Optional[dict]:
    """D1 楼龄与新旧（docs/02；10-26）。photos = [(photo, reading, read_by), …]，photo 要有 url、caption、可选 row（照片编号，默认按顺序 01…）。
    规则（模型只说看见了什么，结论在这里）：有 worn → worn；厨房 / 卫生间 dated 或两张以上 dated → dated；有 new 且没 dated → new；其余 good。
    状态永远是 inferred：照片挑最好的时候拍（R-B3），条件报告才是记录。dated / worn 标 notable（不管问没问都讲）；要"新 / 翻新过"的人看到 dated / worn 是冲突。"""
    lid = listing["id"]
    n = num_of(lid)
    seen: List[Tuple[str, str, List[str], dict, dict, str, int]] = []
    for i, (photo, reading, read_by) in enumerate(photos):
        cond = str(reading.get("condition") or "").lower()
        if cond not in CONDITION_WORDS:
            continue
        room = str(reading.get("room") or "").lower()
        seen.append((room, cond, _list(reading.get("condition_signs"))[:3], photo, reading, read_by, i + 1))
    if not seen:
        return None
    conds = [c for _, c, *_ in seen]
    wet_dated = any(c == "dated" and r in WET_ROOMS for r, c, *_ in seen)
    if "worn" in conds:
        overall = "worn"
    elif wet_dated or conds.count("dated") >= 2:
        overall = "dated"
    elif "new" in conds and "dated" not in conds:
        overall = "new"
    else:
        overall = "good"
    bits = []
    for room, cond, signs, *_ in seen:
        label = VIEW_LABELS.get(room, "photo").lower()
        bits.append(f"the {label} looks {cond}" + (f" ({', '.join(signs)})" if signs else ""))
    detail = "; ".join(bits[:4])
    tail = " Photos are taken at their best, so treat this as a hint; the condition report at signing is the record."
    why = f"From the photos: {detail}.{tail}" if len(seen) > 1 else f"From the photo, {detail}.{tail}"
    evidence = []
    for room, cond, signs, photo, reading, read_by, i in seen:
        num = photo.get("row") or f"{i:02d}"
        evidence.append({"table": "photo_facts", "row": f"{lid}-photo-{num}", "material_id": f"M-{n}-photo-{num}", "text": photo_line(reading, photo.get("caption", "")),
                         "read_by": read_by, "image": photo["url"], "confidence": reading.get("condition_confidence") or None})
    notable = overall in ("dated", "worn")
    return {"status": "inferred", "value": CONDITION_WORDS[overall], "short": overall, "condition": overall, "notable": notable,
            "if_wanted": "conflict" if notable else "inferred", "why": why, "evidence": evidence}


def facts_from_reading(listing: dict, photo: dict, reading: dict, read_by: str) -> Dict[str, dict]:
    """一套房的读图结果 → 要写进矩阵 facts 的格子。规则：
    C2 家具（docs/01 R-A3、R-B1）：盖章 = 家具视为不存在 → 推断不随租，notable（不管问没问都亮）；没盖章 = 照片不算数 → 未知。
    C3 炉灶（R-B2）：明火 = 燃气（推断）；平面炉 = 电，电磁炉分不出（推断，想要电磁炉的人要问）。"""
    lid = listing["id"]
    n = num_of(lid)
    ev_photo = {"table": "photo_facts", "row": f"{lid}-photo-01", "material_id": f"M-{n}-photo-01", "text": photo_line(reading, photo.get("caption", "")),
                "read_by": read_by, "image": photo["url"]}
    ev_listing = {"table": "listings", "row": lid, "material_id": f"M-{n}-listing", "text": "features: no 'Furnished'"}
    furn = _list(reading.get("furniture"))
    wm = reading.get("watermark_text")
    staged = bool(reading.get("virtual_staging")) or bool(wm and re.search(r"stag|render|virtual", str(wm), re.I))
    out: Dict[str, dict] = {}
    if staged:
        out["C2"] = {"status": "inferred", "value": "Staged photos", "short": "staged", "notable": True, "if_wanted": "conflict",
                     "why": f"The listing photo is stamped '{wm or 'virtually staged'}', so the {furniture_phrase(furn)} in it won't be there, and nothing in the listing says it comes furnished.",
                     "evidence": [ev_photo, ev_listing]}
    elif furn:
        out["C2"] = {"status": "unknown", "value": None, "notable": False, "if_wanted": "unknown",
                     "why": f"The photo shows {furniture_phrase(furn)}, but photos don't count: nothing in the listing says any of it stays, and it may be the previous tenant's.",
                     "evidence": [ev_photo, ev_listing]}
    else:
        out["C2"] = {"status": "unknown", "value": None, "notable": False, "if_wanted": "unknown",
                     "why": "The photo shows no furniture, and nothing in the listing says it comes furnished.", "evidence": [ev_photo, ev_listing]}
    cook = str(reading.get("cooktop") or "").lower()
    if cook == "gas":
        out["C3"] = {"status": "inferred", "value": "Gas", "short": "gas", "notable": False, "want": "gas",
                     "why": "The kitchen photo shows gas burners on the cooktop, so it's gas as far as the photo goes; the condition report would confirm it.",
                     "evidence": [ev_photo]}
    elif cook == "flat_electric":
        out["C3"] = {"status": "inferred", "value": "Electric", "short": "electric", "notable": False, "want": "electric",
                     "why": "The kitchen photo shows a flat glass cooktop, so it's electric, but ceramic and induction look the same in a photo: ask for the model if induction matters.",
                     "evidence": [ev_photo]}
    d1 = condition_fact(listing, [(dict(photo, row="01"), reading, read_by)])
    if d1:
        out["D1"] = d1
    return out


def write(dry: bool = False, only: Optional[str] = None) -> int:
    m = manifest()
    readings = latest_readings()
    matrix = load_json(MATRIX)
    dims = matrix.setdefault("dims", {})
    dims.setdefault("C3", {"label": "Stove", "hard": False})
    dims.setdefault("D1", {"label": "Condition", "hard": False})
    by_id = {L["id"]: L for L in matrix["listings"]}
    n = 0
    for it in listing_items(m, only):
        L = by_id.get(it["listing"])
        row = readings.get(it["listing"])
        if L is None or row is None:
            print(f"write {it['listing']}: " + ("not in the matrix" if L is None else "no reading yet (run read)"))
            continue
        photo = {"file": it["file"], "url": URL_BASE + it["file"], "set": it.get("set"), "caption": it.get("caption"), "stamp": it.get("stamp"),
                 "source": it.get("source"), "read_by": row["served_model"], "read_at": row["ts"], "route": row["route"], "sha256": row["sha256"]}
        facts = facts_from_reading(L, photo, row["reading"], row["served_model"])
        print(f"write {it['listing']}: photo {it['file']} → " + "; ".join(f"{d} {f['status']} ({f.get('value') or '-'})" for d, f in facts.items()))
        if dry:
            for d, f in facts.items():
                print(f"   {d}: {f['why']}")
            continue
        L["photo"] = photo
        for d, f in facts.items():
            L.setdefault("facts", {})[d] = f
        n += 1
    if not dry:
        MATRIX.write_text(json.dumps(matrix, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {n} listings into {MATRIX.relative_to(ROOT)}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["prepare", "read", "write", "all"])
    ap.add_argument("--listing", help="只处理这一套，如 L-0002")
    ap.add_argument("--provider", choices=["meterless", "nvidia"], help="read：强制走 Nightshift 或直连；默认先 Nightshift、被拒就直连")
    ap.add_argument("--dry", action="store_true", help="write：只打印，不改矩阵")
    a = ap.parse_args()
    llm.load_env()
    if a.step in ("prepare", "all"):
        prepare(a.listing)
    if a.step in ("read", "all"):
        read(a.listing, a.provider)
    if a.step in ("write", "all"):
        write(a.dry, a.listing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
