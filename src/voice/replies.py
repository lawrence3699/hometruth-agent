# -*- coding: utf-8 -*-
"""读中介的回复（10-26 参考 Dot 改造的一部分）：一句中介的话 → 它回答的是清单上哪一格、新状态是什么、原话里哪一段把它定下来的。

先让 Nemotron 读（经 Meterless Nightshift 转发，src/llm/provider.py；转发不通就直连并记录），JSON 回来后规则校验：
维度得在清单里、状态只有四种、引用必须是原话的子串、解释里不许冒出原话没有的数字；校验不过、超时或模型不在就退回三条正则（老的演示路径）。
谁读的（llm / rules、模型名、毫秒）记在 reader 里，界面的 Changes 面板和信念日志（beliefs.py）都带着。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.append(str(ROOT / "src"))
try:
    from llm import provider as llm
except Exception:  # noqa: BLE001
    llm = None

DIMS: Dict[str, dict] = json.loads((HERE / "mock_matrix.json").read_text(encoding="utf-8"))["dims"]
STATUSES = ("supported", "inferred", "conflict", "unknown")
MEANING = {  # 给模型看的一句话：每一格问的是什么
    "A1": "weekly rent against the renter's budget", "B1": "number of bedrooms", "G1": "commute time to the renter's anchor",
    "A4": "move-in / availability date", "J1": "whether pets are allowed", "C1": "air conditioning (where, what kind)",
    "A6": "bills and utilities included or not", "C2": "furniture and staging (is the place furnished as photographed)",
    "E4": "noise and quiet", "E2": "sunlight and orientation", "H1": "legal disclosures the landlord must make", "C3": "stove / cooktop type",
}
# 老的三条规则：模型不在时的兜底，也是回归基线走的路（NEEDS_PARSER=rules）
RULES = [
    (r"living room only|no air ?con in the bed|not in the bedroom", "C1", "conflict", "The agent confirms the split system is in the living room only."),
    (r"pets? (are|is) (fine|ok|okay|allowed|welcome)|yes to the (cat|dog|pet)|(cat|dog) is fine", "J1", "supported", "The agent confirmed pets are allowed, in writing."),
    (r"no pets|pets? (are|is) not allowed", "J1", "conflict", "The agent says no pets. Under NSW rules that still needs a set ground, so it's a conflict to push on."),
]
PROMPT = """You read ONE reply from a rental agent and map it to ONE condition on a renter's check-list for one listing.
Conditions (code: what it asks):
{dims}
Listing: {street}. What the sources say so far: {cells}
What the renter wants: {profile}
Reply with ONE JSON object and nothing else:
{{"dim": "<code>", "status": "supported|inferred|conflict|unknown", "quote": "<the exact words from the reply that settle it>", "why": "<one short plain sentence; no numbers that are not in the reply>"}}
status: supported = the agent plainly confirms what the renter wants; conflict = the agent says the opposite, or attaches a condition that clashes with what the renter wants or with what the sources said; inferred = the agent hints but does not confirm; unknown = the agent dodges or says they will check.
If the reply answers nothing on the list, reply {{"dim": null}}."""


def rules_only() -> bool:
    return os.environ.get("NEEDS_PARSER", "auto").strip().lower() == "rules"


def ready() -> bool:
    """模型路可用吗（和 policy.needs_llm_ready 同一口径）。"""
    if llm is None or rules_only():
        return False
    try:
        return llm.select().name != "none"
    except Exception:  # noqa: BLE001
        return False


def timeout_s() -> float:
    return float(os.environ.get("REPLY_LLM_TIMEOUT", "6"))


def read_rules(text: str) -> Optional[dict]:
    t = text.lower()
    for pat, dim, status, why in RULES:
        if re.search(pat, t):
            return {"dim": dim, "status": status, "why": why, "quote": None, "reader": {"parser": "rules"}}
    return None


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().replace("’", "'").split())


def _json_object(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def validate(obj: dict, text: str) -> Tuple[Optional[dict], str]:
    """模型给的 JSON 过规则：返回 (结果, 拒绝原因)。"""
    dim = obj.get("dim")
    if dim in (None, "", "null"):
        return None, "model says the reply answers nothing on the list"
    dim = str(dim).strip().upper()
    if dim not in DIMS or dim == "H1":
        return None, f"dim {dim!r} not on the list"
    status = str(obj.get("status") or "").strip().lower()
    if status not in STATUSES:
        return None, f"status {status!r} not one of {STATUSES}"
    quote = " ".join(str(obj.get("quote") or "").split())
    if quote and _norm(quote) not in _norm(text):
        return None, "quote is not in the reply"
    why = " ".join(str(obj.get("why") or "").split())[:200]
    if set(re.findall(r"\d+", why)) - set(re.findall(r"\d+", text)):
        return None, "why adds a number the reply does not have"
    if not why:
        why = f"The agent's reply settles {DIMS[dim]['label'].lower()}: {status}."
    return {"dim": dim, "status": status, "why": why, "quote": quote or None}, ""


def read_llm(text: str, L: dict, cells: Dict[str, dict], profile: dict) -> Tuple[Optional[dict], dict]:
    """只做模型那一步。返回 (结果或 None, reader meta)；失败原因在 meta['reason']。"""
    dims = "\n".join(f"- {d}: {v['label']} — {MEANING.get(d, v['label'].lower())}" for d, v in DIMS.items() if d != "H1")
    cell_view = {d: f"{c['status']}" + (f" ({c['why'][:90]})" if c.get("why") else "") for d, c in cells.items() if d != "H1"}
    system = PROMPT.format(dims=dims, street=L["street"], cells=json.dumps(cell_view), profile=json.dumps(profile))
    try:
        res = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": f"Agent's reply: {text}"}], task="agent_reply",
                       temperature=0, max_tokens=160, retries=0, timeout=timeout_s())
    except Exception as e:  # noqa: BLE001
        return None, {"parser": "rules", "reason": f"{getattr(e, 'kind', type(e).__name__)}: {str(e)[:160]}"}
    meta = {"parser": "llm", "provider": res.provider, "model": res.model, "served_model": res.served_model, "ms": res.ms,
            "fallback_from": res.fallback_from or None}
    obj = _json_object(res.text)
    if obj is None:
        return None, dict(meta, parser="rules", reason="model answer was not a JSON object")
    out, why_not = validate(obj, text)
    if out is None:
        return None, dict(meta, parser="rules", reason=why_not)
    out["reader"] = meta
    return out, meta


def read(text: str, L: dict, cells: Dict[str, dict], profile: dict, *, deterministic: bool = False) -> Tuple[Optional[dict], dict]:
    """模型先读、规则校验、规则兜底。返回 (结果或 None, reader meta)。结果：{dim, status, why, quote, reader}。"""
    if not deterministic and ready():
        out, meta = read_llm(text, L, cells, profile)
        if out is not None:
            return out, meta
        rules = read_rules(text)
        if rules is not None:
            rules["reader"] = dict(meta, parser="rules", fallback="rules")
            return rules, rules["reader"]
        return None, meta
    rules = read_rules(text)
    if rules is None:
        return None, {"parser": "rules", "reason": "no rule matched"}
    return rules, rules["reader"]


def dim_words(dim: str) -> str:
    return DIMS.get(dim, {}).get("label", dim)
