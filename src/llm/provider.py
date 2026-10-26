#!/usr/bin/env python3
"""模型调用入口：Meterless Runtime（Nightshift）优先 → 直连 NVIDIA → 无。只依赖标准库（Python 3.9 起）。

合同：docs/hackathon/meterless_power_prompt.md（Meterless Runtime 1.4, provider contract v4，2026-10-25 从 meterless.ai 取回）。
设置读项目根目录 .env（不覆盖已有环境变量）：
  METERLESS_BASE_URL       Nightshift Console 里的 Runtime 地址，默认 http://127.0.0.1:8088/v1；直接粘 connect 链接也行
  METERLESS_RUNTIME_TOKEN  Console 里的 Runtime access token（合同里的 meterless_runtime_token 键；不是 NVIDIA key）
  METERLESS_MODEL          路由模式，默认 meterless/auto（不是模型名；可钉 meterless/fast 等，见 models 命令）
  METERLESS_CONNECT_LINK   可选：http://<host>:<port>/connect#k=<key>[&m=<model>]，一次填好地址、token、模式
  METERLESS_TOKEN_FILE     可选：<stateDir>/proxy-token 的路径，token 为空时从这里读
  METERLESS_APP            meterless-app 头，默认 hometruth
  NVIDIA_API_KEY           直连 NVIDIA 用（Nightshift 没开或连不上时的回退）；NVIDIA_TEXT_MODEL、NVIDIA_VL_MODEL
  LLM_PROVIDER             auto（默认：meterless → nvidia → none）| meterless（只走 Nightshift）| nvidia | none
每次调用追加一行到 runs/llm_log.jsonl：provider、model、prompt 哈希、耗时、token 数；不记 key、token、连接链接。
思考模式：chat(..., thinking=False)（默认）在请求体里带 chat_template_kwargs.enable_thinking=false。2026-10-25 实测 nemotron-3.5：
  不带它时模型先写 reasoning_content，max_tokens 小就只剩推理、content 为空；提示词里写 /no_think 没有用。

命令行：
  python3 src/llm/provider.py status              现在会选哪个 provider、为什么
  python3 src/llm/provider.py detect [--save]     Auto Detect（8088/8090/8787/11434 × 127.0.0.1/localhost/[::1]）；--save 写进 .env
  python3 src/llm/provider.py models              模型发现（GET /v1/models）
  python3 src/llm/provider.py chat "Say hi." [--stream] [--model meterless/fast] [--provider nvidia]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "runs" / "llm_log.jsonl"

PROVIDER_ID = "meterless"
PROVIDER_NAME = "Meterless Runtime"
DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
DEFAULT_MODEL = "meterless/auto"
APP_ID = "hometruth"
PLACEHOLDER_TOKENS = {"rt-local"}
DISPOSITIONS = ("auto", "fast", "deep", "cheap", "local", "fusion")
DETECT_PORTS = (8088, 8090, 8787, 11434)
DETECT_HOSTS = ("127.0.0.1", "localhost", "[::1]")
TIMEOUT_S = 180.0  # 合同：模型加载可能要几分钟
RETRY_DELAYS = (2.0, 4.0, 8.0)  # 429 / 额度错误
SELECT_TTL_S = 60.0

NV_BASE = "https://integrate.api.nvidia.com/v1"
NV_TEXT_DEFAULT = "nvidia/nemotron-3.5-lightning-30b-a3b"
NV_VL_DEFAULT = "nvidia/nemotron-3.5-super-vl-120b-a12b"

THINKING_OFF_KW = {"enable_thinking": False}  # Nemotron 3.5 / Qwen3 系列认这个；/no_think 文本对 nemotron-3.5 无效（2026-10-25 实测）
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
REFUSAL_CODES = {"class_carrier_unsupported", "class_no_route", "class_not_ready", "mesh_level_unavailable"}

_env_loaded = False
_log_lock = threading.Lock()
_sel_lock = threading.Lock()
_sel_cache: Optional["Selection"] = None


# ---------------------------------------------------------------- 设置
def env_file() -> Optional[Path]:
    """默认项目根目录 .env；HOMETRUTH_ENV_FILE 可指向别的文件，设成空串则不读（测试用）。"""
    v = os.environ.get("HOMETRUTH_ENV_FILE")
    if v is None:
        return ROOT / ".env"
    return Path(v).expanduser() if v.strip() else None


def load_env(force: bool = False) -> None:
    global _env_loaded
    if _env_loaded and not force:
        return
    _env_loaded = True
    path = env_file()
    if path is None or not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def normalize_base_url(raw: str) -> str:
    """合同：有无 scheme、带 /v1、/v1/chat/completions、/v1/models、/healthz 都归一成 <host>/v1，绝不出 /v1/v1。"""
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return DEFAULT_BASE_URL
    if "://" not in s:
        s = "http://" + s
    u = urllib.parse.urlsplit(s)
    path = u.path.rstrip("/")
    for suffix in ("/chat/completions", "/models", "/healthz"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    while path.endswith("/v1/v1"):
        path = path[:-3]
    if not path.endswith("/v1"):
        path += "/v1"
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc, path, "", ""))


def parse_connect_link(text: str) -> Optional[dict]:
    """http(s)://<host>:<port>/connect#k=<key>[&m=<model>][&n=<app>] → base_url / api_key / model / app。
    只有 http(s)、路径 /connect、片段里有 k 才算；一个普通的 base URL 不是失败的链接。"""
    s = (text or "").strip().strip('"').strip("'")
    if "#" not in s:
        return None
    try:
        u = urllib.parse.urlsplit(s)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc or u.path.rstrip("/") != "/connect":
        return None
    frag: Dict[str, str] = {}
    for piece in u.fragment.split("&"):
        if "=" in piece:
            k, v = piece.split("=", 1)
            frag[k] = urllib.parse.unquote(v)
    if not frag.get("k"):
        return None
    origin = f"{u.scheme}://{u.netloc}"
    return {"base_url": origin + "/v1", "api_key": frag["k"], "model": frag.get("m") or DEFAULT_MODEL,
            "app": frag.get("n") or APP_ID, "health_url": origin + "/healthz"}


@dataclass
class MeterlessConfig:
    base_url: str
    token: str = field(repr=False)
    model: str
    app: str
    base_source: str  # env / connect_link / default
    token_source: str  # env / connect_link / token_file / ""
    notes: List[str] = field(default_factory=list)


@dataclass
class NvidiaConfig:
    key: str = field(repr=False)
    base_url: str
    text_model: str
    vl_model: str


def meterless_config() -> MeterlessConfig:
    load_env()
    notes: List[str] = []
    link = parse_connect_link(_env("METERLESS_CONNECT_LINK")) or parse_connect_link(_env("METERLESS_BASE_URL"))
    raw_base = _env("METERLESS_BASE_URL")
    if link:
        base, base_source = link["base_url"], "connect_link"
    elif raw_base:
        base, base_source = normalize_base_url(raw_base), "env"
    else:
        base, base_source = DEFAULT_BASE_URL, "default"
    token = _env("METERLESS_RUNTIME_TOKEN") or _env("meterless_runtime_token") or _env("METERLESS_API_KEY")
    token_source = "env" if token else ""
    if token in PLACEHOLDER_TOKENS:
        notes.append("placeholder rt-local is rejected; paste the real Runtime token from the Nightshift Console")
        token, token_source = "", ""
    if not token and link:
        token, token_source = link["api_key"], "connect_link"
    if not token and _env("METERLESS_TOKEN_FILE"):
        p = Path(_env("METERLESS_TOKEN_FILE")).expanduser()
        try:
            t = p.read_text(encoding="utf-8").strip()
            if t and t not in PLACEHOLDER_TOKENS:
                token, token_source = t, "token_file"
        except OSError:
            notes.append("METERLESS_TOKEN_FILE is not readable")
    model = _env("METERLESS_MODEL") or (link["model"] if link else DEFAULT_MODEL)
    app = (_env("METERLESS_APP") or (link["app"] if link else APP_ID)).lower()
    return MeterlessConfig(base, token, model, app, base_source, token_source, notes)


def nvidia_config() -> NvidiaConfig:
    load_env()
    key = _env("NVIDIA_API_KEY")
    return NvidiaConfig(key if key.startswith("nvapi-") else "", NV_BASE, _env("NVIDIA_TEXT_MODEL", NV_TEXT_DEFAULT),
                        _env("NVIDIA_VL_MODEL", NV_VL_DEFAULT))


# ---------------------------------------------------------------- 错误
HINTS = {
    "unreachable": "Meterless Runtime isn't reachable at {base}. Start Nightshift, or run Auto Detect: python3 src/llm/provider.py detect",
    "timeout": "No answer from {base} within the time limit. A model load can take minutes; try again or pin a lighter route.",
    "unauthorized": "Paste the Runtime token from the Nightshift Console into METERLESS_RUNTIME_TOKEN in .env.",
    "model_not_found": "That model or route isn't served here. List what is: python3 src/llm/provider.py models",
    "rate_limited": "Rate limited or out of quota. Wait a moment, or pick another lane in Nightshift.",
    "server_error": "The server failed on its side. Check Nightshift's run details or logs.",
    "bad_response": "The answer couldn't be read as an OpenAI-compatible response.",
    "no_provider": "No model provider is configured: set METERLESS_RUNTIME_TOKEN (Nightshift) or NVIDIA_API_KEY in .env.",
}


class LLMError(Exception):
    """kind: unreachable / timeout（传输失败，可回退）| unauthorized / model_not_found / rate_limited / refused /
    bad_request / server_error / bad_response / no_provider。message 先放服务端原话，有 fix[] 用 fix，否则加我们的提示。"""

    def __init__(self, kind: str, server_message: str = "", *, status: int = 0, code: str = "", fix: Optional[List[str]] = None,
                 provider: str = "", base: str = "", chat_carrier: Optional[bool] = None):
        self.kind, self.status, self.code, self.fix = kind, status, code, list(fix or [])
        self.provider, self.base, self.chat_carrier = provider, base, chat_carrier
        self.server_message = server_message
        parts = [server_message] if server_message else []
        if self.fix:
            parts.extend(self.fix)
        elif kind in HINTS and kind != "refused":
            parts.append(HINTS[kind].format(base=base or "the configured address"))
        super().__init__(" ".join(p.strip() for p in parts if p and p.strip()) or kind)

    @property
    def transport(self) -> bool:
        return self.kind in ("unreachable", "timeout")


def _error_from_body(status: int, body: bytes, provider: str, base: str) -> LLMError:
    msg, code, fix, carrier = "", "", [], None
    try:
        j = json.loads(body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        j = None
    if isinstance(j, dict):
        err = j.get("error")
        meta = j.get("meterless") if isinstance(j.get("meterless"), dict) else {}
        if isinstance(err, dict):
            msg = str(err.get("message") or "")
            code = str(err.get("code") or err.get("type") or "")
            if isinstance(err.get("meterless"), dict):
                meta = err["meterless"]
        elif isinstance(err, str):
            msg = err
        msg = msg or str(j.get("detail") or j.get("message") or j.get("title") or "")
        if isinstance(meta.get("fix"), list):
            fix = [str(x) for x in meta["fix"]]
        if isinstance(meta.get("chat_carrier"), bool):
            carrier = meta["chat_carrier"]
    elif body:
        msg = body[:300].decode("utf-8", errors="replace")
    low = (msg + " " + code).lower()
    if status in (401, 403):
        kind = "unauthorized"
    elif status == 429 and code == "auth_rate_limited":
        kind = "unauthorized"  # 坏 key 被限流：要 key，不重试
    elif status == 429 or status == 402 or "quota" in low:
        kind = "rate_limited"
    elif code in REFUSAL_CODES or carrier is False:
        kind = "refused"
    elif status in (404, 410) or ("model" in low and re.search(r"not found|does not exist|unknown|not available|unsupported|no such", low)):
        kind = "model_not_found"
    elif status >= 500:
        kind = "server_error"
    else:
        kind = "bad_request"
    return LLMError(kind, _redact(msg)[:400], status=status, code=code, fix=fix, provider=provider, base=base, chat_carrier=carrier)


def _redact(s: str) -> str:
    s = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "nvapi-***", s or "")
    s = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", s)
    s = re.sub(r"#k=[^&\s]+", "#k=***", s)
    tok = meterless_config().token if _env_loaded else ""
    if tok and len(tok) >= 6:
        s = s.replace(tok, "***")
    return s


# ---------------------------------------------------------------- HTTP
def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _open(req: urllib.request.Request, timeout: float):
    # 本机地址不走系统代理
    if _host(req.full_url) in LOOPBACK:
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _transport_error(e: BaseException, provider: str, base: str) -> LLMError:
    reason = getattr(e, "reason", e)
    if isinstance(reason, (socket.timeout, TimeoutError)) or isinstance(e, (socket.timeout, TimeoutError)):
        return LLMError("timeout", "", provider=provider, base=base)
    return LLMError("unreachable", _redact(str(reason))[:200], provider=provider, base=base)


def _headers(provider: str, token: str, app: str, chat: bool, trace: bool = False) -> Dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "hometruth/0.2"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if provider == PROVIDER_ID:
        h["meterless-app"] = app
        if chat:
            h["meterless-scope"] = "user"
        if trace:
            h["meterless-trace"] = "on"
    if chat:
        h["Content-Type"] = "application/json"
    return h


def _get_json(url: str, headers: Dict[str, str], timeout: float, provider: str, base: str) -> Tuple[int, Any, int]:
    """返回 (HTTP 状态, JSON 或 None, 毫秒)；连不上抛 LLMError。"""
    req = urllib.request.Request(url, headers=headers, method="GET")
    t0 = time.time()
    try:
        with _open(req, timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _transport_error(e, provider, base) from None
    ms = round((time.time() - t0) * 1000)
    try:
        return status, json.loads(raw.decode("utf-8") or "null"), ms
    except (ValueError, UnicodeDecodeError):
        return status, None, ms


# ---------------------------------------------------------------- 连接、鉴权、模型发现
@dataclass
class Probe:
    state: str  # online / unauthorized / offline
    base_url: str
    status: int = 0  # HTTP 状态；0 = 连不上
    ms: int = 0
    models: List[str] = field(default_factory=list)
    meterless_ids: List[str] = field(default_factory=list)
    error: str = ""


def probe(base_url: Optional[str] = None, token: Optional[str] = None, timeout: float = 5.0) -> Probe:
    """合同：GET /v1/models 说了算。401/403 = unauthorized，200 且有 meterless/* = online，其他 = offline。"""
    cfg = meterless_config()
    base = normalize_base_url(base_url) if base_url else cfg.base_url
    tok = cfg.token if token is None else token
    try:
        status, body, ms = _get_json(base + "/models", _headers(PROVIDER_ID, tok, cfg.app, chat=False), timeout, PROVIDER_ID, base)
    except LLMError as e:
        return Probe("offline", base, 0, 0, error=str(e.server_message or e.kind))
    if status in (401, 403):
        return Probe("unauthorized", base, status, ms, error="token rejected" if tok else "no token sent")
    ids = [str(m.get("id")) for m in (body or {}).get("data", []) if isinstance(m, dict) and m.get("id")] if isinstance(body, dict) else []
    mids = [i for i in ids if i.startswith("meterless/")]
    if status == 200 and mids:
        return Probe("online", base, status, ms, ids, mids)
    why = "HTTP 200 but no meterless/* ids (not a Meterless Runtime?)" if status == 200 else f"HTTP {status}"
    return Probe("offline", base, status, ms, ids, mids, error=why)


def healthz(base_url: Optional[str] = None, timeout: float = 3.0) -> Tuple[bool, int, int, str]:
    """只证明进程在。返回 (通不通, HTTP 状态, 毫秒, 错误)。"""
    cfg = meterless_config()
    base = normalize_base_url(base_url) if base_url else cfg.base_url
    origin = base[: -len("/v1")]
    try:
        status, _, ms = _get_json(origin + "/healthz", _headers(PROVIDER_ID, cfg.token, cfg.app, chat=False), timeout, PROVIDER_ID, base)
    except LLMError as e:
        return False, 0, 0, str(e.server_message or e.kind)
    return status == 200, status, ms, "" if status == 200 else f"HTTP {status}"


def auto_detect(token: Optional[str] = None, timeout: float = 1.0) -> Optional[Probe]:
    """合同：8088、8090、8787、11434 × 127.0.0.1、localhost、[::1]，返回第一个 online 或 unauthorized。"""
    for port in DETECT_PORTS:
        for host in DETECT_HOSTS:
            p = probe(f"http://{host}:{port}/v1", token, timeout)
            if p.state in ("online", "unauthorized"):
                return p
    return None


def save_base_url(url: str) -> Path:
    """Auto Detect 的"保存"：把 METERLESS_BASE_URL 写进 .env（只动这一行，不碰 token）。"""
    path = env_file() or (ROOT / ".env")
    url = normalize_base_url(url)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().startswith("METERLESS_BASE_URL="):
            out.append(f"METERLESS_BASE_URL={url}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"METERLESS_BASE_URL={url}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ["METERLESS_BASE_URL"] = url
    invalidate()
    return path


def discover(timeout: float = 10.0) -> Probe:
    return probe(timeout=timeout)


def nvidia_catalog(timeout: float = 30.0) -> Tuple[int, List[str], int, str]:
    """NVIDIA 公开目录（不要 key）。返回 (HTTP 状态, 模型 id, 毫秒, 错误)。"""
    try:
        status, body, ms = _get_json(NV_BASE + "/models", {"Accept": "application/json", "User-Agent": "hometruth/0.2"}, timeout, "nvidia", NV_BASE)
    except LLMError as e:
        return 0, [], 0, str(e.server_message or e.kind)
    ids = [str(m.get("id")) for m in (body or {}).get("data", []) if isinstance(m, dict)] if isinstance(body, dict) else []
    return status, ids, ms, "" if status == 200 else f"HTTP {status}"


# ---------------------------------------------------------------- 选 provider
@dataclass
class Selection:
    name: str  # meterless / nvidia / none
    model: str
    base_url: str
    reason: str
    mode: str  # LLM_PROVIDER
    meterless_state: str  # online / unauthorized / offline / no_token / disabled
    nvidia_state: str  # key / no_key
    detected: bool = False
    checked_at: float = 0.0

    @property
    def label(self) -> str:
        return {"meterless": "Meterless Runtime", "nvidia": "NVIDIA direct", "none": "none"}[self.name]


def invalidate() -> None:
    global _sel_cache
    with _sel_lock:
        _sel_cache = None


def select(refresh: bool = False) -> Selection:
    """auto：Nightshift 在线就用它；否则有 NVIDIA key 就直连；否则 none。没 token 也没 key 时不发任何网络请求。结果缓存 60 s。"""
    global _sel_cache
    with _sel_lock:
        if _sel_cache and not refresh and time.time() - _sel_cache.checked_at < SELECT_TTL_S:
            return _sel_cache
    load_env()
    mode = _env("LLM_PROVIDER", "auto").lower()
    cfg, nv = meterless_config(), nvidia_config()
    nv_state = "key" if nv.key else "no_key"
    now = time.time()
    if mode == "none":
        sel = Selection("none", "", "", "LLM_PROVIDER=none", mode, "disabled", nv_state, checked_at=now)
    else:
        m_state, base, detected = "disabled", cfg.base_url, False
        if mode in ("auto", "meterless"):
            if not cfg.token:
                m_state = "no_token"
            else:
                p = probe(cfg.base_url, cfg.token, timeout=3.0)
                if p.state == "offline" and p.status == 0:
                    d = auto_detect(cfg.token, timeout=0.5)
                    if d and d.base_url != cfg.base_url:
                        p, detected = d, True
                m_state, base = p.state, p.base_url
        if m_state == "online":
            why = f"Meterless Runtime online at {base}" + (" (found by Auto Detect)" if detected else "")
            sel = Selection("meterless", cfg.model, base, why, mode, m_state, nv_state, detected, now)
        elif mode in ("auto", "nvidia") and nv.key:
            sel = Selection("nvidia", nv.text_model, NV_BASE, f"direct NVIDIA (Meterless {m_state})", mode, m_state, nv_state, checked_at=now)
        else:
            sel = Selection("none", "", "", f"no provider (Meterless {m_state}, NVIDIA {nv_state}, LLM_PROVIDER={mode})", mode, m_state, nv_state,
                            checked_at=now)
    with _sel_lock:
        _sel_cache = sel
    return sel


def available() -> bool:
    return select().name != "none"


# ---------------------------------------------------------------- 文本请求
@dataclass
class ChatResult:
    text: str
    provider: str
    model: str  # 请求的模型或路由模式
    served_model: str  # 响应里的 model（经 Nightshift 时看是不是 Nemotron）
    ms: int
    first_token_ms: Optional[int] = None
    usage: Dict[str, int] = field(default_factory=dict)
    stream: bool = False
    fallback_from: str = ""
    fallback_reason: str = ""
    meterless: Optional[dict] = None
    parts: List[dict] = field(default_factory=list)
    retries: int = 0


THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


def strip_think(text: str) -> str:
    text = THINK_RE.sub("", text or "")
    if "</think>" in text:  # 开头没写 <think> 的推理块
        text = text.split("</think>", 1)[1]
    return text.strip()


def _flatten(content: Any) -> Tuple[str, List[dict]]:
    if isinstance(content, str):
        return content, []
    texts, parts = [], []
    if isinstance(content, list):
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                texts.append(str(p.get("text") or ""))
            elif isinstance(p, dict):
                parts.append(p)
            elif isinstance(p, str):
                texts.append(p)
    return "".join(texts), parts


def _media_lines(parts: List[dict]) -> List[str]:
    lines = []
    for p in parts:
        t = str(p.get("type") or "")
        url = None
        for k in ("image_url", "audio_url", "video_url", "audio", "output_audio", "input_audio"):
            v = p.get(k)
            if isinstance(v, dict):
                url = v.get("url") or (f"data:audio/{v.get('format', 'wav')};base64,{v['data']}" if v.get("data") else None)
            elif isinstance(v, str):
                url = v
            if url:
                break
        url = url or p.get("url")
        if url:
            lines.append(f"{'Image' if 'image' in t else ('Video' if 'video' in t else 'Audio')}: {str(url)[:200]}")
    return lines


def _reasoning_only(resp: Any) -> str:
    """content 为空但 reasoning_content 有字：思考把 max_tokens 吃光了。返回给人看的原因，没有这种情况返回空串。"""
    try:
        ch = (resp.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    except (AttributeError, IndexError, TypeError):
        return ""
    if reasoning and not msg.get("content"):
        return (f"the model spent its whole budget thinking ({len(reasoning)} chars of reasoning_content, finish_reason={ch.get('finish_reason')}); "
                "send chat_template_kwargs.enable_thinking=false (chat(..., thinking=False)) or raise max_tokens")
    return ""


def extract_text(resp: dict) -> Tuple[str, List[dict]]:
    """读每一种回答形状：content 字符串、分段数组、message.audio、顶层 meterless.artifacts[]。"""
    choices = resp.get("choices") or []
    msg = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
    text, parts = _flatten(msg.get("content"))
    if isinstance(msg.get("audio"), dict):
        parts.append({"type": "audio", "audio": msg["audio"]})
    meta = resp.get("meterless") if isinstance(resp.get("meterless"), dict) else {}
    for a in meta.get("artifacts") or []:
        if isinstance(a, dict):
            parts.append(a)
    text = strip_think(text)
    lines = _media_lines(parts)
    if lines:
        text = "\n".join([text] + lines) if text else "\n".join(lines)
    return text, parts


def _usage(u: Any) -> Dict[str, int]:
    if not isinstance(u, dict):
        return {}
    return {k: int(u[k]) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(u.get(k), (int, float))}


def _meterless_meta(resp: dict) -> Optional[dict]:
    m = resp.get("meterless")
    if not isinstance(m, dict):
        return None
    keep = {k: v for k, v in m.items() if k != "artifacts" and not re.search(r"token|key|secret", k, re.I)}
    return keep or None


def prompt_hash(messages: List[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _log(entry: dict) -> None:
    entry = dict({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")}, **entry)
    line = json.dumps(entry, ensure_ascii=False)
    with _log_lock:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _endpoint(provider: str, base_url: Optional[str]) -> Tuple[str, str, str]:
    """返回 (base, token, app)。"""
    if provider == PROVIDER_ID:
        cfg = meterless_config()
        return (base_url or cfg.base_url), cfg.token, cfg.app
    if provider == "nvidia":
        nv = nvidia_config()
        return nv.base_url, nv.key, APP_ID
    raise LLMError("no_provider", f"unknown provider {provider}")


def _model_for(provider: str, model: Optional[str], vision: bool) -> str:
    if provider == PROVIDER_ID:
        if model and not model.startswith("nvidia/"):
            return model
        return meterless_config().model if not vision else "meterless/vision"
    nv = nvidia_config()
    if model and model.startswith("nvidia/"):
        return model
    return nv.vl_model if vision else nv.text_model


def _chat_once(provider: str, messages: List[dict], *, base_url: Optional[str], model: Optional[str], vision: bool, stream: bool,
               on_delta: Optional[Callable[[str], None]], on_progress: Optional[Callable[[Any], None]], temperature: Optional[float],
               max_tokens: Optional[int], timeout: float, retries: int, extra: Optional[dict],
               thinking: Optional[bool] = False) -> ChatResult:
    base, token, app = _endpoint(provider, base_url)
    if not token:
        raise LLMError("unauthorized", "no token configured", provider=provider, base=base)
    mdl = _model_for(provider, model, vision)
    body: Dict[str, Any] = {"model": mdl, "messages": messages, "stream": bool(stream)}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if extra:
        body.update(extra)
    if thinking is False:  # 关思考：对 Nemotron 3.5 是必须的，Nightshift 原样转给 NVIDIA；不认识这个字段的模型会忽略
        ctk = dict(body.get("chat_template_kwargs") or {})
        ctk.setdefault("enable_thinking", False)
        body["chat_template_kwargs"] = ctk
    headers = _headers(provider, token, app, chat=True, trace=on_progress is not None)
    attempt = 0
    while True:
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        t0 = time.time()
        try:
            r = _open(req, timeout)
        except urllib.error.HTTPError as e:
            err = _error_from_body(e.code, e.read(), provider, base)
            if err.kind == "rate_limited" and attempt < min(retries, len(RETRY_DELAYS)):
                time.sleep(RETRY_DELAYS[attempt])
                attempt += 1
                continue
            raise err from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise _transport_error(e, provider, base) from None
        try:
            with r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                reason_hint = ""
                if "text/event-stream" in ctype:
                    res = _read_sse(r, t0, on_delta, on_progress, provider, base)
                else:  # 请求了 stream 也可能回一整个 JSON
                    raw = r.read()
                    try:
                        resp = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        raise LLMError("bad_response", raw[:200].decode("utf-8", errors="replace"), status=r.status, provider=provider, base=base) from None
                    if isinstance(resp, dict) and resp.get("error"):
                        raise _error_from_body(r.status if r.status >= 400 else 500, raw, provider, base)
                    text, parts = extract_text(resp)
                    reason_hint = _reasoning_only(resp)
                    res = ChatResult(text, provider, mdl, str(resp.get("model") or ""), 0, None, _usage(resp.get("usage")), False,
                                     meterless=_meterless_meta(resp), parts=parts)
                    if on_delta and text:
                        on_delta(text)
        except (socket.timeout, TimeoutError) as e:
            raise _transport_error(e, provider, base) from None
        res.model = mdl
        res.ms = round((time.time() - t0) * 1000)
        res.stream = bool(stream)
        res.retries = attempt
        if not res.text and not res.parts:
            raise LLMError("bad_response", "empty answer" + (": " + reason_hint if reason_hint else ""), status=200, provider=provider, base=base)
        return res


def _read_sse(r, t0: float, on_delta, on_progress, provider: str, base: str) -> ChatResult:
    buf: List[str] = []
    parts: List[dict] = []
    first: Optional[int] = None
    usage: Dict[str, int] = {}
    served, meta = "", None
    for raw in r:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            j = json.loads(data)
        except ValueError:
            continue
        if not isinstance(j, dict):
            continue
        if j.get("error"):
            raise _error_from_body(500, data.encode("utf-8"), provider, base)
        m = j.get("meterless")
        if isinstance(m, dict):
            if m.get("progress") is not None and on_progress:
                on_progress(m["progress"])
            meta = _meterless_meta(j) or meta
        served = str(j.get("model") or served)
        usage = _usage(j.get("usage")) or usage
        for ch in j.get("choices") or []:
            delta = (ch or {}).get("delta") or (ch or {}).get("message") or {}
            text, ps = _flatten(delta.get("content"))
            parts.extend(ps)
            if text:
                if first is None:
                    first = round((time.time() - t0) * 1000)
                buf.append(text)
                if on_delta:
                    on_delta(text)
    text = strip_think("".join(buf))
    lines = _media_lines(parts)
    if lines:
        text = "\n".join([text] + lines) if text else "\n".join(lines)
    return ChatResult(text, provider, "", served, 0, first, usage, True, meterless=meta, parts=parts)


def chat(messages: List[dict], *, task: str = "chat", provider: Optional[str] = None, model: Optional[str] = None, vision: bool = False,
         stream: bool = False, on_delta: Optional[Callable[[str], None]] = None, on_progress: Optional[Callable[[Any], None]] = None,
         temperature: Optional[float] = None, max_tokens: Optional[int] = None, timeout: float = TIMEOUT_S,
         retries: int = len(RETRY_DELAYS), extra: Optional[dict] = None, allow_fallback: bool = True,
         thinking: Optional[bool] = False) -> ChatResult:
    """发一次 chat completions。provider 不给就按 select() 选；Nightshift 传输失败（连不上、超时）才回退直连 NVIDIA，
    带类型的拒绝（401、模型不存在、限流、拒绝）原样抛 LLMError。每次调用写一行 runs/llm_log.jsonl。"""
    sel = select() if provider is None else None
    name = provider or sel.name
    base_url = sel.base_url if (sel and sel.name == PROVIDER_ID) else None
    entry: Dict[str, Any] = {"task": task, "provider": name, "prompt_sha256": prompt_hash(messages),
                             "prompt_chars": sum(len(str(m.get("content", ""))) for m in messages), "stream": bool(stream)}
    if name == "none":
        err = LLMError("no_provider", sel.reason if sel else "")
        _log(dict(entry, status="no_provider", ms=0, error=str(err)[:300]))
        raise err
    kw = dict(model=model, vision=vision, stream=stream, on_delta=on_delta, on_progress=on_progress, temperature=temperature,
              max_tokens=max_tokens, timeout=timeout, retries=retries, extra=extra, thinking=thinking)
    t0 = time.time()
    try:
        res = _chat_once(name, messages, base_url=base_url, **kw)
    except LLMError as e:
        fallback_ok = (allow_fallback and name == PROVIDER_ID and e.transport and provider is None and sel is not None
                       and sel.mode == "auto" and nvidia_config().key)
        _log(dict(entry, model=_model_for(name, model, vision), base=_host(e.base or ""), status=e.kind, http=e.status,
                  ms=round((time.time() - t0) * 1000), error=_redact(str(e))[:300], fallback="nvidia" if fallback_ok else ""))
        if e.transport:
            invalidate()  # 下次调用重新探测
        if not fallback_ok:
            raise
        t1 = time.time()
        try:
            res = _chat_once("nvidia", messages, base_url=None, **kw)
        except LLMError as e2:
            _log(dict(entry, provider="nvidia", model=_model_for("nvidia", model, vision), status=e2.kind, http=e2.status,
                      ms=round((time.time() - t1) * 1000), error=_redact(str(e2))[:300], fallback_from=PROVIDER_ID))
            raise
        res.fallback_from, res.fallback_reason = PROVIDER_ID, e.kind
    _log(dict(entry, provider=res.provider, model=res.model, served_model=res.served_model, base=_host(_endpoint(res.provider, base_url)[0]),
              status="ok", ms=res.ms, first_token_ms=res.first_token_ms, tokens=res.usage, retries=res.retries,
              fallback_from=res.fallback_from or None, meterless=res.meterless, answer_chars=len(res.text)))
    return res


def complete(prompt: str, system: Optional[str] = None, **kw) -> ChatResult:
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    return chat(msgs, **kw)


# ---------------------------------------------------------------- 命令行
def _print_selection(sel: Selection) -> None:
    cfg = meterless_config()
    print(f"provider     {sel.label}  ({sel.reason})")
    print(f"model        {sel.model or '-'}")
    print(f"meterless    {sel.meterless_state}  base={cfg.base_url} ({cfg.base_source})  token={'set' if cfg.token else 'missing'}"
          f"{' (' + cfg.token_source + ')' if cfg.token_source else ''}  route={cfg.model}  app={cfg.app}")
    for n in cfg.notes:
        print(f"             note: {n}")
    nv = nvidia_config()
    print(f"nvidia       {'key set' if nv.key else 'no key'}  text={nv.text_model}  vl={nv.vl_model}")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="HomeTruth model provider (Meterless Runtime first, then NVIDIA direct).")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    d = sub.add_parser("detect")
    d.add_argument("--save", action="store_true")
    sub.add_parser("models")
    c = sub.add_parser("chat")
    c.add_argument("prompt")
    c.add_argument("--stream", action="store_true")
    c.add_argument("--model")
    c.add_argument("--provider", choices=["meterless", "nvidia"])
    a = ap.parse_args(argv)
    load_env()
    if a.cmd in (None, "status"):
        _print_selection(select(refresh=True))
        return 0
    if a.cmd == "detect":
        p = auto_detect(meterless_config().token)
        if not p:
            print("Auto Detect: nothing on ports 8088/8090/8787/11434 (127.0.0.1, localhost, [::1]). Is Nightshift running?")
            return 1
        print(f"Auto Detect: {p.state} at {p.base_url} ({p.ms} ms)")
        if a.save:
            print(f"saved METERLESS_BASE_URL to {save_base_url(p.base_url)}")
        return 0
    if a.cmd == "models":
        p = discover()
        print(f"{p.state}  {p.base_url}  HTTP {p.status}  {p.ms} ms  {p.error}")
        for m in p.models:
            print("  " + m)
        return 0 if p.state == "online" else 1
    if a.cmd == "chat":
        try:
            res = complete(a.prompt, provider=a.provider, model=a.model, stream=a.stream,
                           on_delta=(lambda s: print(s, end="", flush=True)) if a.stream else None)
        except LLMError as e:
            print(f"\n{e.kind}: {e}")
            return 1
        print(("\n" if a.stream else "") + ("" if a.stream else res.text))
        print(f"[{res.provider} {res.model} → {res.served_model or '?'} · {res.ms} ms · {res.usage or 'no usage'}"
              f"{' · fallback from ' + res.fallback_from if res.fallback_from else ''}]")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
