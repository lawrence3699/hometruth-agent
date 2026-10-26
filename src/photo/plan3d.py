#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""玩偶屋（docs/10 第 4 节；10-27）：从户型图"立起来"的近似三维视图的数据层。几何来自户型图（阈值 + 连通域分房间），语义来自看图模型
（编号区域是什么房间、每张照片是哪间），光来自已有的日照几何（前端 static/qi/dollhouse.js 自己算），没有一处是凭空生成。

三步：
  segment(plan)          灰度 → 阈值（墙是深色线；彩色渲染图用更低的阈值）→ 墙线膨胀 2 px 让门弧和窗线合上 → 白色连通域 → 去掉碰到图边的背景
                         和面积 < 0.5% 的碎块 → 每个房间一个多边形（Moore 轮廓追踪 + Douglas–Peucker）、外接框、质心、盖章点。只用 PIL + numpy。
                         调试图 runs/plan3d/<DomainId>_regions.png。
  label(plan, regions)   户型图副本上每个区域盖编号章（facts.stamp 一类的画法），**一次**看图调用（task plan3d_rooms）：每个编号是什么房间、
                         在不在这套房之内、置信度、图上印的尺寸文字（可选，用来校准比例）。提示词只许按图上文字和画法判断，不猜。
  assign(listing, rooms, photos)
                         每张照片归房间：先用 runs/photo_facts.jsonl 里同文件的 reading.room；没有的问一次模型（task plan3d_photo，只问房间类型
                         + 两三个可见特征）；类型对到 rooms（多间卧室按顺序；对不上就 room_id = null）。
路由和 style.py 一样：先 Meterless Nightshift 的视觉路由，没有视觉车道就直连 NVIDIA、走了哪条如实记；串行 + 预算内换温度重试（接口不稳时的做法）。
日志 runs/plan3d_facts.jsonl（字段照 photo_facts.jsonl：ts、listing、file、sha256、route、provider、model、served_model、ms、reading、raw，另加 task）。
输出 data/real/photos/<DomainId>/plan3d.json（server.py 的 /real/<id>/plan3d.json 静态提供；这个目录不进 git，部署时单独传）。

跑：python3 src/photo/plan3d.py build [--listing L-D17153470] [--force | --rebuild] [--reread-photos] [--timeout 150] [--threshold 240]
    python3 src/photo/plan3d.py segment --listing L-D17153470        （不调模型，只出调试图）
    python3 src/photo/plan3d.py show --listing L-D17153470           （打印房间表和照片归属）
环境同 facts.py：.env 里的 NVIDIA_API_KEY / METERLESS_*；NVIDIA_VL_MODEL 默认 nvidia/nemotron-3.5-super-vl-120b-a12b。
"""
from __future__ import annotations

import argparse
import base64
import colorsys
import datetime as dt
import io
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from llm import provider as llm  # noqa: E402
from photo import facts  # noqa: E402

MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"
REAL_PHOTOS = ROOT / "data" / "real" / "photos"
LOG = ROOT / "runs" / "plan3d_facts.jsonl"
DEBUG_DIR = ROOT / "runs" / "plan3d"
PHOTO_LOG = ROOT / "runs" / "photo_facts.jsonl"
PLAN_LOG = ROOT / "runs" / "floorplan_facts.jsonl"
REAL_URL = "/real/"

WORK_SIDE = 1400  # 分割时最长边缩到这个以内（坐标最后换算回原图像素）
DILATE_PX = 2  # 墙线膨胀半径：门弧、窗线是 1–2 px 的细线，膨胀后才闭合
MIN_AREA_FRAC = 0.005  # 小于整图 0.5% 的白块不算房间（字母的洞、ST 小格、指北针）
THRESHOLD_BW = 240  # 黑白线图：不是纸白的都算"线"（门弧 ~200–230、窗线 ~220–230 都要算进墙）
THRESHOLD_RENDER = 185  # 彩色渲染图：地板是米色（~200–215），比它深的是墙、门弧、窗线、家具描边 —— 除了成片的贴图（见 TEXTURE_*）
DARK_RENDER = 110  # 彩色渲染图：比它深的一定是线（墙、描边），不看贴图密度
TEXTURE_DENSITY = 0.5  # 中间调像素 7×7 邻域里中间调占比超过一半 = 贴图（阳台砖、灰色家具面），算地板不算墙
WHITE_RENDER = 245  # 彩色渲染图：纸白（和图边连通的才是"外面"；房间里的白沙发不算）
THICK_PX = 2  # 开运算半径：≤ 4 px 的细线（门弧、窗线、洁具描边、文字）不算"厚墙"，房间长回去时可以越过；厚墙越不过
RENDER_MIDTONE_FRAC = 0.08  # 中间调（120–239）像素占比超过这个 → 当彩色渲染图
SPLIT_R1_FRAC = 0.012  # 第一轮"收缩再长回"的半径（最长边的 1.2%）：门弧末端和墙之间 ≤ 2r 的缝合上，房间才分得开
SPLIT_R2_FRAC = 0.024  # 第二轮（只在一个区域里试）：没画门的门洞（≈ 0.8–0.9 m）也分开；分出来的每块都要够大才采纳
CLUTTER_AREA_FRAC = 0.005  # 墙掩模里不和墙网相连的小块（房间名、尺寸文字、家具描边）：面积 < 0.5% 且
CLUTTER_SIDE_FRAC = 0.12  # 外接框长边 < 最长边的 12% → 当杂物，不算墙（免得文字把房间掐成两半）
NOMINAL_LONG_M = 12.0  # 没有尺寸文字时的名义比例：整套房（室内房间并集）的长边 ≈ 12 m
WALL_H_M = 2.6
POLY_EPS_FRAC = 0.007  # Douglas–Peucker 的容差：最长边的 0.7%（1400 px → 10 px；门弧鼓包两三段就够，墙板少一些画面才清爽）
MAX_SIDE = 1024  # 送模型前的缩图（facts.py 的做法）
MAX_BYTES = 170 * 1024
TIMEOUT_S = 90.0  # 一次看图的总预算（房间调用输出长，比 style.py 的 60 s 宽一点；--timeout 150 更有耐心）
ATTEMPT_S = 40.0
TEMPS = (0.0, 0.4, 0.2)
NO_RETRY = ("unauthorized", "no_provider", "refused", "model_not_found", "bad_request", "rate_limited")
_model_lock = threading.Lock()  # NVIDIA 直连并发两个以上整批回 500（10-27 实测），看图一次只发一张

ROOM_TYPES = ("living", "dining", "kitchen", "bedroom 1", "bedroom 2", "bedroom 3", "bedroom 4", "bathroom", "ensuite", "laundry", "hall",
              "balcony", "courtyard", "garage", "storage", "outside", "unknown")
LABELS = {"living": "Living", "dining": "Dining", "kitchen": "Kitchen", "bathroom": "Bathroom", "ensuite": "Ensuite", "laundry": "Laundry",
          "hall": "Hall", "balcony": "Balcony", "courtyard": "Courtyard", "garage": "Garage", "storage": "Storage", "outside": "Outside", "unknown": "Unknown"}
SYNONYMS = {"living room": "living", "lounge": "living", "living/dining": "living", "living & dining": "living", "living and dining": "living",
            "family": "living", "dining room": "dining", "meals": "dining", "kitchenette": "kitchen", "bed": "bedroom 1", "bedroom": "bedroom 1",
            "master bedroom": "bedroom 1", "bed 1": "bedroom 1", "bed 2": "bedroom 2", "bed 3": "bedroom 3", "bed 4": "bedroom 4", "bath": "bathroom",
            "wc": "bathroom", "toilet": "bathroom", "bath/laundry": "bathroom", "bath/l'dry": "bathroom", "l'dry": "laundry", "entry": "hall",
            "entrance": "hall", "corridor": "hall", "hallway": "hall", "foyer": "hall", "terrace": "balcony", "deck": "balcony", "patio": "courtyard",
            "yard": "courtyard", "garden": "courtyard", "carspace": "garage", "car space": "garage", "carport": "garage", "parking": "garage",
            "lock-up garage": "garage", "robe": "storage", "wardrobe": "storage", "store": "storage", "st": "storage", "linen": "storage", "lin": "storage",
            "cupboard": "storage", "pantry": "storage", "study": "living", "exterior": "outside", "street": "outside", "common": "outside", "legend": "outside",
            "other": "unknown", "none": "unknown", "null": "unknown"}
PHOTO_ROOMS = ("living", "dining", "kitchen", "bedroom", "bathroom", "laundry", "hall", "balcony", "courtyard", "garage", "exterior", "other")
PHOTO_SYNONYMS = {"living room": "living", "lounge": "living", "living/dining": "living", "dining room": "dining", "bed": "bedroom", "bath": "bathroom",
                  "toilet": "bathroom", "ensuite": "bathroom", "entry": "hall", "hallway": "hall", "corridor": "hall", "terrace": "balcony", "deck": "balcony",
                  "patio": "courtyard", "garden": "courtyard", "yard": "courtyard", "carspace": "garage", "car space": "garage", "parking": "garage",
                  "building": "exterior", "street": "exterior", "facade": "exterior", "outside": "exterior", "unknown": "other", "none": "other"}
# 照片类型 → 户型图房间类型的候选顺序（开放式厨房常和客厅分不开：没有 kitchen 区域就放到 dining、再到 living）
PHOTO_TO_ROOM = {"living": ("living", "dining"), "dining": ("dining", "living"), "kitchen": ("kitchen", "dining", "living"), "bathroom": ("bathroom", "ensuite"),
                 "laundry": ("laundry", "bathroom"), "hall": ("hall",), "balcony": ("balcony", "courtyard"), "courtyard": ("courtyard", "balcony"), "garage": ("garage",)}

SYSTEM_ROOMS = """HOMETRUTH_PLAN3D_ROOMS_V1
You read ONE floor plan image from a Sydney rental listing. A program has stamped numbered circles on it, one per white region it found. For EACH number say what that region is, using only the printed labels and the drawing (fixtures, furniture symbols, door swings). Never guess: a region with no label and no clear fixture is "unknown".
Reply with ONE JSON object and nothing else:
{"regions": [{"id": 1,
   "room": "living|dining|kitchen|bedroom 1|bedroom 2|bedroom 3|bathroom|ensuite|laundry|hall|balcony|courtyard|garage|storage|outside|unknown",
   "label_text": "the printed label inside or beside the region, exactly as printed, else null",
   "dims_text": "the printed dimensions for that region such as 4.4 x 3.6m, else null",
   "inside": true or false,
   "confidence": "high|medium|low"}, ...],
 "one_line": "one short sentence on what the plan shows"}
Rules: BED / BEDROOM or a bed symbol = bedroom (keep the printed number; one bedroom without a number = bedroom 1); LIVING, LIVING/DINING, LOUNGE or a sofa = living; DINING or a dining table on its own = dining; KITCHEN or a cooktop, sink and benches = kitchen; BATH, WC or a toilet, shower or bath = bathroom (ensuite only if it opens from a bedroom alone; BATH/L'DRY = bathroom); LAUNDRY, L'DRY or a washing machine = laundry; ENTRY, HALL, a corridor or any long narrow region that only connects other rooms = hall (even if a bedroom label is printed next to it); BALCONY, TERRACE = balcony; COURTYARD, GARDEN = courtyard; GARAGE, CARSPACE, CAR SPACE, CARPORT = garage; ST, STORE, ROBE, LIN, PANTRY = storage; a region between the outer wall and the page edge, a legend, a logo or the compass = outside.
If one region covers several printed labels (an open-plan area such as LIVING + DINING + KITCHEN), answer living and put all of its labels in label_text.
inside = true only when the region is part of this home's own living space (rooms, hall, balcony, courtyard); false for garage, car space, common corridors, outside, legend, unknown."""
USER_ROOMS = "This floor plan has {n} numbered regions: {ids}. Fill the JSON with one entry per number, in order. Listing: {caption}."

SYSTEM_PHOTO = """HOMETRUTH_PLAN3D_PHOTO_V1
You read ONE photo from a Sydney rental listing and say which kind of room it shows, from what is visible only. Never describe people, never guess at size, light or value.
Reply with ONE JSON object and nothing else:
{"room": "living|dining|kitchen|bedroom|bathroom|laundry|hall|balcony|courtyard|garage|exterior|other",
 "features": ["two or three visible features, lower case, e.g. sliding door, ceiling fan, purple cabinets"],
 "confidence": "high|medium|low"}"""
USER_PHOTO = "Which room is this listing photo? Caption from the listing: {caption}."


# ---------------------------------------------------------------- 工具
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def domain_id(listing: dict) -> Optional[str]:
    """L-D17153470 → 17153470（也认 source.listing_id、floorplan.url 里的目录名）。"""
    m = re.fullmatch(r"L-D(\d+)", str(listing.get("id") or ""))
    if m:
        return m.group(1)
    src = listing.get("source") or {}
    if src.get("listing_id"):
        return str(src["listing_id"])
    m = re.match(r"/real/(\d+)/", str((listing.get("floorplan") or {}).get("url") or ""))
    return m.group(1) if m else None


def real_path(url: str) -> Optional[Path]:
    """/real/17153470/prep/07.jpg → data/real/photos/17153470/prep/07.jpg（只认这个目录）。"""
    if not str(url).startswith(REAL_URL):
        return None
    p = (REAL_PHOTOS / url[len(REAL_URL):]).resolve()
    return p if REAL_PHOTOS.resolve() in p.parents else None


def file_key(url: str) -> str:
    """photo_facts.jsonl 的 file 字段：/real/17153470/prep/01.jpg → 17153470/prep/01.jpg。"""
    return url[len(REAL_URL):] if str(url).startswith(REAL_URL) else str(url)


def load_matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def listing_by_id(listing_id: str, matrix: Optional[dict] = None) -> Optional[dict]:
    m = matrix or load_matrix()
    return next((L for L in m["listings"] if L["id"] == listing_id), None)


def listings_with_plans(matrix: Optional[dict] = None) -> List[dict]:
    m = matrix or load_matrix()
    return [L for L in m["listings"] if (L.get("floorplan") or {}).get("url") and real_path(L["floorplan"]["url"])]


def _read_log(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("reading"), dict):
            out.append(row)
    return out


def photo_facts_by_file(listing_id: str) -> Dict[str, dict]:
    """runs/photo_facts.jsonl 里这套房每个文件最近一次读图。"""
    out: Dict[str, dict] = {}
    for row in _read_log(PHOTO_LOG):
        if row.get("listing") == listing_id and row.get("file"):
            out[row["file"]] = row
    return out


def plan_facts(listing_id: str) -> Optional[dict]:
    rows = [r for r in _read_log(PLAN_LOG) if r.get("listing") == listing_id]
    return rows[-1] if rows else None


def north_deg(listing_id: str, reading: Optional[dict] = None) -> Optional[float]:
    """指北针在页面上指哪（up=0、right=90、down=180、left=270，斜的 45 的倍数）；户型图没读过或没指北针 → None。"""
    if reading is None:
        row = plan_facts(listing_id)
        reading = row["reading"] if row else None
    if not reading:
        return None
    na = reading.get("north_arrow") or {}
    from photo.floorplan import PAGE_DEG
    pts = str(na.get("points") or "null")
    if not na.get("present") or pts not in PAGE_DEG:
        return None
    return float(PAGE_DEG[pts])


# ---------------------------------------------------------------- segment：阈值 + 连通域
def is_rendered(gray) -> bool:
    """中间调像素多 = 彩色渲染图（地板有颜色、家具有贴图）；否则是黑白线图。"""
    import numpy as np
    h = np.bincount(gray.ravel(), minlength=256) / float(gray.size)
    return bool(h[120:240].sum() > RENDER_MIDTONE_FRAC)


def auto_threshold(gray) -> int:
    """黑白线图用 240（不是纸白的都是线）；彩色渲染图用 110（只把深色当墙，地板和砖都算房间）。"""
    return THRESHOLD_RENDER if is_rendered(gray) else THRESHOLD_BW


def erode(mask, r: int):
    """4 邻域二值腐蚀 r 次（图边外当作和边上一样，碰边的白区腐蚀后还碰边）。"""
    m = mask.copy()
    for _ in range(max(0, r)):
        n = m.copy()
        n[1:, :] &= m[:-1, :]
        n[:-1, :] &= m[1:, :]
        n[:, 1:] &= m[:, :-1]
        n[:, :-1] &= m[:, 1:]
        m = n
    return m


def dilate(mask, r: int):
    m = mask.copy()
    for _ in range(max(0, r)):
        n = m.copy()
        n[1:, :] |= m[:-1, :]
        n[:-1, :] |= m[1:, :]
        n[:, 1:] |= m[:, :-1]
        n[:, :-1] |= m[:, 1:]
        m = n
    return m


def grow(labels, allowed, max_iter: int):
    """把标签从核心一圈圈长回 allowed 里没标签的像素（先到先得），直到填满或 max_iter 轮。"""
    import numpy as np
    lab = labels.copy()
    for _ in range(max_iter):
        changed = False
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.zeros_like(lab)
            if dy == 1:
                src[1:, :] = lab[:-1, :]
            elif dy == -1:
                src[:-1, :] = lab[1:, :]
            elif dx == 1:
                src[:, 1:] = lab[:, :-1]
            else:
                src[:, :-1] = lab[:, 1:]
            cand = (lab == 0) & allowed & (src != 0)
            if cand.any():
                lab[cand] = src[cand]
                changed = True
        if not changed:
            break
    return lab


def declutter(wall, long_side: int):
    """墙掩模里的小块（文字、家具描边、指北针）不算墙：面积 < 0.5% 且外接框长边 < 12% 最长边。门弧连着门铰链所在的墙，不会被去掉。"""
    import numpy as np
    labels, st = components(wall)
    H, W = wall.shape
    small = [k for k, v in st.items() if v["area"] < CLUTTER_AREA_FRAC * W * H and max(v["x1"] - v["x0"], v["y1"] - v["y0"]) < CLUTTER_SIDE_FRAC * long_side]
    if not small:
        return wall
    return wall & ~np.isin(labels, small)


def _sq(mask, r: int, grow_: bool):
    """方形结构元的膨胀 / 腐蚀（PIL 的 Max / MinFilter，C 实现，小半径够快）。"""
    import numpy as np
    from PIL import Image, ImageFilter
    if r <= 0:
        return mask.copy()
    im = Image.fromarray((mask * 255).astype(np.uint8), "L")
    im = im.filter(ImageFilter.MaxFilter(2 * r + 1) if grow_ else ImageFilter.MinFilter(2 * r + 1))
    return np.asarray(im) > 0


def dilate_sq(mask, r: int):
    return _sq(mask, r, True)


def erode_sq(mask, r: int):
    return _sq(mask, r, False)


def texture_mask(gray, lo: int, hi: int):
    """彩色渲染图：中间调像素里邻域密度高的（成片的砖、灰色家具面）→ 贴图，算地板；稀疏的（窗线、门弧）→ 线，算墙。"""
    import numpy as np
    from PIL import Image, ImageFilter
    mid = (gray >= lo) & (gray < hi)
    dens = np.asarray(Image.fromarray((mid * 255).astype(np.uint8), "L").filter(ImageFilter.BoxBlur(3))) / 255.0
    return mid & (dens > TEXTURE_DENSITY)


def _absorb_small(labels, allowed, min_area: float, max_iter: int):
    """小于 min_area 的块从最小的开始逐个清掉、让邻居长进去（细线挡不住，厚墙挡得住；墙围死的小格没人能长进去就留空）。"""
    import numpy as np
    while True:
        ids, counts = np.unique(labels, return_counts=True)
        small = sorted(((c, i) for i, c in zip(ids.tolist(), counts.tolist()) if i != 0 and c < min_area))
        if not small:
            return labels
        _, victim = small[0]
        labels = grow(np.where(labels == victim, 0, labels), allowed, max_iter)  # 没人长得进去的（墙围死的小格）就此留空


def split_regions(free_in, allowed, r1: int, r2: int, min_area: float):
    """房间 = 自由区（线以外）收缩 r1 后的连通核心长回去（长的时候只有厚墙挡得住，门弧 / 窗线 / 洁具描边这种细线两边的核心各长各的，在线上碰头）；
    每块再收缩 r2 试一次（没画门的门洞也断开），离所有核心都远的大块（走廊、门厅）也算一块；不够 min_area 的块被邻居吸收。
    返回 labels（0 = 不是房间）。"""
    import numpy as np
    cores, _ = components(erode(free_in, r1))
    labels = _absorb_small(grow(cores, allowed, 3 * r1 + 60), allowed, min_area, 3 * r1 + 60)
    out = np.zeros_like(labels)
    nxt = 1
    for lab in np.unique(labels):
        if lab == 0:
            continue
        region = labels == lab
        area = int(region.sum())
        if area < min_area:
            continue
        sub, st = components(erode(region & free_in, r2))
        big = [k for k, v in st.items() if v["area"] >= 0.25 * min_area]
        if len(big) >= 2:
            sub = np.where(np.isin(sub, big), sub, 0)
            left = region & ~dilate(sub > 0, r2 + 2)
            ll, lst = components(left)
            k = int(sub.max()) + 1
            for ln, v in lst.items():
                if v["area"] >= min_area:
                    sub[ll == ln] = k
                    k += 1
            grown = _absorb_small(grow(sub, region, 3 * r2 + 60), region, min_area, 3 * r2 + 60)
            parts = [int(x) for x in np.unique(grown) if x != 0]
            if len(parts) >= 2:
                for k in parts:
                    out[grown == k] = nxt
                    nxt += 1
                continue
        out[region] = nxt
        nxt += 1
    return out


def components(mask) -> Tuple[Any, Dict[int, dict]]:
    """4 连通的连通域：游程 + 并查集（纯 Python 只循环游程，不循环像素）。返回 (labels 数组, {label: {area, x0, y0, x1, y1, border}})。"""
    import numpy as np
    H, W = mask.shape
    parent: List[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    m8 = mask.astype(np.int8)
    rows: List[List[Tuple[int, int, int]]] = []
    prev: List[Tuple[int, int, int]] = []
    for y in range(H):
        d = np.diff(np.concatenate(([0], m8[y], [0])))
        xs0 = np.flatnonzero(d == 1).tolist()
        xs1 = np.flatnonzero(d == -1).tolist()
        cur = []
        for x0, x1 in zip(xs0, xs1):
            idx = len(parent)
            parent.append(idx)
            cur.append((x0, x1, idx))
        i = j = 0
        while i < len(prev) and j < len(cur):
            p0, p1, pi = prev[i]
            c0, c1, ci = cur[j]
            if p0 < c1 and c0 < p1:
                union(pi, ci)
            if p1 < c1:
                i += 1
            else:
                j += 1
        rows.append(cur)
        prev = cur
    labels = np.zeros((H, W), np.int32)
    roots: Dict[int, int] = {}
    stats: Dict[int, dict] = {}
    for y, cur in enumerate(rows):
        for x0, x1, idx in cur:
            r = find(idx)
            lab = roots.get(r)
            if lab is None:
                lab = roots[r] = len(roots) + 1
                stats[lab] = {"area": 0, "x0": x0, "y0": y, "x1": x1 - 1, "y1": y, "border": False}
            labels[y, x0:x1] = lab
            st = stats[lab]
            st["area"] += x1 - x0
            if x0 < st["x0"]:
                st["x0"] = x0
            if x1 - 1 > st["x1"]:
                st["x1"] = x1 - 1
            st["y1"] = y
            if y == 0 or y == H - 1 or x0 == 0 or x1 == W:
                st["border"] = True
    return labels, stats


_DIRS = [(0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1)]  # (dy, dx)：W NW N NE E SE S SW，顺时针


def trace_contour(m) -> List[Tuple[int, int]]:
    """Moore 邻域轮廓追踪（m 是四周留 1 px 假边的布尔数组）。返回外轮廓像素 [(x, y), …]。"""
    import numpy as np
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return []
    sy, sx = int(ys[0]), int(xs[0])
    start = (sy, sx)
    cur, back = start, (sy, sx - 1)
    out = [(sx, sy)]
    limit = 4 * (m.shape[0] + m.shape[1]) * 4 + 16
    for _ in range(limit):
        i = _DIRS.index((back[0] - cur[0], back[1] - cur[1]))
        nxt = None
        for k in range(1, 9):
            dy, dx = _DIRS[(i + k) % 8]
            ny, nx = cur[0] + dy, cur[1] + dx
            if m[ny, nx]:
                pdy, pdx = _DIRS[(i + k - 1) % 8]
                nxt, back = (ny, nx), (cur[0] + pdy, cur[1] + pdx)
                break
        if nxt is None:
            break
        cur = nxt
        if cur == start and back == (sy, sx - 1):
            break
        out.append((cur[1], cur[0]))
    return out


def simplify(points: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    """Douglas–Peucker（迭代版），闭合多边形：先按离第一个点最远的点切成两段。"""
    if len(points) < 4:
        return list(points)

    def dist(p, a, b) -> float:
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        qx, qy = ax + t * dx, ay + t * dy
        return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5

    def dp(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        keep = [False] * len(pts)
        keep[0] = keep[-1] = True
        stack = [(0, len(pts) - 1)]
        while stack:
            a, b = stack.pop()
            if b - a < 2:
                continue
            best, bi = 0.0, -1
            for i in range(a + 1, b):
                d = dist(pts[i], pts[a], pts[b])
                if d > best:
                    best, bi = d, i
            if best > eps:
                keep[bi] = True
                stack.append((a, bi))
                stack.append((bi, b))
        return [p for p, k in zip(pts, keep) if k]

    p0 = points[0]
    far = max(range(1, len(points)), key=lambda i: (points[i][0] - p0[0]) ** 2 + (points[i][1] - p0[1]) ** 2)
    first = dp(points[: far + 1])
    second = dp(points[far:] + [points[0]])
    out = first[:-1] + second[:-1]
    cleaned: List[Tuple[float, float]] = []
    for p in out:
        if not cleaned or abs(p[0] - cleaned[-1][0]) + abs(p[1] - cleaned[-1][1]) > 0.5:
            cleaned.append(p)
    if len(cleaned) > 1 and abs(cleaned[0][0] - cleaned[-1][0]) + abs(cleaned[0][1] - cleaned[-1][1]) <= 0.5:
        cleaned.pop()
    return cleaned


def anchor_point(region_mask, cx: float, cy: float) -> Tuple[int, int]:
    """盖章点：房间名通常印在正中，所以先试质心往左上 / 右上 / 左下 / 右下偏 28%（章不盖住字，模型才读得到名字和尺寸），
    要求偏移点和它周围 ±5 px 都在区域里；都不行就用质心；L 形房间质心可能落在墙上 → 用质心所在行最长的一段的中点（再不行逐行找）。"""
    import numpy as np
    H, W = region_mask.shape
    x, y = int(round(cx)), int(round(cy))
    ys, xs = np.nonzero(region_mask)
    if len(ys):
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            px, py = int(round(cx + sx * 0.28 * bw)), int(round(cy + sy * 0.28 * bh))
            if 5 <= px < W - 5 and 5 <= py < H - 5 and region_mask[py - 5:py + 6, px - 5:px + 6].all():
                return px, py
    if 0 <= y < H and 0 <= x < W and region_mask[y, x]:
        return x, y
    order = sorted(range(H), key=lambda r: abs(r - y))
    for r in order:
        row = region_mask[r]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        xs0, xs1 = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        k = int(np.argmax(xs1 - xs0))
        return int((xs0[k] + xs1[k] - 1) // 2), r
    return x, y


def segment(plan_path: Path, threshold: Optional[int] = None, dilate_px: int = DILATE_PX, min_area_frac: float = MIN_AREA_FRAC,
            debug_png: Optional[Path] = None) -> dict:
    """户型图 → 候选房间区域。返回 {width, height, threshold, regions:[{id, area_px, bbox:[x,y,w,h], centroid:[x,y], anchor:[x,y], polygon:[[x,y],…]}]}，
    坐标都是原图像素。区域按阅读顺序编号（先上后下、再左右）。"""
    import numpy as np
    from PIL import Image, ImageFilter
    plan_path = Path(plan_path)
    img = Image.open(plan_path).convert("L")
    W0, H0 = img.size
    work = img.copy()
    work.thumbnail((WORK_SIDE, WORK_SIDE))
    W, H = work.size
    back = W0 / float(W)  # 工作图 → 原图
    gray = np.asarray(work)
    rendered = is_rendered(gray)
    T = int(threshold) if threshold else auto_threshold(gray)
    if rendered:  # 地板有颜色：深色和稀疏的中间调线是墙，成片的中间调贴图（阳台砖）是地板，纸白才可能是外面
        wall_raw = (gray < T) & ~texture_mask(gray, DARK_RENDER, T)
        white = gray >= WHITE_RENDER
    else:  # 黑白线图：不是纸白的都是线
        wall_raw = gray < T
        white = ~wall_raw
    wall = declutter(dilate_sq(wall_raw, dilate_px), max(W, H))
    thick = dilate_sq(dilate_sq(erode_sq(wall_raw, THICK_PX), THICK_PX), dilate_px)  # 开运算去掉细线，剩厚墙
    # "外面" = 和图边连通的纸白（先收几个像素把细线上的断点封住，再放回去）；彩色渲染图的地板不是纸白，所以不会被当成外面
    wl, wst = components(erode_sq(white, dilate_px + 1))
    border_labs = [k for k, v in wst.items() if v["border"]]
    outside = dilate_sq(np.isin(wl, border_labs), dilate_px + 1) if border_labs else np.zeros_like(white)
    free = ~wall & ~outside
    fl, fst = components(free)  # 还碰到图边的白块（图下方说明文字行间的空白）也不是房间
    edge = [k for k, v in fst.items() if v["border"]]
    if edge:
        free &= ~np.isin(fl, edge)
    allowed = ~thick & ~outside
    min_area = min_area_frac * W * H
    r1 = max(3, int(round(SPLIT_R1_FRAC * max(W, H))))
    r2 = max(r1 + 2, int(round(SPLIT_R2_FRAC * max(W, H))))
    labels = split_regions(free, allowed, r1, r2, min_area)
    stats = {}
    for lab in np.unique(labels):
        if lab == 0:
            continue
        ys, xs = np.nonzero(labels == lab)
        stats[int(lab)] = {"area": int(len(ys)), "x0": int(xs.min()), "y0": int(ys.min()), "x1": int(xs.max()), "y1": int(ys.max()), "border": False}
    keep = [(lab, st) for lab, st in stats.items() if st["area"] >= min_area]
    eps = max(2.0, POLY_EPS_FRAC * max(W, H))
    regions = []
    for lab, st in keep:
        x0, y0, x1, y1 = st["x0"], st["y0"], st["x1"], st["y1"]
        sub = labels[y0:y1 + 1, x0:x1 + 1] == lab
        ys, xs = np.nonzero(sub)
        cx, cy = float(xs.mean()) + x0, float(ys.mean()) + y0
        ax, ay = anchor_point(sub, cx - x0, cy - y0)
        padded = np.zeros((sub.shape[0] + 2, sub.shape[1] + 2), bool)
        padded[1:-1, 1:-1] = sub
        contour = [(x + x0 - 1, y + y0 - 1) for x, y in trace_contour(padded)]
        poly = simplify([(float(x), float(y)) for x, y in contour], eps) if len(contour) >= 4 else [(float(x0), float(y0)), (float(x1), float(y0)), (float(x1), float(y1)), (float(x0), float(y1))]
        if len(poly) < 3:
            poly = [(float(x0), float(y0)), (float(x1), float(y0)), (float(x1), float(y1)), (float(x0), float(y1))]
        regions.append({"_label": lab, "area_px": int(round(st["area"] * back * back)),
                        "bbox": [int(round(x0 * back)), int(round(y0 * back)), int(round((x1 - x0 + 1) * back)), int(round((y1 - y0 + 1) * back))],
                        "centroid": [round(cx * back, 1), round(cy * back, 1)], "anchor": [int(round((ax + x0) * back)), int(round((ay + y0) * back))],
                        "polygon": [[round(x * back, 1), round(y * back, 1)] for x, y in poly]})
    band = max(1.0, H0 / 10.0)  # 阅读顺序：按十分之一图高分带，带内从左到右
    regions.sort(key=lambda r: (int(r["centroid"][1] // band), r["centroid"][0]))
    for i, r in enumerate(regions, 1):
        r["id"] = i
    out = {"plan_file": str(plan_path), "width": W0, "height": H0, "threshold": T, "rendered": rendered, "dilate_px": dilate_px, "min_area_frac": min_area_frac,
           "split_r_px": [int(round(r1 * back)), int(round(r2 * back))], "regions": regions}
    if debug_png:
        _debug_image(plan_path, labels, regions, back, debug_png)
    for r in regions:
        r.pop("_label", None)
    return out


def _palette(n: int) -> List[Tuple[int, int, int]]:
    out = []
    for i in range(max(1, n)):
        r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.55, 0.95)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


def _debug_image(plan_path: Path, labels, regions: List[dict], back: float, dest: Path) -> None:
    """每个区域填一种颜色（半透明盖在原图上）并写编号。"""
    import numpy as np
    from PIL import Image, ImageDraw
    base = Image.open(plan_path).convert("RGB")
    H, W = labels.shape
    overlay = np.zeros((H, W, 4), np.uint8)
    cols = _palette(len(regions))
    for r, col in zip(regions, cols):
        m = labels == r["_label"]
        overlay[m] = (col[0], col[1], col[2], 110)
    ov = Image.fromarray(overlay, "RGBA").resize(base.size, Image.NEAREST)
    out = Image.alpha_composite(base.convert("RGBA"), ov)
    draw = ImageDraw.Draw(out)
    rad = max(12, int(min(base.size) * 0.022))
    font = facts._font(int(rad * 1.3))
    for r in regions:
        x, y = r["anchor"]
        draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(30, 30, 30, 230), outline=(255, 255, 255, 255), width=2)
        txt = str(r["id"])
        bb = draw.textbbox((0, 0), txt, font=font)
        draw.text((x - (bb[2] - bb[0]) / 2 - bb[0], y - (bb[3] - bb[1]) / 2 - bb[1]), txt, font=font, fill=(255, 255, 255, 255))
        pts = [tuple(p) for p in r["polygon"]]
        if len(pts) >= 3:
            draw.polygon(pts, outline=(200, 30, 30, 255))
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.convert("RGB").save(dest)


# ---------------------------------------------------------------- label：盖编号章，问一次模型
def stamped_image(plan_path: Path, regions: List[dict]) -> bytes:
    """户型图缩到 ≤ 1024 并在每个区域的盖章点画一个带编号的圆章（facts.stamp 那种深底白字），压到 ≤ 170 KB 的 JPEG。"""
    from PIL import Image, ImageDraw
    img = Image.open(plan_path).convert("RGB")
    W0 = img.size[0]
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    s = img.size[0] / float(W0)
    draw = ImageDraw.Draw(img)
    rad = max(11, int(min(img.size) * 0.021))
    font = facts._font(int(rad * 1.35))
    for r in regions:
        x, y = r["anchor"][0] * s, r["anchor"][1] * s
        draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(178, 34, 34), outline=(255, 255, 255), width=2)
        txt = str(r["id"])
        bb = draw.textbbox((0, 0), txt, font=font)
        draw.text((x - (bb[2] - bb[0]) / 2 - bb[0], y - (bb[3] - bb[1]) / 2 - bb[1]), txt, font=font, fill=(255, 255, 255))
    data = b""
    for q in (88, 85, 80, 75, 70, 62, 55):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_BYTES:
            break
    return data


def ask_model(image: bytes, task: str, system: str, user_text: str, max_tokens: int, timeout: float = TIMEOUT_S) -> Tuple[dict, llm.ChatResult, str, str]:
    """一张图问一次模型（style.ask_model 的做法）：先 Nightshift 的视觉路由，被拒（没有视觉车道）或连不上就直连 NVIDIA，走了哪条如实返回；
    预算 timeout 秒内最多 len(TEMPS) 次尝试，超时 / 服务端 500 / 不是 JSON 就换个温度再试；全程串行。返回 (模型的 JSON, ChatResult, route, 拒绝原因)。"""
    b64 = base64.b64encode(image).decode("ascii")
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": [{"type": "text", "text": user_text},
                                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    deadline = time.time() + timeout
    provider: Optional[str] = None
    route, reason = "", ""
    last: Optional[Exception] = None

    def chat(prov: Optional[str], temperature: float, per: float) -> llm.ChatResult:
        return llm.chat(msgs, task=task, provider=prov, vision=True, temperature=temperature, max_tokens=max_tokens, timeout=max(3.0, per), retries=1)

    with _model_lock:
        for attempt, temperature in enumerate(TEMPS):
            if attempt:
                time.sleep(3.0 + 5.0 * attempt)  # NVIDIA 的看图接口整段时间回 500 时，隔几秒再试才有用（10-26/27 实测）
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
                    reason = f"{e.kind}: {str(e)[:160]}"
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
            obj = facts._json_object(res.text)
            if obj is None:
                last = RuntimeError(f"model answer was not JSON: {res.text[:200]!r}")
                continue
            res.retries = attempt
            return obj, res, route, reason
    raise last or RuntimeError("no time left for the plan reader")


def _log(listing_id: str, task: str, file: str, image: bytes, obj: dict, res: llm.ChatResult, route: str, reason: str, wall_ms: int) -> dict:
    row = {"ts": now_iso(), "task": task, "listing": listing_id, "file": file, "sha256": facts.sha256(image), "bytes": len(image), "route": route,
           "nightshift": reason or None, "provider": res.provider, "model": res.model, "served_model": res.served_model or res.model, "ms": res.ms,
           "wall_ms": wall_ms, "retries": res.retries, "reading": obj, "raw": res.text[:1500]}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def cached(task: str, sha: str) -> Optional[dict]:
    """同一张图、同一个 task 最近一次成功的读图（--force 时不看）。"""
    rows = [r for r in _read_log(LOG) if r.get("task") == task and r.get("sha256") == sha]
    return rows[-1] if rows else None


def norm_room(v: Any) -> str:
    s = re.sub(r"\s+", " ", str(v or "").strip().lower()).strip(" .")
    if s in ROOM_TYPES:
        return s
    if s in SYNONYMS:
        return SYNONYMS[s]
    m = re.match(r"^(?:bed(?:room)?)\s*(\d)$", s)
    if m:
        return f"bedroom {m.group(1)}"
    for k in ("living", "dining", "kitchen", "bath", "laundry", "hall", "balcony", "courtyard", "garage", "robe", "stor", "outside"):
        if k in s:
            return {"bath": "bathroom", "robe": "storage", "stor": "storage"}.get(k, k)
    return "unknown"


def norm_conf(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in ("high", "medium", "low") else "low"


def _bedroom_label(t: str) -> str:
    m = re.match(r"bedroom (\d)", t)
    return f"Bedroom {m.group(1)}" if m else LABELS.get(t, t.title())


def rooms_from_reading(regions: List[dict], reading: dict, read_by: str) -> List[dict]:
    """模型的 JSON + 分割区域 → rooms。模型没提到的编号 → unknown / low；同类型嵌套的区域（车库里的车、客厅里的沙发框）合并进大的那个。"""
    answers: Dict[int, dict] = {}
    for item in reading.get("regions") or []:
        if not isinstance(item, dict):
            continue
        try:
            rid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        answers[rid] = item
    rooms = []
    for r in regions:
        a = answers.get(r["id"], {})
        t = norm_room(a.get("room"))
        inside = a.get("inside")
        if not isinstance(inside, bool):
            inside = t not in ("garage", "outside", "unknown")
        if t in ("garage", "outside"):
            inside = False
        rooms.append({"id": r["id"], "label": _bedroom_label(t), "type": t, "inside": inside, "polygon": r["polygon"], "bbox": r["bbox"],
                      "centroid": r["centroid"], "anchor": r["anchor"], "area_px": r["area_px"], "confidence": norm_conf(a.get("confidence")) if a else "low",
                      "label_text": (str(a["label_text"]).strip()[:60] if a.get("label_text") else None),
                      "dims_text": (str(a["dims_text"]).strip()[:40] if a.get("dims_text") else None), "read_by": read_by, "answered": bool(a)})
    long_side = max([r["bbox"][0] + r["bbox"][2] for r in rooms] + [r["bbox"][1] + r["bbox"][3] for r in rooms] + [1])
    return merge_nested(rooms, long_side)


def _bbox_overlap(a: List[int], b: List[int]) -> float:
    """a 的外接框有多大比例落在 b 的外接框里。"""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    return (ix * iy) / float(max(1, aw * ah))


STRONG = ("living", "dining", "kitchen", "bedroom 1", "bedroom 2", "bedroom 3", "bedroom 4", "bathroom", "ensuite", "laundry")


def _fill(r: dict) -> float:
    """区域面积占它外接框的比例：方正的房间 ≈ 0.8，L 形走廊 ≈ 0.3。"""
    return r["area_px"] / float(max(1, r["bbox"][2] * r["bbox"][3]))


def _bbox_gap(a: List[int], b: List[int]) -> float:
    """两个外接框之间的空隙（相交为 0）。"""
    gx = max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2])
    gy = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
    return max(0.0, gx, gy)


def merge_nested(rooms: List[dict], long_side: int = 1000) -> List[dict]:
    """同类型（卧室要同一号）的两块：小的外接框 ≥ 60% 落在大的里（车库里的车）→ 并入大的、多边形留大的；
    或两块外接框几乎贴着（被车、文字切成两半的车库）→ 并成一块、多边形换成并集外接框。编号保留大的那个。"""
    rooms = sorted(rooms, key=lambda r: -r["area_px"])
    out: List[dict] = []
    for r in rooms:
        host = nested = None
        for h in out:
            same = h["type"] == r["type"] and r["type"] != "unknown"
            compact = _fill(h) >= 0.5  # 走廊的外接框又高又空，谁都"落在"它里面，不算
            weak = {h["type"], r["type"]} & {"storage", "unknown", "garage"} and _bbox_overlap(r["bbox"], h["bbox"]) >= 0.85  # 车库里的车、柜子格
            if compact and (same and _bbox_overlap(r["bbox"], h["bbox"]) >= 0.6 or weak):
                host, nested = h, True
                break
            weakpair = bool({h["type"], r["type"]} & {"storage", "unknown"}) and (h["type"] in STRONG or r["type"] in STRONG)  # 卧室旁的 ROBE 块、被家具切下来的一角
            if (same or weakpair) and _bbox_gap(r["bbox"], h["bbox"]) <= 0.03 * long_side:
                ux0, uy0 = min(h["bbox"][0], r["bbox"][0]), min(h["bbox"][1], r["bbox"][1])
                ux1 = max(h["bbox"][0] + h["bbox"][2], r["bbox"][0] + r["bbox"][2])
                uy1 = max(h["bbox"][1] + h["bbox"][3], r["bbox"][1] + r["bbox"][3])
                if (h["area_px"] + r["area_px"]) / float(max(1, (ux1 - ux0) * (uy1 - uy0))) >= 0.6:  # 并起来还像一间房（走廊 + 卧室并不像）
                    host, nested = h, False
                    break
        if host is None:
            out.append(r)
            continue
        if host["type"] != r["type"]:  # 弱类型让位：garage > 具体房间 > storage > unknown
            rank = lambda t: 3 if t == "garage" else 0 if t == "unknown" else 1 if t == "storage" else 2  # noqa: E731
            if rank(r["type"]) > rank(host["type"]):
                for k in ("type", "label", "inside", "confidence", "label_text", "dims_text"):
                    host[k] = r[k]
        host["area_px"] += r["area_px"]
        x0, y0 = min(host["bbox"][0], r["bbox"][0]), min(host["bbox"][1], r["bbox"][1])
        x1 = max(host["bbox"][0] + host["bbox"][2], r["bbox"][0] + r["bbox"][2])
        y1 = max(host["bbox"][1] + host["bbox"][3], r["bbox"][1] + r["bbox"][3])
        host["bbox"] = [x0, y0, x1 - x0, y1 - y0]
        if not nested:
            host["polygon"] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            host["centroid"] = [round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)]
        host.setdefault("merged_ids", []).append(r["id"])
    if not any(r["type"] == "living" and r["inside"] for r in out):  # 开放式：模型只看见离章最近的字（DINING），最大的那块其实是客厅
        inside = [r for r in out if r["inside"]]
        big = max(inside, key=lambda r: r["area_px"]) if inside else None
        if big and big["type"] in ("dining", "kitchen"):
            big["note"] = f"largest room, labelled {big['type']} by the vision model; treated as the open-plan living area"
            big["label"] = "Living/" + big["type"].title()
            big["type"] = "living"
            big["confidence"] = "medium" if big["confidence"] == "high" else big["confidence"]
    for r in out:  # 又长又空的"储物 / 认不出"其实是走廊（模型只看见旁边印的 ROBE / LIN）
        w, h = r["bbox"][2], r["bbox"][3]
        if r["type"] in ("storage", "unknown") and max(w, h) >= 3 * max(1, min(w, h)) and _fill(r) < 0.5:
            r["note"] = f"long narrow region labelled {r['type']} by the vision model; treated as a hall"
            r["type"], r["label"], r["confidence"] = "hall", LABELS["hall"], "low"
    for r in out:  # label_text 里带了尺寸就去掉（dims_text 单独有）
        if r.get("label_text") and r.get("dims_text") and r["dims_text"] in r["label_text"]:
            r["label_text"] = r["label_text"].replace(r["dims_text"], "").strip(" ,;:-") or None
    seen: Dict[str, dict] = {}
    for r in sorted(out, key=lambda r: (_fill(r) < 0.5, ("high", "medium", "low").index(r["confidence"]), -r["area_px"])):  # 同一号卧室只能有一间：方正、置信度高、面积大的留下
        if not r["type"].startswith("bedroom"):
            continue
        if r["type"] in seen:
            w, h = r["bbox"][2], r["bbox"][3]
            r["type"] = "hall" if max(w, h) >= 3 * max(1, min(w, h)) else "unknown"
            r["label"], r["confidence"] = LABELS[r["type"]], "low"
            r["note"] = "duplicate bedroom number from the vision model; renamed"
        else:
            seen[r["type"]] = r
    return sorted(out, key=lambda r: r["id"])


def label(plan_path: Path, regions: List[dict], listing_id: str, caption: str = "", timeout: float = TIMEOUT_S, force: bool = False) -> Tuple[List[dict], dict]:
    """一次看图调用给每个编号起名。返回 (rooms, 日志行)。"""
    image = stamped_image(plan_path, regions)
    sha = facts.sha256(image)
    row = None if force else cached("plan3d_rooms", sha)
    if row is None:
        ids = ", ".join(str(r["id"]) for r in regions)
        t0 = time.time()
        obj, res, route, reason = ask_model(image, "plan3d_rooms", SYSTEM_ROOMS, USER_ROOMS.format(n=len(regions), ids=ids, caption=caption or listing_id),
                                            max_tokens=120 * len(regions) + 200, timeout=timeout)
        row = _log(listing_id, "plan3d_rooms", str(plan_path.relative_to(REAL_PHOTOS)) if REAL_PHOTOS in plan_path.parents else plan_path.name, image, obj, res,
                   route, reason, round((time.time() - t0) * 1000))
        print(f"rooms {listing_id}: via {route} {row['served_model']} in {res.ms} ms (retries {res.retries}) → {json.dumps(obj, ensure_ascii=False)[:300]}")
    else:
        print(f"rooms {listing_id}: cached reading from {row['ts']} ({row['served_model']})")
    return rooms_from_reading(regions, row["reading"], row["served_model"]), row


# ---------------------------------------------------------------- assign：照片归房间
def norm_photo_room(v: Any) -> str:
    s = re.sub(r"\s+", " ", str(v or "").strip().lower())
    if s in PHOTO_ROOMS:
        return s
    if s in PHOTO_SYNONYMS:
        return PHOTO_SYNONYMS[s]
    for k in PHOTO_ROOMS:
        if k in s:
            return k
    return "other"


def read_photo(listing_id: str, url: str, caption: str, timeout: float = TIMEOUT_S, force: bool = False) -> Optional[dict]:
    """没进过 photo_facts 的照片问一次模型（task plan3d_photo）。读不了（文件不在、模型失败）返回 None。"""
    p = real_path(url)
    if p is None or not p.is_file():
        return None
    from photo.style import thumb
    image = thumb(p.read_bytes(), max_side=768)
    sha = facts.sha256(image)
    row = None if force else cached("plan3d_photo", sha)
    if row is None:
        t0 = time.time()
        try:
            obj, res, route, reason = ask_model(image, "plan3d_photo", SYSTEM_PHOTO, USER_PHOTO.format(caption=caption or "none"), max_tokens=160, timeout=timeout)
        except Exception as e:  # 接口不稳：这张照片留空，不让整套失败
            print(f"photo {listing_id} ({file_key(url)}): FAILED {type(e).__name__}: {str(e)[:160]}")
            return None
        row = _log(listing_id, "plan3d_photo", file_key(url), image, obj, res, route, reason, round((time.time() - t0) * 1000))
        print(f"photo {listing_id} ({file_key(url)}): via {route} {row['served_model']} in {res.ms} ms → {json.dumps(obj, ensure_ascii=False)[:160]}")
    return row


def assign(listing_id: str, rooms: List[dict], photos: List[dict], facts_by_file: Optional[Dict[str, dict]] = None,
           ask: Optional[Callable[[str, str], Optional[dict]]] = None) -> List[dict]:
    """每张照片的房间。photos = [{url, caption}]；facts_by_file = runs/photo_facts.jsonl 里同文件的行（默认自己读）；ask(url, caption) → 日志行 或 None
    （默认 read_photo；测试传假的）。规则：类型按 PHOTO_TO_ROOM 的候选顺序找第一种存在的房间；卧室照片按顺序配 bedroom 1、2…，多出来的
    （只有一间卧室时全归它，否则）room_id = null；exterior / other 不归房。"""
    if facts_by_file is None:
        facts_by_file = photo_facts_by_file(listing_id)
    if ask is None:
        ask = lambda url, caption: read_photo(listing_id, url, caption)  # noqa: E731
    by_type: Dict[str, List[dict]] = {}
    for r in rooms:
        by_type.setdefault(r["type"], []).append(r)
    bedrooms = sorted([r for r in rooms if r["type"].startswith("bedroom")], key=lambda r: r["type"])
    bed_i = 0
    out = []
    for ph in photos:
        url, caption = ph.get("url") or "", ph.get("caption") or ""
        row = facts_by_file.get(file_key(url))
        source, features = "photo_facts", []
        if row is None:
            row = ask(url, caption)
            source = "model" if row else "none"
            features = [str(x)[:40] for x in (row or {}).get("reading", {}).get("features", [])][:3] if row else []
        reading = (row or {}).get("reading") or {}
        kind = norm_photo_room(reading.get("room")) if row else "other"
        conf = norm_conf(reading.get("confidence") or reading.get("condition_confidence")) if row else "low"
        room_id: Optional[int] = None
        if kind == "bedroom":
            if len(bedrooms) == 1:
                room_id = bedrooms[0]["id"]
            elif bed_i < len(bedrooms):
                room_id = bedrooms[bed_i]["id"]
            bed_i += 1
        elif kind in PHOTO_TO_ROOM:
            for i, t in enumerate(PHOTO_TO_ROOM[kind]):
                if by_type.get(t):
                    room_id = by_type[t][0]["id"]
                    if i > 0:
                        conf = "low"  # 退而求其次（厨房照片放进 living）
                    break
        out.append({"url": url, "caption": caption, "room": kind, "room_id": room_id, "confidence": conf, "source": source,
                    "read_by": (row or {}).get("served_model"), "features": features})
    return out


# ---------------------------------------------------------------- scale：尺寸文字校准，否则名义比例
DIMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m?\s*[x×X]\s*(\d+(?:\.\d+)?)\s*m?")


def scale_m_per_px(rooms: List[dict]) -> Tuple[float, str]:
    """图上印了 "4.4 x 3.6m" 的房间：和它的外接框比，取中位数；没有或不合理 → 室内房间并集的长边 ≈ 12 m。"""
    import statistics
    ratios = []
    for r in rooms:
        m = DIMS_RE.search(str(r.get("dims_text") or ""))
        if not m:
            continue
        a, b = float(m.group(1)), float(m.group(2))
        w, h = r["bbox"][2], r["bbox"][3]
        if min(a, b) < 0.8 or max(a, b) > 15 or w < 10 or h < 10 or r.get("merged_ids"):
            continue
        if abs((max(a, b) / min(a, b)) / (max(w, h) / min(w, h)) - 1) > 0.3:  # 开放式大区域印的是其中一间的尺寸：长宽比对不上就不用
            continue
        ratios.append(max(a, b) / max(w, h))
        ratios.append(min(a, b) / min(w, h))
    if ratios:
        s = statistics.median(ratios)
        if 0.003 <= s <= 0.06:
            return round(s, 6), f"printed dimensions ({len(ratios) // 2} rooms)"
    inside = [r for r in rooms if r["inside"]] or rooms
    if not inside:
        return 0.01, "nominal"
    x0 = min(r["bbox"][0] for r in inside)
    y0 = min(r["bbox"][1] for r in inside)
    x1 = max(r["bbox"][0] + r["bbox"][2] for r in inside)
    y1 = max(r["bbox"][1] + r["bbox"][3] for r in inside)
    return round(NOMINAL_LONG_M / max(1, x1 - x0, y1 - y0), 6), f"nominal (long side = {NOMINAL_LONG_M:g} m)"


# ---------------------------------------------------------------- build：一套房
def out_path(listing: dict) -> Optional[Path]:
    did = domain_id(listing)
    return (REAL_PHOTOS / did / "plan3d.json") if did else None


def build(listing: dict, force: bool = False, timeout: float = TIMEOUT_S, threshold: Optional[int] = None, segment_only: bool = False,
          reread_photos: bool = False, rebuild: bool = False) -> Optional[dict]:
    """一套房：分割 → 盖章问房间（--force 重问；--rebuild 用缓存的答案重算规则）→ 照片归房间（photo_facts 优先，其余按 sha256 缓存，
    --reread-photos 重问）→ 比例、指北针 → plan3d.json。"""
    lid = listing["id"]
    did = domain_id(listing)
    plan_url = (listing.get("floorplan") or {}).get("url")
    plan_path = real_path(plan_url) if plan_url else None
    if not did or plan_path is None or not plan_path.is_file():
        print(f"{lid}: no floor plan file")
        return None
    dest = out_path(listing)
    if dest and dest.exists() and not force and not rebuild and not segment_only:
        print(f"{lid}: {dest.relative_to(ROOT)} exists (use --force, or --rebuild to redo it from the cached answers)")
        return json.loads(dest.read_text(encoding="utf-8"))
    seg = segment(plan_path, threshold=threshold, debug_png=DEBUG_DIR / f"{did}_regions.png")
    print(f"{lid}: {len(seg['regions'])} regions (threshold {seg['threshold']}) → runs/plan3d/{did}_regions.png")
    if segment_only:
        for r in seg["regions"]:
            print(f"   #{r['id']:2d} bbox {r['bbox']} area {r['area_px']} poly {len(r['polygon'])} pts")
        return seg
    if not seg["regions"]:
        print(f"{lid}: nothing segmented")
        return None
    caption = f"{listing.get('unit') or ''}/{listing.get('street') or ''} {listing.get('suburb') or ''}".strip(" /")
    rooms, row = label(plan_path, seg["regions"], lid, caption, timeout=timeout, force=force)
    photos_in = [{"url": im.get("url"), "caption": im.get("caption") or ""} for im in (listing.get("images") or []) if im.get("url") and im.get("url") != plan_url]
    photos = assign(lid, rooms, photos_in, ask=lambda url, cap: read_photo(lid, url, cap, timeout=timeout, force=reread_photos))
    m_per_px, scale_src = scale_m_per_px(rooms)
    nd = north_deg(lid)
    photo_models = sorted({p["read_by"] for p in photos if p.get("read_by")})
    doc = {"listing": lid, "domain_id": did, "plan_image": plan_url, "width": seg["width"], "height": seg["height"], "m_per_px": m_per_px, "scale_source": scale_src,
           "wall_height_m": WALL_H_M, "north_deg": nd, "rooms": [{k: v for k, v in r.items() if k != "answered"} for r in rooms], "photos": photos,
           "model": row["served_model"], "route": row["route"], "photo_models": photo_models, "one_line": str(row["reading"].get("one_line") or "")[:200],
           "segment": {"threshold": seg["threshold"], "rendered": seg["rendered"], "dilate_px": seg["dilate_px"], "min_area_frac": seg["min_area_frac"], "split_r_px": seg["split_r_px"]},
           "note": "Approximate: built from the floor plan, not a scan. Room sizes indicative.", "built_at": now_iso()}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{lid}: wrote {dest.relative_to(ROOT)} ({len(rooms)} rooms, {sum(1 for p in photos if p['room_id'])}/{len(photos)} photos placed, "
          f"scale {m_per_px} m/px from {scale_src}, north {nd})")
    return doc


def show(doc: dict) -> None:
    print(f"{doc['listing']}  plan {doc['plan_image']}  {doc['width']}x{doc['height']}  {doc['m_per_px']} m/px ({doc['scale_source']})  north {doc['north_deg']}")
    print(f"  rooms named by {doc['model']} via {doc['route']}; photos matched by {', '.join(doc.get('photo_models') or ['photo_facts'])}")
    print("  id  type        inside  conf    label_text        dims        bbox")
    for r in doc["rooms"]:
        print(f"  {r['id']:2d}  {r['type']:<11} {str(r['inside']):<7} {r['confidence']:<7} {str(r.get('label_text') or '-'):<17} {str(r.get('dims_text') or '-'):<11} {r['bbox']}"
              + (f"  (+{r['merged_ids']})" if r.get("merged_ids") else ""))
    print("  photos:")
    for p in doc["photos"]:
        print(f"    {file_key(p['url']):<24} {p['room']:<9} → room {p['room_id']}  {p['confidence']:<6} {p['source']}" + (f"  {p['features']}" if p.get("features") else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["build", "segment", "show"])
    ap.add_argument("--listing", help="只处理这一套，如 L-D17153470（默认全部有户型图的真房源）")
    ap.add_argument("--force", action="store_true", help="已有 plan3d.json 也重做：重新分割、重问房间（照片按缓存）")
    ap.add_argument("--reread-photos", action="store_true", help="没进过 photo_facts 的照片也重问模型（默认按 sha256 用上次的答案）")
    ap.add_argument("--rebuild", action="store_true", help="已有 plan3d.json 也重写，但模型答案用缓存（改了规则、不想再花调用时）")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S, help="一次看图的总预算（秒）")
    ap.add_argument("--threshold", type=int, help="墙线阈值（默认自动：黑白图 240、彩色渲染图 185）")
    a = ap.parse_args()
    llm.load_env()
    matrix = load_matrix()
    targets = [listing_by_id(a.listing, matrix)] if a.listing else listings_with_plans(matrix)
    targets = [t for t in targets if t]
    if not targets:
        print("no listing with a floor plan")
        return 1
    failed: List[str] = []
    for L in targets:
        if a.step == "show":
            p = out_path(L)
            if p and p.exists():
                show(json.loads(p.read_text(encoding="utf-8")))
            else:
                print(f"{L['id']}: no plan3d.json yet (run build)")
        else:
            try:
                build(L, force=a.force, timeout=a.timeout, threshold=a.threshold, segment_only=(a.step == "segment"), reread_photos=a.reread_photos, rebuild=a.rebuild)
            except Exception as e:  # 一套失败（接口整段时间 500）不拖累别的；重跑 build 会接着做
                failed.append(L["id"])
                print(f"{L['id']}: FAILED {type(e).__name__}: {str(e)[:200]}")
    if failed:
        print(f"failed: {', '.join(failed)} (run build again later)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
