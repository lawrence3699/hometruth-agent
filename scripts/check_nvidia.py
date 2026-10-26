#!/usr/bin/env python3
"""NVIDIA / Meterless Nightshift 连通性自检（只依赖标准库，不打印任何 key）。所有模型请求都走 src/llm/provider.py，不另写一套。

用法：python3 scripts/check_nvidia.py            （加 --no-speech 跳过语音链那几行）
读项目根目录 .env：
  NVIDIA_API_KEY            build.nvidia.com 生成的 nvapi-...（直连 NVIDIA 回退和语音链用）
  NVIDIA_TEXT_MODEL         默认 nvidia/nemotron-3.5-lightning-30b-a3b
  NVIDIA_VL_MODEL           默认 nvidia/nemotron-3.5-super-vl-120b-a12b
  METERLESS_BASE_URL        Nightshift Console 里的 Runtime 地址，默认 http://127.0.0.1:8088/v1
  METERLESS_RUNTIME_TOKEN   Nightshift Console 里的 Runtime access token（不是 NVIDIA key）
  METERLESS_MODEL           默认 meterless/auto（路由模式，不是具体模型名）
每行一个结果：PASS / FAIL / SKIP。Nightshift 那几行就是 Power Prompt 要求的四项（连接、鉴权、模型发现、文本请求）加合同完成标准。
语音链（Magpie 合成、Parakeet 识别、Pipecat 管线能否构建）交给 .venv/bin/python src/voice/pipecat_app.py --check，结果原样并进来。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm import provider  # noqa: E402

OK_PROMPT = [{"role": "system", "content": "Reply with exactly one word."}, {"role": "user", "content": "Reply with the single word OK."}]
WRONG_TOKEN = "hometruth-deliberately-wrong-token"


def line(tag: str, ok, msg: str) -> None:
    mark = "PASS" if ok is True else ("SKIP" if ok is None else "FAIL")
    print(f"{mark:4}  {tag:34} {msg}", flush=True)


def short(text: str, n: int = 60) -> str:
    return " ".join((text or "").split())[:n]


def try_chat(**kw):
    try:
        return provider.chat(OK_PROMPT, task="check", max_tokens=64, temperature=0, retries=1, timeout=120, **kw), None
    except provider.LLMError as e:
        return None, e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-speech", action="store_true")
    a = ap.parse_args()
    provider.load_env()
    nv, cfg = provider.nvidia_config(), provider.meterless_config()
    fails = 0

    # 1) NVIDIA 公开目录：不需要 key，顺便确认模型名没下线
    status, ids, ms, err = provider.nvidia_catalog()
    line("NVIDIA catalog", status == 200, f"HTTP {status}, {len(ids)} models, {ms} ms {err}".rstrip())
    fails += status != 200
    for m in (nv.text_model, nv.vl_model):
        listed = m in ids
        line(f"model listed: {m[:28]}", listed if ids else None, "in catalog" if listed else "NOT in catalog (下线或拼错)")
        fails += bool(ids) and not listed

    # 2) 直连 NVIDIA（需要 key）
    if not nv.key:
        line("NVIDIA direct chat", None, "NVIDIA_API_KEY 为空或不是 nvapi- 开头，跳过")
        line("NVIDIA direct VL (text only)", None, "同上")
    else:
        for tag, model in (("NVIDIA direct chat", nv.text_model), ("NVIDIA direct VL (text only)", nv.vl_model)):
            res, e = try_chat(provider="nvidia", model=model)
            line(tag, res is not None, f"{res.ms} ms → {short(res.text)}" if res else f"{e.kind}: {short(str(e), 90)}")
            fails += res is None

    # 3) 经 Nightshift（Power 规则的正路）：连接、鉴权、模型发现、文本请求 + 合同完成标准
    p = provider.probe(cfg.base_url, cfg.token, timeout=10)
    nightshift_chat_ok = False
    if p.status == 0:
        hit = provider.auto_detect(cfg.token, timeout=0.7)
        where = f"Auto Detect 在 {hit.base_url} 找到（{hit.state}），跑 python3 src/llm/provider.py detect --save" if hit else \
            "Auto Detect：8088/8090/8787/11434 都没有（Nightshift 没装或没开）"
        line("Nightshift connection", False, f"{cfg.base_url} 连不上；{where}")
        fails += 1
        for tag in ("Nightshift auth", "Nightshift wrong token → unauth", "Nightshift model discovery", "Nightshift text request",
                    "Nightshift stream", "Nemotron behind Nightshift"):
            line(tag, None, "跳过（先让 Nightshift 连上）")
    else:
        hz_ok, hz_status, hz_ms, _ = provider.healthz(cfg.base_url)
        line("Nightshift connection", True, f"{cfg.base_url} 有应答（/v1/models HTTP {p.status}, /healthz HTTP {hz_status or '-'}）")
        hit = provider.auto_detect(cfg.token, timeout=0.7)
        line("Nightshift Auto Detect", True if hit else None, f"{hit.state} at {hit.base_url}" if hit else "8088/8090/8787/11434 没找到（Runtime 不在默认端口时正常）")
        if not cfg.token:
            line("Nightshift auth", None, "METERLESS_RUNTIME_TOKEN 为空，跳过（Nightshift 右上 Console 里复制）" + ("；" + "；".join(cfg.notes) if cfg.notes else ""))
        else:
            line("Nightshift auth", p.state == "online", {"online": f"token 有效（来源 {cfg.token_source}）", "unauthorized": "token 被拒（401/403）：重新从 Console 复制"}
                 .get(p.state, f"{p.state}: {p.error}"))
            fails += p.state != "online"
        w = provider.probe(cfg.base_url, WRONG_TOKEN, timeout=10)
        line("Nightshift wrong token → unauth", w.state == "unauthorized", f"故意用错 token → {w.state}（合同：必须是 unauthorized，不是 offline）")
        fails += w.state != "unauthorized"
        if p.state != "online":
            for tag in ("Nightshift model discovery", "Nightshift text request", "Nightshift stream", "Nemotron behind Nightshift"):
                line(tag, None, "跳过（token 先要通过）")
        else:
            listed = cfg.model in p.meterless_ids
            line("Nightshift model discovery", True, f"{len(p.meterless_ids)} 个 meterless/* 路由，如 {p.meterless_ids[:4]}" +
                 ("" if listed else f"；{cfg.model} 不在列表里（合同允许，若 chat 报不存在就换成列表里的）"))
            res, e = try_chat(provider="meterless")
            nightshift_chat_ok = res is not None
            line("Nightshift text request", nightshift_chat_ok,
                 f"{cfg.model}: {res.ms} ms → {short(res.text)}（served {res.served_model or '?'}）" if res else f"{e.kind}: {short(str(e), 90)}")
            fails += res is None
            if res is not None:
                rs, es = try_chat(provider="meterless", stream=True)
                line("Nightshift stream", rs is not None, f"首字 {rs.first_token_ms} ms，共 {rs.ms} ms" if rs else f"{es.kind}: {short(str(es), 90)}")
                fails += rs is None
                served = (res.served_model or "").lower()
                if "nemotron" in served:
                    line("Nemotron behind Nightshift", True, f"served model = {res.served_model}")
                elif not served or served.startswith("meterless/"):
                    line("Nemotron behind Nightshift", None, "runtime 没报具体模型；去 Nightshift 的 run details 看是哪条 lane、哪个模型")
                else:
                    line("Nemotron behind Nightshift", False, f"served model = {res.served_model}：把 METERLESS_MODEL 钉到 Nemotron 那条 lane")
                    fails += 1
            else:
                line("Nightshift stream", None, "跳过")
                line("Nemotron behind Nightshift", None, "跳过")

    # 4) 语音链：交给 .venv 里的 Pipecat 应用做（gRPC，和真管线同一条路）
    if not a.no_speech:
        py = ROOT / ".venv" / "bin" / "python"
        if not py.exists():
            line("Pipecat / speech", None, "没有 .venv：按 requirements-voice.txt 顶部那两条命令建")
        else:
            try:
                out = subprocess.run([str(py), str(ROOT / "src" / "voice" / "pipecat_app.py"), "--check"], capture_output=True, text=True,
                                     timeout=180, cwd=str(ROOT))
                rows = [x for x in out.stdout.splitlines() if x[:4] in ("PASS", "FAIL", "SKIP")]
                for x in rows:
                    print(x, flush=True)
                fails += sum(x.startswith("FAIL") for x in rows)
                if not rows:
                    line("Pipecat / speech", False, f"exit {out.returncode}: {short(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else '', 90)}")
                    fails += 1
            except subprocess.TimeoutExpired:
                line("Pipecat / speech", False, "超过 180 s 没跑完")
                fails += 1

    sel = provider.select(refresh=True)
    print(f"\n现在产品会用：{sel.label}（{sel.reason}）")
    ready = fails == 0 and bool(nv.key) and nightshift_chat_ok
    print("READY" if ready else "NOT READY（上面 FAIL/SKIP 的项就是还差的；用户要做的三步见 STATE.md）")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
