# -*- coding: utf-8 -*-
"""收件箱（10-26 参考 Dot 的"用户离开后事件照样到、回来接着推进"）：现在只有一种事件——中介的回复。
它从哪来都行（邮件 / 短信的 webhook、队友替你粘、演示脚本 scripts/agent_reply.py 直接 POST /api/inbox）；
存 runs/inbox/<renter>.jsonl，一行一条：{event_id, ts, renter, listing_id, text, channel, read_at}。
租客回来开查时（policy.Session._search），未读的逐条当新材料处理（翻格、重排、记信念日志）、标已读；同一条只处理一次。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, List, Optional

import memory

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "runs" / "inbox"
MAX_TEXT = 500


def path(renter: str) -> Path:
    return DIR / f"{renter}.jsonl"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _rows(renter: str) -> List[dict]:
    p = path(renter)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event_id"):
            out.append(row)
    return out


def _write(renter: str, rows: List[dict]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path(renter).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def add(renter: Any, listing_id: str, text: str, channel: str = "api") -> Optional[dict]:
    """放一条进去。同一套房、同一段话还没读过就不重复放（返回已有的那条）。"""
    rid = memory.clean_id(renter)
    text = " ".join(str(text or "").split())[:MAX_TEXT]
    if not rid or not listing_id or not text:
        return None
    rows = _rows(rid)
    key = hashlib.sha1(f"{rid}|{listing_id}|{text.lower()}".encode("utf-8")).hexdigest()[:12]
    for r in rows:
        if r.get("listing_id") == listing_id and r.get("text", "").lower() == text.lower() and not r.get("read_at"):
            return r
    row = {"event_id": f"in-{key}", "ts": _now(), "renter": rid, "listing_id": listing_id, "text": text, "channel": str(channel or "api")[:40], "read_at": None}
    rows.append(row)
    _write(rid, rows)
    return row


def unread(renter: Any) -> List[dict]:
    rid = memory.clean_id(renter)
    return [r for r in _rows(rid) if not r.get("read_at")] if rid else []


def mark_read(renter: Any, event_ids: List[str]) -> int:
    rid = memory.clean_id(renter)
    if not rid:
        return 0
    rows, n = _rows(rid), 0
    for r in rows:
        if r.get("event_id") in event_ids and not r.get("read_at"):
            r["read_at"] = _now()
            n += 1
    if n:
        _write(rid, rows)
    return n


def view(renter: Any) -> dict:
    """给 /api/hello：几条没读、每条是哪套房、哪来的、什么时候（正文只给开头，界面不替中介说话）。"""
    items = unread(renter)
    return {"unread": len(items), "items": [{"event_id": r["event_id"], "listing_id": r["listing_id"], "channel": r.get("channel"), "ts": r.get("ts"),
                                             "preview": r["text"][:80]} for r in items]}


def forget(renter: Any) -> bool:
    rid = memory.clean_id(renter)
    if not rid or not path(rid).exists():
        return False
    path(rid).unlink()
    return True
