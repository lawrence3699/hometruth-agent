"""对话策略：反问五样必填、按证据排序、导览事件流、打断后怎么接。
原则：程序判断（问什么、说哪格、怎么排），模板措辞（phraser）。事件协议见 README。"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import beliefs
import inbox
import memory
import narrator
import phraser
import replies

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.append(str(ROOT / "src"))
try:  # 模型层（Meterless → NVIDIA → 无）；导入失败也不影响规则版
    from llm import provider as llm
except Exception:  # noqa: BLE001
    llm = None
MATRIX = json.loads((HERE / "mock_matrix.json").read_text(encoding="utf-8"))
LISTINGS: List[dict] = MATRIX["listings"]
SOURCES: List[dict] = MATRIX["sources"]
DIMS: Dict[str, dict] = MATRIX["dims"]
for _d, _v in {"D1": {"label": "Condition", "hard": False}, "K1": {"label": "Numbers", "hard": False, "pack": "fengshui"}, "K2": {"label": "Through-line", "hard": False, "pack": "fengshui"},
               "K3": {"label": "Doors", "hard": False, "pack": "fengshui"}, "K4": {"label": "Outline", "hard": False, "pack": "fengshui"}}.items():
    DIMS.setdefault(_d, _v)  # 10-26：照片新旧 + 文化偏好核对包；scripts/domain_sample.py build 也会写进矩阵

REQUIRED = [("A1", "budget"), ("B1", "bedrooms"), ("G1", "anchor"), ("A4", "move_in"), ("J1", "pets")]
TOUR_ORDER = ["A1", "B1", "G1", "A4", "J1", "C1", "A6", "C2", "D1", "E4", "E2", "K1", "K2", "K3", "K4"]
FENGSHUI = ["K1", "K2", "K3", "K4"]  # 文化偏好核对包（docs/01 R-H0）：租客说在意才进清单，只核对布局事实，不判吉凶
MAX_ASK_ROUNDS = 2
ASK_PER_ROUND = 2
TOP_N = 3

PLACES = [
    ("central", "Central Station", "central"), ("unsw", "UNSW", "unsw"), ("cbd", "the CBD", "cbd"), ("city", "the CBD", "cbd"),
    ("town hall", "the CBD", "cbd"), ("martin place", "the CBD", "cbd"), ("uts", "UTS", None), ("usyd", "Sydney Uni", None),
    ("sydney uni", "Sydney Uni", None), ("redfern", "Redfern", None), ("randwick", "Randwick", None), ("kensington", "Kensington", None),
    ("kingsford", "Kingsford", None), ("zetland", "Zetland", None), ("mascot", "Mascot", None), ("haymarket", "Haymarket", None),
    ("surry hills", "Surry Hills", None), ("bondi junction", "Bondi Junction", None), ("north sydney", "North Sydney", None),
    ("macquarie park", "Macquarie Park", None), ("parramatta", "Parramatta", None), ("chatswood", "Chatswood", None),
]
ANCHOR_KEY = {label: key for _, label, key in PLACES}
WORDNUM = {"studio": 0, "one": 1, "two": 2, "three": 3, "four": 4, "1": 1, "2": 2, "3": 3, "4": 4, "a": 1, "single": 1}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MONTH_RE = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
FILLERS = {"yeah", "yes", "ok", "okay", "mm", "mhm", "uh", "huh", "right", "sure", "cool", "got", "it", "i", "see", "alright",
           "fine", "yep", "yup", "hmm", "oh", "ah", "nice", "great", "good", "thanks", "thank", "you", "aha", "hm", "yea", "mmm"}
KEYWORDS = [
    ("G1", r"station|train|bus|transport|commute|far|close|near|walk|minutes|light rail|get to"),
    ("C1", r"air[- ]?con|\ba\.?c\b|cooling|heating|split system|ducted"),
    ("J1", r"\bpets?\b|\bcats?\b|\bdogs?\b"),
    ("A1", r"\brent\b|price|cost|budget|cheap|expensive|per week|a week"),
    ("A4", r"\bmove\b|available|\bwhen\b|\bdate\b"),
    ("B1", r"bedroom|\bbeds?\b|\bsize\b|\bbig\b|\brooms?\b"),
    ("A6", r"\bbills?\b|water|electric|internet|utilit"),
    ("H1", r"crime|safe|history|murder|violent|disclosure"),
    ("C2", r"furnish|furniture|sofa|couch|bed frame|staged|staging|\bphotos?\b|\bpictures?\b"),
    ("C3", r"stove|cooktop|\bhob\b|induction|burners?|\boven\b"),
    ("D1", r"renovat|\bmodern\b|\bold\b|\bdated\b|condition|\bnew\b|run[- ]down|\bworn\b|\btired\b|how old"),
    ("E2", r"\bsun|sunlight|\bbright\b|orientation|\baspect\b|which way|facing|\bnorth\b|\bwinter\b"),
    ("E4", r"quiet|nois|peace|traffic"),
    ("K2", r"feng[- ]?shui|through[- ]?line|through[- ]?draught|straight through"),
    ("K1", r"number (four|4)|\bfour\b|unlucky"),
]
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "last": -1}


def _month_index(word: str) -> int:
    w = word.lower()[:3]
    return [m[:3] for m in MONTHS].index(w) + 1


# ---------------------------------------------------------------- 解析（规则版；LLM 版可替换，输出同一结构）
def parse_budget(t: str) -> Optional[int]:
    pats = [
        r"\$\s?(\d{3,4})\b",
        r"\b(\d{3,4})\s*(?:dollars|bucks)\b",
        r"\b(?:under|below|max(?:imum)?|up to|budget(?: of| is)?|less than|around|about|no more than|within|cap(?: of)?)\s*\$?\s?(\d{3,4})\b",
        r"\b(\d{3,4})\s*(?:a|per|/)\s*week\b",
        r"\b(\d{3,4})\s*pw\b",
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            v = int(m.group(1))
            if 150 <= v <= 5000:
                return v
    return None


def parse_bedrooms(t: str) -> Optional[int]:
    m = re.search(r"\b(studio|one|two|three|four|1|2|3|4)[\s-]*(?:bed(?:room)?s?\b|br\b|bdr\b)", t)
    if m:
        return WORDNUM[m.group(1)]
    if re.search(r"\bstudio\b", t):
        return 0
    return None


def parse_anchor(t: str) -> Optional[str]:
    for key, label, _ in PLACES:
        if re.search(r"\b" + re.escape(key) + r"\b", t):
            return label
    return None


def parse_move_in(t: str) -> Optional[dict]:
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_RE + r"\b", t)
    if m:
        day, mon = int(m.group(1)), m.group(2)
        return {"month": _month_index(mon), "day": day, "text": f"{day} {mon[:3].title()}"}
    m = re.search(r"\b(early|mid|late|start of|end of|beginning of)?[\s-]*(?:in\s+)?" + MONTH_RE + r"\b\s*(\d{1,2})?(?:st|nd|rd|th)?\b", t)
    if m:
        part, mon, day = (m.group(1) or "").strip(), m.group(2), m.group(3)
        if mon == "may" and not (part or day or re.search(r"\bin may\b", t)):
            m = None
        else:
            mi = _month_index(mon)
            if day:
                return {"month": mi, "day": int(day), "text": f"{int(day)} {mon[:3].title()}"}
            d = {"early": 5, "start of": 3, "beginning of": 3, "mid": 15, "late": 25, "end of": 27}.get(part, 15)
            name = MONTHS[mi - 1].title()
            label = f"{part}-{name}" if part in ("early", "mid", "late") else (f"{part} {name}" if part else name)
            return {"month": mi, "day": d, "text": label}
    if re.search(r"\b(asap|as soon as possible|right away|immediately|straight away|now)\b", t):
        return {"month": None, "day": None, "text": "as soon as possible", "asap": True}
    if re.search(r"\bnext month\b", t):
        nm = dt.date.today().month % 12 + 1
        return {"month": nm, "day": 10, "text": "next month"}
    return None


def parse_pets(t: str) -> Optional[dict]:
    if re.search(r"\b(no pets?|don'?t have (?:a |any )?pets?|without (?:a |any )?pets?|pet[- ]free|no animals?)\b", t):
        return {"has": False, "text": "no pets"}
    m = re.search(r"\b(cats?|dogs?|puppy|kitten|pets?|rabbit|bird)\b", t)
    if m:
        w = m.group(1)
        kind = {"cats": "cat", "dogs": "dog", "pets": "pet"}.get(w, w)
        return {"has": True, "kind": kind, "text": f"a {kind}"}
    return None


def parse_extras(t: str) -> List[dict]:
    ex: List[dict] = []
    if re.search(r"air[- ]?con(?:ditioning|ditioner)?|\ba\.?c\b|split system|ducted", t):
        ex.append({"dim": "C1", "label": "Air con in the bedroom" if re.search(r"\bbed", t) else "Air con"})
    if re.search(r"\b(furnished|furniture)\b", t) and not re.search(r"\bunfurnished\b", t):
        ex.append({"dim": "C2", "label": "Furnished"})
    m = re.search(r"\b(gas|induction|electric)\b[^.]{0,20}\b(stove|cooktop|hob|burners?|cooking)\b|\b(stove|cooktop|hob)\b", t)
    if m:  # C3 炉灶（docs/02）：照片能读出燃气 / 平面炉（R-B2）
        want = m.group(1) or ""
        ex.append({"dim": "C3", "label": {"gas": "Gas stove", "induction": "Induction cooktop", "electric": "Electric cooktop"}.get(want, "Stove"), "want": want or None})
    if re.search(r"\b(bills?|utilities|water|electricity|internet)\b[^.]{0,30}\b(included|inclusive|covered)\b|\bincluded\b[^.]{0,20}\b(bills?|water)\b", t):
        ex.append({"dim": "A6", "label": "Bills included"})
    if re.search(r"\bquiet\b|\bnoise\b|\bnoisy\b", t):
        ex.append({"dim": "E4", "label": "Quiet"})
    if re.search(r"\bsun(?:ny|light|shine)?\b|north[- ]facing|natural light|\baspect\b|\borientation\b|winter sun|afternoon sun|morning sun", t):
        ex.append({"dim": "E2", "label": "Sunlight"})
    if re.search(r"renovat|\bmodern\b|new(?:ish|er|ly built| build)\b|not (too )?old|\bdated\b|run[- ]down|\bcondition\b|good nick|\btired\b|\bworn\b", t):
        ex.append({"dim": "D1", "label": "Condition"})  # D1 楼龄与新旧（docs/02）：照片里看得见的新旧
    if re.search(r"feng[- ]?shui|fengshui|风水|lucky number|number (four|4)|unlucky|through[- ]?draught|bagua", t):
        for d in FENGSHUI:  # 风水包：租客开口才装（R-H0），四格一起进清单
            ex.append({"dim": d, "label": PACK_LABELS[d], "pack": "fengshui"})
    return ex


def parse_max_commute(t: str) -> Optional[int]:
    m = re.search(r"\b(?:within|under|less than|max(?:imum)?|no more than)\s*(\d{2})\s*min", t)
    return int(m.group(1)) if m else None


def new_profile() -> dict:
    return {"budget": None, "bedrooms": None, "anchor": None, "move_in": None, "pets": None, "extras": [], "max_commute": 40}


def rules_fields(text: str, pending: Optional[List[str]] = None) -> dict:
    """规则解析一句话，返回认出的字段（没认出的是 None / []）。pending 是上一轮问了的必填项，接受裸数字、yes / no 短答。"""
    t = text.lower().strip()
    pending = pending or []
    b = parse_budget(t)
    if b is None and "A1" in pending:
        m = re.fullmatch(r"\D*(\d{3,4})\D*", t)
        if m and 150 <= int(m.group(1)) <= 5000:
            b = int(m.group(1))
    n = parse_bedrooms(t)
    if n is None and "B1" in pending:
        m = re.fullmatch(r"\D*(studio|one|two|three|four|1|2|3|4)\D*", t)
        if m:
            n = WORDNUM[m.group(1)]
    p = parse_pets(t)
    if p is None and "J1" in pending:
        if re.fullmatch(r"\W*(yes|yeah|yep|i do|we do)\W*", t):
            p = {"has": True, "kind": "pet", "text": "a pet"}
        elif re.fullmatch(r"\W*(no|nope|none|no pets?)\W*", t):
            p = {"has": False, "text": "no pets"}
    return {"budget": b, "bedrooms": n, "anchor": parse_anchor(t), "move_in": parse_move_in(t), "pets": p,
            "max_commute": parse_max_commute(t), "extras": parse_extras(t)}


def apply_fields(profile: dict, f: dict) -> Dict[str, str]:
    """把字段写进 profile，返回改了什么（给措辞用）。规则版和模型版共用，所以两条路的结果结构完全一样。"""
    changed: Dict[str, str] = {}
    b = f.get("budget")
    if b is not None and b != profile["budget"]:
        profile["budget"] = b
        changed["budget"] = f"under {b} a week"
    n = f.get("bedrooms")
    if n is not None and n != profile["bedrooms"]:
        profile["bedrooms"] = n
        changed["bedrooms"] = phraser.NUM_WORDS.get(n, str(n))
    a = f.get("anchor")
    if a and a != profile["anchor"]:
        profile["anchor"] = a
        changed["anchor"] = a
    mv = f.get("move_in")
    if mv and mv != profile["move_in"]:
        profile["move_in"] = mv
        changed["move_in"] = mv["text"]
    p = f.get("pets")
    if p and p != profile["pets"]:
        profile["pets"] = p
        changed["pets"] = p["text"] if p.get("has") else "no pets"
    mc = f.get("max_commute")
    if mc and mc != profile["max_commute"]:
        profile["max_commute"] = mc
        changed["max_commute"] = str(mc)
    for ex in f.get("extras") or []:
        if all(e["dim"] != ex["dim"] for e in profile["extras"]):
            profile["extras"].append(ex)
            changed["extras"] = ex["label"].lower()
    return changed


def parse_into(profile: dict, text: str, pending: Optional[List[str]] = None) -> Dict[str, str]:
    """把一句话里能认出的字段写进 profile，返回改了什么（给措辞用）。"""
    return apply_fields(profile, rules_fields(text, pending))


# ---------------------------------------------------------------- 解析（模型版）：Nemotron 经 Meterless 解析，规则校验和兜底
EXTRA_LABELS = {"C2": "Furnished", "A6": "Bills included", "E4": "Quiet", "E2": "Sunlight", "C3": "Stove", "D1": "Condition"}
PACK_LABELS = {"K1": "Numbers (no 4)", "K2": "No through-line", "K3": "Doors clear of wet rooms", "K4": "Square outline"}
EXTRA_GROUND = {"C1": r"air|\ba\.?c\b|cool|split|ducted|heat", "C2": r"furnish", "C3": r"stove|cooktop|\bhob\b|induction|burner", "A6": r"bill|utilit|water|electric|internet|included",
                "E4": r"quiet|nois|peace", "E2": r"\bsun|light|north|bright"}
FIELD_DIM = {"budget": "A1", "bedrooms": "B1", "anchor": "G1", "move_in": "A4", "pets": "J1"}
STOP = {"the", "near", "close", "to", "in", "at", "of", "and", "station", "uni", "university", "my", "our", "work", "a", "an", "street"}
NEEDS_PROMPT = """HOMETRUTH_NEEDS_V1
You turn one thing a renter said into JSON for a Sydney rental search. Today is {today}.
Reply with one JSON object and nothing else. Include only the keys this utterance actually gives; leave every other key out (a missing key means null, missing extras means none). Keys and shapes:
{{"budget": int|null, "bedrooms": int|null, "anchor": string|null, "move_in": {{"month": 1-12, "day": 1-31, "text": string}} | {{"asap": true}} | null, "pets": {{"has": bool, "kind": string|null}} | null, "extras": [{{"dim": "C1"|"C2"|"C3"|"A6"|"E4"|"E2", "label": string}}], "max_commute": int|null}}
Rules:
- Fill a key only when this utterance says it. Otherwise leave it out. Never guess or carry over.
- budget: most they will pay per week in AUD, as an integer ("under 900" -> 900, "nine hundred" -> 900).
- bedrooms: number of bedrooms; a studio is 0.
- anchor: where they commute to or want to live near. If it is one of these, use exactly this name: {anchors}. Otherwise the place name they said.
- move_in: when they need to move in. "mid-November" -> {{"month": 11, "day": 15, "text": "mid-November"}}; early -> day 5; late -> day 25; a relative date like "in two weeks" -> work it out from today; "asap" or "now" -> {{"asap": true}}.
- pets: {{"has": true, "kind": "cat"}} if they have a pet; {{"has": false}} if they say they have none.
- extras: C1 air conditioning, C2 furnished, C3 the stove or cooktop type (gas, induction, electric), A6 bills included, E4 quiet, E2 sunlight. Only these six.
- max_commute: the longest commute in minutes, if they give one.
- The assistant just asked about: {pending}. A short reply like "900", "yes" or "no" answers those.
Profile so far (context only, do not repeat it): {profile}"""


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\$?\d{1,5}\s*", v):
        return int(re.sub(r"\D", "", v))
    return None


def _json_object(text: str) -> Optional[dict]:
    s = re.sub(r"```(?:json)?", "", text or "")
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        obj = json.loads(s[i:j + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _canon_anchor(a: str) -> str:
    """模型给的地名对到 PLACES 的标准名（evaluate 靠它找通勤行）；对不上就原样留着，G1 会诚实地标未知。"""
    low = a.lower().strip()
    for key, label, _ in PLACES:
        if low in (key, label.lower()):
            return label
    for key, label, _ in PLACES:
        if re.search(r"\b" + re.escape(key) + r"\b", low):
            return label
    return a.strip()


def _grounded_anchor(anchor: str, t: str) -> bool:
    words = [w for w in re.findall(r"[a-z]+", anchor.lower()) if len(w) >= 3 and w not in STOP]
    if any(re.search(r"\b" + re.escape(w), t) for w in words):
        return True
    return any(label == anchor and re.search(r"\b" + re.escape(key) + r"\b", t) for key, label, _ in PLACES)


def validate_llm_fields(obj: dict, text: str, pending: List[str]) -> Tuple[dict, Dict[str, str]]:
    """校验模型给的字段：类型、范围、标准名，并且每个值都要在原话（或刚问的必填项）里找得到依据。返回 (通过的字段, 被拒的原因)。"""
    t = text.lower()
    out: dict = {"budget": None, "bedrooms": None, "anchor": None, "move_in": None, "pets": None, "max_commute": None, "extras": []}
    bad: Dict[str, str] = {}
    digits = set(re.findall(r"\d+", t.replace(",", "")))
    short = len(re.findall(r"[a-z0-9']+", t)) <= 4  # "900"、"yes"、"no pets" 这种短答才靠"刚问过"放宽
    b = _int(obj.get("budget"))
    if obj.get("budget") is not None:
        if b is None or not 150 <= b <= 5000:
            bad["budget"] = "not an integer in 150..5000"
        elif str(b) in digits or re.search(r"hundred|thousand|\d\s*k\b|grand", t):
            out["budget"] = b
        else:
            bad["budget"] = f"{b} not in the utterance"
    n = _int(obj.get("bedrooms"))
    if obj.get("bedrooms") is not None:
        word = {v: k for k, v in WORDNUM.items() if k.isalpha() and k not in ("a", "single")}.get(n, "")
        said_n = str(n) in digits or (word and re.search(r"\b" + word + r"\b", t)) or (n == 1 and re.search(r"\b(a|single)[\s-]*bed", t))
        if n is None or not 0 <= n <= 6:
            bad["bedrooms"] = "not an integer in 0..6"
        elif said_n and (re.search(r"bed|\bbr\b|studio|room", t) or ("B1" in pending and short)):
            out["bedrooms"] = n
        else:
            bad["bedrooms"] = f"{n} bedrooms not in the utterance"
    a = obj.get("anchor")
    if a is not None:
        if not isinstance(a, str) or not a.strip() or len(a) > 60:
            bad["anchor"] = "not a short place name"
        else:
            label = _canon_anchor(a)
            if _grounded_anchor(label, t) or _grounded_anchor(a, t):
                out["anchor"] = label
            else:
                bad["anchor"] = f"{a!r} not in the utterance"
    mv = obj.get("move_in")
    if mv is not None:
        when_words = (r"\b(asap|soon|now|immediately|right away|straight away|today|tomorrow|week|weeks|weekend|fortnight|month|months|next|"
                      r"days?)\b|\d{1,2}(st|nd|rd|th)\b|\d{1,2}/\d{1,2}")
        grounded = re.search(MONTH_RE + r"|" + when_words, t)
        if not isinstance(mv, dict):
            bad["move_in"] = "not an object"
        elif not grounded:
            bad["move_in"] = "no date words in the utterance"
        elif mv.get("asap") is True:
            out["move_in"] = {"month": None, "day": None, "text": "as soon as possible", "asap": True}
        else:
            mo, dy = _int(mv.get("month")), _int(mv.get("day"))
            if mo is None or not 1 <= mo <= 12 or (dy is not None and not 1 <= dy <= 31):
                bad["move_in"] = "month/day out of range"
            else:
                dy = dy or 15
                label = mv.get("text") if isinstance(mv.get("text"), str) and 0 < len(mv["text"].strip()) <= 40 else ""
                out["move_in"] = {"month": mo, "day": dy, "text": label.strip() or f"{dy} {MONTHS[mo - 1][:3].title()}"}
    p = obj.get("pets")
    if p is not None:
        pet_words = r"\b(pets?|cats?|dogs?|kitten|puppy|rabbit|bird|fish|animals?)\b"
        if not isinstance(p, dict) or not isinstance(p.get("has"), bool):
            bad["pets"] = "not {has: bool}"
        elif not (re.search(pet_words, t) or ("J1" in pending and short)):
            bad["pets"] = "no pet words in the utterance"
        elif p["has"]:
            kind = p.get("kind") if isinstance(p.get("kind"), str) and re.fullmatch(r"[a-z ]{2,20}", p["kind"].lower().strip()) else "pet"
            kind = kind.lower().strip()
            kind = {"cats": "cat", "dogs": "dog", "pets": "pet"}.get(kind, kind)
            out["pets"] = {"has": True, "kind": kind, "text": f"a {kind}"}
        else:
            out["pets"] = {"has": False, "text": "no pets"}
    mc = _int(obj.get("max_commute"))
    if obj.get("max_commute") is not None:
        if mc is None or not 5 <= mc <= 120:
            bad["max_commute"] = "not an integer in 5..120"
        elif str(mc) in digits and re.search(r"\bmin", t):
            out["max_commute"] = mc
        else:
            bad["max_commute"] = f"{mc} minutes not in the utterance"
    seen = set()
    for ex in obj.get("extras") or []:
        d = ex.get("dim") if isinstance(ex, dict) else None
        if d not in EXTRA_GROUND or d in seen:
            if d is not None:
                bad[f"extras.{d}"] = "unknown or repeated dimension"
            continue
        if not re.search(EXTRA_GROUND[d], t) or (d == "C2" and "unfurnished" in t):
            bad[f"extras.{d}"] = "not in the utterance"
            continue
        seen.add(d)
        label = ("Air con in the bedroom" if re.search(r"\bbed", t) else "Air con") if d == "C1" else EXTRA_LABELS[d]
        out["extras"].append({"dim": d, "label": label})
    return out, bad


def needs_llm_ready() -> bool:
    """模型路可用吗：NEEDS_PARSER=rules 强制规则；否则看 provider 选择（没 token 也没 key 时不发网络请求）。"""
    if llm is None or os.environ.get("NEEDS_PARSER", "auto").strip().lower() == "rules":
        return False
    try:
        return llm.select().name != "none"
    except Exception:  # noqa: BLE001
        return False


def rules_meta(reason: str = "") -> dict:
    if not reason:
        if llm is None:
            reason = "model layer not importable"
        elif os.environ.get("NEEDS_PARSER", "auto").strip().lower() == "rules":
            reason = "NEEDS_PARSER=rules"
        else:
            try:
                reason = llm.select().reason
            except Exception as e:  # noqa: BLE001
                reason = f"provider check failed: {e}"
    return {"parser": "rules", "reason": reason}


_NEEDS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="needs-llm")


def _needs_timeout() -> float:
    return float(os.environ.get("NEEDS_LLM_TIMEOUT", "8"))


def _prompt_view(profile: dict) -> dict:
    view = {k: profile[k] for k in ("budget", "bedrooms", "anchor", "move_in", "pets", "max_commute")}
    view["extras"] = [e["dim"] for e in profile["extras"]]
    return view


def _needs_llm_call(text: str, view: dict, pending: List[str]) -> Tuple[Optional[dict], dict]:
    """只做模型那一步：发请求、抽 JSON。返回 (JSON 对象或 None, meta)。不碰 profile，所以可以放在线程里先跑起来。
    失败时（没 provider、超时、401、回的不是 JSON）对象是 None，meta 是规则版的 meta（带原因），调用方退回规则。"""
    anchors = ", ".join(sorted({label for _, label, _ in PLACES}))
    asked = ", ".join(f"{d} ({k})" for d, k in REQUIRED if d in pending) or "nothing"
    system = NEEDS_PROMPT.format(today=dt.date.today().isoformat(), anchors=anchors, pending=asked, profile=json.dumps(view))
    try:
        res = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": f"Utterance: {text}"}], task="needs_parse",
                       temperature=0, max_tokens=200, retries=0, timeout=_needs_timeout())  # 只写有值的字段，200 个 token 绰绰有余
    except Exception as e:  # noqa: BLE001  没 provider、超时、401 … 全部回退规则
        return None, rules_meta(f"{getattr(e, 'kind', type(e).__name__)}: {str(e)[:160]}")
    meta = {"parser": "llm", "provider": res.provider, "model": res.model, "served_model": res.served_model, "ms": res.ms,
            "fallback_from": res.fallback_from or None}
    obj = _json_object(res.text)
    if obj is None:
        m = rules_meta("model answer was not a JSON object")
        m.update({k: meta[k] for k in ("provider", "model", "served_model", "ms")})
        return None, m
    return obj, meta


def start_needs_llm(text: str, profile: dict, pending: Optional[List[str]] = None) -> Future:
    """把模型请求先放进线程跑起来，主线程这时可以先把过渡句说出去；之后 parse_needs_llm(..., started=这个) 拿结果。"""
    return _NEEDS_POOL.submit(_needs_llm_call, text, _prompt_view(profile), list(pending or []))


def parse_needs_llm(text: str, profile: dict, pending: Optional[List[str]] = None,
                    started: Optional[Future] = None) -> Tuple[Dict[str, str], dict]:
    """provider 可用时让模型把一句话解析成和 parse_into 相同的字段，规则做校验和兜底：
    模型给的每个字段先过 validate_llm_fields；被拒或没给的字段用规则的结果；模型整个不可用（没 provider、超时、不是 JSON）就全用规则。
    started 是 start_needs_llm 先跑起来的请求（过渡句先说的那条路）；不给就在这里同步调模型。
    返回 (changed, meta)；meta 写进 needs 事件：parser = llm / rules，以及 provider、模型、耗时、被拒和规则补的字段。"""
    pending = pending or []
    rf = rules_fields(text, pending)
    if started is None and not needs_llm_ready():
        return apply_fields(profile, rf), rules_meta()
    if started is not None:
        try:
            obj, meta = started.result(timeout=_needs_timeout() + 10)
        except FutureTimeout:
            obj, meta = None, rules_meta("timeout: parse thread did not return")
    else:
        obj, meta = _needs_llm_call(text, _prompt_view(profile), pending)
    if obj is None:
        return apply_fields(profile, rf), meta
    fields, bad = validate_llm_fields(obj, text, pending)
    from_rules = []
    for k in ("budget", "bedrooms", "anchor", "move_in", "pets", "max_commute"):
        if fields[k] is None and rf[k] is not None:
            fields[k] = rf[k]
            from_rules.append(k)
    for ex in rf["extras"]:
        same = next((e for e in fields["extras"] if e["dim"] == ex["dim"]), None)
        if same is not None:
            if ex.get("want") and not same.get("want"):  # 模型只报了维度，规则还认出了要燃气还是电磁炉
                same.update(want=ex["want"], label=ex["label"])
            continue
        fields["extras"].append(ex)
        from_rules.append(f"extras.{ex['dim']}")
    meta["disagree"] = [k for k in ("budget", "bedrooms", "anchor", "move_in", "pets", "max_commute")
                        if k not in from_rules and rf[k] is not None and fields[k] is not None and rf[k] != fields[k]]
    if bad:
        meta["rejected"] = bad
    if from_rules:
        meta["from_rules"] = from_rules
    return apply_fields(profile, fields), meta


ASK_WORDS = {"A1": r"budget|rent|week|spend|price|pay", "B1": r"bedroom|room|studio", "G1": r"where|commute|work|study|near|area|based",
             "A4": r"move|when|date|start", "J1": r"pet|animal|cat|dog"}


def polish_llm(sentence: str, fields: List[str]) -> str:
    """可选（POLISH_LLM=1，默认关）：让模型把反问句说得更自然。只改措辞：必须还是一句问句、每个被问的必填项都还在、不多出数字，
    否则用模板原句。导览和"为什么合适"的句子永远用模板。"""
    if os.environ.get("POLISH_LLM", "0").strip() not in ("1", "true", "on") or not needs_llm_ready():
        return sentence
    try:
        res = llm.chat([{"role": "system", "content": "Rephrase the assistant's question so it sounds natural when spoken. "
                                                      "Keep every thing it asks about, add nothing, one sentence, under 30 words. Reply with the sentence only."},
                        {"role": "user", "content": sentence}], task="polish_ask", temperature=0.3, max_tokens=80, retries=0,
                       timeout=float(os.environ.get("NEEDS_LLM_TIMEOUT", "8")))
    except Exception:  # noqa: BLE001
        return sentence
    out = res.text.strip().strip('"')
    ok = (out.endswith("?") and len(out) <= 200 and "\n" not in out and not (set(re.findall(r"\d+", out)) - set(re.findall(r"\d+", sentence)))
          and all(re.search(ASK_WORDS[f], out.lower()) for f in fields))
    return out if ok else sentence


def missing_required(profile: dict) -> List[str]:
    return [dim for dim, key in REQUIRED if profile[key] is None]


# ---------------------------------------------------------------- 材料分段 + 下一步（10-27，docs/01 同一口径）
# 新州租客申请前拿不到第三方看房报告，所以材料按"什么时候能拿到"分五段：挂牌 → 公开数据 → 中介 → 自己看房 → 签约。
# 前三段是证据来源（evidence.stage）；看房和签约永远不是证据来源，只作为"下一步"（cell.next）出现。
STAGES = ["listing", "public", "agent", "viewing", "signing"]
STAGE_LABELS = {"listing": "From the listing", "public": "Public data", "agent": "From the agent", "viewing": "Your viewing", "signing": "At signing"}
STAGE_OF_TABLE = {"listings": "listing", "photo_facts": "listing", "floorplan_facts": "listing",  # 挂牌页、挂牌照片（看图模型读）、户型图
                  "public_rent": "public", "public_transit": "public", "sun_geometry": "public", "geo_estimate": "public",  # 公开表 + 由公开数据算出来的
                  "documents": "agent"}  # 中介回复、by-laws、法定披露的回答：都是中介给的材料


def stage_of(evidence: dict) -> str:
    """一条证据属于哪一段。documents 按 row / material_id 判：reply / bylaws / disclosure → agent；租客自己拍的 → viewing；
    合同 / 条件报告 / inventory → signing（首版数据里没有后两类）。其他表按 STAGE_OF_TABLE，不认识的表当公开数据。"""
    if evidence.get("stage") in STAGES:
        return evidence["stage"]
    table = evidence.get("table")
    if table == "documents":
        key = f"{evidence.get('row') or ''} {evidence.get('material_id') or ''}".lower()
        if re.search(r"repl|by-?law|disclos", key):
            return "agent"
        if re.search(r"viewing|visit|renter-photo", key):
            return "viewing"
        if re.search(r"condition[-_ ]report|inventory|lease|contract", key):
            return "signing"
        return "agent"
    return STAGE_OF_TABLE.get(table, "public")


NEXT_TEXT = {"ask_agent": "Ask the agent", "see_at_viewing": "See at the viewing", "check_at_signing": "Check at signing"}
# 维度 → [(主下一步, 看什么 / 问什么), (次下一步, …)]；hint 不超过 12 个英文词。没登记的维度（G1、A7）没有下一步：没中位数 / 没时刻表就是 unknown。
NEXT_STEP: Dict[str, List[Tuple[str, str]]] = {
    "A1": [("ask_agent", "current asking rent")],
    "A4": [("ask_agent", "earliest move-in date")],
    "A6": [("ask_agent", "which bills the rent includes"), ("check_at_signing", "the lease lists them")],
    "B1": [("ask_agent", "how many rooms count as bedrooms")],
    "C1": [("ask_agent", "air con in the bedrooms, not just the living room"), ("see_at_viewing", "look for a unit or vent in each bedroom")],
    "C2": [("ask_agent", "what stays"), ("check_at_signing", "the inventory is the record")],
    "C3": [("see_at_viewing", "look at the cooktop: flame rings or a flat top")],
    "D1": [("see_at_viewing", "benchtops, tiles, carpet"), ("check_at_signing", "the condition report at signing")],
    "E4": [("see_at_viewing", "go at 6 pm and listen")],
    "H1": [("ask_agent", "the agent must answer: deaths, flood, fire, drug lab, asbestos, cladding, sale")],
    "J1": [("ask_agent", "landlord consent in writing; by-laws clause")],
    "K1": [("see_at_viewing", "the level on the building directory")],
    "K2": [("see_at_viewing", "stand at the entry: can you see straight out the back")],
    "K3": [("see_at_viewing", "where the bathroom door faces")],
    "K4": [("see_at_viewing", "walk the outline: notches and missing corners")],
}
OPEN_STATUSES = ("unknown", "inferred", "conflict")


def _agent_replied(cell: dict) -> bool:
    """这格的证据里已经有一条真正的中介回复（material_id 形如 M-0002-reply-01；'Not asked yet' 占位行的 material_id 是 null）。"""
    return any(e.get("table") == "documents" and re.search(r"repl", str(e.get("material_id") or ""), re.I) for e in cell.get("evidence") or [])


def _clock_word(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    h = (h + (1 if m >= 30 else 0)) % 24
    return "midday" if h == 12 else ("midnight" if h == 0 else f"{h} am" if h < 12 else f"{h - 12} pm")


def _e2_next(cell: dict) -> Tuple[str, str]:
    """E2 日照：朝向未知 → 问中介朝向；有朝向但只是日照几何推断 → 去看房，挑冬至主窗有直射的那段时间的中点去。"""
    sun = next((e for e in cell.get("evidence") or [] if e.get("table") == "sun_geometry"), None)
    if not cell.get("value") and sun is None:
        return "ask_agent", "which way the living room faces"
    m = re.search(r"(\d{2}:\d{2})\s*[–-]\s*(\d{2}:\d{2})", str((sun or {}).get("text") or ""))
    if not m:
        return "see_at_viewing", "visit in daylight and look at the main window"
    (h1, m1), (h2, m2) = ((int(x) for x in m.group(1).split(":")), (int(x) for x in m.group(2).split(":")))
    mid = ((h1 * 60 + m1) + (h2 * 60 + m2)) // 2
    return "see_at_viewing", f"visit around {_clock_word(f'{mid // 60:02d}:{mid % 60:02d}')}; the main window should be in sun"


def next_for(dim: str, status: Optional[str], cell: dict) -> Optional[dict]:
    """status 不是 supported 的格子的下一步：{kind, text, hint}。主下一步优先；这格已经有中介回复而仍没落实的，跳到次下一步（下一段材料），
    没有次的维度仍是主。conflict 和 unknown 同样处理。没有下一步（G1、A7、没登记的维度）返回 None。"""
    if status not in OPEN_STATUSES:
        return None
    steps = [_e2_next(cell)] if dim == "E2" else NEXT_STEP.get(dim)
    if not steps:
        return None
    kind, hint = steps[-1] if (steps[0][0] == "ask_agent" and len(steps) > 1 and _agent_replied(cell)) else steps[0]
    return {"kind": kind, "text": NEXT_TEXT[kind], "hint": hint}


# ---------------------------------------------------------------- 评估与排序（程序算）
def _mock_id() -> str:
    return "mock-" + uuid.uuid4().hex[:8]


def _ev(items: List[dict]) -> List[dict]:
    return [dict(it, stage=stage_of(it), mock=True, request_id=_mock_id()) for it in items]


def _cell(dim: str, status: str, value: Any = None, why: str = "", evidence: Optional[List[dict]] = None, fail: bool = False, **extra) -> dict:
    c = {"dim": dim, "label": DIMS[dim]["label"], "hard": DIMS[dim].get("hard", False), "status": status, "value": value, "why": why,
         "evidence": _ev(evidence or []), "fail": fail}
    c.update(extra)
    nxt = next_for(dim, status, c)
    if nxt:
        c["next"] = nxt  # 未知 / 推断 / 冲突的格子都带一个明确的下一步
    return c


def _cell_extra(f: dict) -> dict:
    """矩阵事实里给卡片用的附加字段（short = 卡片上的一个词，photo = 这行有照片证据）。"""
    out = {}
    if f.get("short"):
        out["short"] = f["short"]
    if any(e.get("table") == "photo_facts" for e in f.get("evidence", [])):
        out["photo"] = True
    if any(e.get("table") == "floorplan_facts" for e in f.get("evidence", [])):
        out["plan"] = True  # 这行的证据是户型图（看图模型读的，带置信度）
    if f.get("confidence"):
        out["confidence"] = f["confidence"]
    return out


def _wanted_status(dim: str, f: dict, ex: dict) -> str:
    """租客点名要的项，状态要相对"要什么"来定：照片盖章的家具对要家具的人是冲突（if_wanted）；要燃气灶而照片里是平面炉是冲突，
    要电磁炉而照片只看得出"电"仍是未知（R-B2：陶瓷和电磁分不出）。"""
    if dim in ("C2", "D1") or dim in FENGSHUI:  # 要家具 / 要新 / 要方正的人：照片或户型图看出相反的事就是冲突
        return f.get("if_wanted", f["status"])
    if dim == "C3" and ex.get("want") and f.get("want"):
        want, seen = ex["want"], f["want"]
        if want == seen or (want == "induction" and seen == "electric"):
            return "inferred" if want == seen else "unknown"
        return "conflict"
    return f["status"]


def _target_date(move_in: dict) -> Optional[dt.date]:
    if not move_in or move_in.get("asap"):
        return None
    today = dt.date.today()
    year = today.year if move_in["month"] >= today.month else today.year + 1
    return dt.date(year, move_in["month"], min(move_in["day"], 28))


def evaluate(L: dict, profile: dict, overrides: Dict[str, dict]) -> Dict[str, dict]:
    cells: Dict[str, dict] = {}
    facts = L["facts"]
    if profile["budget"] is not None:
        ok = L["rent"] <= profile["budget"]
        cells["A1"] = _cell("A1", "supported" if ok else "conflict", f"${L['rent']}/wk", evidence=facts["A1"]["evidence"], fail=not ok,
                            **({"median": facts["A1"]["median"]} if facts["A1"].get("median") else {}))  # 真房源：Domain 本区中位租金（广告说 vs 来源说）
    if profile["bedrooms"] is not None:
        ok = L["bedrooms"] >= profile["bedrooms"]
        cells["B1"] = _cell("B1", "supported" if ok else "conflict", f"{L['bedrooms']} bed", evidence=facts["B1"]["evidence"], fail=not ok)
    if profile["anchor"]:
        key = ANCHOR_KEY.get(profile["anchor"])
        row = L["commute"].get(key) if key else None
        if row is None:
            cells["G1"] = _cell("G1", "unknown", None, why=f"No transit row for {profile['anchor']} in the prototype table.",
                                evidence=[{"table": "public_transit", "row": f"{L['suburb']}→{profile['anchor']}", "material_id": None, "text": "No row yet"}])
        elif row.get("estimate"):  # 真房源（scripts/domain_sample.py）：按直线距离估的，不是时刻表 → 最多"推断"，超限仍是冲突
            ok = row["min"] <= profile.get("max_commute", 40)
            cells["G1"] = _cell("G1", "inferred" if ok else "conflict", row, estimate=True,
                                evidence=[{"table": "geo_estimate", "row": f"{L['id']}→{profile['anchor']}", "material_id": None,
                                           "text": f"About {row['min']} min by {row['mode']}: {row.get('km', '?')} km in a straight line, an estimate from the distance, not a timetable"}])
        else:
            ok = row["min"] <= profile.get("max_commute", 40)
            cells["G1"] = _cell("G1", "supported" if ok else "conflict", row,
                                evidence=[{"table": "public_transit", "row": f"{L['suburb']}→{profile['anchor']} 08:00", "material_id": None,
                                           "text": f"{row['min']} min by {row['mode']}, weekday 8:00 departure"}])
    if profile["move_in"]:
        avail = dt.date.fromisoformat(L["available_from"])
        target = _target_date(profile["move_in"])
        if target is None:
            gap = (avail - dt.date.today()).days
            ok = gap <= 14
        else:
            gap = (avail - target).days
            ok = gap <= 7
        cells["A4"] = _cell("A4", "supported" if ok else "conflict", f"{avail.day} {avail:%b}", evidence=facts["A4"]["evidence"], gap_days=max(gap, 0))
    if profile["pets"] and profile["pets"].get("has"):
        f = overrides.get("J1") or facts["J1"]
        cells["J1"] = _cell("J1", f["status"], None, why=f["why"], evidence=f["evidence"])
    for ex in profile["extras"]:
        d = ex["dim"]
        f = overrides.get(d) or facts.get(d)
        if f:
            cells[d] = _cell(d, _wanted_status(d, f, ex), f.get("value"), why=f["why"], evidence=f["evidence"], **_cell_extra(f))
        else:
            cells[d] = _cell(d, "unknown", None, why="Nothing in the materials covers it.")
    for d in ("C2", "D1"):
        if d not in cells and (overrides.get(d) or facts.get(d) or {}).get("notable"):
            # 照片事实（src/photo/facts.py）：照片盖着 VIRTUALLY STAGED、或者厨房卫生间看着旧 / 破，不管租客问没问都要讲——照片定下的预期和实际不符
            f = overrides.get(d) or facts[d]
            cells[d] = _cell(d, f["status"], f.get("value"), why=f["why"], evidence=f["evidence"], notable=True, **_cell_extra(f))  # 说出来，但不计分（rank）
    f = facts["H1"]
    cells["H1"] = _cell("H1", f["status"], None, why=f["why"], evidence=f["evidence"])
    return cells


WEIGHT = {"supported": 3.0, "inferred": 1.5, "unknown": 0.0, "conflict": -3.0}


def rank(profile: dict, overrides: Dict[str, Dict[str, dict]]) -> Tuple[List[dict], int]:
    ranked, excluded = [], 0
    for L in LISTINGS:
        cells = evaluate(L, profile, overrides.get(L["id"], {}))
        if any(c["fail"] for c in cells.values()):
            excluded += 1
            continue
        scored = {d: c for d, c in cells.items() if d != "H1" and not c.get("notable")}  # 没问却要讲的坏消息（盖章家具、看着旧）只说不计分
        score = sum(WEIGHT[c["status"]] * (2 if c["hard"] else 1) for c in scored.values())
        counts = {"supported": sum(c["status"] == "supported" for c in scored.values()),
                  "inferred": sum(c["status"] == "inferred" for c in scored.values()),
                  "open": sum(c["status"] in ("unknown", "conflict") for c in scored.values())}
        ranked.append({"listing": L, "cells": cells, "score": score, "counts": counts})
    ranked.sort(key=lambda r: (-r["score"], r["listing"]["rent"]))
    return ranked, excluded


def listing_summary(L: dict) -> dict:
    """/api/listings 用（卡片墙、浏览网格、详情页）：只读摘要。字段和 card 事件的 listing 一致（没有 rank / cells），另加 suburb、
    postcode、special，以及 facts：每个维度在矩阵里登记的事实（固定状态 + 证据的表 / 行 / 原文）——详情页"What the sources say"就是它。
    不带 request_id：那是查询时才有的；也不替用户判断（Rent / Bedrooms / Move-in 的状态要等需求来了才算）。"""
    base = {k: v for k, v in card_payload(L, {}, 0).items() if k not in ("rank", "cells")}
    facts = []
    for dim, f in (L.get("facts") or {}).items():
        d = DIMS.get(dim, {})
        fact = {"dim": dim, "label": d.get("label", dim), "hard": bool(d.get("hard")), "status": f.get("status")}
        for k in ("value", "short"):  # 有才加：卡片上的一个词 / 格子的值（"N-facing"、"Staged photos"）
            if f.get(k) is not None:
                fact[k] = f[k]
        fact["next"] = next_for(dim, f.get("status"), f)  # 按矩阵的固定状态算；supported 或没登记的维度是 null
        fact["evidence"] = [dict({"table": e.get("table"), "row": e.get("row"), "material_id": e.get("material_id"), "text": e.get("text"), "stage": stage_of(e)},
                                 **{k: e[k] for k in ("read_by", "image") if e.get(k)}) for e in f.get("evidence", [])]
        facts.append(fact)
    out = dict(base, suburb=L["suburb"], postcode=L.get("postcode"), special=L.get("special"), facts=facts)
    if L.get("photo"):  # 看图模型读过的那张照片：卡片、轨道、详情页都用它（有盖章的就是盖章版），而不是按顺序轮配的示意图
        p = L["photo"]
        out.update(image=p["url"], photo_set=p.get("set"), photo_caption=p.get("caption"), photo_stamp=p.get("stamp"), photo_read_by=p.get("read_by"))
    for k in ("source", "images", "floorplan", "sun", "description", "headline", "lat", "lng", "parking"):  # 真房源（scripts/domain_sample.py）：相册、户型图、日照几何、出处
        if L.get(k) is not None:
            out[k] = L[k]
    if L.get("features") is not None:  # 10-27：挂牌自己的设施清单（真房源，scripts/real_features.py 从 data/real/domain 抄进矩阵；空数组也带上），详情页 Features 网格
        out["features"] = list(L["features"])
    if L.get("commute"):  # 10-27：通勤表（到 Central / UNSW / CBD 几分钟、什么方式、是否估算），详情页 "HomeTruth says" 那格；和 G1 用的是同一张表
        out["commute"] = L["commute"]
    return out


def card_payload(L: dict, cells: Dict[str, dict], rank_no: int) -> dict:
    short = {"A1": lambda c: c["value"], "B1": lambda c: c["value"], "G1": lambda c: (f"{c['value']['min']} min" if c["value"] else "no row"),
             "A4": lambda c: c["value"]}
    out = []
    for d in TOUR_ORDER + ["H1"]:
        if d in cells:
            c = cells[d]
            row = {"dim": d, "label": c["label"], "status": c["status"],
                   "short": c.get("short") or short.get(d, lambda c: {"supported": "yes", "inferred": "likely", "conflict": "clash", "unknown": "?"}[c["status"]])(c), "hard": c["hard"]}
            if c.get("photo"):
                row["photo"] = True  # 这行的证据里有照片（看图模型读的）
            if c.get("plan"):
                row["plan"] = True  # 户型图读的
            if c.get("confidence"):
                row["confidence"] = c["confidence"]
            if c.get("estimate"):
                row["estimate"] = True
            if c.get("next"):
                row["next"] = c["next"]["kind"]  # 下一步只给 kind（ask_agent / see_at_viewing / check_at_signing）；全文在 evidence 的格子里
            out.append(row)
    payload = {"id": L["id"], "rank": rank_no, "title": f"{L['unit']}/{L['street']}, {L['suburb']}", "rent": L["rent"], "bedrooms": L["bedrooms"],
               "bathrooms": L["bathrooms"], "available_from": L["available_from"], "cells": out}
    if L.get("photo"):
        payload["image"] = L["photo"]["url"]
    if L.get("source"):
        payload["source"] = {"site": L["source"].get("site"), "listing_id": L["source"].get("listing_id"), "url": L["source"].get("url")}
    return payload


def _open_cells(cells: Dict[str, dict], kind: str) -> List[Tuple[str, dict]]:
    """还没落实、而且下一步是 kind 的格子，最值得处理的排前面：硬条件先，未知 < 冲突 < 推断。H1 另有 wrap 里的那句，不在这里。"""
    order = {"unknown": 0, "conflict": 1, "inferred": 2}
    cands = [(d, c) for d, c in cells.items() if d != "H1" and c["status"] in order and (c.get("next") or {}).get("kind") == kind]
    cands.sort(key=lambda dc: (not dc[1]["hard"], order[dc[1]["status"]]))
    return cands


def best_question(cells: Dict[str, dict]) -> Optional[Tuple[str, dict]]:
    """最值得问中介的格子：只在下一步是 ask_agent 的格子里挑；没有可问的就不出问题（build_tour 改说 viewing_check 那句）。"""
    cands = _open_cells(cells, "ask_agent")
    return cands[0] if cands else None


def viewing_check(cells: Dict[str, dict]) -> Optional[Tuple[str, dict]]:
    """最值得去看房核的格子（下一步是 see_at_viewing）。"""
    cands = _open_cells(cells, "see_at_viewing")
    return cands[0] if cands else None


def build_tour(ranked: List[dict], profile: dict, excluded: int, narration: Optional[Dict[int, Future]] = None) -> List[dict]:
    """导览计划。narration 是 narrator.start_tour 发出去的请求（每套房一个 Future）：每句话先放模板，附上 (Future, 键)，
    讲到那句时（_emit_plan）再取模型写的版本，取不到就照模板说。"""
    plan: List[dict] = []
    idx = [0]

    def say(text: str, step: str, fut: Optional[Future] = None, key: Optional[str] = None) -> None:
        if not text:
            return
        ev = {"type": "say", "idx": idx[0], "text": text, "step": step}
        if fut is not None and key:
            ev["_nar"] = (fut, key)
        plan.append(ev)
        idx[0] += 1

    shown = ranked[:TOP_N]
    legal_pending = any(it["cells"]["H1"]["status"] == "unknown" for it in shown)
    for i, item in enumerate(shown):
        L, cells = item["listing"], item["cells"]
        fut = (narration or {}).get(i)
        plan.append({"type": "card", "listing": card_payload(L, cells, i + 1)})
        say(phraser.intro(i, L), f"L{i}", fut, "intro")
        for d in TOUR_ORDER:
            if d in cells:
                c = cells[d]
                plan.append({"type": "highlight", "listing_id": L["id"], "dim": d, "status": c["status"]})
                plan.append({"type": "evidence", "listing_id": L["id"], "dim": d, "label": c["label"], "status": c["status"], "items": c["evidence"]})
                say(phraser.cell_sentence(d, c, L, profile), f"L{i}.{d}", fut, f"cells.{d}")
        say(phraser.special(L), f"L{i}.special", fut, "special")
        bq = best_question(cells)
        if bq:
            plan.append({"type": "highlight", "listing_id": L["id"], "dim": bq[0], "status": bq[1]["status"], "question": True})
            say(phraser.best_question(bq[0], bq[1], profile), f"L{i}.question", fut, "question")
        else:  # 没有可问中介的：最值得去看房核的那格说一句 "worth checking at the viewing"
            vc = viewing_check(cells)
            if vc:
                plan.append({"type": "highlight", "listing_id": L["id"], "dim": vc[0], "status": vc[1]["status"], "viewing": True})
                say(phraser.viewing_check(vc[0], vc[1]), f"L{i}.viewing", fut, "viewing")
        if i < len(shown) - 1:
            say(phraser.transition(i + 1, len(shown)), f"L{i}.next", fut, "next")
    last = (narration or {}).get(len(shown) - 1) if shown else None
    say(phraser.wrap(len(shown), excluded, legal_pending), "wrap", last, "wrap")
    return plan


def narration_ready() -> bool:
    return narrator.enabled()


# ---------------------------------------------------------------- 打断分类与问题回答
def classify(text: str) -> str:
    t = text.lower().strip()
    words = re.findall(r"[a-z']+", t)
    if not words or all(w in FILLERS for w in words):
        return "resume"
    if re.search(r"\b(skip|next one|next|move on)\b", t):
        return "next"
    if re.search(r"\b(stop|pause|hold on|hang on|wait|that's enough|enough)\b", t):
        return "stop"
    if re.search(r"\b(continue|go on|carry on|resume|keep going|go ahead)\b", t):
        return "resume"
    if re.search(r"\b(agent|landlord|they|owner)\b.*\b(said|says|replied|confirmed|wrote|told)\b|living room only|pets? (are|is) (fine|ok|okay|allowed)", t):
        return "agent_reply"
    if re.search(r"^(is|are|does|do|did|can|could|how|what|which|where|when|why|who|will|would|was|were|has|have|tell me|show me)\b", t) or "?" in t:
        return "question"
    probe = new_profile()
    if parse_into(probe, t):
        return "update"
    return "question" if len(words) > 2 else "unclear"


def find_listing(text: str, ranked: List[dict], current: Optional[str]) -> Optional[dict]:
    t = text.lower()
    for item in ranked:
        street = item["listing"]["street"].lower()
        name = re.sub(r"^\d+\s+", "", street)
        if name.split()[0] in t:
            return item
    for word, i in ORDINALS.items():
        if re.search(r"\b" + word + r"\b", t):
            shown = ranked[:TOP_N]
            if shown:
                return shown[i if i >= 0 else len(shown) - 1] if (i < len(shown)) else None
    for item in ranked:
        if item["listing"]["id"] == current:
            return item
    return ranked[0] if ranked else None


def dim_for(text: str) -> Optional[str]:
    t = text.lower()
    for d, pat in KEYWORDS:
        if re.search(pat, t):
            return d
    return None


def listing_by_id(lid: Any) -> Optional[dict]:
    return next((L for L in LISTINGS if L["id"] == lid), None)


def street_word(street: str) -> str:
    """街名里第一个有字母的词（"2 Harrow Crescent" → harrow）：模型写的句子得点到这套房。"""
    for w in re.findall(r"[A-Za-z']+", str(street or "")):
        if w.lower() not in ("unit", "apt", "flat"):
            return w.lower()
    return str(street or "").lower()


def open_loops(ranked: List[dict], profile: dict) -> List[dict]:
    """还在等中介回答的格子：前几套每套最值得问的那个问题（build_tour 用同一个 best_question）。记进记忆，下次开场会提。"""
    out = []
    for it in ranked[:TOP_N]:
        bq = best_question(it["cells"])
        if bq:
            L = it["listing"]
            out.append({"listing": L["id"], "street": L["street"], "dim": bq[0], "label": DIMS[bq[0]]["label"], "status": bq[1]["status"],
                        "question": phraser.best_question(bq[0], bq[1], profile)})
    return out


def hello_view(renter: Any) -> Optional[dict]:
    """GET /api/hello 的 memory 字段：上次的需求（memory.view）+ 离开时到的回复（inbox）+ 信念翻转记录（beliefs）。没有记忆就 None。"""
    rid = memory.clean_id(renter)
    view = memory.view(memory.load(rid)) if rid else None
    if view is None:
        return None
    away = inbox.view(rid)
    for it in away["items"]:  # 界面要说是哪套房，不是编号
        L = listing_by_id(it["listing_id"])
        it["street"] = L["street"] if L else it["listing_id"]
    return dict(view, away=away, beliefs=beliefs.view(rid))


def forget_renter(renter: Any) -> dict:
    """Forget me：记忆、收件箱、信念日志一起删。"""
    return {"memory": memory.forget(renter), "inbox": inbox.forget(renter), "beliefs": beliefs.forget(renter)}


# ---------------------------------------------------------------- 会话
class Session:
    def __init__(self, sid: str):
        self.id = sid
        self.profile = new_profile()
        self.asked_rounds = 0
        self.pending: List[str] = []
        self.plan: List[dict] = []
        self.pos = 0
        self.ranked: List[dict] = []
        self.excluded = 0
        self.current: Optional[str] = None
        self.overrides: Dict[str, Dict[str, dict]] = {}
        self.changes: List[dict] = []
        self.quick = False
        self.parse_meta: dict = {"parser": "rules"}
        self.deterministic = False  # 回归 / 基线：过渡句固定、不让模型写台词
        self.request_text = ""  # 最近一句需求的原话（给模型写台词时参考）
        self.heard_said = False  # 反问前已经把听懂的需求复述过一遍（模型写台词时才有），开场就不再重复
        self.heard: List[str] = []  # 最近三句原话：导览的台词要知道租客一开始说了什么（有猫、要空调），不只是 "Under 900"
        self.renter: Optional[str] = None  # 浏览器给的租客编号（memory.py）；没有就不记、不认
        self.memory: Optional[dict] = None  # 这位租客上次的需求（attach_renter 装进来）
        self.remembered: List[str] = []  # 哪些字段是从记忆预填的、这次还没重说（needs 事件带出去，界面标"上次的"）
        self.greeted = False  # "Welcome back…" 说过没有（开场只说一次：要么机器先开口问，要么租客先说话时顺带说）
        self.awaiting: Optional[str] = None  # 机器先开口问了、还在等回答（"welcome"）；误触发的打断要重问这句而不是开查
        self.lock = threading.Lock()

    # ---- 欢迎回来（memory.py）----
    def attach_renter(self, renter_id: Any, prefill: bool = True) -> Optional[dict]:
        """认下这位租客：有记忆、还没开始说需求就把上次的需求预填进来；信念日志里翻过的格子（中介回复过的）也一并恢复。返回记忆（没有就 None）。"""
        self.renter = memory.clean_id(renter_id)
        self.memory = memory.load(self.renter) if self.renter else None
        if self.renter and not self.overrides:
            self.overrides = beliefs.overrides(self.renter)  # 上次中介说了的，这次还算数（beliefs.py 重放）
        if self.memory and prefill and not self.plan and not any(self.profile.get(k) is not None for k in memory.FIELDS) and not self.profile["extras"]:
            self.profile = memory.profile_from(self.memory)
            self.remembered = memory.remembered_fields(self.profile)
        return self.memory

    def welcome(self) -> Iterator[dict]:
        """机器先开口（8631 一连上、8630 第一次点麦克风）："Welcome back. Last time it was … Same again, or has anything changed?"。
        没有记忆就什么都不说。"""
        if not self.memory or self.plan or self.greeted:
            return
        self.greeted = True
        self.pending = []
        self.awaiting = "welcome"
        yield {"type": "state", "phase": "thinking", "label": "Welcome back"}
        yield {"type": "needs", "profile": self._profile_view(), "missing": missing_required(self.profile), "asking": [], **self._parse_view(), **self._needs_memory()}
        extra, streets = self._welcome_extra()
        fact = phraser.welcome_question(self.memory.get("summary") or phraser.summary(self.profile), extra)
        text = fact
        if self._nar():
            must = [r"welcome|back|last time"] + [re.escape(street_word(s)) for s in streets]  # 离开时到的回复 / 还在等的问题得点到那套房
            text = narrator.line("welcome", fact, context=self._ctx(), required=narrator.nums(fact), question=True, must=must) or fact
        yield {"type": "ask", "fields": [], "text": text}
        yield self._said(text, fact, expects_answer=True, step="welcome")
        yield {"type": "done"}

    def _needs_memory(self) -> dict:
        return {"remembered": list(self.remembered)} if self.remembered else {}

    def _welcome_extra(self) -> Tuple[str, List[str]]:
        """开场多说的那句：离开时收件箱到了中介回复（先），不然就是上次还在等中介回答的问题。返回 (句子, 要点名的街名)。"""
        if self.renter:
            streets: List[str] = []
            for it in inbox.unread(self.renter):
                L = listing_by_id(it["listing_id"])
                if L and L["street"] not in streets:
                    streets.append(L["street"])
            if streets:
                return phraser.away_line(streets), streets
        open_items = [o for o in ((self.memory or {}).get("open") or []) if o.get("street")][:2]
        if open_items:
            return phraser.open_line(open_items), [o["street"] for o in open_items]
        return "", []

    def _restated(self, changed: Dict[str, str]) -> None:
        """这轮重说了的字段不再算"上次的"。"""
        if self.remembered and changed:
            self.remembered = [f for f in self.remembered if f not in changed]

    # 事件小工具
    @staticmethod
    def _say(text: str, **kw) -> dict:
        return dict({"type": "say", "idx": None, "text": text}, **kw)

    def _nar(self) -> bool:
        """这轮让模型写台词吗：模型可用且不是回归（deterministic）。"""
        return not self.deterministic and narrator.enabled()

    def _ctx(self) -> dict:
        return {"renter_said": " / ".join(self.heard)[:400], "heard": list(self.heard), "needs": self._profile_view()}

    def _said(self, text: str, fact: str, **kw) -> dict:
        """模型写的那句（text）和模板（fact）不同时标 by: llm。"""
        ev = self._say(text, **kw)
        if text != fact:
            ev["by"] = "llm"
        return ev

    def handle_turn(self, body: dict) -> Iterator[dict]:
        text = (body.get("text") or "").strip()
        inter = body.get("interrupted") or {}
        self.deterministic = bool(body.get("deterministic"))
        if text:
            self.request_text = text
            self.heard = (self.heard + [text])[-3:]
            self.awaiting = None
        if body.get("listing_id"):
            self.current = body["listing_id"]
        if body.get("renter") and self.renter is None:
            self.attach_renter(body["renter"])
        if body.get("welcome"):  # 机器先开口的那轮（没有文字）
            yield from self.welcome()
            return
        if self.plan and not inter.get("active") and self.renter and inbox.unread(self.renter):  # 导览中途收件箱到了中介回复："Just in…"，先折进来再接这句话
            yield from self._inbox_now(live=True)
        if inter.get("active") and self.plan:
            yield from self._interrupted(text, inter)
            return
        pending, self.pending = self.pending, []
        kind = classify(text) if (self.plan and not pending) else "update"
        thinking_shown = False
        if kind == "update":  # 说需求、答反问、改需求：过渡句先出声，模型在线程里解析，规则校验兜底
            yield {"type": "state", "phase": "thinking", "label": "Analysing your request"}
            thinking_shown = True
            started = start_needs_llm(text, self.profile, pending) if needs_llm_ready() else None
            yield self._say(phraser.bridge(pending, variety=not self.deterministic), step="bridge")  # "Got it." / "Thanks."：不依赖解析结果，所以能先说
            if started is not None:
                changed, self.parse_meta = parse_needs_llm(text, self.profile, pending, started=started)
            else:
                changed, self.parse_meta = parse_into(self.profile, text, pending), rules_meta()
        else:  # 提问、续播、中介回复等：和原来一样只用规则
            changed = parse_into(self.profile, text, pending)
        self._restated(changed)
        if kind == "agent_reply" and self.plan:
            yield from self._agent_reply(text)
            return
        if kind == "question" and self.plan and not changed:
            if self._nar():
                yield self._say(phraser.pick("answer"), step="bridge")  # 模型写答案要 1 s 上下，先出声
            yield from self._answer(text)
            yield {"type": "state", "phase": "idle", "label": "Ready"}
            yield {"type": "done"}
            return
        if kind == "resume" and self.plan and self.pos < len(self.plan):
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
            return
        yield from self._search(changed, thinking_shown=thinking_shown)  # 没开查过时 changed 只给欢迎回来那句用（"this time budget 800"）

    # 开查：缺必填就问，否则搜 + 导览
    def _search(self, changed: Dict[str, str], thinking_shown: bool = False) -> Iterator[dict]:
        missing = missing_required(self.profile)
        if not thinking_shown:  # 模型解析那条路刚亮过同一个状态，不重复发
            yield {"type": "state", "phase": "thinking", "label": "Analysing your request"}
        if missing and self.asked_rounds < MAX_ASK_ROUNDS:
            ask = missing[:ASK_PER_ROUND]
            self.asked_rounds += 1
            self.pending = ask
            q0 = polish_llm(phraser.ask_sentence(ask), ask)
            q = q0
            yield {"type": "needs", "profile": self._profile_view(), "missing": missing, "asking": ask, **self._parse_view(), **self._needs_memory()}
            if self._nar():  # 先复述听懂的部分（模板，立刻能说），模型同时把反问写得自然；写坏了就用模板
                heard = phraser.summary(self.profile)
                if heard:
                    yield self._say(phraser.heard_sentence(heard, variety=not self.deterministic), step="heard")
                    self.heard_said = True
                q1 = narrator.line("ask", q0, context=self._ctx(), allowed=narrator.nums(heard), question=True)
                if q1 and all(re.search(ASK_WORDS[f], q1.lower()) for f in ask):
                    q = q1
                elif q1:
                    narrator.log.info(f"ask: dropped, does not ask every item {ask}: {q1[:100]!r}")
            yield {"type": "ask", "fields": ask, "text": q}
            yield self._said(q, q0, expects_answer=True, step="ask")
            yield {"type": "done"}
            return
        yield {"type": "needs", "profile": self._profile_view(), "missing": missing, "assumed": missing, **self._parse_view(), **self._needs_memory()}
        if self.memory and not self.plan:  # 第一次开查、有上次的记忆：欢迎回来那句代替需求复述（机器先开口问过的话只说"same as last time, then"）
            extra, streets = ("", []) if self.greeted else self._welcome_extra()  # 租客先开口的：离开时到的回复 / 还在等的问题也在这句里提
            fact = phraser.welcome_search(self.memory.get("summary") or "", changed, greeted=self.greeted, extra=extra)
            text = fact
            if self._nar():
                vals = set().union(*(narrator.nums(str(v)) for v in changed.values())) if changed else set()
                text = narrator.line("back", fact, context=self._ctx(), required=vals | narrator.nums(fact), statement=True,
                                     must=[r"welcome|back|last time|same|as before|rest"] + [re.escape(street_word(s)) for s in streets]) or fact  # "back", not "ack": nothing to re-rank on a first search
            self.greeted = True
            self.heard_said = True
            yield self._said(text, fact, step="welcome")
            yield self._say(phraser.opening_parts(self.profile, missing, len(SOURCES))[-1], step="opening")
        elif changed and self.plan:
            fact = phraser.updated(changed)
            text = fact
            if self._nar():
                vals = set().union(*(narrator.nums(str(v)) for v in changed.values())) if changed else set()
                text = narrator.line("ack", fact, context=self._ctx(), required=vals, statement=True,
                                     must=r"re-?rank|rank|again|re-?check|look|search|update|redo|re-?run|re-?sort|refresh|adjust|re-?do") or fact
            yield self._said(text, fact, step="update")
        else:
            parts = phraser.opening_parts(self.profile, missing, len(SOURCES))
            if self._nar():  # 口语化：先复述（反问前复述过就不再说）、再"让我看看"、再假设 + 开查那句
                glue = []
                s = phraser.summary(self.profile)
                if s and not self.heard_said:
                    glue.append(phraser.heard_sentence(s, variety=True))
                glue.append(phraser.thinking(self.profile.get("anchor"), variety=True))
                glue.append(parts[-1])
                parts = glue
            self.heard_said = False
            for part in parts:
                yield self._say(part, step="opening")
        yield from self._inbox_now(live=False)  # 离开时到的中介回复（inbox.py）：先翻格、记信念日志，再排名（"…I've folded that in before ranking"）
        yield {"type": "state", "phase": "searching", "label": "Checking sources"}
        self.ranked, self.excluded = rank(self.profile, self.overrides)
        n_pass = len(self.ranked)
        if self.renter:  # 记住这次的需求、前几套和还在等中介答的问题（memory.py）：下次开场 "Welcome back…"
            self.memory = memory.save(self.renter, self.profile, [r["listing"]["id"] for r in self.ranked[:TOP_N]], self.request_text, self.id,
                                      open=open_loops(self.ranked, self.profile)) or self.memory
        nar = None
        if self._nar() and self.ranked:  # 三套房的台词请求现在就发出去，查来源、说开场的这几秒刚好够模型写
            shown = self.ranked[:TOP_N]
            legal_pending = any(it["cells"]["H1"]["status"] == "unknown" for it in shown)
            nar = narrator.start_tour(shown, self.profile, self.heard, TOUR_ORDER, best_question,
                                      phraser.wrap(len(shown), self.excluded, legal_pending), legal_pending, self.excluded, viewing_check=viewing_check)
        for i, src in enumerate(SOURCES):
            rid = _mock_id()
            stage = stage_of({"table": src["table"]})  # 来源面板按五段分组（listing / public / agent；viewing、signing 两段永远是空的）
            yield {"type": "source", "name": src["name"], "label": src["label"], "table": src["table"], "stage": stage, "status": "running", "request_id": rid}
            time.sleep(random.uniform(0.15, 0.35) if self.quick else random.uniform(0.4, 1.0))
            yield {"type": "source", "name": src["name"], "label": src["label"], "table": src["table"], "stage": stage, "status": "done", "request_id": rid,
                   "rows": src["rows"], "ms": random.randint(180, 2400), "mock": True}
            if i == 1:
                yield self._say(phraser.found(n_pass, min(TOP_N, n_pass), variety=True) if self._nar() else phraser.shortlist(n_pass, min(TOP_N, n_pass)),
                                step="shortlist")
        self.quick = True
        self.plan = build_tour(self.ranked, self.profile, self.excluded, narration=nar)
        self.pos = 0
        yield {"type": "state", "phase": "touring", "label": "Walking you through"}
        yield from self._emit_plan()

    def _emit_plan(self) -> Iterator[dict]:
        while self.pos < len(self.plan):
            ev = self.plan[self.pos]
            self.pos += 1
            if ev["type"] == "card":
                self.current = ev["listing"]["id"]
            if ev["type"] == "say" and "_nar" in ev:  # 讲到这句了：取模型写的版本，取不到就照模板
                fut, key = ev.pop("_nar")
                text = narrator.take(fut, key)
                if text and text != ev["text"]:
                    ev["text"], ev["by"] = text, "llm"
            yield ev
        yield {"type": "state", "phase": "idle", "label": "Ready"}
        yield {"type": "done"}

    def resume(self, spoken_idx: Optional[int], listing_id: Optional[str] = None) -> Iterator[dict]:
        """误触发的打断（噪声、"嗯"、自己的回声）：不说话，直接从被切断的那句接着播。Pipecat 版用；浏览器版在前端暂停续播。"""
        if not self.plan:
            return
        self._rewind_to(spoken_idx)
        if listing_id:
            self.current = listing_id
        yield {"type": "state", "phase": "touring", "label": "Continuing"}
        yield from self._emit_plan()

    def resume_before_plan(self, cut_sentence: Optional[str]) -> Iterator[dict]:
        """开查前被误触发打断（自己的回声、噪声、"嗯"）：被切断的那条线程已经取消，不会自己回来，所以——
        反问还挂着就把问题重问一遍；机器先开口的欢迎问句还没等到回答就重问；需求已经说了就重新开查（开场句、来源、排名从头来）；
        什么都没说过就只把被切断的那句重说一遍。"""
        if self.plan:
            yield from self.resume(None)
            return
        if self.pending:
            q = phraser.ask_sentence(self.pending)
            yield {"type": "ask", "fields": list(self.pending), "text": q}
            yield self._said(q, q, expects_answer=True, step="repeat")
            yield {"type": "done"}
            return
        if self.awaiting == "welcome" and self.memory:
            q = cut_sentence or phraser.welcome_question(self.memory.get("summary") or phraser.summary(self.profile))
            yield {"type": "ask", "fields": [], "text": q}
            yield self._said(q, q, expects_answer=True, step="repeat")
            yield {"type": "done"}
            return
        if self.request_text:
            yield from self._search({}, thinking_shown=False)  # 它自己以 done 收尾（反问那支也是）
            return
        if cut_sentence:
            yield self._say(cut_sentence, step="repeat")
        yield {"type": "done"}

    def _rewind_to(self, spoken_idx: Optional[int]) -> None:
        """客户端报告最后一句完整说完的 idx；从它后面接着播（被切断的那句重播）。"""
        if spoken_idx is None:
            self.pos = 0
            return
        for i, ev in enumerate(self.plan):
            if ev["type"] == "say" and ev.get("idx") == spoken_idx:
                self.pos = i + 1
                return

    def _interrupted(self, text: str, inter: dict) -> Iterator[dict]:
        self._rewind_to(inter.get("spoken_idx"))
        if inter.get("listing_id"):
            self.current = inter["listing_id"]
        kind = classify(text)
        yield {"type": "state", "phase": "thinking", "label": "One sec"}
        if kind == "resume":
            yield self._say("Sure.", step="resume")
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
        elif kind == "next":
            nxt = next((i for i in range(self.pos, len(self.plan)) if self.plan[i]["type"] == "card"), None)
            if nxt is None:
                self.pos = max(0, len(self.plan) - 1)
                yield self._say("That was the last one. Here's the wrap-up.", step="next")
            else:
                self.pos = nxt
                yield self._say(phraser.pick("next", not self.deterministic), step="next")
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
        elif kind == "stop":
            yield self._say("Okay, I'll pause here. Say continue when you're ready.", step="stop")
            yield {"type": "state", "phase": "idle", "label": "Paused"}
            yield {"type": "done"}
        elif kind == "question":
            if self._nar():
                yield self._say(phraser.pick("answer"), step="bridge")
            yield from self._answer(text)
            cur = next((i for i, it in enumerate(self.ranked[:TOP_N]) if it["listing"]["id"] == self.current), None)
            if cur is not None and self.pos < len(self.plan):
                yield self._say(phraser.back(cur, variety=not self.deterministic), step="back")
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
        elif kind == "agent_reply":
            yield from self._agent_reply(text)
        elif kind == "update":
            started = start_needs_llm(text, self.profile) if needs_llm_ready() else None
            yield self._say(phraser.bridge([], interrupted=True, variety=not self.deterministic), step="bridge")  # "Okay."：先出声，模型同时解析
            if started is not None:
                changed, self.parse_meta = parse_needs_llm(text, self.profile, started=started)
            else:
                changed, self.parse_meta = parse_into(self.profile, text), rules_meta()
            if changed:
                yield from self._search(changed)
            else:
                yield self._say("I didn't catch a condition there. I'll carry on, interrupt me any time.", step="unclear")
                yield from self._emit_plan()
        else:
            yield self._say("Sorry, I didn't catch that. I'll carry on, interrupt me any time.", step="unclear")
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()

    def _answer(self, text: str) -> Iterator[dict]:
        if re.search(r"\b(which|best|cheapest|closest|recommend|top)\b", text.lower()) and not any(re.search(r"\b" + w + r"\b", text.lower()) for w in ORDINALS):
            fact = phraser.ranking(self.ranked)
            out = narrator.line("answer", fact, statement=True, context=self._ctx(), required=narrator.nums(fact), must=r"score|highest|top|best|cheapest|first|strongest") if self._nar() else None
            yield self._said(out or fact, fact, step="answer")
            return
        item = find_listing(text, self.ranked, self.current)
        if item is None:
            yield self._say("I don't have a shortlist yet. Tell me what you're after and I'll search.", step="answer")
            return
        L, cells = item["listing"], item["cells"]
        d = dim_for(text)
        if d and d in cells:
            c = cells[d]
            yield {"type": "highlight", "listing_id": L["id"], "dim": d, "status": c["status"]}
            yield {"type": "evidence", "listing_id": L["id"], "dim": d, "label": c["label"], "status": c["status"], "items": c["evidence"]}
            fact = phraser.answer(d, c, L, self.profile)
            out = None
            if self._nar():
                spec = narrator.cell_spec(d, c, L, self.profile)
                out = narrator.line("answer", fact, statement=True, context=self._ctx(), required=spec["required"], allowed=spec["allowed"], status=spec["status"],
                                    words=spec["words"], overlap=0.3)
            yield self._said(out or fact, fact, step="answer")
        elif d:
            fact = phraser.no_fact(L, DIMS[d]["label"].lower())
            out = narrator.line("answer", fact, statement=True, context=self._ctx(), status="unknown", words=narrator.DIM_WORDS.get(d)) if self._nar() else None
            yield self._said(out or fact, fact, step="answer")
        else:
            fact = phraser.no_fact(L, "that")
            out = narrator.line("answer", fact, statement=True, context=self._ctx(), status="unknown") if self._nar() else None
            yield self._said(out or fact, fact, step="answer")

    def _agent_reply(self, text: str) -> Iterator[dict]:
        """演示第 7 步：租客转达（或粘贴）中介的回复 → 当新材料：Nemotron 读出它答的是哪一格（replies.py），翻格、重排、记信念日志（beliefs.py）；
        同一条回复第二次来不重复做（参考 Dot：恢复 / 重放时不把外部动作做两遍）。"""
        item = find_listing(text, self.ranked, self.current)
        if item is None:
            yield self._say("Which place is that reply about?", step="agent")
            yield {"type": "done"}
            return
        L = item["listing"]
        if self._nar():
            yield self._say(phraser.pick("agent"), step="bridge")  # 模型读回复 + 写"变化"那句要 1–2 s，先出声
        res = self._apply_reply(text, L, source="agent_reply")
        if res["status"] == "unmapped":
            yield self._say("Noted, but I couldn't map that reply to a condition. Which item does it answer?", step="agent")
            yield {"type": "done"}
            return
        if res["status"] in ("duplicate", "same"):
            fact = (phraser.already_noted if res["status"] == "duplicate" else phraser.same_as_sources)(L, DIMS[res["dim"]]["label"], res["to"])
            yield self._say(fact, step="agent")
            yield {"type": "state", "phase": "idle", "label": "Ready"}
            yield {"type": "done"}
            return
        ch = res["change"]
        yield ch
        yield from self._reply_ui(ch)
        fact = phraser.change_sentence(L, ch["label"], ch["from"], ch["to"], res["consequence"])
        yield self._said(self._change_line(L, ch, fact, res["consequence"]), fact, step="change")
        self._rebuild_plan_keeping_place()
        yield {"type": "state", "phase": "idle", "label": "Ready"}
        yield {"type": "done"}

    def _apply_reply(self, text: str, L: dict, *, source: str, event_id: Optional[str] = None, channel: Optional[str] = None) -> dict:
        """一条中介回复落到状态上（不发事件）：读（replies.py）→ 查重 → 覆盖那格 → 重排 → 记信念日志（beliefs.py）→ 记 change。
        返回 {"status": changed | same | duplicate | unmapped, ...}。"""
        item = next((it for it in self.ranked if it["listing"]["id"] == L["id"]), None)
        cells = item["cells"] if item else evaluate(L, self.profile, self.overrides.get(L["id"], {}))
        res, meta = replies.read(text, L, cells, self._profile_view(), deterministic=self.deterministic)
        if res is None:
            return {"status": "unmapped", "reader": meta}
        dim, new, why, quote = res["dim"], res["status"], res["why"], res.get("quote")
        eid = event_id or beliefs.event_id(L["id"], dim, new, text)
        if any(c.get("event_id") == eid for c in self.changes) or (self.renter and beliefs.seen(self.renter, eid)):
            return {"status": "duplicate", "dim": dim, "to": new, "reader": meta, "event_id": eid}
        old = cells.get(dim, {}).get("status", "unknown")
        if old == new:
            return {"status": "same", "dim": dim, "to": new, "reader": meta, "event_id": eid}
        if dim not in cells and all(e["dim"] != dim for e in self.profile["extras"]):
            self.profile["extras"].append({"dim": dim, "label": DIMS[dim]["label"]})  # 中介答了，这项就进清单
        n = (sum(1 for r in beliefs.load(self.renter) if r.get("listing_id") == L["id"]) if self.renter else sum(1 for c in self.changes if c["listing_id"] == L["id"])) + 1
        override = {"status": new, "why": why, "evidence": [{"table": "documents", "row": f"agent_replies/{L['id']}", "material_id": f"M-{L['id'][2:]}-reply-{n:02d}",
                                                             "text": quote or text, "channel": channel, "reader": meta.get("parser")}]}
        prev = {k: dict(v) for k, v in self.overrides.items()}
        before = [it["listing"]["id"] for it in rank(self.profile, prev)[0][:TOP_N]]
        self.overrides.setdefault(L["id"], {})[dim] = override
        self.ranked, self.excluded = rank(self.profile, self.overrides)
        after = [it["listing"]["id"] for it in self.ranked[:TOP_N]]
        row = beliefs.record(self.renter, listing_id=L["id"], street=L["street"], dim=dim, label=DIMS[dim]["label"], old=old, new=new, source=source,
                             text=text, override=override, session_id=self.id, event_id_=eid, reader=meta, rank_before=before, rank_after=after,
                             channel=channel) if self.renter else None  # 只有带租客编号的会话落盘（跨会话算数）；回归 / 测试的会话版本号只在会话里数
        if row is None:
            from_v = 1 + sum(1 for c in self.changes if c["listing_id"] == L["id"] and c["dim"] == dim)
            from_v, version = from_v, from_v + 1
        else:
            from_v, version = row["from_version"], row["version"]
        change = {"type": "change", "listing_id": L["id"], "street": L["street"], "dim": dim, "label": DIMS[dim]["label"], "from": old, "to": new,
                  "source": source, "channel": channel, "ts": dt.datetime.now().isoformat(timespec="seconds"), "rank_before": before, "rank_after": after,
                  "event_id": eid, "from_version": from_v, "version": version, "quote": quote, "reader": meta.get("parser"), "model": meta.get("model")}
        self.changes.append(change)
        consequence = ""
        if before != after and after:
            top = next(it for it in self.ranked if it["listing"]["id"] == after[0])["listing"]
            consequence = f"That moves {top['street']} to the top." if after[0] != before[0] else "The order stays the same."
        return {"status": "changed", "change": change, "dim": dim, "to": new, "consequence": consequence, "reader": meta, "event_id": eid}

    def _reply_ui(self, ch: dict) -> Iterator[dict]:
        """翻格之后给界面的三件：卡片更新、高亮、证据（导览已经发过卡片时才有意义）。"""
        L = listing_by_id(ch["listing_id"])
        new_item = next((it for it in self.ranked if it["listing"]["id"] == ch["listing_id"]), None)
        if L is None or new_item is None:
            return
        after = ch.get("rank_after") or []
        yield {"type": "card_update", "listing": card_payload(L, new_item["cells"], after.index(L["id"]) + 1 if L["id"] in after else 0)}
        yield {"type": "highlight", "listing_id": L["id"], "dim": ch["dim"], "status": ch["to"]}
        yield {"type": "evidence", "listing_id": L["id"], "dim": ch["dim"], "label": ch["label"], "status": ch["to"], "items": new_item["cells"][ch["dim"]]["evidence"]}

    def _change_line(self, L: dict, ch: dict, fact: str, consequence: str) -> str:
        """让模型把"变化"那句说自然；得说出新状态的意思和是哪套房，换了第一名也得点名，不然用模板。"""
        if not self._nar():
            return fact
        to_words = {"supported": r"supported|confirmed|checks out|now a yes|in writing", "conflict": r"conflict|doesn'?t match|clash|contradict|snag",
                    "inferred": r"infer|likely|probably", "unknown": r"unknown|can'?t confirm|open"}[ch["to"]]
        out = narrator.line("change", fact, context=self._ctx(), allowed=narrator.nums(fact), words=narrator.DIM_WORDS.get(ch["dim"]),
                            must=[to_words, re.escape(street_word(L["street"]))], overlap=0.3)
        m = re.match(r"That moves (.+) to the top\.", consequence or "")
        top_word = street_word(m.group(1)) if m else ""
        if out and top_word and top_word not in out.lower():
            out = None  # 换了第一名却没说出是哪套：用模板
        return out or fact

    def _inbox_now(self, live: bool) -> Iterator[dict]:
        """收件箱里没读的中介回复（inbox.py，离开时到的）：逐条翻格、重排、记信念日志、标已读。
        live = 导览中途（"Just in…"，卡片跟着更新），否则是开查时排名之前（"…I've folded that in before ranking"）。"""
        if not self.renter:
            return
        items = inbox.unread(self.renter)
        if not items:
            return
        for it in items:
            inbox.mark_read(self.renter, [it["event_id"]])  # 先标已读：就算下面出错也不会下一轮再来一遍
            L = listing_by_id(it["listing_id"])
            if L is None:
                continue
            res = self._apply_reply(it["text"], L, source="inbox_live" if live else "inbox", event_id=it["event_id"], channel=it.get("channel"))
            if res["status"] == "unmapped":
                yield self._say(phraser.inbox_unmapped(L, it.get("channel")), step="away")
                continue
            if res["status"] in ("duplicate", "same"):
                yield self._say((phraser.already_noted if res["status"] == "duplicate" else phraser.same_as_sources)(L, DIMS[res["dim"]]["label"], res["to"]), step="away")
                continue
            ch = res["change"]
            yield ch
            if live:
                yield from self._reply_ui(ch)
            fact = phraser.inbox_change(L, ch["label"], ch["from"], ch["to"], it.get("channel"), live, res["consequence"])
            yield self._said(self._change_line(L, ch, fact, res["consequence"] if live else ""), fact, step="away")
        if live and self.plan:
            self._rebuild_plan_keeping_place()

    def _rebuild_plan_keeping_place(self) -> None:
        """中介回复改了格子、可能重排之后重建导览计划，但记住讲到哪了：导览已经讲完就还算讲完（"继续"不会从头再来一遍）；
        讲到一半就停在当前这套房还没讲过的第一格（已经讲过的格子，包括刚被改的那格，不重复；"continue / go on" 从这里接着讲）。"""
        if self.plan and self.pos == 0:  # 还没开讲（中介回复在开讲前到了）：计划重建，照样从头讲
            self.plan = build_tour(self.ranked, self.profile, self.excluded)
            return
        cur_id = self.current
        tour_done = not self.plan or self.pos >= len(self.plan)
        spoken = set()
        card = None
        for ev in self.plan[:self.pos]:
            if ev["type"] == "card":
                card = ev["listing"]["id"]
            elif ev["type"] == "say" and card == cur_id:
                spoken.add(ev["step"].split(".", 1)[1] if "." in ev["step"] else "intro")
        self.plan = build_tour(self.ranked, self.profile, self.excluded)
        if tour_done:
            self.pos = len(self.plan)
            return
        card_pos = next((k for k, ev in enumerate(self.plan) if ev["type"] == "card" and ev["listing"]["id"] == cur_id), None)
        if card_pos is None:  # 这套房重排后掉出前三：当作讲完
            self.pos = len(self.plan)
            return
        k = next((k for k in range(card_pos + 1, len(self.plan))
                  if self.plan[k]["type"] == "card"
                  or (self.plan[k]["type"] == "say" and (self.plan[k]["step"].split(".", 1)[1] if "." in self.plan[k]["step"] else "intro") not in spoken)),
                 len(self.plan))
        while k - 1 > card_pos and self.plan[k - 1]["type"] in ("highlight", "evidence"):
            k -= 1  # 把下一格前面的高亮 / 证据事件也带上
        self.pos = k

    def _parse_view(self) -> dict:
        """needs 事件里标明这次需求是哪条路解析的（parser: llm / rules）和细节。"""
        m = dict(self.parse_meta)
        return {"parser": m.pop("parser", "rules"), "parse": m}

    def _profile_view(self) -> dict:
        p = self.profile
        return {"budget": p["budget"], "bedrooms": p["bedrooms"], "anchor": p["anchor"], "move_in": p["move_in"]["text"] if p["move_in"] else None,
                "pets": (p["pets"]["text"] if p["pets"] else None), "extras": [e["label"] for e in p["extras"]], "max_commute": p["max_commute"]}


class Sessions:
    def __init__(self) -> None:
        self._s: Dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, sid: str) -> Session:
        with self._lock:
            if sid not in self._s:
                self._s[sid] = Session(sid)
            return self._s[sid]

    def reset(self, sid: str) -> None:
        with self._lock:
            self._s.pop(sid, None)


SESSIONS = Sessions()
