#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""户型图事实（10-26）：让 Nemotron VL 读挂牌的户型图，只记"图上画了什么"：指北针朝哪、入户门和客厅主开口（阳台门 / 大窗）在哪面墙、
入户门是不是直通主开口（K2 穿堂，R-H2）、开门见厕 / 见灶、厨厕门相对（K3，R-H3）、外轮廓方不方正（K4，R-H4）；每项带置信度（R-H6）。
朝向（E1 / E2）也从这里来：指北针 + 主开口在哪面墙 → 主窗朝向（推断）；没指北针就是未知（R-C1）。
模型只说看见了什么，结论（状态词）在 k_facts / aspect_from_plan 这两个规则函数里。风水包默认不装（R-H0）：这些格子只在租客说在意时进清单，
叫"文化偏好核对"，只核对布局事实，不判吉凶。
日志 runs/floorplan_facts.jsonl（每行：房源、文件、路由、served_model、模型 JSON）。"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from llm import provider as llm  # noqa: E402
from photo import facts  # noqa: E402

LOG = ROOT / "runs" / "floorplan_facts.jsonl"

SYSTEM = """HOMETRUTH_FLOORPLAN_FACTS_V1
You read ONE floor plan image from a Sydney rental listing. Report only what is drawn. Use null whenever the drawing does not show it; never guess.
Directions are PAGE directions (top / bottom / left / right of the image), not compass directions.
Reply with ONE JSON object and nothing else:
{"is_floor_plan": true or false,
 "north_arrow": {"present": true or false, "points": "up|up-right|right|down-right|down|down-left|left|up-left|null" (the page direction the N arrow points to)},
 "entry_door": {"found": true or false, "wall": "top|bottom|left|right|null"},
 "living_main_opening": {"found": true or false, "wall": "top|bottom|left|right|null", "kind": "balcony|window|null"} (the balcony door or the largest window of the living room),
 "entry_faces_main_opening": true, false or null (true only if a straight line from the entry door reaches the balcony door or a large window with no wall in between),
 "bathroom_door_faces_entry": true, false or null (a bathroom or toilet door directly in view of the entry door),
 "stove_visible_from_entry": true, false or null (the cooktop symbol, if drawn, directly in view of the entry door),
 "kitchen_bathroom_doors_face_each_other": true, false or null,
 "outline": "rectangular|l_shaped|irregular|unclear" (the outer outline of the apartment, ignoring the balcony),
 "missing_corner": true, false or null (a clear notch out of an otherwise rectangular outline),
 "rooms": ["each labelled room, lower case"],
 "confidence": {"north_arrow": "high|medium|low", "entry": "high|medium|low", "opening": "high|medium|low", "layout": "high|medium|low"},
 "one_line": "one plain sentence (at most 25 words) on what the plan shows"}"""
USER = "Read this floor plan and fill the JSON. Listing: {caption}."

PAGE_DEG = {"up": 0, "up-right": 45, "right": 90, "down-right": 135, "down": 180, "down-left": 225, "left": 270, "up-left": 315}
WALL_DEG = {"top": 0, "right": 90, "bottom": 180, "left": 270}
ASPECT_NAMES = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def ask_model(image: bytes, caption: str, provider: Optional[str] = None, timeout: float = 120.0) -> Tuple[dict, llm.ChatResult, str, str]:
    """和 facts.ask_model 一样的路由（先 Nightshift 视觉路由、没有就直连 NVIDIA，如实记录），换一套提示词。"""
    b64 = base64.b64encode(image).decode("ascii")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": USER.format(caption=caption)},
                                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    kw = dict(task="floorplan_facts", vision=True, temperature=0.0, max_tokens=500, timeout=timeout, retries=1)

    def call(prov: Optional[str]) -> llm.ChatResult:
        for attempt in range(3):
            try:
                return llm.chat(msgs, provider=prov, **kw)
            except llm.LLMError as e:
                if e.kind not in ("server_error", "rate_limited") or attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
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
    obj = facts._json_object(res.text)
    if obj is None:
        raise RuntimeError(f"model answer was not JSON: {res.text[:200]!r}")
    return obj, res, route, reason


def read(listing_id: str, file: str, image: bytes, caption: str, provider: Optional[str] = None) -> dict:
    t0 = time.time()
    obj, res, route, reason = ask_model(image, caption, provider)
    row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "listing": listing_id, "file": file, "sha256": facts.sha256(image),
           "bytes": len(image), "route": route, "nightshift": reason or None, "provider": res.provider, "model": res.model,
           "served_model": res.served_model or res.model, "ms": res.ms, "wall_ms": round((time.time() - t0) * 1000), "reading": obj, "raw": res.text[:800]}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"plan {listing_id} ({file}): via {route} {row['served_model']} in {res.ms} ms → {json.dumps(obj, ensure_ascii=False)[:200]}")
    return row


def latest() -> Dict[str, dict]:
    """每套房最近一次读户型图。"""
    out: Dict[str, dict] = {}
    if not LOG.exists():
        return out
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("listing") and isinstance(row.get("reading"), dict):
            out[row["listing"]] = row
    return out


# ---------------------------------------------------------------- 规则：读图结果 → 朝向、K2–K4
def _conf(reading: dict, key: str) -> str:
    c = reading.get("confidence") or {}
    v = str(c.get(key) or "").lower()
    return v if v in ("high", "medium", "low") else "low"


def aspect_from_plan(reading: dict) -> Tuple[Optional[str], str, str]:
    """(朝向 N/NE/…, 怎么来的, 置信度)。要指北针 + 客厅主开口在哪面墙；缺一个就是 None（R-C1）。"""
    na = reading.get("north_arrow") or {}
    op = reading.get("living_main_opening") or {}
    if not na.get("present") or str(na.get("points") or "null") not in PAGE_DEG:
        return None, "no north arrow on the floor plan", "low"
    wall = str(op.get("wall") or "null")
    if not op.get("found") or wall not in WALL_DEG:
        return None, "the living room's main opening is not clear on the plan", "low"
    bearing = (WALL_DEG[wall] - PAGE_DEG[str(na["points"])]) % 360
    name = ASPECT_NAMES[int(((bearing + 22.5) % 360) // 45)]
    conf = max((_conf(reading, "north_arrow"), _conf(reading, "opening")), key=lambda c: ("high", "medium", "low").index(c))  # 取两者里较低的
    return name, f"floor plan: north arrow points {na['points']} on the page and the {op.get('kind') or 'main opening'} is on the {wall} wall", conf


def k_facts(listing: dict, plan: dict, reading: dict, read_by: str) -> Dict[str, dict]:
    """K2 穿堂、K3 开门见厕 / 见灶 / 厨厕相对、K4 缺角（docs/02；规则 R-H2–R-H4、R-H6）。plan 要有 url（户型图）和 row。
    状态相对默认偏好（别穿堂、别开门见厕灶、要方正）：户型图靠模型读，按 R-H6 一律"推断"带置信度，犯了的对在意的人是冲突（if_wanted）；
    画不清（null）→ 未知。"""
    lid = listing["id"]
    n = facts.num_of(lid)
    ev = {"table": "floorplan_facts", "row": f"{lid}-plan", "material_id": f"M-{n}-plan", "text": str(reading.get("one_line") or "Floor plan read."),
          "read_by": read_by, "image": plan["url"]}
    lay = _conf(reading, "layout")
    out: Dict[str, dict] = {}

    def cell(dim: str, hit: Optional[bool], yes_val: str, no_val: str, yes_why: str, no_why: str, null_why: str) -> dict:
        if hit is None:
            return {"status": "unknown", "value": None, "why": null_why + " Ask the agent for a clearer plan.", "evidence": [dict(ev, confidence=lay)]}
        return {"status": "inferred", "value": yes_val if hit else no_val, "short": (yes_val if hit else no_val).lower(), "if_wanted": "conflict" if hit else "inferred",
                "flag": bool(hit), "confidence": lay, "why": (yes_why if hit else no_why) + f" Read off the floor plan by the vision model ({lay} confidence), so inferred, not measured.",
                "evidence": [dict(ev, confidence=lay)]}

    efo = reading.get("entry_faces_main_opening")
    out["K2"] = cell("K2", efo if isinstance(efo, bool) else None, "Through-line", "No through-line",
                     "The entry door looks straight through to the balcony door or main window.", "The entry door does not look straight through to the balcony or main window.",
                     "The plan does not make clear whether the entry looks straight through to the balcony.")
    b, s_, kb = reading.get("bathroom_door_faces_entry"), reading.get("stove_visible_from_entry"), reading.get("kitchen_bathroom_doors_face_each_other")
    seen = [x for x in (b, s_, kb) if isinstance(x, bool)]
    hit3: Optional[bool] = (any(seen) if seen else None)
    parts = []
    if b is True:
        parts.append("a bathroom door is in view of the entry")
    if s_ is True:
        parts.append("the cooktop is in view of the entry")
    if kb is True:
        parts.append("the kitchen and bathroom doors face each other")
    out["K3"] = cell("K3", hit3, "Door faces wet room", "Doors clear", ("On the plan " + ", ".join(parts) + ".") if parts else "On the plan a wet-room door faces the entry.",
                     "On the plan neither the bathroom door nor the cooktop is in view of the entry, and the kitchen and bathroom doors do not face each other.",
                     "The plan does not show the bathroom door or the cooktop clearly enough to tell.")
    outline = str(reading.get("outline") or "unclear").lower()
    mc = reading.get("missing_corner")
    if outline == "unclear" and not isinstance(mc, bool):
        hit4: Optional[bool] = None
    else:
        hit4 = bool(mc) or outline in ("l_shaped", "irregular")
    out["K4"] = cell("K4", hit4, "Missing corner", "Square outline",
                     f"The outline is {outline.replace('_', '-')}" + (" with a notch out of it" if mc else "") + ", so a corner is missing.",
                     "The outer outline is rectangular with no corner missing.", "The outline is not clear enough on the plan to judge.")
    return out


def k1_fact(listing: dict, floor: Optional[int], floor_how: str) -> dict:
    """K1 门牌、楼层数字（R-H1）：读，来自挂牌地址；楼层从门牌推的标"推断"。默认偏好"别带 4"：有 4 → 对在意的人是冲突。"""
    lid = listing["id"]
    n = facts.num_of(lid)
    unit = str(listing.get("unit") or "")
    digits = unit + (str(floor) if floor is not None else "")
    has4 = "4" in digits
    where = []
    if "4" in unit:
        where.append(f"unit {unit}")
    if floor is not None and "4" in str(floor):
        where.append(f"level {floor}")
    text = f"Address: {listing['unit']}/{listing['street']}" + (f"; level {floor} ({floor_how})" if floor is not None else "; floor not stated")
    ev = [{"table": "listings", "row": lid, "material_id": f"M-{n}-listing", "text": text}]
    status = "supported" if floor_how in ("listing text", "unknown") or floor is None else "inferred"
    if has4:
        return {"status": status, "value": "Has a 4", "short": "has a 4", "flag": True, "if_wanted": "conflict",
                "why": f"The number includes a 4 ({' and '.join(where)})." + (" The level is worked out from the unit number, so inferred." if floor_how == "unit number" else ""), "evidence": ev}
    return {"status": status, "value": "No 4", "short": "no 4", "flag": False, "if_wanted": status,
            "why": f"Unit {unit}" + (f", level {floor}" if floor is not None else "") + ": no 4 in the numbers." + (" Floor not stated, so only the unit number is checked." if floor is None else ""), "evidence": ev}
