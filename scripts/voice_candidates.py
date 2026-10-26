#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选声音对比：同一段话，每个声音各录一句，拼成一个带编号报幕的对比音频（给人挑声音用）。

Magpie 多语种模型（8631 现在用的）的英文声线有 Mia / Jason / Aria / Leo / Sofia / Ray，每个还有 .Neutral / .Calm / .Angry / .Sad 等情绪变体
（服务端 GetRivaSynthesisConfig 查到的 subvoices；声音名写成 Magpie-Multilingual.EN-US.<名字>[.<情绪>]）。macOS say 的声音也能放进来对比（--say）。

跑：.venv/bin/python scripts/voice_candidates.py --name base --voices Aria,Mia,Sofia,Jason,Leo,Ray
    .venv/bin/python scripts/voice_candidates.py --name calm --voices Aria.Calm,Mia.Calm,Sofia.Calm,Jason.Calm,Leo.Calm,Ray.Calm
    .venv/bin/python scripts/voice_candidates.py --name eleven --voices "" --eleven Charlie,Sarah,George,Matilda,Daniel,Lily（要 .env 里的 ELEVENLABS_API_KEY）
    .venv/bin/python scripts/voice_candidates.py --list（列出 ElevenLabs 账户里全部声音和模型）
    可加 --say Karen,Samantha（本机声音）、--text "..."（换句子）、--eleven-model eleven_multilingual_v2。
输出：runs/recordings/voices/<name>.m4a（报幕 "Number 1, Aria." + 句子，依次）、<name>.md（编号、声音、合成用时、单个文件名）、每个声音单独的 <声音>.m4a。
"""
from __future__ import annotations

import argparse
import datetime as dt
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

DEFAULT_TEXT = ("First up: a two-bedroom on 31 Fenwick Street, Zetland, 890 a week. "
                "Rent sits inside your 900 budget, so that one checks out. Pets are allowed with the owners corporation's written consent.")
RATE = 22050


def say_pcm(text: str, voice: str, rate: int) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = Path(d) / "x.aiff", Path(d) / "x.wav"
        subprocess.run(["say", "-v", voice, "-r", "178", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", str(aiff), str(wav)], check=True, capture_output=True)
        with wave.open(str(wav), "rb") as w:
            return w.readframes(w.getnframes())


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def to_m4a(wav: Path) -> Path:
    m4a = wav.with_suffix(".m4a")
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "64000", str(wav), str(m4a)], check=True, capture_output=True)
    return m4a


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", default="candidates")
    ap.add_argument("--voices", default="Aria,Mia,Sofia,Jason,Leo,Ray", help="Magpie EN-US 声线，逗号分开；可带情绪后缀，如 Aria.Calm；空串 = 不录 Magpie")
    ap.add_argument("--say", default="", help="macOS say 的声音，逗号分开，如 Karen,Samantha")
    ap.add_argument("--eleven", default="", help="ElevenLabs 的声音（名字或 voice_id），逗号分开，如 Charlie,Sarah；写 Charlie@eleven_turbo_v2_5 可以给单个声音指定模型；要 ELEVENLABS_API_KEY")
    ap.add_argument("--eleven-model", default=None, help="ElevenLabs 模型，默认 .env 的 ELEVENLABS_MODEL 或 eleven_flash_v2_5")
    ap.add_argument("--list", action="store_true", help="只列出 ElevenLabs 账户里的声音和模型，不录")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--label-voice", default="Samantha", help="报幕用的本机声音")
    ap.add_argument("--out-dir", default=str(ROOT / "runs" / "recordings" / "voices"))
    a = ap.parse_args()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if a.list:
        key = eleven.api_key()
        if not key:
            print("ELEVENLABS_API_KEY 为空：elevenlabs.io → 头像 → API Keys → Create，粘进 .env", file=sys.stderr)
            return 2
        try:
            try:
                sub = eleven.subscription(key)
                print(f"account: tier {sub.get('tier')}, {sub.get('used')}/{sub.get('limit')} characters used this month")
            except eleven.ElevenError as e:
                if not eleven.missing_permission(e):
                    raise
                print("account: (this key has no user_read permission, so the quota can't be read here; see elevenlabs.io → Usage)")
            print("models:")
            for m in eleven.list_models(key):
                if m["tts"]:
                    print(f"   {m['model_id']:28} {m['name']} ({m['languages']} languages)")
            print("voices:")
            for v in eleven.list_voices(key):
                lab = v["labels"]
                print(f"   {eleven.short_name(v['name']):10} {v['voice_id']}  {v['category']:9} {lab.get('accent', '')} {lab.get('gender', '')} {lab.get('age', '')} {lab.get('description', '')} {lab.get('use_case', '')}  [{v['name']}]".rstrip())
        except eleven.ElevenError as e:
            print(f"ElevenLabs: {e}", file=sys.stderr)
            return 1
        return 0

    items: List[Tuple[str, str]] = [(f"Magpie-Multilingual.EN-US.{v.strip()}", "magpie") for v in a.voices.split(",") if v.strip()]
    items += [(v.strip(), "say") for v in a.say.split(",") if v.strip()]
    items += [(v.strip(), "eleven") for v in a.eleven.split(",") if v.strip()]
    if any(kind == "eleven" for _, kind in items) and not eleven.api_key():
        print("要录 ElevenLabs 得先把 ELEVENLABS_API_KEY 放进 .env（elevenlabs.io → 头像 → API Keys → Create）", file=sys.stderr)
        return 2

    svc = cfg = riva = None
    if any(kind == "magpie" for _, kind in items):
        import pipecat_app as app  # noqa: WPS433
        import riva.client as riva  # noqa: WPS433
        cfg = app.Config.load()
        if not cfg.key:
            print("NVIDIA_API_KEY 为空，录不了 Magpie", file=sys.stderr)
            return 2
        svc = riva.SpeechSynthesisService(app._auth(cfg, cfg.tts_function_id))

    silence = lambda s: b"\x00\x00" * int(RATE * s)  # noqa: E731
    parts: List[bytes] = []
    rows = []
    for n, (voice, kind) in enumerate(items, 1):
        t0 = time.time()
        try:
            if kind == "magpie":
                pcm = svc.synthesize(a.text, voice, language_code="en-US", encoding=riva.AudioEncoding.LINEAR_PCM, sample_rate_hz=RATE).audio
            elif kind == "eleven":
                vname, _, vmodel = voice.partition("@")
                pcm = eleven.synth(a.text, vname, eleven.api_key(), vmodel or a.eleven_model, sample_rate=RATE, voice_settings=eleven.voice_settings_from_env())
            else:
                pcm = say_pcm(a.text, voice, RATE)
        except Exception as e:  # noqa: BLE001
            print(f"{n:2d} {voice}: FAILED {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            rows.append((n, voice, kind, None, None))
            continue
        ms = int((time.time() - t0) * 1000)
        short = voice.split("EN-US.")[-1] if kind == "magpie" else (f"ElevenLabs {voice.replace('@', ' ')}" if kind == "eleven" else f"macOS {voice}")
        wav = out_dir / f"{short.replace(' ', '_')}.wav"
        write_wav(wav, pcm, RATE)
        m4a = to_m4a(wav)
        wav.unlink()
        secs = len(pcm) / 2 / RATE
        rows.append((n, voice, kind, ms, m4a.name))
        print(f"{n:2d} {short:18} {secs:4.1f} s audio, synth {ms} ms → {m4a.name}")
        spoken = short.replace(".", ", ").replace("eleven_", "model ").replace("_", " ")
        label = say_pcm(f"Number {n}, {spoken}.", a.label_voice, RATE)
        parts += [silence(0.6), label, silence(0.5), pcm, silence(0.9)]

    combined_wav = out_dir / f"{a.name}.wav"
    write_wav(combined_wav, b"".join(parts), RATE)
    combined = to_m4a(combined_wav)
    combined_wav.unlink()
    total = sum(len(p) for p in parts) / 2 / RATE
    md = [f"# 候选声音对比 · {a.name} · {dt.datetime.now():%Y-%m-%d %H:%M}", "",
          f"句子：{a.text}", "", f"合成一遍文件：{combined.name}（{total:.0f} s，每段前面有本机 {a.label_voice} 报编号）", "",
          "| 编号 | 声音 | 来源 | 合成用时 | 单独文件 |", "|---|---|---|---|---|"]
    for n, voice, kind, ms, fn in rows:
        src = {"magpie": "Magpie（NVIDIA，8631 默认）", "eleven": f"ElevenLabs（{voice.partition('@')[2] or a.eleven_model or eleven.model()}）", "say": "macOS say（本机，8630 用的那种）"}[kind]
        md.append(f"| {n} | {voice} | {src} | {ms if ms is not None else 'FAILED'} ms | {fn or '-'} |")
    md.append("")
    md.append("切换：8631 在 .env 里改 `MAGPIE_VOICE=Magpie-Multilingual.EN-US.<声音>[.<情绪>]` 后重启；按句缓存按声音分开存，换声音后固定句会在后台重新预热。"
              " 换 ElevenLabs：`TTS_PROVIDER=elevenlabs` + `ELEVENLABS_VOICE=<名字或 id>`，重启 8631。")
    (out_dir / f"{a.name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nwrote {combined} ({total:.0f} s) and {a.name}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
