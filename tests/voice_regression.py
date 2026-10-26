#!/usr/bin/env python3
"""语音原型文字流程回归：按脚本对 /api/turn 发一串话，记下事件流，和基线比。只依赖标准库。

抓基线（改代码前，对正在跑的旧版服务）：
  python3 tests/voice_regression.py --base http://127.0.0.1:8630 --out runs/voice_regression/baseline.jsonl
跑新版并比对：
  python3 tests/voice_regression.py --base http://127.0.0.1:8632 --out runs/voice_regression/new.jsonl --compare runs/voice_regression/baseline.jsonl
随机字段（request_id、ms、t_first_ms、ts）比之前去掉；needs 事件里新加的 parser / parse 字段不参与比对，单独打印。
脚本：说需求 → 反问 → 回答 → 开场 → 来源 → 三张卡导览 → 打断提问 → skip → stop → continue → 改需求 → 中介回复翻格重排。
默认每轮带 deterministic: true（过渡句固定、台词用模板），所以和老基线逐字可比。
--narration：不带这个标记，让模型写台词；这时只比"说以外"的事件（卡片、高亮、证据、状态、needs），每句台词打印出来看，
并数一数多少句是模型写的（by: llm）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
RANDOM_KEYS = {"request_id", "ms", "t_first_ms", "ts"}
NEW_NEEDS_KEYS = {"parser", "parse"}


def turn(base: str, body: dict) -> List[dict]:
    req = urllib.request.Request(base + "/api/turn", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "HomeTruth-client/1"}, method="POST")  # 公网经 Cloudflare：Python-urllib 的默认 UA 会被浏览器完整性检查拦（1010）
    events: List[dict] = []
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def scrub(obj):
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in RANDOM_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def comparable(ev: dict) -> dict:
    ev = scrub(ev)
    if ev.get("type") == "needs":
        ev = {k: v for k, v in ev.items() if k not in NEW_NEEDS_KEYS}
    return ev


def nth_say(events: List[dict], n: int) -> Optional[dict]:
    says = [e for e in events if e.get("type") == "say" and e.get("idx") is not None]
    return says[n] if n < len(says) else None


def first_card(events: List[dict]) -> Optional[str]:
    for e in events:
        if e.get("type") == "card":
            return e["listing"]["id"]
    return None


def run(base: str, deterministic: bool = True) -> List[dict]:
    sid = "regress-" + uuid.uuid4().hex[:8]
    out: List[dict] = []
    state: Dict[str, Optional[str]] = {"listing": None}

    def step(name: str, text: str, interrupted: Optional[dict] = None) -> List[dict]:
        body = {"session": sid, "text": text, "source": "text", "listing_id": state["listing"],
                "interrupted": interrupted or {"active": False}, "deterministic": deterministic}
        t0 = time.time()
        evs = turn(base, body)
        ms = round((time.time() - t0) * 1000)
        for e in evs:
            if e.get("type") in ("card", "card_update"):
                state["listing"] = e["listing"]["id"]
            elif e.get("type") == "highlight":
                state["listing"] = e["listing_id"]
        out.append({"step": name, "text": text, "interrupted": bool(interrupted and interrupted.get("active")), "ms": ms, "events": evs})
        return evs

    def cut(evs: List[dict], n: int) -> dict:
        """模拟浏览器：第 n 句导览说完、第 n+1 句说到一半被打断。"""
        done, cutting = nth_say(evs, n), nth_say(evs, n + 1)
        return {"active": True, "spoken_idx": done["idx"] if done else None, "listing_id": first_card(evs),
                "cut_sentence": cutting["text"] if cutting else None}

    step("need", "Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom.")
    tour = step("answer", "Under 900, mid-November.")
    state["listing"] = first_card(tour)
    step("interrupt_question", "Is the first one close to the station?", cut(tour, 4))
    step("interrupt_skip", "skip", cut(tour, 6))
    step("interrupt_stop", "stop", cut(tour, 8))
    step("continue", "continue")
    step("update", "Actually make it under 850 a week.")
    step("agent_reply", "The agent said the split system is in the living room only.")
    return out


def summary(steps: List[dict]) -> str:
    lines = []
    for s in steps:
        kinds: Dict[str, int] = {}
        for e in s["events"]:
            kinds[e["type"]] = kinds.get(e["type"], 0) + 1
        say0 = next((e["text"] for e in s["events"] if e.get("type") == "say"), "")
        needs = [e for e in s["events"] if e.get("type") == "needs"]
        parser = needs[-1].get("parser", "-") if needs else "-"
        lines.append(f"{s['step']:20} {len(s['events']):3} events {s['ms']:6} ms  parser={parser:6} first say: {say0[:70]}")
        lines.append("    " + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())))
    return "\n".join(lines)


def no_say(events: List[dict]) -> List[dict]:
    """模型写台词时句子每次不同、还会多几句过渡：只比"说以外"的事件（ask 的句子也去掉）。"""
    out = []
    for e in events:
        if e.get("type") == "say":
            continue
        if e.get("type") == "ask":
            e = {k: v for k, v in e.items() if k != "text"}
        out.append(e)
    return out


def narration_report(steps: List[dict]) -> None:
    total = llm = 0
    for s in steps:
        says = [e for e in s["events"] if e.get("type") == "say"]
        n_llm = sum(1 for e in says if e.get("by") == "llm")
        total += len(says); llm += n_llm
        print(f"\n[{s['step']}] {n_llm}/{len(says)} lines model-written")
        for e in says:
            print(f"   {'LLM ' if e.get('by') == 'llm' else 'tmpl'} {e.get('step', ''):12} {e['text'][:150]}")
    print(f"\nmodel-written lines: {llm}/{total}")


def compare(new: List[dict], base: List[dict], loose: bool = False) -> int:
    bad = 0
    for a, b in zip(new, base):
        ea, eb = [comparable(e) for e in a["events"]], [comparable(e) for e in b["events"]]
        if loose:
            ea, eb = no_say(ea), no_say(eb)
        if ea == eb:
            print(f"SAME  {a['step']:20} {len(ea)} events")
            continue
        bad += 1
        print(f"DIFF  {a['step']:20} new {len(ea)} events vs base {len(eb)}")
        for i, (x, y) in enumerate(zip(ea, eb)):
            if x != y:
                print(f"      first difference at event {i}:\n        new : {json.dumps(x)[:300]}\n        base: {json.dumps(y)[:300]}")
                break
    if len(new) != len(base):
        bad += 1
        print(f"DIFF  step count {len(new)} vs {len(base)}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8632")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare")
    ap.add_argument("--narration", action="store_true", help="let the model write the lines; compare everything except the spoken sentences")
    a = ap.parse_args()
    steps = run(a.base.rstrip("/"), deterministic=not a.narration)
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps) + "\n", encoding="utf-8")
    print(summary(steps))
    if a.narration:
        narration_report(steps)
    print(f"\nwrote {out}")
    if a.compare:
        p = Path(a.compare)
        base = [json.loads(x) for x in (p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8").splitlines() if x.strip()]
        bad = compare(steps, base, loose=a.narration)
        print("\nREGRESSION PASS" if bad == 0 else f"\nREGRESSION FAIL ({bad} step(s) differ)")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
