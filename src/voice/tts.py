"""句级语音合成，后端可换：say（本机，调试用）/ openai / elevenlabs / browser（交给浏览器）。
Magpie（NVIDIA）走 gRPC，等拿到 key 后用 Pipecat 接，不在这里。结果按 sha1(后端+声音+送去合成的文本+声音参数) 缓存到 runs/tts_cache。
ElevenLabs 时和 8631 一样：句首按这句在流程里的位置加情绪标签（tone.py，只进嘴）、带 .env 里的声音参数（eleven.voice_settings_from_env）。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

import eleven
import tone

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "runs" / "tts_cache"
PREFERRED = ["Karen", "Samantha", "Daniel", "Moira", "Tessa", "Rishi"]
_voices: Optional[list] = None


def backend() -> str:
    b = os.environ.get("TTS_BACKEND", "auto")
    if b != "auto":
        return b
    if os.environ.get("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if shutil.which("say"):
        return "say"
    return "browser"


def mac_voices() -> list:
    global _voices
    if _voices is None:
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
            _voices = [line.split()[0] for line in out.splitlines() if line.strip()]
        except Exception:
            _voices = []
    return _voices


def voice_name() -> str:
    b = backend()
    if b == "say":
        want = os.environ.get("TTS_VOICE")
        if want and want in mac_voices():
            return want
        for v in PREFERRED:
            if v in mac_voices():
                return v
        return "Samantha"
    if b == "openai":
        return os.environ.get("OPENAI_TTS_VOICE", "coral")
    if b == "elevenlabs":  # same voice as 8631: ELEVENLABS_VOICE is a name (Sarah), looked up once and cached by eleven.py
        vid = os.environ.get("ELEVENLABS_VOICE_ID")
        if vid:
            return vid
        name = os.environ.get("ELEVENLABS_VOICE")
        if name:
            try:
                return eleven.voice_id(name, os.environ["ELEVENLABS_API_KEY"])
            except Exception:  # noqa: BLE001 — no network or unknown name: fall back to the default voice
                pass
        return "21m00Tcm4TlvDq8ikWAM"
    return "browser"


def voice_label() -> str:
    """给人看的声音名（/api/hello 和启动行）：ElevenLabs 时是名字而不是 id。"""
    b = backend()
    if b == "elevenlabs":
        return os.environ.get("ELEVENLABS_VOICE") or eleven.voice()
    return voice_name()


def speak_text(text: str, step: Optional[str] = None, status: Optional[str] = None) -> str:
    """送去合成的文本：ElevenLabs 且模型认标签时，句首按 step / 格子状态加情绪标签（tone.py）；别的后端原句。"""
    if backend() != "elevenlabs" or not eleven.tags_enabled(eleven.model()):
        return text
    t = tone.tag_for(step or "", text, status or None)
    return f"{t} {text}" if t else text


def synthesize(text: str, voice: Optional[str] = None, step: Optional[str] = None, status: Optional[str] = None) -> Tuple[Optional[bytes], str]:
    """返回 (音频字节, content-type)。browser 后端返回 (None, '')，由浏览器自己合成。step / status 只影响 ElevenLabs 的情绪标签。"""
    b = backend()
    if b == "browser":
        return None, ""
    voice = voice or voice_name()
    speak = speak_text(text, step, status)
    settings = eleven.voice_settings_from_env() if b == "elevenlabs" else {}
    model = eleven.model() if b == "elevenlabs" else ""
    key = hashlib.sha1(f"{b}|{voice}|{model}|{json.dumps(settings, sort_keys=True) if settings else ''}|{speak}".encode("utf-8")).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    ext = "wav" if b == "say" else "mp3"
    ctype = "audio/wav" if b == "say" else "audio/mpeg"
    out = CACHE / f"{key}.{ext}"
    if out.exists():
        return out.read_bytes(), ctype
    if b == "say":
        data = _say(text, voice, CACHE / f"{key}.aiff", out)
    elif b == "openai":
        data = _openai(text, voice)
    elif b == "elevenlabs":
        data = _elevenlabs(speak, voice, settings)
    else:
        raise RuntimeError(f"unknown TTS_BACKEND {b}")
    out.write_bytes(data)
    return data, ctype


def _say(text: str, voice: str, aiff: Path, wav: Path) -> bytes:
    rate = os.environ.get("TTS_RATE", "180")
    subprocess.run(["say", "-v", voice, "-r", rate, "-o", str(aiff), text], check=True, timeout=60)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", str(aiff), str(wav)], check=True, timeout=60)
    try:
        aiff.unlink()
    except OSError:
        pass
    return wav.read_bytes()


def _post(url: str, headers: dict, body: dict, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _openai(text: str, voice: str) -> bytes:  # 未实测：本机没有 key
    return _post(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/audio/speech",
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        {"model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice, "input": text, "response_format": "mp3"},
    )


def _elevenlabs(text: str, voice_id: str, settings: Optional[dict] = None) -> bytes:
    """单句整段合成（mp3）。模型、声音参数和 8631 读同一套环境变量；text 已经带情绪标签。"""
    body = {"text": text, "model_id": eleven.model()}
    if settings:
        body["voice_settings"] = dict(settings)
    return _post(f"{eleven.base_url()}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128", {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, body)
