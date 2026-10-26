#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录一段语音导览的演示音频（不用麦克风、不用浏览器）。

在进程里跑 policy.Session（台词交给模型写、过渡句随机），机器人的句子用 Magpie 合成（和 8631 同一把声音 Aria），
租客的句子用 macOS say 的另一把声音（Daniel），按真实对话的节奏拼起来：句间 0.35 s，换人 0.7 s，打断前 0.4 s。
对话脚本（和 tests/voice_regression.py 同一条线，截短到 90 s 左右）：说需求 → 反问 → 回答 → 第一套讲到一半被问问题 → 答完接着讲 →
"Skip." → 第二套 → "Stop."

跑：.venv/bin/python scripts/voice_demo_clip.py [--out runs/recordings/<名字>] [--template] [--user-voice Daniel] [--tts magpie|elevenlabs] [--eleven-voice Charlie]
  --template：不让模型写台词、过渡句固定（对照用）。--tts 默认跟 .env 的 TTS_PROVIDER（没设就是 magpie）。
输出：<out>.wav（单声道 16 位）、<out>.m4a（AAC，发给人听的）、<out>.md（逐句字幕：时间点、谁说的、模板还是模型写的）。
没有 NVIDIA key 时机器人的句子退回 macOS say 的 Samantha（声音不同，流程一样）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))

from llm import provider as llm  # noqa: E402

llm.load_env()

import eleven  # noqa: E402
import tone  # noqa: E402
import narrator  # noqa: E402
import policy  # noqa: E402

GAP_LINE, GAP_TURN, GAP_CUT = 0.35, 0.7, 0.4  # 秒：句间 / 换人 / 打断前

# (租客说的话, 机器人这轮最多说几句就被打断；None = 说完)
SCRIPT: List[Tuple[str, Optional[int]]] = [
    ("Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom.", None),
    ("Under 900 a week, mid-November.", 7),  # 过渡句、开查、入围、第一套的前三格
    ("Are the bills included?", 4),  # 问一个没核对过的点：诚实说未知、加进要问中介的问题，再接着讲

    ("Skip.", 3),
    ("Stop.", None),
]

# 场景二「两个 UNSW 学生带猫」：五样必填分两轮给、导览中途追问空调和账单、跳下一套、转达中介回复（宠物）、改预算重排、结束。
# 每一步的"最多说几句"是按 --dry 跑出来的台词数定的；台词改了要重新 --dry 对一下。
SCRIPT_UNSW: List[Tuple[str, Optional[int]]] = [
    ("Hi! We're two UNSW students moving to Sydney. We want two bedrooms close to UNSW, and we've got a cat.", None),  # 复述 + 反问预算、入住
    ("Around 900 a week at most, and we need to move in mid-November. Oh, and air con in the bedroom would be great.", 7),  # 过渡、开查、入围、第一套开头两格
    ("Sorry, is the air con actually in the bedroom?", 6),  # 追问一格：按证据答，接着讲到宠物
    ("What about bills?", 12),  # 再追问一格（没核对过→诚实说不知道、记下问中介），讲完第一套、第二套讲到宠物（推断）
    ("Next.", 7),  # 第三套讲到宠物（listing 写 no pets：冲突）
    ("The Alder Lane agent said pets are fine as long as we clean the carpets when we leave.", None),  # 10-26 起真房源进池子，Harrow（两个冲突）排不进前三，改转达 Alder Lane 的  # 转达中介回复：改状态、说变化
    ("Okay, go on.", None),  # 接着讲完第三套 + 收尾（含五年暴力犯罪披露的法定必问）
    ("Actually, can we keep it under 800 a week?", 4),  # 改预算：确认、重排、重新入围（890 那套掉出去）
    ("That's enough for today, thanks.", None),
]
SCENARIOS = {"short": SCRIPT, "unsw": SCRIPT_UNSW}
PERSONAS = {"short": "租客：一个人带猫，两房，近 Central", "unsw": "租客：两个 UNSW 学生带猫，两房近 UNSW，预算 900 → 改 800，转达中介回复"}


class Voices:
    def __init__(self, user_voice: str, rate: int, tts: str = "magpie", eleven_voice: Optional[str] = None, user_tts: str = "say", dry: bool = False):
        self.user_voice, self.rate = user_voice, rate
        self.user_tts = user_tts if (user_tts == "elevenlabs" and eleven.api_key()) else "say"  # 租客也可以用 ElevenLabs 的声音，整段听起来像两个真人
        self.dry = dry  # 不合成（设计场景、对台词数用），全是静音
        self.user_label = f"ElevenLabs {eleven.model()} ({user_voice})" if self.user_tts == "elevenlabs" else f"macOS say {user_voice}"
        self.cfg = None
        self.svc = None
        self.tts = tts
        self.eleven_voice = eleven_voice or eleven.voice()
        self.eleven_model = eleven.model()
        self.eleven_settings = {}
        self.mood = tone.Mood(False)  # 情绪标签只在 ElevenLabs 认标签的模型上开（和 8631 同一套规则）
        self.bot_label = f"macOS say Samantha ({rate} Hz)"
        if tts == "elevenlabs":
            if not eleven.api_key():
                print("ELEVENLABS_API_KEY 为空，退回 macOS say", file=sys.stderr)
                self.tts = "say"
            else:
                self.eleven_settings = eleven.voice_settings_from_env()
                self.mood = tone.Mood(eleven.tags_enabled(self.eleven_model))
                self.bot_label = (f"ElevenLabs {self.eleven_model} ({self.eleven_voice}, {rate} Hz"
                                  + (", tags on" if self.mood.enabled else "") + (f", settings {self.eleven_settings}" if self.eleven_settings else "") + ")")
            return
        try:
            import pipecat_app as app  # noqa: WPS433
            import riva.client  # noqa: WPS433
            cfg = app.Config.load()
            if cfg.key:
                self.svc = riva.client.SpeechSynthesisService(app._auth(cfg, cfg.tts_function_id))
                self.cfg, self.riva = cfg, riva.client
                for r in (rate, 24000, 16000):  # Magpie 认哪个采样率就用哪个
                    try:
                        self.svc.synthesize("Hello.", cfg.tts_voice, language_code=cfg.tts_language, encoding=riva.client.AudioEncoding.LINEAR_PCM, sample_rate_hz=r)
                        self.rate = r
                        break
                    except Exception as e:  # noqa: BLE001
                        print(f"Magpie at {r} Hz: {str(e)[:80]}", file=sys.stderr)
                else:
                    self.svc = None
                if self.svc is not None:
                    self.bot_label = f"Magpie {cfg.tts_voice} ({self.rate} Hz)"
        except Exception as e:  # noqa: BLE001
            print(f"Magpie unavailable ({type(e).__name__}: {str(e)[:80]}), bot lines via macOS say", file=sys.stderr)

    def user_line(self, text: str) -> bytes:
        """租客那句：--user-tts elevenlabs 用 ElevenLabs 声音（不加情绪标签），否则 macOS say。"""
        if self.dry:
            return b"\x00\x00" * int(self.rate * 0.1)
        if self.user_tts == "elevenlabs":
            try:
                return eleven.synth(text, self.user_voice, eleven.api_key(), self.eleven_model, sample_rate=self.rate, voice_settings=self.eleven_settings)
            except eleven.ElevenError as e:
                print(f"ElevenLabs (renter) failed on {text[:40]!r}: {str(e)[:100]} → say", file=sys.stderr)
        return self.user(text)

    def bot(self, text: str, spoken: Optional[str] = None) -> bytes:
        """text = 字幕里的原句；spoken = 真正送去合成的（带情绪标签），没有就同 text。"""
        if self.dry:
            return b"\x00\x00" * int(self.rate * 0.1)
        if self.tts == "elevenlabs":
            try:
                return eleven.synth(spoken or text, self.eleven_voice, eleven.api_key(), self.eleven_model, sample_rate=self.rate, voice_settings=self.eleven_settings)
            except eleven.ElevenError as e:
                print(f"ElevenLabs failed on {text[:40]!r}: {str(e)[:100]} → say", file=sys.stderr)
                return self.say(text, "Samantha")
        if self.svc is not None:
            try:
                return self.svc.synthesize(text, self.cfg.tts_voice, language_code=self.cfg.tts_language,
                                           encoding=self.riva.AudioEncoding.LINEAR_PCM, sample_rate_hz=self.rate).audio
            except Exception as e:  # noqa: BLE001
                print(f"Magpie failed on {text[:40]!r}: {str(e)[:80]} → say", file=sys.stderr)
        return self.say(text, "Samantha")

    def user(self, text: str) -> bytes:
        return self.say(text, self.user_voice)

    def say(self, text: str, voice: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            aiff, wav = Path(d) / "x.aiff", Path(d) / "x.wav"
            subprocess.run(["say", "-v", voice, "-r", "178", "-o", str(aiff), text], check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{self.rate}", "-c", "1", str(aiff), str(wav)], check=True, capture_output=True)
            with wave.open(str(wav), "rb") as w:
                return w.readframes(w.getnframes())


class Tape:
    def __init__(self, rate: int):
        self.rate, self.parts, self.cues = rate, [], []
        self.pos = 0.0

    def silence(self, secs: float) -> None:
        self.parts.append(b"\x00\x00" * int(self.rate * secs))
        self.pos += secs

    def add(self, who: str, text: str, pcm: bytes, by: str = "") -> None:
        self.cues.append((self.pos, who, by, text))
        self.parts.append(pcm)
        self.pos += len(pcm) / 2 / self.rate

    def write(self, wav: Path) -> None:
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"".join(self.parts))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None, help="输出文件名（不带后缀），默认 runs/recordings/voice_demo_<时间>")
    ap.add_argument("--template", action="store_true", help="不让模型写台词、过渡句固定（对照）")
    ap.add_argument("--user-voice", default="Daniel")
    ap.add_argument("--rate", type=int, default=22050)
    ap.add_argument("--tts", choices=["magpie", "elevenlabs"], default=(os.environ.get("TTS_PROVIDER") or "magpie").strip().lower() or "magpie")
    ap.add_argument("--eleven-voice", default=None, help="ElevenLabs 声音名字或 id，默认 .env 的 ELEVENLABS_VOICE")
    ap.add_argument("--user-tts", choices=["say", "elevenlabs"], default="say", help="租客的声音用谁合成；elevenlabs 时 --user-voice 写 ElevenLabs 的名字（如 Jessica）")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="short", help="哪套对话脚本：short（五轮）或 unsw（两个学生带猫，八轮，含追问 / 中介回复 / 改预算）")
    ap.add_argument("--dry", action="store_true", help="不合成、不出音频，只打台词和写 .md（设计场景用，零成本）")
    a = ap.parse_args()
    script = SCENARIOS[a.scenario]
    if a.template:
        os.environ["NARRATION_LLM"] = "0"
        os.environ["VOICE_VARIETY"] = "0"
    out = Path(a.out) if a.out else ROOT / "runs" / "recordings" / f"voice_demo_{dt.datetime.now():%Y%m%d_%H%M%S}"
    out.parent.mkdir(parents=True, exist_ok=True)

    voices = Voices(a.user_voice, a.rate, tts=a.tts if a.tts in ("magpie", "elevenlabs") else "magpie", eleven_voice=a.eleven_voice, user_tts=a.user_tts, dry=a.dry)
    tape = Tape(voices.rate)
    s = policy.Session("clip-" + dt.datetime.now().strftime("%H%M%S"))
    print(f"scenario: {a.scenario} ({PERSONAS[a.scenario]}) | bot voice: {voices.bot_label} | user voice: {voices.user_label} | narration: {'llm' if narrator.enabled() else 'template'}" + (" | DRY" if a.dry else ""))

    pending: List[dict] = []  # 机器人还没说出口的句子（被打断后剩下的）
    spoken_idx = -1
    spoken_listing = None
    t_run = time.time()
    for text, cap in script:
        tape.silence(GAP_CUT if pending else GAP_TURN)
        tape.add("renter", text, voices.user_line(text))
        body = {"text": text, "source": "voice", "listing_id": s.current}
        if pending:
            lid = spoken_listing or s.current
            body["listing_id"] = lid
            body["interrupted"] = {"active": True, "spoken_idx": spoken_idx, "listing_id": lid, "cut_sentence": pending[0]["text"]}
        t0 = time.time()
        events = list(s.handle_turn(body))
        cur = None
        for e in events:  # 每句话属于哪套房（打断时要报给服务端，不然"Back to the …"会报错套）
            if e.get("type") == "card":
                cur = e["listing"]["id"]
            tag = voices.mood.tag(e)  # 情绪标签：按顺序喂每个事件（highlight 带格子状态）
            if e.get("type") == "say":
                e["_listing"] = cur
                if tag:
                    e["_tag"] = tag
        says = [e for e in events if e.get("type") == "say"]
        print(f"[{time.time() - t0:5.2f} s] renter: {text!r} → {len(says)} lines ({sum(1 for e in says if e.get('by') == 'llm')} model-written)")
        take = says if cap is None else says[:cap]
        pending = says[len(take):]
        tape.silence(GAP_TURN)
        for k, e in enumerate(take):
            if k:
                tape.silence(GAP_LINE)
            spoken = f"{e['_tag']} {e['text']}" if e.get("_tag") else None
            tape.add("hometruth", e["text"], voices.bot(e["text"], spoken), e.get("by", "template") + (f" {e['_tag']}" if e.get("_tag") else ""))
            if e.get("idx") is not None:  # 导览句带 idx（打断后从这里接着讲）；过渡句 / 反问没有
                spoken_idx = e["idx"]
            if e.get("_listing"):
                spoken_listing = e["_listing"]
            print(f"      {'LLM ' if e.get('by') == 'llm' else 'tmpl'} {e.get('step', ''):12} {e.get('_tag', ''):13}{e['text']}")
    tape.silence(0.8)

    wav = out.with_suffix(".wav")
    m4a = out.with_suffix(".m4a")
    if not a.dry:
        tape.write(wav)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "64000", str(wav), str(m4a)], check=True, capture_output=True)  # 22.05 kHz 单声道最高 64 kbps
    lines = [f"# 语音导览演示录音 {dt.datetime.now():%Y-%m-%d %H:%M}", "",
             f"- 场景：{a.scenario}（{PERSONAS[a.scenario]}）",
             f"- 机器人声音：{voices.bot_label}；租客声音：{voices.user_label}（录音里的「租客」是合成的，不是真人）",
             f"- 台词：{'模型写（Nemotron 经 Nightshift）+ 规则审，过不了审的用模板' if narrator.enabled() else '全模板（对照）'}；"
             f"模型调用 {narrator.STATS['calls']} 次，过审 {narrator.STATS['accepted']} 行，拒 {narrator.STATS['rejected']}，照抄 {narrator.STATS['copied']}，失败 {narrator.STATS['failed']}，超时 {narrator.STATS['timeouts']}",
             f"- 时长 {tape.pos:.1f} s；生成用时 {time.time() - t_run:.0f} s；文件 {m4a.name} / {wav.name}", "",
             "| 时间 | 谁 | 来源 | 句子 |", "|---|---|---|---|"]
    for pos, who, by, text in tape.cues:
        lines.append(f"| {int(pos // 60)}:{pos % 60:04.1f} | {who} | {by or '-'} | {text.replace('|', '/')} |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {out.with_suffix('.md').name}" + ("" if a.dry else f", {m4a} ({tape.pos:.1f} s), {wav.name}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
