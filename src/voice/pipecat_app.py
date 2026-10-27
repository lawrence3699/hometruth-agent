#!/usr/bin/env python3
"""HomeTruth 语音导览 · Pipecat 版：浏览器麦克风 →（WebRTC）→ Silero VAD → NVIDIA 识别 → 我们的"脑"（policy.Session）→ NVIDIA Magpie 合成 →（WebRTC）→ 浏览器。

和 server.py（浏览器版，8630）共用同一个 policy.Session：需求解析、反问、开查、导览、打断后怎么接，全在 policy.py；这里只管"听、说、打断"。
跑（先建 .venv，见 requirements-voice.txt 顶部）：
  .venv/bin/python src/voice/pipecat_app.py                → http://127.0.0.1:8631（要 NVIDIA_API_KEY）
  .venv/bin/python src/voice/pipecat_app.py --fake-speech  → 没 key 也能演示：不开识别（打字代替说话），合成用 macOS say；WebRTC、打断、事件和播音同步都是真的
  .venv/bin/python src/voice/pipecat_app.py --dry-run      → 不连任何服务：验证导入、配置、管线能搭起来，打印还缺什么
  .venv/bin/python src/voice/pipecat_app.py --check        → dry-run + 有 key 时真连一次 Magpie 合成和 Parakeet 识别（scripts/check_nvidia.py 调它）
环境变量（项目根目录 .env，说明见 .env.example）：NVIDIA_API_KEY、NVIDIA_RIVA_SERVER、NVIDIA_ASR_FUNCTION_ID、NVIDIA_ASR_MODEL、
  MAGPIE_FUNCTION_ID、MAGPIE_MODEL、MAGPIE_VOICE、MAGPIE_LANGUAGE、MAGPIE_TTS_CACHE（默认 1：按句缓存合成，固定句子预热）、VOICE_INTERRUPT_MIN_WORDS（默认 2：机器说话时至少两个词、而且不是它自己的回声才算打断；0 = 一有人声就打断）、
  SMART_TURN（默认 1：smart-turn v3 判断说完没）、SMART_TURN_STOP_SECS（默认 1.2）、NARRATION_LLM / NARRATION_LLM_TIMEOUT（台词交给模型写，见 narrator.py）、
  PIPECAT_HOST、PIPECAT_PORT、PIPECAT_ICE_SERVERS、PIPECAT_LOG。

和前端（static/pipecat.html）的约定：
  我们的事件（needs/source/card/highlight/evidence/change/say/state/done/error，格式同 server.py 的 SSE）原样作为 RTVI server-message 发出。
  除 error 外都是"有序"消息：排在前一句话的音频后面才发，所以卡片、高亮和说话对得上；打断时没播的事件连同音频一起丢掉。
  打字：client-message 类型 hometruth-text，数据 {text}；正在说话时打字等于打断（和浏览器版一样）。
  停（Stop 按钮、Esc）：hometruth-stop，停下但记住说到哪，说 "continue" 接着讲。重新开始：hometruth-reset。
"""
import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import importlib.metadata
import io
import json
import os
import re
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from llm import provider as llm  # noqa: E402  标准库实现；顺便负责读 .env

llm.load_env()

import narrator  # noqa: E402
import phraser  # noqa: E402
import inbox  # noqa: E402  中介回复的收件箱：runs/inbox/<renter>.jsonl（/api/inbox）
import memory  # noqa: E402  欢迎回来：runs/memory/<renter>.json
import policy  # noqa: E402
import zetaris_live  # noqa: E402
import tts as mac_tts  # noqa: E402  只在 --fake-speech 用：macOS say + runs/tts_cache
import eleven
import tone  # noqa: E402  嘴可切换：TTS_PROVIDER=elevenlabs 时用

CHECK_ROW = "Pipecat pipeline (dry-run)"
if {"--dry-run", "--check"} & set(sys.argv):
    os.environ.setdefault("LOGURU_LEVEL", "WARNING")  # 自检时不要 Pipecat 导入时的横幅
try:
    from loguru import logger
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        DataFrame,
        ErrorFrame,
        Frame,
        InterimTranscriptionFrame,
        InterruptionFrame,
        OutputTransportMessageFrame,
        OutputTransportMessageUrgentFrame,
        StartFrame,
        TranscriptionFrame,
        TTSAudioRawFrame,
        TTSSpeakFrame,
        TTSStartedFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.processors.frameworks.rtvi.frames import RTVIClientMessageFrame
    from pipecat.processors.frameworks.rtvi.models import MESSAGE_LABEL
    from pipecat.services.nvidia.stt import NvidiaSTTService
    from pipecat.services.nvidia.tts import NvidiaTTSService
    from pipecat.services.settings import TTSSettings
    from pipecat.services.tts_service import TTSService
    from pipecat.transcriptions.language import Language
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCPatchRequest, SmallWebRTCRequest, SmallWebRTCRequestHandler
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.turns.user_start import MinWordsUserTurnStartStrategy, VADUserTurnStartStrategy
    from pipecat.turns.types import ProcessFrameResult
    from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
    from pipecat.turns.user_turn_processor import UserTurnProcessor
    from pipecat.turns.user_turn_strategies import UserTurnStrategies
    from pipecat.workers.runner import WorkerRunner
    try:  # 轮次检测模型（smart-turn v3，随 pipecat 自带的 ONNX 文件，本机 CPU 跑）；装不全就退回固定静音秒数
        from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
        from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
    except ImportError:
        SmartTurnParams = LocalSmartTurnAnalyzerV3 = TurnAnalyzerUserTurnStopStrategy = None  # type: ignore[assignment]
except ImportError as e:  # 用了系统 python3，或者 .venv 没装好
    print(f"FAIL  {CHECK_ROW:34} 导入失败（{e}）：用 .venv/bin/python 跑；没有 .venv 按 requirements-voice.txt 顶部装", flush=True)
    sys.exit(2)

# function id 是 NVIDIA 托管部署的编号，从 build.nvidia.com 各模型页的 API 示例里抄（2026-10-25 核对）；NVIDIA 重新部署会变，变了只改 .env。
ASR_FUNCTION_ID = "1598d209-5e27-4d3c-8079-4751568b1081"  # nvidia/parakeet-ctc-1_1b-asr（英文、流式）
ASR_MODEL = "parakeet-ctc-1.1b-asr"
TTS_FUNCTION_ID = "877104f7-e885-42b9-8de8-f6e4c6303969"  # nvidia/magpie-tts-multilingual
TTS_MODEL = "magpie-tts-multilingual"
TTS_VOICE = "Magpie-Multilingual.EN-US.Aria"
RIVA_SERVER = "grpc.nvcf.nvidia.com:443"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CHECK_SENTENCE = "Two bedrooms near Central, under nine hundred a week."
VOICE_LOG = ROOT / "runs" / "voice_log.jsonl"
TTS_CACHE_DIR = ROOT / "runs" / "tts_cache" / "magpie"  # Magpie 按句缓存的 PCM（提速二）
# 和 static/app.js 的 FILLERS 一样：打断后只听到这些词，当误触发
FILLERS = {"yeah", "yes", "ok", "okay", "mm", "mhm", "uh", "huh", "right", "sure", "cool", "got", "it", "i", "see", "alright", "fine", "yep",
           "yup", "hmm", "oh", "ah", "nice", "great", "good", "thanks", "thank", "you", "aha", "hm", "yea", "mmm"}


@dataclass
class Config:
    fake_speech: bool
    key: str
    server: str
    asr_function_id: str
    asr_model: str
    tts_function_id: str
    tts_model: str
    tts_voice: str
    tts_language: str
    min_words: int
    host: str
    port: int
    ice_servers: List[str] = field(default_factory=list)
    turn_key_id: str = ""  # Cloudflare Realtime TURN key（CF_TURN_KEY_ID / CF_TURN_API_TOKEN）：有就向 Cloudflare 领短期 TURN 凭据给两端（校园网那台在 NAT 后面）；没有就只用 PIPECAT_ICE_SERVERS 里的 STUN
    turn_token: str = ""
    turn_ttl: int = 86400
    tts_cache: bool = True
    tts_provider: str = "magpie"  # 嘴用谁：magpie（默认，NVIDIA Riva）或 elevenlabs（第三方，要 ELEVENLABS_API_KEY）
    eleven_key: str = ""
    eleven_voice: str = ""
    eleven_model: str = ""
    eleven_tags: bool = False  # 句首情绪标签（tone.py）：ELEVENLABS_TAGS=auto 时 v3 / v4 模型开
    eleven_settings: dict = field(default_factory=dict)  # ELEVENLABS_STABILITY / SIMILARITY / STYLE / SPEED / SPEAKER_BOOST，只带填了的
    eleven_settings_error: str = ""
    smart_turn: bool = True  # SMART_TURN=0 退回固定静音秒数
    smart_turn_stop_secs: float = 1.2  # 模型拿不准时最多等这么久的静音

    @classmethod
    def load(cls, fake_speech: bool = False) -> "Config":
        env = os.environ.get
        try:
            min_words = max(0, int(env("VOICE_INTERRUPT_MIN_WORDS") or 2))
        except ValueError:
            min_words = 2
        return cls(fake_speech=fake_speech, key=llm.nvidia_config().key, server=env("NVIDIA_RIVA_SERVER") or RIVA_SERVER,
                   asr_function_id=env("NVIDIA_ASR_FUNCTION_ID") or ASR_FUNCTION_ID, asr_model=env("NVIDIA_ASR_MODEL") or ASR_MODEL,
                   tts_function_id=env("MAGPIE_FUNCTION_ID") or TTS_FUNCTION_ID, tts_model=env("MAGPIE_MODEL") or TTS_MODEL,
                   tts_voice=env("MAGPIE_VOICE") or TTS_VOICE, tts_language=env("MAGPIE_LANGUAGE") or "en-US", min_words=min_words,
                   host=env("PIPECAT_HOST") or "127.0.0.1", port=int(env("PIPECAT_PORT") or 8631),
                   ice_servers=[s.strip() for s in (env("PIPECAT_ICE_SERVERS") or "").split(",") if s.strip()],
                   turn_key_id=(env("CF_TURN_KEY_ID") or "").strip(), turn_token=(env("CF_TURN_API_TOKEN") or "").strip(), turn_ttl=int(env("CF_TURN_TTL") or 86400),
                   tts_cache=(env("MAGPIE_TTS_CACHE") or "1").strip().lower() not in ("0", "off", "false", "no"),
                   tts_provider=(env("TTS_PROVIDER") or "magpie").strip().lower(), eleven_key=eleven.api_key(), eleven_voice=eleven.voice(), eleven_model=eleven.model(),
                   eleven_tags=eleven.tags_enabled(eleven.model()), eleven_settings=_eleven_settings()[0], eleven_settings_error=_eleven_settings()[1],
                   smart_turn=(env("SMART_TURN") or "1").strip().lower() not in ("0", "off", "false", "no"),
                   smart_turn_stop_secs=float(env("SMART_TURN_STOP_SECS") or 1.2))

    def problems(self) -> List[str]:
        """真语音版还缺什么（人话，不含 key 本身）。"""
        out = []
        if not self.key:
            out.append("NVIDIA_API_KEY 为空或不是 nvapi- 开头（build.nvidia.com 右上角生成）")
        for name, v in (("NVIDIA_ASR_FUNCTION_ID", self.asr_function_id), ("MAGPIE_FUNCTION_ID", self.tts_function_id)):
            if not UUID.match(v):
                out.append(f"{name} 不像 function id：{v!r}")
        if self.tts_language not in {x.value for x in Language}:
            out.append(f"MAGPIE_LANGUAGE 不认识：{self.tts_language!r}（例：en-US）")
        if self.tts_provider not in ("magpie", "elevenlabs"):
            out.append(f"TTS_PROVIDER 只能是 magpie 或 elevenlabs：{self.tts_provider!r}")
        if self.eleven_settings_error:
            out.append(f"ElevenLabs 声音参数：{self.eleven_settings_error}")
        if self.tts_provider == "elevenlabs" and not self.eleven_key:
            out.append("ELEVENLABS_API_KEY 为空（elevenlabs.io 右上角头像 → API Keys → Create，粘进 .env）")
        return out

    def describe(self) -> dict:
        stt = "none (typing only)" if self.fake_speech else f"NVIDIA {self.asr_model}"
        return {"mode": "fake-speech" if self.fake_speech else "nvidia", "stt": stt, "tts": tts_label(self),
                "interrupt": f"after {self.min_words} words while it speaks (own echo ignored), 1 word when silent" if self.min_words and not self.fake_speech else "on voice (VAD)",
                "turn": turn_label(self), "narration": "llm" if narrator.enabled() else "template",
                "ice": "cloudflare-turn" if (self.turn_key_id and self.turn_token) else ("turn" if any(u.lower().startswith("turn") for u in self.ice_servers) else ("stun" if self.ice_servers else "none"))}


def tts_label(cfg: "Config") -> str:
    if cfg.fake_speech:
        return f"macOS say ({mac_tts.voice_name()})"
    if cfg.tts_provider == "elevenlabs":
        extra = (", tags on" if cfg.eleven_tags else "") + ("" if eleven.streams_over_websocket(cfg.eleven_model) else ", HTTP stream") + ("" if cfg.eleven_key else ", NO KEY")
        return f"ElevenLabs {cfg.eleven_model} ({cfg.eleven_voice}{extra})"
    return f"NVIDIA {cfg.tts_model} ({cfg.tts_voice})" + (", sentence cache on" if cfg.tts_cache else "")


def make_speaker(cfg: "Config"):
    """嘴：按 TTS_PROVIDER 造合成器。magpie（默认）= NVIDIA Riva 流式 + 按句缓存；elevenlabs = Pipecat 自带的 ElevenLabs WebSocket 流式服务
    （声音名字在这里换成 voice_id，查一次缓存 7 天）。识别、脑子、界面都不受这个选择影响。"""
    if cfg.fake_speech:
        return MacSayTTSService(mac_tts.voice_name())
    if cfg.tts_provider == "elevenlabs":
        vid = eleven.voice_id(cfg.eleven_voice, cfg.eleven_key)
        vs = eleven.voice_settings_from_env()  # 填错直接报清楚
        if eleven.streams_over_websocket(cfg.eleven_model):
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService  # noqa: WPS433  只在选了它时才导入
            return ElevenLabsTTSService(api_key=cfg.eleven_key, settings=ElevenLabsTTSService.Settings(voice=vid, model=cfg.eleven_model, **vs))
        return http_eleven_service_class()(api_key=cfg.eleven_key, voice=vid, model=cfg.eleven_model, voice_settings=vs)
    try:
        lang = Language(cfg.tts_language)
    except ValueError:
        lang = Language.EN_US
    kw = dict(api_key=cfg.key or None, server=cfg.server, model_function_map={"function_id": cfg.tts_function_id, "model_name": cfg.tts_model},
              settings=NvidiaTTSService.Settings(voice=cfg.tts_voice, language=lang))
    return CachedMagpieTTSService(cache_dir=TTS_CACHE_DIR, **kw) if cfg.tts_cache else NvidiaTTSService(**kw)


def _eleven_settings():
    try:
        return eleven.voice_settings_from_env(), ""
    except eleven.ElevenError as e:
        return {}, str(e)


_HTTP_ELEVEN_CLS = None


def http_eleven_service_class():
    """v3 / v4 系列不上 TTS WebSocket（服务端回 400 unsupported_model，让用 text-to-dialogue），所以走 Pipecat 的 HTTP 流式服务
    （/stream/with-timestamps，实测首字节约 0.45 s，和 flash 一样）。aiohttp 会话要在事件循环里建，所以放到 start() 里。"""
    global _HTTP_ELEVEN_CLS
    if _HTTP_ELEVEN_CLS is not None:
        return _HTTP_ELEVEN_CLS
    from pipecat.services.elevenlabs.tts import ELEVENLABS_CONTEXT_UNSUPPORTED_MODELS, ElevenLabsHttpTTSService  # noqa: WPS433

    class HttpElevenLabsTTSService(ElevenLabsHttpTTSService):
        def __init__(self, *, api_key: str, voice: str, model: str, voice_settings: Optional[dict] = None):
            if not eleven.accepts_context(model):
                ELEVENLABS_CONTEXT_UNSUPPORTED_MODELS.add(model)  # v3 系列不收 previous_text
            super().__init__(api_key=api_key, aiohttp_session=None,
                             settings=ElevenLabsHttpTTSService.Settings(voice=voice, model=model, **(voice_settings or {})))

        async def start(self, frame):
            if self._session is None:
                import aiohttp  # noqa: WPS433
                self._session = aiohttp.ClientSession()
            await super().start(frame)

        async def stop(self, frame):
            await super().stop(frame)
            await self._close_session()

        async def cancel(self, frame):
            await super().cancel(frame)
            await self._close_session()

        async def _close_session(self):
            sess, self._session = self._session, None
            if sess is not None and not sess.closed:
                await sess.close()

    _HTTP_ELEVEN_CLS = HttpElevenLabsTTSService
    return _HTTP_ELEVEN_CLS


def smart_turn_available() -> bool:
    return LocalSmartTurnAnalyzerV3 is not None and TurnAnalyzerUserTurnStopStrategy is not None


def turn_label(cfg: "Config") -> str:
    if cfg.smart_turn and smart_turn_available():
        return f"smart-turn v3 (local), silence cap {cfg.smart_turn_stop_secs:g} s"
    return "speech timeout 0.6 s"


def make_user_turns(cfg: "Config", said: Callable[[], Tuple[str, str]]) -> "UserTurnProcessor":
    """谁在说话、说完了没：开始 = 机器没说话时一个词、机器说话时至少 N 个词且不是它自己的回声（N=0 退回纯人声 VAD）；
    结束 = smart-turn v3 听语调判断"说完了"（拿不准时最多等 stop_secs 的静音），再等最终转写到；
    SMART_TURN=0 或模型装不上时退回"静音 0.6 s + 转写到"。user_turn_stop_timeout 是只有噪声没转写时的兜底。"""
    start = [EchoAwareUserTurnStartStrategy(min_words=cfg.min_words, said=said)] if cfg.min_words and not cfg.fake_speech else [VADUserTurnStartStrategy()]
    return UserTurnProcessor(user_turn_strategies=UserTurnStrategies(start=start, stop=turn_stop_strategies(cfg)), user_turn_stop_timeout=2.5)


def turn_stop_strategies(cfg: "Config") -> list:
    if cfg.smart_turn and smart_turn_available():
        analyzer = LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=cfg.smart_turn_stop_secs))
        return [TurnAnalyzerUserTurnStopStrategy(turn_analyzer=analyzer)]
    return [SpeechTimeoutUserTurnStopStrategy()]


def tokens(t: str) -> List[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", (t or "").lower()).split()


def is_filler(t: str) -> bool:
    w = tokens(t)
    return bool(w) and all(x in FILLERS for x in w)


def echo_like(t: str, *said: str, min_tokens: int = 2) -> bool:
    """听到的话大半是自己正在播 / 刚播完的那句 → 音箱回声。"""
    w = tokens(t)
    if len(w) < min_tokens:
        return False
    heard = {x for s in said for x in tokens(s)}
    return sum(x in heard for x in w) / len(w) >= 0.6


def is_echo(t: str, *said: str) -> bool:
    """听到的话大半是自己刚说的 → 自己的回声（同 app.js isEcho）。"""
    return echo_like(t, *said, min_tokens=3)


class EchoAwareUserTurnStartStrategy(MinWordsUserTurnStartStrategy):
    """docs/00 §4.4 第 1、3、5 条的"开口"判定：机器没在说话时一个词就算（和 MinWords 一样）；机器在说话时要至少 min_words 个词，
    而且这些词不能大半是它正在播 / 刚播完的那句——那是音箱回声，不算打断（真转写到了 Brain 那边还会再按回声丢掉）。
    10-26 之前是纯人声 VAD：机器自己的声音从音箱进麦克风就把自己打断，开查的线程被取消后没人再开查，界面停在 Ready。"""

    def __init__(self, *, min_words: int, said: Callable[[], Tuple[str, str]], **kwargs):
        super().__init__(min_words=min_words, **kwargs)
        self._said = said

    async def _handle_transcription(self, frame):
        if self._bot_speaking:
            text = frame.text or ""
            if len(tokens(text)) < max(1, self._min_words) or echo_like(text, *self._said()):
                await self.trigger_reset_aggregation()
                return ProcessFrameResult.CONTINUE
        return await super()._handle_transcription(frame)


def ui_message(ev: dict) -> dict:
    return {"label": MESSAGE_LABEL, "type": "server-message", "data": ev}


def log_turn(entry: dict) -> None:
    VOICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = dict({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, **entry)
    with VOICE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@dataclass
class SayPlayedFrame(DataFrame):
    """跟在每句话后面的标记。输出传输把它前面的音频真正播完才往下推，Tracker 收到就知道这句说完了。"""
    idx: Optional[int]
    text: str
    turn: int


class Brain(FrameProcessor):
    """我们的"脑"：把听到的话（或打的字）交给 policy.Session，把它吐出的事件变成"说"和"界面消息"。

    policy 是同步生成器（开查时会 sleep），放在线程里跑，每个事件交回事件循环推给下游。
    打断：Pipecat 一检测到人声就切断播音；这里记下打断上下文（说完的最后一句、正在看的房源、被切断的句子），
    等这段话听完再决定：真打断 → 交给 policy 按五条标准处理；噪声、"嗯"、自己的回声 → 不说话，从被切断的那句接着播。
    """

    COMMIT_GRACE_S = 0.35  # 用户停下后再等一下迟到的最终转写
    LATE_FINAL_S = 0.8  # 打断了却还没字时，再多等这么久才算误触发

    def __init__(self, session: policy.Session, source: str):
        super().__init__(name="HomeTruthBrain")
        self.session = session
        self.source = source
        self.turn = 0  # 每开一轮、每次打断都 +1；旧线程的事件和旧标记一律作废
        self.active_turn: Optional[int] = None  # 线程还在跑的那一轮
        self.cancel = threading.Event()
        self.queued = 0  # 已送去合成、还没播完的句子数
        self.mood = tone.Mood(False)  # 情绪标签（只进嘴）；build_worker 按配置换成开着的
        self.spoken_idx: Optional[int] = None  # 最后一句完整播完的导览句编号（Tracker 更新）
        self.listing_id: Optional[str] = None  # 前端正在看的房源（Tracker 按播出的 card/highlight 更新）
        self.current_say: Optional[str] = None  # 正在播的句子
        self.last_said = ""
        self.bot_speaking = False
        self.user_speaking = False
        self.heard: List[str] = []  # 这段话的最终转写
        self.ictx: Optional[dict] = None  # 打断时抓到的上下文
        self.commit_task: Optional[asyncio.Task] = None
        self.renter_id = ""  # 浏览器报的租客编号（hometruth-renter），New search 后仍记着，这样下一次开查还会记忆

    def busy(self) -> bool:
        return self.queued > 0 or self.bot_speaking or (self.active_turn is not None and self.active_turn == self.turn)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):  # 人声（UserTurnProcessor）或我们自己广播的
            self._stop_current()
            await self.push_frame(frame, direction)
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
            await self.push_frame(frame, direction)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            await self.push_frame(frame, direction)
        elif isinstance(frame, UserStartedSpeakingFrame):
            self.user_speaking = True
            self._cancel_commit()
            await self.push_frame(frame, direction)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.user_speaking = False
            self._schedule_commit()
            await self.push_frame(frame, direction)
        elif isinstance(frame, TranscriptionFrame):  # 前端已经经 RTVI 观察者拿到转写，这里只收集，不往下传
            if frame.text.strip():
                self.heard.append(frame.text.strip())
            if not self.user_speaking:
                self._schedule_commit()
        elif isinstance(frame, InterimTranscriptionFrame):
            pass
        elif isinstance(frame, RTVIClientMessageFrame) and frame.type == "hometruth-text":
            text = str((frame.data or {}).get("text") or "").strip()
            if text:
                await self._start_turn(text, "text")
        elif isinstance(frame, RTVIClientMessageFrame) and frame.type == "hometruth-stop":
            await self._pause()
        elif isinstance(frame, RTVIClientMessageFrame) and frame.type == "hometruth-reset":
            await self._reset()
        elif isinstance(frame, RTVIClientMessageFrame) and frame.type == "hometruth-renter":  # 浏览器一连上就报租客编号：有记忆就先开口
            self.renter_id = str((frame.data or {}).get("renter") or "")
            mem = self.session.attach_renter(self.renter_id)
            if mem and not self.session.greeted and not self.session.plan and not self.busy():
                await self._run(lambda: self.session.welcome(), "(welcome back)", "memory", interrupted=False, kind="welcome")
        else:
            await self.push_frame(frame, direction)

    # ---- 打断与提交 ----
    def _stop_current(self) -> None:
        """当前这轮作废：线程停、没播的句子作废；正在说话就记下打断上下文。"""
        if self.ictx is None and self.busy():
            self.ictx = {"active": True, "spoken_idx": self.spoken_idx, "listing_id": self.listing_id, "cut_sentence": self.current_say}
        self.turn += 1
        self.cancel.set()
        self.queued = 0
        self.current_say = None

    def _cancel_commit(self) -> None:
        if self.commit_task and not self.commit_task.done():
            self.commit_task.cancel()
        self.commit_task = None

    def _schedule_commit(self) -> None:
        self._cancel_commit()
        self.commit_task = self.create_task(self._commit(), "commit")

    async def _commit(self) -> None:
        await asyncio.sleep(self.COMMIT_GRACE_S)
        if not self.heard and self.ictx is not None:  # 打断了却还没字：最终转写可能还在路上
            await asyncio.sleep(self.LATE_FINAL_S)
        if self.user_speaking:
            return
        self.commit_task = None  # 从这里起不再被新的人声取消
        text, self.heard = " ".join(self.heard).strip(), []
        inter, self.ictx = self.ictx, None
        if inter is not None and (not text or is_filler(text) or is_echo(text, inter.get("cut_sentence") or "", self.last_said)):
            if inter.get("paused"):  # 用户按了停：噪声不能让它自己接着说，等真的一句话
                self.ictx = inter
                return
            await self._run(lambda: self._resume_events(inter), text or "(no words)", "voice", interrupted=True, kind="resume")
            return
        if inter is None and (not text or is_echo(text, self.current_say or "", self.last_said)):
            return
        await self._start_turn(text, "voice", inter)

    def _resume_events(self, inter: dict) -> Iterator[dict]:
        """误触发（回声、噪声、"嗯"）：导览中就从被切断的那句接着播；还没开查就看卡在哪一步——反问重问、欢迎问句重问、
        需求已说就重新开查（之前只把被切断的那句重说一遍，开查的线程早被取消，界面就停在 Ready）。"""
        if self.session.plan:
            return self.session.resume(inter.get("spoken_idx"), inter.get("listing_id"))
        return self.session.resume_before_plan(inter.get("cut_sentence"))

    async def _start_turn(self, text: str, source: str, inter: Optional[dict] = None) -> None:
        if self.busy():  # 还在说（打字打断、迟到的转写）：先停下，记上下文
            self._stop_current()
            await self.broadcast_interruption()
        if inter is None:
            inter, self.ictx = self.ictx, None
        body = {"text": text, "source": source, "listing_id": self.listing_id, "interrupted": inter or {"active": False}}
        await self._run(lambda: self.session.handle_turn(body), text, source, interrupted=bool(inter and inter.get("active")))

    async def _pause(self) -> None:
        """Stop 按钮 / Esc：停下但记住说到哪；之后说 "continue" 从被切断的那句接着讲。"""
        if self.busy():
            self._stop_current()
            await self.broadcast_interruption()
        if self.ictx is not None:
            self.ictx["paused"] = True
        await self.push_frame(OutputTransportMessageUrgentFrame(message=ui_message({"type": "state", "phase": "idle", "label": "Paused"})))

    async def _reset(self) -> None:
        if self.busy():
            self._stop_current()
            await self.broadcast_interruption()
        self.ictx, self.heard = None, []
        self.session = policy.Session(self.session.id)
        if self.renter_id:
            self.session.attach_renter(self.renter_id, prefill=False)  # New search = 从头说需求，但这次开查仍会记下来
        self.spoken_idx = self.listing_id = self.current_say = None
        self.last_said = ""

    # ---- 跑 policy ----
    async def _run(self, make_events: Callable[[], Iterator[dict]], text: str, source: str, *, interrupted: bool, kind: str = "turn") -> None:
        self.turn += 1
        turn, self.active_turn = self.turn, self.turn
        self.cancel = cancel = threading.Event()
        loop = asyncio.get_running_loop()
        session, t0 = self.session, time.time()

        def work() -> None:
            first_ms, n, status = None, 0, "ok"
            try:
                with session.lock:
                    for ev in make_events():
                        if cancel.is_set():
                            status = "interrupted"
                            break
                        if first_ms is None:
                            first_ms = round((time.time() - t0) * 1000)
                            ev = dict(ev, t_first_ms=first_ms)
                        asyncio.run_coroutine_threadsafe(self._emit(ev, turn), loop).result(timeout=30)
                        n += 1
            except Exception as e:  # 把异常也送到前端，便于调试
                status = f"error: {e}"
                with contextlib.suppress(Exception):
                    asyncio.run_coroutine_threadsafe(self._emit({"type": "error", "message": str(e)}, turn), loop).result(timeout=5)
            finally:
                with contextlib.suppress(Exception):
                    loop.call_soon_threadsafe(self._finished, turn)
                log_turn({"kind": kind, "source": f"pipecat-{self.source}:{source}", "session": session.id, "text": text[:200],
                          "interrupted": interrupted, "first_event_ms": first_ms, "events": n, "total_ms": round((time.time() - t0) * 1000),
                          "status": status})

        threading.Thread(target=work, name=f"hometruth-turn-{turn}", daemon=True).start()

    def _finished(self, turn: int) -> None:
        if self.active_turn == turn:
            self.active_turn = None

    async def _emit(self, ev: dict, turn: int) -> None:
        if turn != self.turn:  # 这一轮已经被打断
            return
        if ev.get("type") == "error":
            await self.push_frame(OutputTransportMessageUrgentFrame(message=ui_message(ev)))
            return
        await self.push_frame(OutputTransportMessageFrame(message=ui_message(ev)))
        tag = self.mood.tag(ev)  # 每个事件都过一遍：highlight 告诉它格子状态，say 拿标签
        if ev.get("type") == "say" and ev.get("text"):
            self.queued += 1
            await self.push_frame(TTSSpeakFrame(text=f"{tag} {ev['text']}" if tag else ev["text"], append_to_context=False))
            await self.push_frame(SayPlayedFrame(idx=ev.get("idx"), text=ev["text"], turn=turn))


class Tracker(FrameProcessor):
    """放在输出传输后面：只有真正播出去、发出去的东西才会走到这里。据此更新"说到哪句、看到哪套房、正在说哪句"。"""

    def __init__(self, brain: Brain):
        super().__init__(name="HomeTruthTracker")
        self.brain = brain

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        b = self.brain
        if isinstance(frame, SayPlayedFrame):
            if frame.turn == b.turn:
                b.queued = max(0, b.queued - 1)
                b.last_said, b.current_say = frame.text, None
                if frame.idx is not None:
                    b.spoken_idx = frame.idx
            return  # 标记到此为止
        if isinstance(frame, OutputTransportMessageFrame):
            ev = (frame.message or {}).get("data") or {}
            kind = ev.get("type")
            if kind == "say":
                b.current_say = ev.get("text")
            elif kind == "card":
                b.listing_id = (ev.get("listing") or {}).get("id") or b.listing_id
            elif kind == "highlight":
                b.listing_id = ev.get("listing_id") or b.listing_id
            elif kind == "state" and ev.get("phase") == "touring" and ev.get("label") == "Walking you through":
                b.spoken_idx = None  # 新的一套导览开始了，旧编号作废
        await self.push_frame(frame, direction)


class MacSayTTSService(TTSService):
    """没 key 时的替身合成：macOS say（经 tts.py，带缓存）。在管线里的位置、帧、打断和 Magpie 完全一样，只是声音来源不同。"""

    def __init__(self, voice: str, **kwargs):
        super().__init__(push_start_frame=True, push_stop_frames=True, settings=TTSSettings(model="macos-say", voice=voice, language=None), **kwargs)
        self._voice = voice

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str):
        try:
            await self.start_tts_usage_metrics(text)
            data, _ = await asyncio.to_thread(mac_tts.synthesize, text, self._voice)
            with wave.open(io.BytesIO(data)) as w:
                rate, pcm = w.getframerate(), w.readframes(w.getnframes())

            async def chunks():
                step = rate // 10 * 2  # 100 ms，16 位单声道
                for i in range(0, len(pcm), step):
                    yield pcm[i:i + step]

            async for frame in self._stream_audio_frames_from_iterator(chunks(), in_sample_rate=rate, context_id=context_id):
                await self.stop_ttfb_metrics()
                yield frame
        except Exception as e:
            yield ErrorFrame(error=f"macOS say failed: {e}")
        finally:
            await self.stop_ttfb_metrics()


def fixed_sentences() -> List[str]:
    """每轮都可能原样说的句子：过渡句、反问模板、开查句、导览里的固定话。管线第一次起来后后台预合成进缓存，演示时这些句子零等待。"""
    out = phraser.all_bridges() + phraser.all_glue() + ["Got it.", "Thanks.", "Okay.", "Sure.", "Sure, next one.", "Next one.", "And the last one.",
           "That was the last one. Here's the wrap-up.", "Okay, I'll pause here. Say continue when you're ready.",
           "I didn't catch a condition there. I'll carry on, interrupt me any time.",
           "Sorry, I didn't catch that. I'll carry on, interrupt me any time.", f"Checking {len(policy.SOURCES)} sources now."]
    dims = [d for d, _ in policy.REQUIRED]
    out += [phraser.ask_sentence([d]) for d in dims]
    out += [phraser.ask_sentence([a, b]) for i, a in enumerate(dims) for b in dims[i + 1:]]
    out += [phraser.shortlist(n, min(policy.TOP_N, n)) for n in range(0, 5)]
    out += [phraser.back(i) for i in range(policy.TOP_N)]
    return list(dict.fromkeys(out))


class CachedMagpieTTSService(NvidiaTTSService):
    """Magpie 合成按句缓存（提速二）。同一句话（同声音、语言、采样率）第二次起不再去 NVIDIA，直接播缓存的 PCM，省掉约 0.5 s 的首块等待；
    fixed_sentences() 里的固定句子在管线第一次起来后由后台线程预合成。缓存文件 runs/tts_cache/magpie/<sha1>.pcm（16 位单声道，采样率同管线输出）；
    说到一半被打断的句子不入库（生成器被关掉就走不到写文件那一步）。MAGPIE_TTS_CACHE=0 关掉。"""

    _warmed = False

    def __init__(self, *args, cache_dir: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_hits = 0
        self.cache_misses = 0

    def _cache_path(self, text: str) -> Path:
        key = f"{self._settings.model}|{self._settings.voice}|{self._settings.language}|{self._settings.quality}|{self.sample_rate}|{text.strip()}"
        return self._cache_dir / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".pcm")

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if not CachedMagpieTTSService._warmed and self._service is not None:
            CachedMagpieTTSService._warmed = True
            threading.Thread(target=self._warm, name="magpie-warm", daemon=True).start()

    def _warm(self) -> None:
        sentences = fixed_sentences()
        todo = [t for t in sentences if not self._cache_path(t).exists()]
        done = 0
        for t in todo:
            try:
                audio = self._service.synthesize(t, self._settings.voice, language_code=str(self._settings.language or "en-US"),
                                                 encoding=self._encoding, sample_rate_hz=self.sample_rate).audio
            except Exception as e:  # noqa: BLE001  预热失败不影响正常合成
                logger.warning(f"Magpie cache warm-up stopped at {t!r}: {e}")
                break
            if audio:
                self._cache_path(t).write_bytes(audio)
                done += 1
        logger.info(f"Magpie sentence cache: {done} warmed now, {len(sentences) - len(todo)} were already there ({self._cache_dir})")

    async def run_tts(self, text: str, context_id: str):
        path = self._cache_path(text)
        if path.exists():
            pcm = await asyncio.to_thread(path.read_bytes)
            if pcm:
                self.cache_hits += 1
                if not self.audio_context_available(context_id):
                    await self.create_audio_context(context_id)
                    await self.start_ttfb_metrics()
                    yield TTSStartedFrame(context_id=context_id)
                await self.start_tts_usage_metrics(text)
                await self.stop_ttfb_metrics()
                step = self.sample_rate // 10 * 2  # 100 ms，16 位单声道
                for i in range(0, len(pcm), step):
                    yield TTSAudioRawFrame(audio=pcm[i:i + step], sample_rate=self.sample_rate, num_channels=1, context_id=context_id)
                return
        self.cache_misses += 1
        buf, clean = bytearray(), True
        async for frame in super().run_tts(text, context_id):
            if isinstance(frame, TTSAudioRawFrame):
                buf += frame.audio
            elif isinstance(frame, ErrorFrame):
                clean = False
            yield frame
        if clean and buf:
            await asyncio.to_thread(path.write_bytes, bytes(buf))


def build_worker(conn: SmallWebRTCConnection, cfg: Config, session: policy.Session):
    """一条 WebRTC 连接一条管线、一个 policy.Session。返回 (worker, transport, brain, 处理器列表)。"""
    transport = SmallWebRTCTransport(webrtc_connection=conn, params=TransportParams(audio_in_enabled=True, audio_out_enabled=True))
    brain = Brain(session, "fake" if cfg.fake_speech else "nvidia")
    brain.mood = tone.Mood(cfg.tts_provider == "elevenlabs" and cfg.eleven_tags and not cfg.fake_speech)
    turns = make_user_turns(cfg, lambda: (brain.current_say or "", brain.last_said or ""))  # 开口判定要知道机器正在说什么
    procs = [transport.input(), VADProcessor(vad_analyzer=SileroVADAnalyzer())]
    if cfg.fake_speech:
        pass
    else:
        procs.append(NvidiaSTTService(api_key=cfg.key or None, server=cfg.server,
                                      model_function_map={"function_id": cfg.asr_function_id, "model_name": cfg.asr_model}))
    speaker = make_speaker(cfg)
    procs += [turns, brain, speaker, transport.output(), Tracker(brain)]
    worker = PipelineWorker(Pipeline(procs), params=PipelineParams(enable_metrics=True), idle_timeout_secs=1800)
    return worker, transport, brain, procs


async def run_bot(conn: SmallWebRTCConnection, cfg: Config) -> None:
    session = policy.Session(f"pipecat-{(conn.pc_id or 'peer').split('-')[-1][:8]}")
    worker, transport, _, _ = build_worker(conn, cfg, session)

    @transport.event_handler("on_client_disconnected")
    async def _gone(transport, client):
        await worker.cancel(reason="client disconnected")

    await WorkerRunner(handle_sigint=False).run(worker)


def serve(cfg: Config) -> None:
    import uvicorn
    from fastapi import BackgroundTasks, FastAPI
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import mimetypes
    mimetypes.add_type("font/woff2", ".woff2")
    mimetypes.add_type("text/javascript", ".js")

    handler = SmallWebRTCRequestHandler(ice_servers=ice_objects(ice_servers_for(cfg)))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        yield
        await handler.close()

    app = FastAPI(title="HomeTruth voice (Pipecat)", lifespan=lifespan)

    @app.get("/")
    async def index():  # the qi.home-shell page (static/qi); the previous page stays at /classic
        return FileResponse(HERE / "static" / "qi" / "pipecat.html", headers={"Cache-Control": "no-store"})

    @app.get("/classic")
    async def classic():
        return FileResponse(HERE / "static" / "pipecat.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/hello")
    async def hello(renter: str = ""):  # ?renter=<id>：这位租客上次的需求（memory.py），没有就 null
        sel = await asyncio.to_thread(llm.select)
        parser = await asyncio.to_thread(policy.needs_llm_ready)
        return dict(cfg.describe(), llm=f"{sel.label} · {sel.model}" if sel.name != "none" else "none", llm_reason=sel.reason,
                    needs_parser="llm" if parser else "rules", pipecat=importlib.metadata.version("pipecat-ai"), server_time=time.time(),
                    zetaris=zetaris_live.status(), memory=policy.hello_view(renter))

    @app.post("/api/forget")
    async def forget(body: dict):  # 界面上的 Forget me：记忆、收件箱、信念日志一起删
        policy.forget_renter((body or {}).get("renter"))
        return {"status": "forgotten"}

    @app.post("/api/inbox")
    async def inbox_post(body: dict):  # 中介回复到了（webhook / scripts/agent_reply.py）：进这位租客的收件箱；下一句话 "Just in…" / 下次开查 "While you were away…" 折进来
        body = body or {}
        lid = str(body.get("listing_id") or "").strip()
        if policy.listing_by_id(lid) is None:
            return JSONResponse({"error": f"unknown listing_id {lid!r}"}, status_code=404)
        row = inbox.add(body.get("renter"), lid, str(body.get("text") or ""), str(body.get("channel") or "api"))
        if row is None:
            return JSONResponse({"error": "renter (the browser's ht_renter), listing_id and text are required"}, status_code=400)
        return {"status": "queued", "event": row, "unread": inbox.view(row["renter"])["unread"]}

    @app.get("/api/listings")
    async def listings():  # 卡片墙、浏览网格、详情页用，和 server.py 的同名接口一样（policy.listing_summary）
        return {"listings": [policy.listing_summary(L) for L in policy.LISTINGS]}

    @app.get("/api/ice")
    async def ice():  # 浏览器那端的 ICE 服务器清单：和服务端同一份（STUN，或 Cloudflare TURN 的短期凭据）；空清单 = 只用本机候选（局域网演示）
        return {"iceServers": await asyncio.to_thread(ice_servers_for, cfg)}

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
        async def connected(conn: SmallWebRTCConnection):
            background_tasks.add_task(run_bot, conn, cfg)

        handler.update_ice_servers(ice_objects(await asyncio.to_thread(ice_servers_for, cfg)))  # TURN 凭据快过期就换新的
        return await handler.handle_web_request(request=request, webrtc_connection_callback=connected)

    @app.patch("/api/offer")
    async def ice_candidates(request: SmallWebRTCPatchRequest):
        await handler.handle_patch_request(request)
        return {"status": "success"}

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    real_photos = HERE.parents[1] / "data" / "real" / "photos"  # 真房源照片（本地缓存，不进 git）
    if real_photos.is_dir():
        app.mount("/real", StaticFiles(directory=str(real_photos)), name="real")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


# ---- 自检 ----
def row(tag: str, ok, msg: str) -> None:
    """和 scripts/check_nvidia.py 同一个格式，它会原样并进去。"""
    mark = "PASS" if ok is True else ("SKIP" if ok is None else "FAIL")
    print(f"{mark:4}  {tag:34} {msg}", flush=True)


# ---- ICE / TURN（docs/10：校园网 Windows 部署）----
TURN_API = "https://rtc.live.cloudflare.com/v1/turn/keys/{key}/credentials/generate-ice-servers"
_turn_cache: dict = {"until": 0.0, "servers": []}


def _ice_entry(spec: str) -> dict:
    """PIPECAT_ICE_SERVERS 里的一项：'stun:host:port'，或带静态账号的中继 'turn:host:port?transport=udp|user|password'（自己的 coturn、公共中继）。"""
    parts = [p.strip() for p in spec.split("|")]
    d: dict = {"urls": parts[0]}
    if len(parts) >= 3 and parts[1]:
        d["username"], d["credential"] = parts[1], parts[2]
    return d


def ice_servers_for(cfg: Config) -> List[dict]:
    """两端共用的 ICE 服务器清单（dict：urls / username / credential）。有 Cloudflare TURN key 就领一份短期凭据（缓存到过期前 10 分钟），
    领不到就退回 PIPECAT_ICE_SERVERS 的 STUN 并在日志里说一句；没有 key 就只有 STUN。"""
    import json
    import urllib.request
    base = [_ice_entry(u) for u in cfg.ice_servers]
    if not (cfg.turn_key_id and cfg.turn_token):
        return base
    now = time.time()
    if _turn_cache["servers"] and now < _turn_cache["until"]:
        return _turn_cache["servers"]
    try:
        req = urllib.request.Request(TURN_API.format(key=cfg.turn_key_id), data=json.dumps({"ttl": cfg.turn_ttl}).encode(),
                                     headers={"Authorization": f"Bearer {cfg.turn_token}", "Content-Type": "application/json",
                                              "User-Agent": "HomeTruth-voice/1"}, method="POST")  # Cloudflare 拦 Python-urllib 的默认 UA（403）
        with urllib.request.urlopen(req, timeout=10) as r:
            got = json.loads(r.read().decode())
        servers = []
        for s in got.get("iceServers") or []:
            raw = s.get("urls")
            urls = [u for u in (raw if isinstance(raw, list) else [raw]) if u and ":53?" not in u and not u.endswith(":53")]  # 53 口浏览器不让用
            if urls:
                servers.append({k: v for k, v in (("urls", urls), ("username", s.get("username")), ("credential", s.get("credential"))) if v})
        if not servers:
            raise ValueError("empty iceServers in the reply")
        _turn_cache.update(until=now + max(60, cfg.turn_ttl - 600), servers=servers)
        logger.info(f"TURN: Cloudflare credentials fetched ({len(servers)} ICE entries, ttl {cfg.turn_ttl}s)")
        return servers
    except Exception as e:  # noqa: BLE001  领不到就退回 STUN，不让语音线整个起不来
        logger.warning(f"TURN: Cloudflare credentials failed ({type(e).__name__}: {e}); STUN only")
        return base


def ice_objects(servers: List[dict]) -> Optional[List["IceServer"]]:
    return [IceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential")) for s in servers] or None


def dry_run(cfg: Config) -> Tuple[bool, str, List[str]]:
    """不连任何服务：真的把管线对象搭出来（WebRTC 不握手、识别和合成不建 gRPC 连接）。搭得起来就说明导入、参数、版本对得上。"""
    async def build():
        conn = SmallWebRTCConnection()
        try:
            worker, _, _, procs = build_worker(conn, cfg, policy.Session("dry-run"))
            return [type(p).__name__ for p in procs], worker.rtvi is not None
        finally:
            with contextlib.suppress(Exception):
                await conn.disconnect()

    t0 = time.time()
    try:
        names, rtvi = asyncio.run(build())
    except Exception as e:
        return False, f"{type(e).__name__}: {llm._redact(str(e))[:160]}", []
    ms = round((time.time() - t0) * 1000)
    return True, f"pipecat {importlib.metadata.version('pipecat-ai')}, {len(names)} 个处理器{' + RTVI' if rtvi else ''}，搭建 {ms} ms", names


def _grpc_error(e: Exception) -> str:
    code = getattr(e, "code", None)
    if callable(code):
        name = getattr(code(), "name", str(code()))
        details = llm._redact(str(e.details() if callable(getattr(e, "details", None)) else e))
        hint = {"UNAUTHENTICATED": "key 不对或过期", "PERMISSION_DENIED": "这个 key 没有该模型的权限",
                "NOT_FOUND": "function id 失效：去 build.nvidia.com 模型页抄新的填 .env",
                "UNAVAILABLE": "连不上（网络、代理或服务暂时不可用）", "INVALID_ARGUMENT": "参数不对（声音名、语言、采样率）"}.get(name, "")
        return f"{name}: {details[:120]}" + (f"（{hint}）" if hint else "")
    return f"{type(e).__name__}: {llm._redact(str(e))[:140]}"


def _timed(fn: Callable, timeout: float):
    ex = ThreadPoolExecutor(max_workers=1)
    t0 = time.time()
    try:
        return ex.submit(fn).result(timeout=timeout), None, round((time.time() - t0) * 1000)
    except FutureTimeout:
        return None, f"超过 {timeout:.0f} s 没回应", round((time.time() - t0) * 1000)
    except Exception as e:
        return None, _grpc_error(e), round((time.time() - t0) * 1000)
    finally:
        ex.shutdown(wait=False)


def _auth(cfg: Config, function_id: str):
    import riva.client
    return riva.client.Auth(None, True, cfg.server, [["function-id", function_id], ["authorization", f"Bearer {cfg.key}"]])


def synth_once(cfg: Config, text: str) -> bytes:
    import riva.client
    svc = riva.client.SpeechSynthesisService(_auth(cfg, cfg.tts_function_id))
    return svc.synthesize(text, cfg.tts_voice, language_code=cfg.tts_language, encoding=riva.client.AudioEncoding.LINEAR_PCM, sample_rate_hz=16000).audio


def recognize_once(cfg: Config, pcm16k: bytes) -> str:
    import riva.client
    svc = riva.client.ASRService(_auth(cfg, cfg.asr_function_id))
    conf = riva.client.StreamingRecognitionConfig(config=riva.client.RecognitionConfig(
        encoding=riva.client.AudioEncoding.LINEAR_PCM, language_code="en-US", max_alternatives=1, enable_automatic_punctuation=True,
        sample_rate_hertz=16000, audio_channel_count=1), interim_results=False)
    chunks = [pcm16k[i:i + 3200] for i in range(0, len(pcm16k), 3200)]  # 100 ms 一块，和管线里一样流式送
    out = [r.alternatives[0].transcript.strip() for resp in svc.streaming_response_generator(chunks, conf)
           for r in resp.results if r.is_final and r.alternatives]
    return " ".join(x for x in out if x)


def check(cfg: Config) -> int:
    ok, msg, _ = dry_run(cfg)
    row(CHECK_ROW, ok, msg)
    fails = int(not ok)
    bad = [p for p in cfg.problems() if not p.startswith("NVIDIA_API_KEY")]
    if bad:
        row("Speech config", False, "；".join(bad))
        fails += 1
    if not cfg.key:
        row("Magpie TTS (speech out)", None, "NVIDIA_API_KEY 为空或不是 nvapi- 开头，跳过")
        row("Parakeet ASR (speech in)", None, "同上")
        return 1 if fails else 0
    if cfg.eleven_key or cfg.tts_provider == "elevenlabs":
        if not cfg.eleven_key:
            row("ElevenLabs TTS (speech out)", False, "TTS_PROVIDER=elevenlabs 但 ELEVENLABS_API_KEY 为空")
            fails += 1
        else:
            check_text = (tone.tag_for("shortlist", CHECK_SENTENCE) + " " + CHECK_SENTENCE) if cfg.eleven_tags else CHECK_SENTENCE
            pcm, e_err, e_ms = _timed(lambda: eleven.synth(check_text, cfg.eleven_voice, cfg.eleven_key, cfg.eleven_model, 22050, voice_settings=cfg.eleven_settings), 60)
            if pcm:
                try:
                    sub = eleven.subscription(cfg.eleven_key)
                    quota = f"，账户 {sub.get('tier')}，本月已用 {sub.get('used')}/{sub.get('limit')} 字符"
                except Exception:  # noqa: BLE001
                    quota = ""
                row("ElevenLabs TTS (speech out)", True, f"{cfg.eleven_voice} / {cfg.eleven_model}{' + 情绪标签' if cfg.eleven_tags else ''}{'' if eleven.streams_over_websocket(cfg.eleven_model) else '，HTTP 流式'}: {len(pcm) / 44100:.1f} s 音频，{e_ms} ms"
                    + ("（当前 TTS_PROVIDER=magpie，没在用）" if cfg.tts_provider != "elevenlabs" else "") + quota)
            else:
                row("ElevenLabs TTS (speech out)", False, e_err or "回了空音频")
                fails += int(cfg.tts_provider == "elevenlabs")
    audio, err, ms = _timed(lambda: synth_once(cfg, CHECK_SENTENCE), 60)
    if audio:
        row("Magpie TTS (speech out)", True, f"{cfg.tts_voice}: {len(audio) / 32000:.1f} s 音频，{ms} ms" + ("（当前 TTS_PROVIDER=elevenlabs，没在用）" if cfg.tts_provider == "elevenlabs" else ""))
    else:
        row("Magpie TTS (speech out)", False, err or "回了空音频")
        row("Parakeet ASR (speech in)", None, "跳过（拿合成的那段音频来测识别，合成先要通）")
        return 1
    heard, err, ms = _timed(lambda: recognize_once(cfg, audio), 60)
    if heard:
        want, got = set(tokens(CHECK_SENTENCE)), set(tokens(heard))
        row("Parakeet ASR (speech in)", True, f"{cfg.asr_model}: 听回来 \"{heard[:60]}\"（{len(want & got)}/{len(want)} 词对上，{ms} ms）")
    else:
        row("Parakeet ASR (speech in)", False, err or "没识别出字")
        fails += 1
    return 1 if fails else 0


def dry_run_report(cfg: Config) -> int:
    ok, msg, names = dry_run(cfg)
    print(f"管线：{' → '.join(names) if names else '(没搭起来)'}")
    row(CHECK_ROW, ok, msg)
    sel = llm.select()
    print("配置：")
    print(f"  NVIDIA_API_KEY          {'有（nvapi-…）' if cfg.key else '缺'}")
    print(f"  识别                    {cfg.asr_model}  function {cfg.asr_function_id}  @ {cfg.server}")
    print(f"  合成                    {tts_label(cfg)}" + (f"  function {cfg.tts_function_id}（{cfg.tts_language}）" if cfg.tts_provider == "magpie" else ""))
    print(f"  打断                    {cfg.describe()['interrupt']}；端口 {cfg.port}")
    print(f"  轮次检测                {turn_label(cfg)}；台词：{'模型写、规则审' if narrator.enabled() else '模板'}")
    print(f"  需求解析                {'模型（' + sel.label + '）' if policy.needs_llm_ready() else '规则'}；模型层现在会用：{sel.label}（{sel.reason}）")
    missing = cfg.problems()
    if missing:
        print("真语音版还缺：\n  - " + "\n  - ".join(missing))
        print("缺 key 时可以先用 --fake-speech 演示（打字代替说话，macOS say 发声）。")
    else:
        print("真语音版需要的配置都在（是否真能连通跑 --check）。")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="HomeTruth voice tour on Pipecat (NVIDIA Parakeet + Magpie over SmallWebRTC).")
    ap.add_argument("--dry-run", action="store_true", help="build the pipeline without connecting to anything; print what is missing")
    ap.add_argument("--check", action="store_true", help="dry-run, then one real Magpie synthesis and Parakeet recognition if a key is set")
    ap.add_argument("--fake-speech", action="store_true", help="no key needed: typing instead of speech recognition, macOS say instead of Magpie")
    ap.add_argument("--port", type=int, help="default PIPECAT_PORT or 8631")
    a = ap.parse_args()
    if a.fake_speech:
        os.environ["TTS_BACKEND"] = "say"  # 只影响本进程：tts.py 走 macOS say
    cfg = Config.load(fake_speech=a.fake_speech)
    if a.port:
        cfg.port = a.port
    logger.remove()
    logger.add(sys.stderr, level="ERROR" if (a.dry_run or a.check) else os.environ.get("PIPECAT_LOG", "INFO"))
    if a.check:
        return check(cfg)
    if a.dry_run:
        return dry_run_report(cfg)
    if not cfg.fake_speech and cfg.problems():
        print("真语音版起不来，还缺：\n  - " + "\n  - ".join(cfg.problems()) + "\n没 key 先用 --fake-speech 演示。", flush=True)
        return 2
    d = cfg.describe()
    if zetaris_live.enable():  # same as server.py: searches query the evidence through Zetaris (the tables point at the 8630 endpoint)
        zetaris_live.warm([s["name"] for s in policy.SOURCES], [L["id"] for L in policy.LISTINGS])
    print(f"HomeTruth voice (Pipecat) on http://{cfg.host}:{cfg.port}  (zetaris={'live' if zetaris_live.ENABLED else 'off'}, mode={d['mode']}, stt={d['stt']}, tts={d['tts']}, "
          f"needs parser={'llm' if policy.needs_llm_ready() else 'rules'}, narration={d['narration']}, turn={d['turn']})", flush=True)
    serve(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
