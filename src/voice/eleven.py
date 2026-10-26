# -*- coding: utf-8 -*-
"""ElevenLabs 合成的小工具（不依赖 Pipecat）：列声音 / 列模型 / 名字→voice_id / 单句合成 / 账户额度。
8631 的管线用 Pipecat 自带的 ElevenLabsTTSService 流式合成；这里只负责启动前把声音名字换成 id、自检，和脚本里的单句合成（录对比用）。
key 只从环境变量 ELEVENLABS_API_KEY 读（放 .env，不进仓库）。ELEVENLABS_BASE_URL 只在测试里改（指向假服务器）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "runs" / "tts_cache" / "elevenlabs_voices.json"
DEFAULT_MODEL = "eleven_v4_turbo"  # 最有情绪、低延迟、认情绪标签；要最快就 eleven_flash_v2_5（语气平）
TAG_FAMILIES = ("eleven_v3", "eleven_v4")  # 认 [happy] / [thoughtful] 这类标签的模型；它们不上 TTS WebSocket，走 HTTP 流式  # 最快的一档（首块约 75 ms）；eleven_turbo_v2_5 折中；eleven_multilingual_v2 最像人但慢
DEFAULT_VOICE = "Charlie"  # ElevenLabs 自带声音里的澳洲口音男声；用户听完对比再定
ID_RE = re.compile(r"^[A-Za-z0-9]{15,40}$")
_MEM: Dict[str, List[dict]] = {}


class ElevenError(RuntimeError):
    pass


def missing_permission(err: Exception) -> bool:
    """key 少了某个权限（ElevenLabs 建 key 时可以只勾部分权限），返回 401 + missing_permissions。"""
    return "missing_permissions" in str(err) or "missing the permission" in str(err)


def base_url() -> str:
    return (os.environ.get("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io").rstrip("/")


def api_key() -> str:
    return (os.environ.get("ELEVENLABS_API_KEY") or "").strip()


def model() -> str:
    return (os.environ.get("ELEVENLABS_MODEL") or DEFAULT_MODEL).strip()


def voice() -> str:
    return (os.environ.get("ELEVENLABS_VOICE") or DEFAULT_VOICE).strip()


def _request(path: str, *, key: str, body: Optional[dict] = None, timeout: float = 20.0) -> bytes:
    if not key:
        raise ElevenError("ELEVENLABS_API_KEY is empty")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise ElevenError(f"HTTP {e.code} on {path.split('?')[0]}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ElevenError(f"{path.split('?')[0]}: {e}") from None


def list_voices(key: str) -> List[dict]:
    """账户能用的声音：自带的（premade）+ 自己库里的。只留名字、id 和几个标签。"""
    data = json.loads(_request("/v1/voices", key=key))
    out = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        out.append({"voice_id": v.get("voice_id", ""), "name": v.get("name", ""), "category": v.get("category", ""),
                    "labels": {k: labels[k] for k in ("accent", "gender", "age", "description", "use_case") if labels.get(k)}})
    return out


def list_models(key: str) -> List[dict]:
    data = json.loads(_request("/v1/models", key=key))
    return [{"model_id": m.get("model_id", ""), "name": m.get("name", ""), "tts": bool(m.get("can_do_text_to_speech")),
             "languages": len(m.get("languages") or [])} for m in data if isinstance(m, dict)]


def subscription(key: str) -> dict:
    d = json.loads(_request("/v1/user/subscription", key=key))
    return {"tier": d.get("tier"), "used": d.get("character_count"), "limit": d.get("character_limit")}


def _voices_cached(key: str, refresh: bool = False) -> List[dict]:
    if not refresh and key in _MEM:
        return _MEM[key]
    if not refresh and CACHE.exists() and time.time() - CACHE.stat().st_mtime < 7 * 86400:
        try:
            table = json.loads(CACHE.read_text(encoding="utf-8"))
            if isinstance(table, list) and table:
                _MEM[key] = table
                return table
        except ValueError:
            pass
    table = list_voices(key)
    _MEM[key] = table
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return table


def voice_id(name_or_id: str, key: str, refresh: bool = False) -> str:
    """名字（Charlie）或 voice_id 都行。名字用 /v1/voices 查，结果缓存 7 天（runs/tts_cache/elevenlabs_voices.json）；没查到就当它是 id。"""
    s = (name_or_id or "").strip()
    if not s:
        raise ElevenError("ELEVENLABS_VOICE is empty")
    table = _voices_cached(key, refresh)
    for v in table:
        if v["voice_id"] == s or v["name"].lower() == s.lower() or short_name(v["name"]).lower() == s.lower():
            return v["voice_id"]
    if not refresh:
        return voice_id(s, key, refresh=True)  # 新加的声音还没进缓存
    if ID_RE.match(s):
        return s
    names = ", ".join(sorted(short_name(v["name"]) for v in table if v.get("name")))[:500]
    raise ElevenError(f"voice {s!r} not found in this account; available: {names}")


def short_name(name: str) -> str:
    """账户里自带声音的名字长这样：「Charlie - Deep, Confident, Energetic」；短名就是破折号前面那截。"""
    return (name or "").split(" - ", 1)[0].strip()


def supports_tags(model_id: Optional[str]) -> bool:
    """这个模型认句首的情绪标签吗（v3 / v4 系列认；flash / turbo / multilingual 不认，会把标签念出来或忽略）。"""
    return (model_id or "").startswith(TAG_FAMILIES)


def streams_over_websocket(model_id: Optional[str]) -> bool:
    """能走 TTS WebSocket（/stream-input）吗。v3 / v4 系列服务端回 400 unsupported_model，只能走 HTTP 流式。"""
    return not supports_tags(model_id)


def accepts_context(model_id: Optional[str]) -> bool:
    """接受 previous_text / next_text 上下文吗（v3 系列不接受，v4 接受）。"""
    return not (model_id or "").startswith("eleven_v3")


def tags_enabled(model_id: Optional[str] = None) -> bool:
    """ELEVENLABS_TAGS：auto（默认）= 模型认就加；1 强制加；0 关。"""
    v = (os.environ.get("ELEVENLABS_TAGS") or "auto").strip().lower()
    if v in ("0", "off", "no", "false"):
        return False
    if v in ("1", "on", "yes", "true"):
        return True
    return supports_tags(model_id or model())


SETTING_ENVS = [("ELEVENLABS_STABILITY", "stability", 0.0, 1.0), ("ELEVENLABS_SIMILARITY", "similarity_boost", 0.0, 1.0),
                ("ELEVENLABS_STYLE", "style", 0.0, 1.0), ("ELEVENLABS_SPEED", "speed", 0.7, 1.2)]


def voice_settings_from_env() -> dict:
    """声音参数，只带 .env 里填了的；都留空就不发（用 ElevenLabs 默认）。填错范围报 ElevenError。"""
    out = {}
    for env_name, key, lo, hi in SETTING_ENVS:
        raw = (os.environ.get(env_name) or "").strip()
        if not raw:
            continue
        try:
            val = float(raw)
        except ValueError:
            raise ElevenError(f"{env_name} must be a number between {lo:g} and {hi:g}, got {raw!r}")
        if not lo <= val <= hi:
            raise ElevenError(f"{env_name} must be between {lo:g} and {hi:g}, got {raw}")
        out[key] = val
    boost = (os.environ.get("ELEVENLABS_SPEAKER_BOOST") or "").strip().lower()
    if boost in ("1", "on", "true", "yes"):
        out["use_speaker_boost"] = True
    elif boost in ("0", "off", "false", "no"):
        out["use_speaker_boost"] = False
    return out


def synth(text: str, voice_name_or_id: str, key: str, model_id: Optional[str] = None, sample_rate: int = 22050, timeout: float = 30.0,
          voice_settings: Optional[dict] = None) -> bytes:
    """单句整段合成，返回 16 位单声道 PCM（采样率 sample_rate，pcm_16000 / 22050 / 24000 / 44100 之一）。
    text 里可以带句首情绪标签（认标签的模型才有用，见 tone.py）；voice_settings 见 voice_settings_from_env。"""
    vid = voice_id(voice_name_or_id, key)
    body = {"text": text, "model_id": model_id or model()}
    if voice_settings:
        body["voice_settings"] = dict(voice_settings)
    return _request(f"/v1/text-to-speech/{vid}?output_format=pcm_{int(sample_rate)}", key=key, body=body, timeout=timeout)
