#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装修风格匹配（软偏好；10-27 队友提的）：租客上传一到三张自己喜欢的室内照片，看图模型（Nemotron VL，经 src/llm/provider.py：先 Meterless
Nightshift，转发不通或没有视觉车道就直连 NVIDIA，走了哪条如实记到 runs/llm_log.jsonl）只抽装修 finishes 的属性 —— 地板、色调、厨房、采光、新旧、
几个风格词 —— 再和每套房挂牌照片（listing.photo，看图模型读过的那张）的同一组属性对比，给每套房一行 "Style match 78% · timber floors, light palette"
和理由。状态永远是 inferred，是软偏好：不进硬条件、不影响排名、不进导览台词；卡片上写 "Soft preference"。
提示词明确不许描述人、人群、国籍、年龄（项目不变量：不写任何人口描述）。

模块：
  read_reference(images)      每张参考照片一次模型调用（task style_profile），合并成一个 profile：枚举字段取多数、平手取第一张、unknown 不参与；
                              style_words 取并集去重前 6 个。全部失败返回 None（原因记在 runs/style/errors.jsonl），不抛出去。
  listing_profiles()          每套房的挂牌照片读一次（task style_facts），按文件 sha256 缓存在 runs/style_facts.jsonl（格式同 runs/photo_facts.jsonl）。
  match(ref, lp)              权重 floor 30 / palette 25 / kitchen 20 / light 15 / era 10；任一侧 unknown 的属性跳过、权重重新归一；可比属性少于 2 个 → None。
  api_post(body) / api_get(query) / forget(renter)
                              server.py 的 POST / GET /api/style 和 /api/forget 顺手调的清理。结果在 runs/style/<renter>.json，原图在
                              runs/style/uploads/<renter>/（runs/ 不进 git，也不对外提供静态访问）。
跑：python3 src/photo/style.py warm [--force] [--listing L-0002] [--timeout 150]    预读全部挂牌照片（已读过的跳过；--force 重读；接口不稳时放宽预算）
    python3 src/photo/style.py demo --images a.jpg b.jpg             打印参考 profile 和每套房的分数表
环境同 facts.py：.env 里的 NVIDIA_API_KEY / METERLESS_*；NVIDIA_VL_MODEL 默认 nvidia/nemotron-3.5-super-vl-120b-a12b。缩图要 Pillow（requirements-voice.txt 里有）。
"""
from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import io
import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from llm import provider as llm  # noqa: E402

MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"
STATIC_PHOTOS = ROOT / "src" / "voice" / "static" / "qi" / "assets" / "photos"
REAL_PHOTOS = ROOT / "data" / "real" / "photos"
STATIC_URL = "/static/qi/assets/photos/"
REAL_URL = "/real/"
LOG = ROOT / "runs" / "style_facts.jsonl"  # 挂牌照片的读图缓存（同 runs/photo_facts.jsonl 的格式）
STYLE_DIR = ROOT / "runs" / "style"  # <renter>.json、uploads/<renter>/、errors.jsonl
MAX_SIDE = 768  # 送模型前缩到最长边 768（facts.py 的做法；NVIDIA 直连内联 base64 约 180 KB 封顶）
MAX_BYTES = 170 * 1024
TIMEOUT_S = 60.0  # 一张图的总预算（路由用默认；warm --timeout 150 可以更有耐心）
ATTEMPT_S = 25.0  # 单次尝试的上限（最后一次用掉剩下的预算）
TEMPS = (0.0, 0.4, 0.2)  # 每次尝试的温度：先确定性的 0，不回就换个采样路径
MAX_TOKENS = 200  # 回答约 80 token；上限小一点，服务端偶发的不收口生成早点停
MAX_IMAGES = 3
MAX_UPLOAD = 3 * 1024 * 1024  # 解码后每张 ≤ 3 MB
RENTER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # 浏览器的 ht_renter 是 r-<24 hex>；也是 runs/style 下的文件名，所以不许有点和斜杠

ATTRS = ("floor", "palette", "kitchen", "light", "era")
VALUES = {"floor": ("timber", "carpet", "tile", "stone", "concrete"), "palette": ("light", "dark", "warm", "cool", "neutral"),
          "kitchen": ("modern", "classic", "dated"), "light": ("bright", "moderate", "dim"), "era": ("new", "recent", "older")}
WEIGHTS = {"floor": 30, "palette": 25, "kitchen": 20, "light": 15, "era": 10}
SYNONYMS = {"floor": {"wood": "timber", "wooden": "timber", "hardwood": "timber", "floorboards": "timber", "floorboard": "timber", "parquet": "timber",
                      "oak": "timber", "laminate": "timber", "vinyl": "timber", "tiles": "tile", "tiled": "tile", "ceramic": "tile", "porcelain": "tile",
                      "marble": "stone", "terrazzo": "stone", "polished concrete": "concrete", "carpeted": "carpet", "rug": "carpet"},
            "palette": {"white": "light", "pale": "light", "bright": "light", "black": "dark", "moody": "dark", "earthy": "warm", "beige": "warm",
                        "grey": "neutral", "gray": "neutral", "muted": "neutral"},
            "kitchen": {"contemporary": "modern", "new": "modern", "renovated": "modern", "traditional": "classic", "old": "dated", "older": "dated",
                        "worn": "dated", "none": "unknown", "not visible": "unknown", "no kitchen": "unknown"},
            "light": {"light": "bright", "sunny": "bright", "well lit": "bright", "well-lit": "bright", "medium": "moderate", "average": "moderate",
                      "dark": "dim", "low": "dim"},
            "era": {"brand new": "new", "renovated": "new", "modern": "recent", "contemporary": "recent", "old": "older", "dated": "older", "period": "older"}}
PHRASE = {"floor": {"timber": "timber floors", "carpet": "carpet", "tile": "tiled floors", "stone": "stone floors", "concrete": "concrete floors"},
          "palette": {v: f"{v} palette" for v in VALUES["palette"]},
          "kitchen": {v: f"{v} kitchen" for v in VALUES["kitchen"]},
          "light": {"bright": "bright rooms", "moderate": "moderate light", "dim": "dim rooms"},
          "era": {"new": "new finishes", "recent": "recent finishes", "older": "older finishes"}}
MISS = {"floor": "floor is {listing}, your reference is {ref}", "palette": "palette is {listing}, your reference is {ref}",
        "kitchen": "kitchen looks {listing}, your reference is {ref}", "light": "light looks {listing}, your reference is {ref}",
        "era": "finishes look {listing}, your reference is {ref}"}

SYSTEM = """HOMETRUTH_STYLE_V1
You read ONE interior photo for a renter and report only the finishes that are visible. Answer "unknown" for anything the photo does not show. Never describe, count or guess at people, groups, nationality, ethnicity or age; never judge size, value or location.
Reply with ONE JSON object and nothing else:
{"floor": "timber|carpet|tile|stone|concrete|unknown",
 "palette": "light|dark|warm|cool|neutral|unknown",
 "kitchen": "modern|classic|dated|unknown" (unknown unless a kitchen is in view; modern = flat-panel cabinetry, stone benchtops; classic = shaker or timber cabinetry in good order; dated = laminate benchtops, old tiles or cabinetry),
 "light": "bright|moderate|dim|unknown" (natural light in the room),
 "era": "new|recent|older|unknown" (new = just built or renovated; recent = the last decade or so; older = clearly older finishes),
 "style_words": ["up to 4 short lower-case phrases for the decor style, e.g. scandi, minimalist, warm timber, industrial"],
 "one_line": "one short sentence about the finishes and feel of the room, nothing about people"}"""
USER_REF = "This is a photo of a room the renter likes. Fill the JSON for its finishes and style."
USER_LISTING = "This is the lead photo of a rental listing. Fill the JSON for its finishes and style. Caption from the listing: {caption}."

_read_lock = threading.Lock()  # 两位租客同时上传时，缺的挂牌照片只读一遍
NO_RETRY = ("unauthorized", "no_provider", "refused", "model_not_found", "bad_request", "rate_limited")  # 这些再试也一样（429 在 provider 里已重试过一次）
_model_lock = threading.Lock()  # NVIDIA 直连并发两个以上就整批回 500（10-27 实测），所以看图一次只发一张


# ---------------------------------------------------------------- 工具
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _note_error(where: str, err: str, **extra: Any) -> None:
    """模型出错、JSON 解析失败：记一行 runs/style/errors.jsonl，不抛到路由外。"""
    try:
        _append(STYLE_DIR / "errors.jsonl", dict({"ts": now_iso(), "where": where, "error": err[:400]}, **extra))
    except OSError:
        pass


def load_listings() -> List[dict]:
    """mock_matrix.json 里的 listings（别的会话可能正在改这个文件：读到半截就等一下再读一次）。"""
    for attempt in range(3):
        try:
            return json.loads(MATRIX.read_text(encoding="utf-8"))["listings"]
        except (ValueError, KeyError):
            if attempt == 2:
                raise
            time.sleep(0.3)
    return []


def photo_path(L: dict) -> Optional[Path]:
    """listing.photo.url → 文件：/static/qi/assets/photos/<file> 在 src/voice/static/qi/assets/photos/，/real/<id>/prep/NN.jpg 在 data/real/photos/。"""
    p = L.get("photo") or {}
    url = str(p.get("url") or "")
    if url.startswith(STATIC_URL):
        return STATIC_PHOTOS.joinpath(*url[len(STATIC_URL):].split("/"))
    if url.startswith(REAL_URL):
        return REAL_PHOTOS.joinpath(*url[len(REAL_URL):].split("/"))
    f = str(p.get("file") or "")
    if f:
        for base in (STATIC_PHOTOS, REAL_PHOTOS):
            cand = base.joinpath(*f.split("/"))
            if cand.exists():
                return cand
    return None


def image_kind(data: bytes) -> Optional[str]:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def thumb(data: bytes, max_side: int = MAX_SIDE) -> bytes:
    """送模型前缩到最长边 ≤ max_side 的 JPEG，压到 MAX_BYTES 以内（facts.py 的做法；手机照片按 EXIF 转正）。没装 Pillow：够小就原样送。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if len(data) <= MAX_BYTES:
            return data
        raise RuntimeError("Pillow is needed to shrink this photo (pip install pillow)")
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    out = b""
    for q in (85, 80, 75, 70, 62, 55, 45):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        out = buf.getvalue()
        if len(out) <= MAX_BYTES:
            break
    return out


# ---------------------------------------------------------------- 模型：一张图一次调用
def ask_model(image: bytes, task: str, user_text: str, timeout: float = TIMEOUT_S) -> Tuple[dict, "llm.ChatResult", str, str]:
    """一张图问一次模型。路由和 facts.ask_model 一样：先 Nightshift 的视觉路由，被拒（没有视觉车道）或连不上就直连 NVIDIA，走了哪条如实返回。
    预算 timeout 秒内最多 len(TEMPS) 次尝试，每次 ≤ ATTEMPT_S 秒（最后一次用掉剩下的）：超时 / 服务端 500 / 不是 JSON 就换个温度再试
    （10-27 实测：NVIDIA 的看图接口这几天不稳，同一张图有时 2 s 回、有时 60 s 不回或直接 500，和图、提示词无关）。全程串行（_model_lock：
    并发两个以上它整批回 500）。返回 (模型的 JSON, ChatResult, route, Nightshift 拒绝的原因)；都失败抛最后的 llm.LLMError / RuntimeError，调用方兜住。
    测试里 monkeypatch 这个函数。"""
    b64 = base64.b64encode(image).decode("ascii")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": user_text},
                                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    deadline = time.time() + timeout
    provider: Optional[str] = None  # None = 让 provider.py 选（Nightshift 优先）；被拒一次后面的尝试直接 nvidia
    route, reason = "", ""
    last: Optional[Exception] = None

    def chat(prov: Optional[str], temperature: float, per: float) -> "llm.ChatResult":
        return llm.chat(msgs, task=task, provider=prov, vision=True, temperature=temperature, max_tokens=MAX_TOKENS, timeout=max(3.0, per), retries=1)

    with _model_lock:
        for attempt, temperature in enumerate(TEMPS):
            if attempt:
                time.sleep(2.0)
            left = deadline - time.time()
            if left < 10:
                break
            per = left if attempt == len(TEMPS) - 1 else min(ATTEMPT_S, left)
            try:
                try:
                    res = chat(provider, temperature, per)
                except llm.LLMError as e:
                    if provider is not None or e.transport or e.kind == "no_provider":
                        raise
                    reason = f"{e.kind}: {str(e)[:160]}"  # Nightshift 的带类型拒绝（没有视觉车道）：这次和后面的尝试都直连 NVIDIA
                    provider = "nvidia"
                    res = chat(provider, temperature, min(per, deadline - time.time()))
            except llm.LLMError as e:
                last = e
                if e.kind in NO_RETRY:
                    raise
                continue
            if not route:
                route = "nvidia-direct" if res.provider == "nvidia" else "meterless"
                if res.fallback_from:
                    route, reason = "nvidia-direct (fallback)", res.fallback_reason
            obj = _json_object(res.text)
            if obj is None:
                last = RuntimeError(f"model answer was not JSON: {res.text[:200]!r}")
                continue
            res.retries = attempt
            return obj, res, route, reason
    raise last or RuntimeError("no time left for the photo reader")


# ---------------------------------------------------------------- 读数 → 属性
def normalize(obj: Any) -> dict:
    """模型的 JSON → 五个枚举属性（不认识的词按同义表归一，归不了就 unknown）+ style_words（≤ 4，小写）+ one_line。"""
    obj = obj if isinstance(obj, dict) else {}
    out: Dict[str, Any] = {}
    for a in ATTRS:
        v = str(obj.get(a) or "unknown").strip().lower()
        v = re.sub(r"[^a-z -]", "", v).strip()
        if v not in VALUES[a]:
            v = SYNONYMS[a].get(v, "unknown")
        out[a] = v if v in VALUES[a] else "unknown"
    words = obj.get("style_words")
    if isinstance(words, str):
        words = re.split(r"[,;/]", words)
    seen: List[str] = []
    for w in words or []:
        w = re.sub(r"\s+", " ", str(w)).strip().lower()[:40]
        if w and w not in seen:
            seen.append(w)
    out["style_words"] = seen[:4]
    out["one_line"] = re.sub(r"\s+", " ", str(obj.get("one_line") or "")).strip()[:200]
    return out


def merge_profiles(readings: List[dict]) -> dict:
    """几张参考照片 → 一个 profile：枚举字段取多数、平手取最先出现的（第一张）、unknown 不参与；style_words 取并集去重前 6 个。"""
    readings = [normalize(r) for r in readings]
    prof: Dict[str, Any] = {}
    for a in ATTRS:
        counts: Dict[str, int] = {}
        order: List[str] = []
        for r in readings:
            v = r[a]
            if v == "unknown":
                continue
            if v not in counts:
                counts[v] = 0
                order.append(v)
            counts[v] += 1
        prof[a] = max(order, key=lambda v: (counts[v], -order.index(v))) if order else "unknown"
    words: List[str] = []
    for r in readings:
        for w in r["style_words"]:
            if w not in words:
                words.append(w)
    prof["style_words"] = words[:6]
    prof["one_line"] = next((r["one_line"] for r in readings if r["one_line"]), "")
    prof["photos"] = len(readings)
    prof["status"] = "inferred"
    return prof


def match(ref: Optional[dict], lp: Optional[dict]) -> Optional[dict]:
    """参考 profile 对一套房的挂牌照片 profile：相符的属性拿它的权重，任一侧 unknown 的属性不比、权重重新归一；可比属性少于 2 个返回 None。"""
    if not ref or not lp:
        return None
    total = got = n = 0
    reasons: List[str] = []
    misses: List[str] = []
    for a in ATTRS:
        rv, lv = str(ref.get(a) or "unknown"), str(lp.get(a) or "unknown")
        if rv == "unknown" or lv == "unknown":
            continue
        n += 1
        w = WEIGHTS[a]
        total += w
        if rv == lv:
            got += w
            reasons.append(PHRASE[a].get(rv, f"{rv} {a}"))
        else:
            misses.append(MISS[a].format(listing=lv, ref=rv))
    if n < 2 or total <= 0:
        return None
    n_ref = int(ref.get("photos") or 1)
    return {"score": int(100 * got / total + 0.5), "status": "inferred", "reasons": reasons, "misses": misses,
            "basis": f"from {n_ref} reference photo{'s' if n_ref != 1 else ''} and the listing's lead photo", "compared": n}


def chips(profile: dict) -> List[str]:
    """卡片 / 面板上的短语："timber floors · light palette · modern kitchen"。"""
    return [PHRASE[a][profile[a]] for a in ATTRS if profile.get(a) in PHRASE[a]]


# ---------------------------------------------------------------- 参考照片
def _read_one(image: bytes, task: str, user_text: str) -> dict:
    """一张图 → 日志行（成功有 reading，失败有 error）。"""
    t0 = time.time()
    try:
        sent = thumb(image)
        obj, res, route, reason = ask_model(sent, task, user_text)
    except Exception as e:  # 模型出错、不是 JSON、图坏了：记下来，这张不算
        return {"ts": now_iso(), "error": f"{type(e).__name__}: {str(e)[:300]}", "wall_ms": round((time.time() - t0) * 1000)}
    return {"ts": now_iso(), "sha256": sha256(image), "bytes": len(sent), "route": route, "nightshift": reason or None, "provider": res.provider,
            "model": res.model, "served_model": res.served_model or res.model, "ms": res.ms, "wall_ms": round((time.time() - t0) * 1000),
            "reading": obj, "raw": (res.text or "")[:800]}


def read_reference(images: List[bytes]) -> Optional[dict]:
    """每张参考照片一次模型调用（task style_profile，一张接一张），合并成一个 profile；profile["reads"] 是每张的路由 / 模型 / 毫秒。
    全部失败返回 None（原因在 runs/style/errors.jsonl）。"""
    images = list(images)[:MAX_IMAGES]
    if not images:
        return None
    rows = [_read_one(im, "style_profile", USER_REF) for im in images]  # 串行：NVIDIA 直连并发就回 500
    good = [r for r in rows if isinstance(r.get("reading"), dict)]
    for r in rows:
        if r.get("error"):
            _note_error("read_reference", r["error"])
    if not good:
        return None
    prof = merge_profiles([r["reading"] for r in good])
    prof["reads"] = [{k: r.get(k) for k in ("route", "provider", "model", "served_model", "ms", "error")} for r in rows]
    prof["failed"] = len(rows) - len(good)
    return prof


# ---------------------------------------------------------------- 挂牌照片（缓存）
def _log_rows() -> List[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("sha256") and isinstance(row.get("reading"), dict):
            out.append(row)
    return out


def cached_rows() -> Dict[str, dict]:
    """{文件 sha256: 最近一次读图行}。"""
    out: Dict[str, dict] = {}
    for row in _log_rows():
        out[row["sha256"]] = row
    return out


def read_listing(L: dict, path: Path, data: bytes, timeout: float = TIMEOUT_S) -> dict:
    """一套房的挂牌照片问一次模型（task style_facts），追加到 runs/style_facts.jsonl；失败抛出去（调用方决定跳过还是停）。"""
    caption = str((L.get("photo") or {}).get("caption") or "").strip() or "no caption"
    t0 = time.time()
    sent = thumb(data)
    obj, res, route, reason = ask_model(sent, "style_facts", USER_LISTING.format(caption=caption), timeout=timeout)
    try:
        rel = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        rel = path.name
    row = {"ts": now_iso(), "listing": L["id"], "file": rel, "sha256": sha256(data), "bytes": len(sent), "route": route, "nightshift": reason or None,
           "provider": res.provider, "model": res.model, "served_model": res.served_model or res.model, "ms": res.ms,
           "wall_ms": round((time.time() - t0) * 1000), "reading": obj, "raw": (res.text or "")[:800]}
    _append(LOG, row)
    return row


def listing_profiles(read_missing: bool = True, force: bool = False, only: Optional[str] = None, verbose: bool = False,
                     timeout: float = TIMEOUT_S) -> Dict[str, dict]:
    """{listing_id: profile}，profile = normalize(reading) + source（文件、sha256、路由、模型、毫秒、时间）。
    缓存按文件 sha256（runs/style_facts.jsonl）；read_missing 时没读过的现读（force 全部重读）；照片不在盘上或读失败的跳过（verbose 打印）。"""
    out: Dict[str, dict] = {}
    with _read_lock:
        cache = {} if force else cached_rows()
        for L in load_listings():
            lid = L.get("id")
            if not lid or (only and lid != only):
                continue
            path = photo_path(L)
            if path is None or not path.exists():
                if verbose:
                    print(f"style {lid}: no lead photo on disk ({(L.get('photo') or {}).get('url')!r}), skipped")
                continue
            data = path.read_bytes()
            row = cache.get(sha256(data))
            if row is None:
                if not read_missing:
                    continue
                t0 = time.time()
                try:
                    row = read_listing(L, path, data, timeout)
                except Exception as e:
                    _note_error("listing_profiles", f"{type(e).__name__}: {str(e)[:300]}", listing=lid)
                    if verbose:
                        print(f"style {lid} ({path.name}): FAILED after {round((time.time() - t0) * 1000)} ms: {str(e)[:160]}")
                    continue
                if verbose:
                    print(f"style {lid} ({path.name}): via {row['route']} {row['served_model']} in {row['ms']} ms → {json.dumps(normalize(row['reading']), ensure_ascii=False)[:200]}")
            elif verbose:
                print(f"style {lid} ({path.name}): cached ({row.get('ts')}, {row.get('served_model')})")
            prof = normalize(row["reading"])
            prof["source"] = {k: row.get(k) for k in ("file", "sha256", "route", "provider", "model", "served_model", "ms", "ts")}
            prof["source"]["image"] = (L.get("photo") or {}).get("url")
            out[lid] = prof
    return out


# ---------------------------------------------------------------- 路由（server.py 只转调这三个）
def _safe_name(name: Any, i: int, kind: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(name or "")).name).strip("._")[:60] or "photo"
    if not base.lower().endswith((".jpg", ".jpeg", ".png")):
        base += ".jpg" if kind == "jpeg" else ".png"
    return f"{i + 1:02d}-{base}"


def _decode_images(images: Any) -> Tuple[Optional[List[Tuple[str, bytes]]], str]:
    """请求里的 images: [{name, data}] → [(文件名, 原始字节)]；不合规返回 (None, 一句英文说明)。"""
    if not isinstance(images, list) or not images:
        return None, "Send at least one photo (images: [{name, data}], data = base64 JPEG or PNG)."
    if len(images) > MAX_IMAGES:
        return None, f"At most {MAX_IMAGES} photos per upload."
    out: List[Tuple[str, bytes]] = []
    for i, im in enumerate(images):
        if not isinstance(im, dict) or not isinstance(im.get("data"), str):
            return None, f"Photo {i + 1} has no base64 data."
        s = im["data"].strip()
        if s.startswith("data:"):
            s = s.split(",", 1)[1] if "," in s else ""
        s = re.sub(r"\s+", "", s)
        if len(s) > (MAX_UPLOAD * 4 // 3) + 8:
            return None, f"Photo {i + 1} is larger than 3 MB; shrink it first."
        try:
            raw = base64.b64decode(s, validate=True)
        except (ValueError, binascii.Error):
            return None, f"Photo {i + 1} is not valid base64."
        if not raw:
            return None, f"Photo {i + 1} is empty."
        if len(raw) > MAX_UPLOAD:
            return None, f"Photo {i + 1} is larger than 3 MB after decoding; shrink it first."
        kind = image_kind(raw)
        if kind is None:
            return None, f"Photo {i + 1} must be a JPEG or PNG."
        out.append((_safe_name(im.get("name"), i, kind), raw))
    return out, ""


def _result_path(renter: str) -> Path:
    return STYLE_DIR / f"{renter}.json"


def api_post(body: Any) -> Tuple[int, dict]:
    """POST /api/style {renter, images: [{name, data}]} → (HTTP 状态, JSON)。成功：{profile, matches: {listing_id: match}, model, route, ms}。"""
    body = body if isinstance(body, dict) else {}
    renter = str(body.get("renter") or "").strip()
    if not RENTER_RE.match(renter):
        return 400, {"error": "renter is required: the browser's ht_renter id (letters, digits, - and _ only)."}
    images, why = _decode_images(body.get("images"))
    if images is None:
        return 400, {"error": why}
    t0 = time.time()
    up = STYLE_DIR / "uploads" / renter
    try:
        if up.exists():
            shutil.rmtree(up)
        up.mkdir(parents=True, exist_ok=True)
        for name, raw in images:
            (up / name).write_bytes(raw)
    except OSError as e:
        _note_error("api_post.save", str(e), renter=renter)
    profile = read_reference([raw for _, raw in images])
    if profile is None:
        return 502, {"error": "The photo reader is not answering right now; try again in a minute."}
    try:
        lps = listing_profiles(read_missing=True)
    except Exception as e:  # 挂牌照片那边坏了也先把 profile 给出去
        _note_error("api_post.listings", f"{type(e).__name__}: {str(e)[:300]}", renter=renter)
        lps = {}
    matches = {}
    for lid, lp in lps.items():
        m = match(profile, lp)
        if m:
            m["listing_photo"] = lp.get("source", {}).get("image")
            matches[lid] = m
    first = next((r for r in profile.get("reads", []) if r.get("served_model")), {})
    out = {"profile": profile, "matches": matches, "model": first.get("served_model") or first.get("model"), "route": first.get("route"),
           "ms": round((time.time() - t0) * 1000)}
    stored = dict(out, renter=renter, ts=now_iso(), uploads=[name for name, _ in images])
    try:
        STYLE_DIR.mkdir(parents=True, exist_ok=True)
        _result_path(renter).write_text(json.dumps(stored, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError as e:
        _note_error("api_post.store", str(e), renter=renter)
    return 200, out


def api_get(query: Any) -> Tuple[int, dict]:
    """GET /api/style?renter=ID → 存的结果；没有就 {profile: null, matches: {}}。query 是 urllib.parse.parse_qs 的字典或 {renter: str}。"""
    q = query if isinstance(query, dict) else {}
    v = q.get("renter")
    renter = str((v[0] if isinstance(v, list) and v else v) or "").strip()
    if not RENTER_RE.match(renter):
        return 400, {"error": "renter is required: the browser's ht_renter id."}
    p = _result_path(renter)
    if not p.exists():
        return 200, {"profile": None, "matches": {}}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 200, {"profile": None, "matches": {}}
    return 200, {k: obj.get(k) for k in ("profile", "matches", "model", "route", "ms", "ts")}


def forget(renter: Any) -> dict:
    """Forget me 顺手删：runs/style/<renter>.json 和 uploads/<renter>/。"""
    renter = str(renter or "").strip()
    if not RENTER_RE.match(renter):
        return {"style": False, "uploads": 0}
    removed = False
    p = _result_path(renter)
    if p.exists():
        try:
            p.unlink()
            removed = True
        except OSError:
            pass
    up = STYLE_DIR / "uploads" / renter
    n = 0
    if up.is_dir():
        n = sum(1 for f in up.iterdir() if f.is_file())
        shutil.rmtree(up, ignore_errors=True)
    return {"style": removed, "uploads": n}


# ---------------------------------------------------------------- CLI
def warm(force: bool = False, only: Optional[str] = None, timeout: float = TIMEOUT_S) -> Dict[str, dict]:
    t0 = time.time()
    before = {r["sha256"] for r in _log_rows()}
    profs = listing_profiles(read_missing=True, force=force, only=only, verbose=True, timeout=timeout)
    rows = [r for r in _log_rows() if force or r["sha256"] not in before]
    routes = sorted({r["route"] for r in rows})
    models = sorted({r["served_model"] for r in rows})
    print(f"warm: {len(profs)} listings have a style profile, {len(rows)} read now ({sum(r['ms'] for r in rows)} ms model time, "
          f"{round(time.time() - t0, 1)} s wall); route {', '.join(routes) or '-'}; model {', '.join(models) or '-'}; cache {LOG.relative_to(ROOT)}")
    return profs


def demo(paths: List[str]) -> int:
    images = []
    for p in paths:
        data = Path(p).read_bytes()
        if image_kind(data) is None:
            raise SystemExit(f"{p}: not a JPEG or PNG")
        images.append(data)
    t0 = time.time()
    prof = read_reference(images)
    if prof is None:
        print("reference: the photo reader failed for every photo (see runs/style/errors.jsonl)")
        return 1
    print(f"reference ({len(images)} photo{'s' if len(images) != 1 else ''}, {round((time.time() - t0) * 1000)} ms): " +
          " · ".join(chips(prof)) + (f" · words: {', '.join(prof['style_words'])}" if prof["style_words"] else ""))
    print(f"  {json.dumps({a: prof[a] for a in ATTRS})}  one_line: {prof['one_line']}")
    for r in prof["reads"]:
        print(f"  read via {r.get('route')} {r.get('served_model')} in {r.get('ms')} ms" + (f" ERROR {r['error']}" if r.get("error") else ""))
    lps = listing_profiles(read_missing=True, verbose=False)
    by_id = {L["id"]: L for L in load_listings()}
    rows = []
    for lid, lp in lps.items():
        m = match(prof, lp)
        rows.append((lid, m, lp))
    rows.sort(key=lambda t: (-(t[1]["score"] if t[1] else -1), t[0]))
    print(f"\n{'listing':<13} {'address':<28} {'score':>5}  {'listing photo':<58} reasons / misses")
    for lid, m, lp in rows:
        L = by_id.get(lid, {})
        addr = f"{L.get('street', '')}, {L.get('suburb', '')}"[:28]
        lpd = " ".join(f"{a}={lp[a]}" for a in ATTRS)
        if m is None:
            print(f"{lid:<13} {addr:<28} {'-':>5}  {lpd:<58} (fewer than 2 comparable attributes)")
        else:
            print(f"{lid:<13} {addr:<28} {m['score']:>4}%  {lpd:<58} {', '.join(m['reasons']) or '-'}" + (f" | {'; '.join(m['misses'])}" if m["misses"] else ""))
    missing = [lid for lid in by_id if lid not in lps]
    if missing:
        print(f"\nno style profile (photo missing or read failed): {', '.join(missing)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["warm", "demo"])
    ap.add_argument("--images", nargs="+", help="demo：一到三张参考照片")
    ap.add_argument("--listing", help="warm：只读这一套，如 L-0002")
    ap.add_argument("--force", action="store_true", help="warm：已读过的也重读")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S, help=f"warm：每张图的总预算秒数（默认 {TIMEOUT_S:.0f}；接口不稳时给 150，多试一次）")
    a = ap.parse_args()
    llm.load_env()
    if a.step == "warm":
        warm(a.force, a.listing, a.timeout)
        return 0
    if not a.images:
        ap.error("demo needs --images a.jpg [b.jpg c.jpg]")
    return demo(a.images[:MAX_IMAGES])


if __name__ == "__main__":
    sys.exit(main())
