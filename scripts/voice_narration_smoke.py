# -*- coding: utf-8 -*-
"""台词交给模型写的冒烟：不起服务，在进程里跑五轮对话（需求 → 回答 → 打断提问 → 改预算 → 中介回复），
每句台词标出是模板（tmpl）还是模型写的（llm），带时间；最后一行是 narrator 的统计（调用 / 过审 / 拒 / 照抄 / 失败 / 超时）。
跑：.venv/bin/python scripts/voice_narration_smoke.py（要 .env 里有 key、Nightshift 开着；没 key 全是 tmpl）。
narrator 的日志（每套房几行过审、哪几行为什么被拒）同时打在 stderr。"""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "src" / "voice"))
from llm import provider as llm
llm.load_env()
import policy, narrator
print("provider:", llm.select().label, "| narration enabled:", narrator.enabled(), "| needs llm:", policy.needs_llm_ready())
s = policy.Session("smoke")
def run(text, inter=None):
    t0 = time.time(); last = t0; n = 0
    for ev in s.handle_turn({"text": text, "source": "text", "interrupted": inter or {"active": False}}):
        now = time.time()
        if ev["type"] == "say":
            print(f"  +{now - t0:5.2f}s (+{now - last:4.2f}) [{ev.get('by', 'tmpl'):4}] {ev.get('step', ''):12} {ev['text']}")
        elif ev["type"] in ("ask", "needs", "state"):
            print(f"  +{now - t0:5.2f}s          {ev['type']:5} {ev.get('label') or ev.get('fields') or ev.get('parser', '')}")
        last = now; n += 1
    print(f"  -- {n} events, {time.time() - t0:.2f} s total")
print("== turn 1"); run("Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom.")
print("== turn 2"); run("Under 900, mid-November.")
print("== turn 3 (interrupt with a question after the 4th tour line)")
run("Is the first one close to the station?", {"active": True, "spoken_idx": 3, "listing_id": s.current, "cut_sentence": "x"})
print("== turn 4 (interrupt: change budget)")
run("Actually make it under 850 a week.", {"active": True, "spoken_idx": 5, "listing_id": s.current, "cut_sentence": "x"})
print("== turn 5 (agent reply)"); run("The agent said the split system is in the living room only.")
print("stats:", narrator.STATS)
