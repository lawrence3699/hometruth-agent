# -*- coding: utf-8 -*-
"""欢迎回来（docs/06 §4B；Meterless H-MEM 式的跨会话记忆，按规范自实现、没用官方包）：记住这位租客上次开查时的需求和前几套房，
下次一进来先说 "Welcome back. Last time it was two bedrooms near Central with a cat — same again, or has anything changed?"，需求 chip 预填。

存哪：runs/memory/<renter_id>.json。renter_id 由浏览器生成、放它自己的 localStorage（没有账号系统，换台浏览器就是新人）；
只存需求（预算 / 卧室 / 通勤地 / 入住 / 宠物 / 附加项）、上次入围的房源编号、保存时间和来过几次，不存原话以外的任何东西，没有人口描述。
谁都能让它忘掉：POST /api/forget（界面上的 Forget me）。"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import phraser

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "runs" / "memory"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
FIELDS = ("budget", "bedrooms", "anchor", "move_in", "pets")  # 五样必填（policy.REQUIRED 的字段名）
VERSION = 1


def clean_id(renter_id: Any) -> Optional[str]:
    """只认字母、数字、- 和 _（4 到 64 位）；别的都当没有，免得拿它拼路径。"""
    s = str(renter_id or "").strip()
    return s if ID_RE.match(s) else None


def path(renter_id: str) -> Path:
    return DIR / f"{renter_id}.json"


def _profile_ok(p: Any) -> bool:
    if not isinstance(p, dict):
        return False
    if p.get("budget") is not None and not isinstance(p["budget"], int):
        return False
    if p.get("bedrooms") is not None and not isinstance(p["bedrooms"], int):
        return False
    if p.get("anchor") is not None and not isinstance(p["anchor"], str):
        return False
    mv = p.get("move_in")
    if mv is not None and not (isinstance(mv, dict) and (mv.get("asap") or (isinstance(mv.get("month"), int) and isinstance(mv.get("day"), int) and mv.get("text")))):
        return False
    pets = p.get("pets")
    if pets is not None and not (isinstance(pets, dict) and "has" in pets and pets.get("text")):
        return False
    if not isinstance(p.get("extras", []), list) or any(not (isinstance(e, dict) and e.get("dim") and e.get("label")) for e in p.get("extras", [])):
        return False
    return True


def load(renter_id: Optional[str]) -> Optional[dict]:
    """有记忆就返回整条（dict），没有或坏了就 None。"""
    rid = clean_id(renter_id)
    if not rid:
        return None
    p = path(rid)
    if not p.exists():
        return None
    try:
        mem = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(mem, dict) or not _profile_ok(mem.get("profile")) or not any(mem["profile"].get(k) is not None for k in FIELDS):
        return None
    return mem


def profile_from(mem: dict) -> dict:
    """记忆里的需求 → 一份新的 profile（和 policy.new_profile() 同形，缺的键补默认）。"""
    p = copy.deepcopy(mem["profile"])
    out = {"budget": p.get("budget"), "bedrooms": p.get("bedrooms"), "anchor": p.get("anchor"), "move_in": p.get("move_in"), "pets": p.get("pets"),
           "extras": [dict(e) for e in p.get("extras", [])], "max_commute": p.get("max_commute") or 40}
    return out


def remembered_fields(profile: dict) -> List[str]:
    """预填了哪些（给 needs 事件的 remembered，界面把这些 chip 标成"上次的"）。"""
    out = [k for k in FIELDS if profile.get(k) is not None]
    if profile.get("extras"):
        out.append("extras")
    return out


def save(renter_id: Optional[str], profile: dict, top: List[str], heard: str = "", session_id: str = "",
         open: Optional[List[dict]] = None) -> Optional[dict]:
    """开查一次就记一次：最近一次的需求赢。open = 还在等中介回答的格子（每套房最值得问的那个问题），下次开场会提。返回写下的那条。"""
    rid = clean_id(renter_id)
    if not rid or not any(profile.get(k) is not None for k in FIELDS):
        return None
    old = load(rid) or {}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    p = {k: copy.deepcopy(profile.get(k)) for k in FIELDS}
    p["extras"] = [dict(e) for e in profile.get("extras", [])]
    p["max_commute"] = profile.get("max_commute") or 40
    mem = {"version": VERSION, "renter": rid, "first_seen": old.get("first_seen") or now, "saved_at": now, "visits": int(old.get("visits") or 0) + 1,
           "profile": p, "summary": phraser.summary(p), "top": [str(x) for x in top][:5], "last_heard": (heard or "")[:200], "session": session_id,
           "open": [dict(o) for o in (open or [])][:5], "rejected": [str(x) for x in (old.get("rejected") or [])][:50]}
    DIR.mkdir(parents=True, exist_ok=True)
    path(rid).write_text(json.dumps(mem, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return mem


def add_rejected(renter_id: Optional[str], listing_id: str) -> None:
    """租客说不要的那套（"too far" / "not that one"）：记下来，下次排名也跳过（policy.Session.attach_renter 读回来）。"""
    rid = clean_id(renter_id)
    if not rid:
        return
    mem = load(rid)
    if not mem:
        return
    rej = [str(x) for x in (mem.get("rejected") or [])]
    if str(listing_id) not in rej:
        rej.append(str(listing_id))
    mem["rejected"] = rej[-50:]
    path(rid).write_text(json.dumps(mem, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def forget(renter_id: Optional[str]) -> bool:
    rid = clean_id(renter_id)
    if not rid:
        return False
    p = path(rid)
    if not p.exists():
        return False
    p.unlink()
    return True


def ago(saved_at: str, now: Optional[dt.datetime] = None) -> str:
    """"3 hours ago" 这种给人看的相对时间。"""
    try:
        t = dt.datetime.fromisoformat(saved_at)
    except (TypeError, ValueError):
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    s = max(0, int((now - t).total_seconds()))
    if s < 60:
        return "just now"
    if s < 3600:
        m = s // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = s // 86400
    return "yesterday" if d == 1 else f"{d} days ago"


def view(mem: Optional[dict]) -> Optional[dict]:
    """给 /api/hello 的那份：界面开场要显示的东西（需求的显示版、摘要句、多久以前、来过几次、上次的前几套）。"""
    if not mem:
        return None
    p = profile_from(mem)
    return {"saved_at": mem.get("saved_at"), "ago": ago(mem.get("saved_at") or ""), "visits": mem.get("visits", 1), "summary": mem.get("summary") or phraser.summary(p),
            "profile": {"budget": p["budget"], "bedrooms": p["bedrooms"], "anchor": p["anchor"], "move_in": p["move_in"]["text"] if p["move_in"] else None,
                        "pets": p["pets"]["text"] if p["pets"] else None, "extras": [e["label"] for e in p["extras"]], "max_commute": p["max_commute"]},
            "remembered": remembered_fields(p), "top": list(mem.get("top") or []), "open": list(mem.get("open") or [])[:3]}
