# -*- coding: utf-8 -*-
"""信念日志（docs/06 §4D，10-26 参考 Dot 的"持久化任务状态"改造）：按 Meterless World Model 的口径自实现，没用官方包——
只追加、不改旧行；每套房的每一格有版本号，状态翻转才算新版本（v1 = 开查时来源说的，v2 = 中介回复之后……）；
每行写清谁让它变的（粘进来的中介回复 / 离开时收件箱里到的回复）、哪个会话、什么时候、翻转前后的排名。

存哪：runs/beliefs/<owner>.jsonl，owner 是租客编号（浏览器 localStorage 的 ht_renter，有记忆时）或会话编号。
同一条回复（event_id）只记一次：恢复 / 重放时不会把外部动作做两遍（Dot 那份资料里"恢复任务时避免重复执行"那一条）。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "runs" / "beliefs"
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{4,80}$")
VERSION = 1


def clean_owner(owner: Any) -> Optional[str]:
    s = str(owner or "").strip()
    return s if ID_RE.match(s) else None


def path(owner: str) -> Path:
    return DIR / f"{owner}.jsonl"


def event_id(listing_id: str, dim: str, new: str, text: str) -> str:
    """同一套房、同一格、同一结论、同一段话 → 同一个事件编号（去重用）。"""
    key = f"{listing_id}|{dim}|{new}|{' '.join(str(text or '').lower().split())}"
    return "ev-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def load(owner: Any) -> List[dict]:
    o = clean_owner(owner)
    if not o or not path(o).exists():
        return []
    rows = []
    for line in path(o).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("listing_id") and row.get("dim"):
            rows.append(row)
    return rows


def versions(owner: Any) -> Dict[Tuple[str, str], int]:
    """(房源, 维度) → 当前版本（没翻过就是 1）。"""
    out: Dict[Tuple[str, str], int] = {}
    for row in load(owner):
        out[(row["listing_id"], row["dim"])] = int(row.get("version") or 1)
    return out


def seen(owner: Any, eid: str) -> bool:
    return any(row.get("event_id") == eid for row in load(owner))


def record(owner: Any, *, listing_id: str, street: str, dim: str, label: str, old: str, new: str, source: str, text: str,
           override: Optional[dict] = None, session_id: str = "", event_id_: Optional[str] = None, reader: Optional[dict] = None,
           rank_before: Optional[List[str]] = None, rank_after: Optional[List[str]] = None, channel: Optional[str] = None) -> Optional[dict]:
    """追加一行；同一个 event_id 已经有了就什么都不写、返回 None。返回写下的那行（带 from_version / version）。
    override = policy 写进 Session.overrides 的那格（status / why / evidence），下次这位租客回来照它恢复（overrides()）。"""
    o = clean_owner(owner)
    if not o:
        return None
    eid = event_id_ or event_id(listing_id, dim, new, text)
    if seen(o, eid):
        return None
    cur = versions(o).get((listing_id, dim), 1)
    row = {"schema": VERSION, "event_id": eid, "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "owner": o,
           "session": session_id, "listing_id": listing_id, "street": street, "dim": dim, "label": label, "from": old, "to": new,
           "from_version": cur, "version": cur + 1, "source": source, "channel": channel, "text": str(text or "")[:500],
           "override": override or {}, "reader": reader or {}, "rank_before": list(rank_before or []), "rank_after": list(rank_after or [])}
    DIR.mkdir(parents=True, exist_ok=True)
    with path(o).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def overrides(owner: Any) -> Dict[str, Dict[str, dict]]:
    """把日志重放成 policy 的 overrides：{房源: {维度: 那格}}，后写的覆盖先写的。租客回来时 Session.attach_renter 用它恢复信念。"""
    out: Dict[str, Dict[str, dict]] = {}
    for row in load(owner):
        cell = row.get("override") or {"status": row.get("to"), "why": "", "evidence": []}
        if cell.get("status"):
            out.setdefault(row["listing_id"], {})[row["dim"]] = dict(cell)
    return out


def recent(owner: Any, n: int = 5) -> List[dict]:
    rows = load(owner)
    keep = ("event_id", "ts", "listing_id", "street", "dim", "label", "from", "to", "from_version", "version", "source", "channel", "session")
    out = []
    for r in rows[-n:][::-1]:
        d = {k: r.get(k) for k in keep}
        d["reader"] = (r.get("reader") or {}).get("parser")
        d["model"] = (r.get("reader") or {}).get("model")
        out.append(d)
    return out


def view(owner: Any, n: int = 5) -> dict:
    """给 /api/hello：翻过几次、最近几行（界面 Changes 面板开场就能列出"earlier"）。"""
    rows = load(owner)
    return {"flips": len(rows), "recent": recent(owner, n)}


def forget(owner: Any) -> bool:
    o = clean_owner(owner)
    if not o or not path(o).exists():
        return False
    path(o).unlink()
    return True
