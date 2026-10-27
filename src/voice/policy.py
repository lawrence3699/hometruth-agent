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
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import beliefs
import inbox
import memory
import narrator
import phraser
import replies
import zetaris_live  # 10-27：取证经 Zetaris（每次开查一条 SELECT / 来源；没 key 时不联网）

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
BEAT_MS = 1500  # 10-28 简短播报：每讲完一套停一下（beat 事件），外放的人能插上话；没人说话就接着讲


def tour_mode() -> str:
    """VOICE_TOUR=brief（默认，docs/12：每套三句，说 tell me more 再展开）或 full（10-27 前的逐格讲法）。"""
    m = os.environ.get("VOICE_TOUR", "brief").strip().lower()
    return m if m in ("brief", "full") else "brief"

PLACES = [
    ("central", "Central Station", "central"), ("unsw", "UNSW", "unsw"), ("cbd", "the CBD", "cbd"), ("city", "the CBD", "cbd"),
    ("town hall", "the CBD", "cbd"), ("martin place", "the CBD", "cbd"), ("uts", "UTS", None), ("usyd", "Sydney Uni", None),
    ("sydney uni", "Sydney Uni", None), ("redfern", "Redfern", None), ("randwick", "Randwick", None), ("kensington", "Kensington", None),
    ("kingsford", "Kingsford", None), ("zetland", "Zetland", None), ("mascot", "Mascot", None), ("haymarket", "Haymarket", None),
    ("surry hills", "Surry Hills", None), ("bondi junction", "Bondi Junction", None), ("north sydney", "North Sydney", None),
    ("macquarie park", "Macquarie Park", None), ("parramatta", "Parramatta", None), ("chatswood", "Chatswood", None),
]
ANCHOR_ALIASES = [  # 10-28：语音识别常见的拼法 / 口语叫法 → PLACES 里的标准名
    (r"\byou and (?:s ?w|south wales)\b|\bu ?n ?s ?w\b|\bu\.n\.s\.w\b|\bnew south wales uni(?:versity)?\b|\buni(?:versity)? of new south wales\b|\bkensington campus\b", "UNSW"),
    (r"\bcentral (?:train )?station\b|\bcentral\b", "Central Station"),
    (r"\b(?:sydney )?c\.?b\.?d\.?\b|\bthe city\b|\bcity cent(?:re|er)\b", "the CBD"),
    (r"\bu ?t ?s\b|\buni(?:versity)? of technology\b", "UTS"),
    (r"\bsydney uni(?:versity)?\b|\bu ?syd\b|\buni(?:versity)? of sydney\b", "Sydney Uni"),
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
        r"\b(\d{3,4})\s*(?:max(?:imum)?|tops|or (?:less|under|below)|at (?:the )?most)\b",  # 10-28 "can we make it 800 max?"
        r"\b(?:make it|make that|change it to|bring it down to|drop it to|raise it to|up it to|go up to|go down to)\s*\$?\s?(\d{3,4})\b",
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
    if re.search(r"\b(just me|only me|just myself|on my own|by myself|living alone|for one person|single person)\b", t):
        return 1  # 10-28 "it's just me"：一个人住按一房算
    return None


def parse_anchor(t: str) -> Optional[str]:
    for key, label, _ in PLACES:
        if re.search(r"\b" + re.escape(key) + r"\b", t):
            return label
    for pat, label in ANCHOR_ALIASES:
        if re.search(pat, t):
            return label
    return None


VAGUE_PLACE = r"\b(the beach|beaches|near the water|by the sea|the coast|the uni|uni|university|work|the office|my office|the station|a station)\b"


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
STOP = {"the", "near", "close", "to", "in", "at", "of", "and", "station", "uni", "university", "my", "our", "work", "a", "an", "street",
        "beach", "beaches", "coast", "water", "sea", "office"}  # 10-28：模型把 "near the beach" 填成 Bondi Beach，只靠 beach 这个词不算原话里有
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
    return any(label == anchor and re.search(r"\b" + re.escape(key) + r"\b", t) for key, label, _ in PLACES) or \
        any(label == anchor and re.search(pat, t) for pat, label in ANCHOR_ALIASES)


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


# 10-28（docs/12 模拟顾客 P18）：反问时说 "I don't know when yet"，以前下一轮还接着问 "when do you need to move in?"。说过不知道的必填项不再问，
# 开查时照常假设并说出口（"any move-in date"）。
DONT_KNOW = {"A4": r"\b(?:(?:don'?t|do not) know|not sure|no idea|unsure|haven'?t decided|undecided)\b[^.?!]*\bwhen\b|\bwhenever\b|\bflexible\b|\bno rush\b|\bany ?time\b",
             "G1": r"\b(?:(?:don'?t|do not) know|not sure|no idea|unsure)\b[^.?!]*\bwhere\b|\banywhere\b",
             "A1": r"\b(?:(?:don'?t|do not) know|not sure|no idea|unsure)\b[^.?!]*\b(?:budget|how much|spend)\b",
             "B1": r"\b(?:(?:don'?t|do not) know|not sure|no idea|unsure)\b[^.?!]*\b(?:bedrooms?|rooms?|how many)\b",
             "J1": r"\b(?:(?:don'?t|do not) know|not sure|no idea|unsure)\b[^.?!]*\bpets?\b"}


def sentences(text: str) -> List[str]:
    """一段话拆成一句一个 say（10-28，docs/12：句与句之间能打断，最长一句不超过 8 秒左右）。"""
    return [x for x in re.split(r"(?<=[.?!])\s+(?=[A-Z0-9])", (text or "").strip()) if x]


def declined_fields(text: str, fields: List[str]) -> List[str]:
    t = text.lower()
    return [f for f in fields if f in DONT_KNOW and re.search(DONT_KNOW[f], t)]


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
    # 每条证据标上从哪来（zetaris_live.stamp）：返回它的那条 Zetaris 查询（request_id + SQL）、中介回复，或本地副本；不再有 mock
    return [dict(it, stage=stage_of(it), **zetaris_live.stamp(it)) for it in items]


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


def commute_evidence(L: dict, anchor: str) -> Tuple[Optional[dict], dict]:
    """G1 的通勤行和它的那条证据。evaluate 用它，zetaris_rows 发给 Zetaris 的也是它，所以两边的 evidence_id 对得上。"""
    key = ANCHOR_KEY.get(anchor)
    row = L["commute"].get(key) if key else None
    if row is None:
        return None, {"table": "public_transit", "row": f"{L['suburb']}→{anchor}", "material_id": None, "text": "No row yet"}
    if row.get("estimate"):  # 真房源（scripts/domain_sample.py）：按直线距离估的，不是时刻表
        return row, {"table": "geo_estimate", "row": f"{L['id']}→{anchor}", "material_id": None,
                     "text": f"About {row['min']} min by {row['mode']}: {row.get('km', '?')} km in a straight line, an estimate from the distance, not a timetable"}
    return row, {"table": "public_transit", "row": f"{L['suburb']}→{anchor} 08:00", "material_id": None,
                 "text": f"{row['min']} min by {row['mode']}, weekday 8:00 departure"}


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
        row, ev = commute_evidence(L, profile["anchor"])
        if row is None:
            cells["G1"] = _cell("G1", "unknown", None, why=f"No transit row for {profile['anchor']} in the prototype table.", evidence=[ev])
        elif row.get("estimate"):  # 真房源：距离估算 → 最多"推断"，超限仍是冲突
            ok = row["min"] <= profile.get("max_commute", 40)
            cells["G1"] = _cell("G1", "inferred" if ok else "conflict", row, estimate=True, evidence=[ev])
        else:
            ok = row["min"] <= profile.get("max_commute", 40)
            cells["G1"] = _cell("G1", "supported" if ok else "conflict", row, evidence=[ev])
    if profile["move_in"] and not L.get("available_from"):
        # 真房源的搜索卡片没有可入住日（scripts/domain_sample.py 记成 None）：硬条件未知 = 待确认，不算满足、也不排除（CLAUDE.md 第 4 节）；
        # 中介回复了入住日（replies.py 落到 A4 的覆盖）就照回复的状态，不再是 no date
        f = overrides.get("A4") or facts.get("A4") or {}
        st = (f.get("status") or "unknown") if overrides.get("A4") else "unknown"
        cells["A4"] = _cell("A4", st, None, why=f.get("why") or "The listing gives no move-in date; ask the agent.", evidence=f.get("evidence"),
                            short="no date" if st == "unknown" else "per agent")
    elif profile["move_in"]:
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


_ZROWS: Dict[str, List[dict]] = {}


def zetaris_rows(source: str) -> Optional[List[dict]]:
    """/api/zetaris/<source> 发布的表（Zetaris 把它注册成 REST 表，scripts/zetaris/10_register_hometruth.sql）：这个来源的每条证据一行，
    列见 zetaris_live.COLUMNS，全是字符串。证据就是 evaluate 用的那几条（矩阵 facts 的证据 + commute_evidence 算的通勤行，三个有表的地点），
    evidence_id 两边一样。同一条证据挂在几套房上就有几行（按 listing_id 过滤要用）。不认识的来源返回 None。"""
    if source not in {s["name"] for s in SOURCES}:
        return None
    if source in _ZROWS:
        return _ZROWS[source]
    tables, out, seen = zetaris_live.tables_of(source), [], set()

    def add(L: dict, dim: str, e: dict) -> None:
        eid = zetaris_live.evidence_id(e)
        if e.get("table") in tables and (eid, L["id"]) not in seen:
            seen.add((eid, L["id"]))
            out.append({"evidence_id": eid, "listing_id": L["id"], "dim": dim, "source_table": str(e.get("table")), "row_ref": str(e.get("row") or ""),
                        "material_id": str(e.get("material_id") or ""), "fact": str(e.get("text") or "")})
    anchors = sorted({label for _, label, key in PLACES if key})
    for L in LISTINGS:
        for dim, f in (L.get("facts") or {}).items():
            for e in f.get("evidence", []):
                add(L, dim, e)
        for a in anchors:
            row, e = commute_evidence(L, a)
            if row is not None:
                add(L, "G1", e)
    _ZROWS[source] = out
    return out


def _has_plan3d(url: Optional[str]) -> bool:
    """户型图 /real/<文件夹>/prep/NN.jpg → data/real/photos/<文件夹>/plan3d.json 在不在（src/photo/plan3d.py build 生成，进仓库）。"""
    m = re.match(r"/real/([^/]+)/", url or "")
    return bool(m) and (ROOT / "data" / "real" / "photos" / m.group(1) / "plan3d.json").exists()


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
    if (L.get("source") or {}).get("card_only"):  # 10-27：只存了搜索结果卡片的真房源（没有正文）；页面据此说"只有卡片"而不是"挂牌没写"
        out["card_only"] = True
    for k in ("source", "images", "floorplan", "sun", "description", "headline", "lat", "lng", "parking"):  # 真房源（scripts/domain_sample.py）：相册、户型图、日照几何、出处
        if L.get(k) is not None:
            out[k] = L[k]
    if out.get("floorplan"):  # 10-27：46 套卡片房源也认出了户型图，但分房间的玩偶屋（plan3d.json）只有做过的几套有；页面据此写 "3D plan" 还是 "Floor plan"
        out["floorplan"] = dict(out["floorplan"], has_3d=_has_plan3d(out["floorplan"].get("url")))
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
    # 10-27：独立屋 / 没单元号的卡片不再显示 "/12 X Street"
    payload = {"id": L["id"], "rank": rank_no, "title": (f"{L['unit']}/" if L.get("unit") else "") + f"{L['street']}, {L['suburb']}", "rent": L["rent"], "bedrooms": L["bedrooms"],
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


def _full_events(plan: List[dict], say, i: int, n: int, item: dict, profile: dict, fut: Optional[Future] = None) -> None:
    """一套房的逐格讲法（10-27 前的默认；现在是 full 模式和 "tell me more"）。"""
    L, cells = item["listing"], item["cells"]
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


BRIEF_ORDER = {"conflict": 0, "unknown": 1, "inferred": 2}


def brief_open(cells: Dict[str, dict]) -> Tuple[List[Tuple[str, dict]], List[Tuple[str, dict]]]:
    """还没落实的格子：(租客要的, 没问但照片说了的)，最要紧的在前：冲突 > 未知 > 推断，硬条件先。"""
    cands = [(d, c) for d, c in cells.items() if d != "H1" and c["status"] in BRIEF_ORDER
             and not (d == "G1" and c["status"] == "inferred")]  # 估算的通勤：第一句已经说了 "about 24 minutes"
    cands.sort(key=lambda dc: (not dc[1]["hard"], BRIEF_ORDER[dc[1]["status"]], TOUR_ORDER.index(dc[0]) if dc[0] in TOUR_ORDER else 99))
    return [x for x in cands if not x[1].get("notable")], [x for x in cands if x[1].get("notable")]


def _brief_events(plan: List[dict], say, i: int, item: dict, profile: dict, asked_q: Dict[str, int], variety: bool = False) -> None:
    """一套房三句（docs/12）：地址 + 租金 + 通勤；最多两件没落实的（全对就 checks out）；最该问中介的一句（前面问过同样的就说 same question）。"""
    L, cells = item["listing"], item["cells"]
    plan.append({"type": "card", "listing": card_payload(L, cells, i + 1)})
    say(phraser.brief_intro(i, L, cells, profile, variety), f"L{i}")
    asked, notable = brief_open(cells)
    told = asked[:2] if asked else notable[:1]
    for d, c in told:
        plan.append({"type": "highlight", "listing_id": L["id"], "dim": d, "status": c["status"]})
        plan.append({"type": "evidence", "listing_id": L["id"], "dim": d, "label": c["label"], "status": c["status"], "items": c["evidence"]})
    sp = phraser.short_special(L)
    if sp and (re.search(r"\d|minute", sp) or (profile.get("anchor") and profile["anchor"].lower() in sp.lower())):
        sp = ""  # 通勤已经在第一句里了
    verdict = phraser.brief_verdict([phraser.caveat(d, c) for d, c in asked[:2]], [] if asked else [phraser.caveat(d, c) for d, c in notable[:1]], sp, variety)
    if asked_q.get("said:" + verdict):  # 和前面一套一字不差：换个说法，不原样重复（asked_q 里 said: 开头的键记说过的句子）
        verdict = phraser.verdict_again([d for d, _ in asked[:2]])
    asked_q["said:" + verdict] = 1
    say(verdict, f"L{i}.brief")
    bq = best_question(cells)
    if bq:
        plan.append({"type": "highlight", "listing_id": L["id"], "dim": bq[0], "status": bq[1]["status"], "question": True})
        say(phraser.brief_question(bq[0], bq[1], profile, L, asked_q.get(bq[0], 0), variety), f"L{i}.question")
        asked_q[bq[0]] = asked_q.get(bq[0], 0) + 1
    else:
        vc = viewing_check(cells)
        if vc:
            plan.append({"type": "highlight", "listing_id": L["id"], "dim": vc[0], "status": vc[1]["status"], "viewing": True})
            say(phraser.brief_viewing(vc[0], vc[1]), f"L{i}.viewing")


def _headline_events(plan: List[dict], say, i: int, item: dict, profile: dict) -> None:
    L, cells = item["listing"], item["cells"]
    plan.append({"type": "card", "listing": card_payload(L, cells, i + 1)})
    say(phraser.headline(i, L, cells, profile), f"L{i}")


def build_tour(ranked: List[dict], profile: dict, excluded: int, narration: Optional[Dict[int, Future]] = None, mode: str = "full",
               start_idx: int = 0, only: Optional[Set[str]] = None, variety: bool = False) -> List[dict]:
    """导览计划。mode：full = 逐格讲（narration 是 narrator.start_tour 发出去的请求，每套房一个 Future：每句先放模板，附上 (Future, 键)，
    讲到那句时 _emit_plan 再取模型写的版本）；brief = 每套三句、套与套之间一个 beat（docs/12）；headlines = 每套一句。
    start_idx：句子编号从几开始（一个会话里的编号不重复，客户端报回来的旧编号不会对上新计划的另一句）。only：只讲这几套（改需求后没听过的）。"""
    plan: List[dict] = []
    idx = [start_idx]

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
    asked_q: Dict[str, int] = {}  # 同一个问题前面问过几次（第二次 "same question"，第三次换个说法）
    told = 0
    for i, item in enumerate(shown):
        if only is not None and item["listing"]["id"] not in only:
            bq = best_question(item["cells"])
            if bq:
                asked_q[bq[0]] = asked_q.get(bq[0], 0) + 1  # 这套之前讲过：它的问题算问过了
            continue
        if mode == "full":
            _full_events(plan, say, i, len(shown), item, profile, (narration or {}).get(i))
            if i < len(shown) - 1:
                say(phraser.transition(i + 1, len(shown)), f"L{i}.next", (narration or {}).get(i), "next")
            continue
        if told:
            plan.append({"type": "beat", "ms": BEAT_MS})
        told += 1
        if mode == "headlines":
            _headline_events(plan, say, i, item, profile)
        else:
            _brief_events(plan, say, i, item, profile, asked_q, variety)
    if mode == "full":
        last = (narration or {}).get(len(shown) - 1) if shown else None
        say(phraser.wrap(len(shown), excluded, legal_pending), "wrap", last, "wrap")
    elif shown:
        say(phraser.brief_wrap(len(shown), legal_pending), "wrap")
    return plan


def narration_ready() -> bool:
    return narrator.enabled()


# ---------------------------------------------------------------- 打断分类与问题回答
# 10-28（docs/12）：真人插话的说法。先剥掉开头的语气词（wait, / sorry, / oh and …），只有整句就是命令才算 stop / next / continue
# （"Wait, does that one allow cats?" 是在问问题；"Is the next one cheaper?" 是在问下一套）；带问号的改需求（"can we make it 800 max?"）算改需求。
MARKERS = r"(?:oh|um+|uh+|erm?|ah|okay|ok|so|well|hmm+|hey|right|sorry|wait|hang on|hold on|actually|no|yeah|yes|yep|look|listen|and|but|please)"
STOP_BARE = r"(stop|pause|wait|hold on|hang on|wait a (sec|second|moment|minute)|one (sec|second|moment)|just a (sec|second|moment)|that'?s enough|enough|" \
            r"be quiet|quiet|shush|stop talking|stop there|pause there|pause it|stop it)"
NEXT_BARE = r"(next|next one|the next one|skip|skip (it|this|that)( one)?|move on|on to the next( one)?|go on to the next( one)?|next place|next please|" \
            r"skip ahead|keep going to the next( one)?)"
RESUME_BARE = r"(continue|go on|carry on|resume|keep going|go ahead|you can continue|sure go on|yes go on|okay go on|let'?s continue|continue then)"
REPEAT_RE = re.compile(r"\b(say (that|it) again|repeat (that|it|the last (bit|part|one|sentence))|what (was that|did you (just )?say)|"
                       r"(didn'?t|did not|couldn'?t) (catch|hear|get) (that|it|what you said)|come again|pardon( me)?|one more time)\b")
QUESTIONS_RE = re.compile(r"\b((draft|write|list|give me|send( me)?|read( me)?|show( me)?|what are|make|get) (me )?(the |my |those |some |all the |your )?(agent |list of )?questions"
                          r"|questions (for|to) (the )?agents?|what (should|do) i ask|what to ask)\b")
SHORTER_RE = re.compile(r"\b(short(er)? version|shorter|too long|(talk|go|speak) (faster|quicker)|speed (it )?up|just the (highlights|headlines|key (points|bits)|main (points|bits)|gist|basics)|"
                        r"get to the point|sum (it|them|that) up|summari[sz]e|quick(er)? version|less detail|keep it (short|brief)|in short|briefly)\b")
DETAIL_RE = re.compile(r"\b(tell me more|more (about|on|detail|details|info|information)|full (details|rundown|picture|version)|all the details|in (more )?detail|"
                       r"details (on|about|for)|everything about|walk me through (it|that|this|the \w+( one)?)|go through (it|that|this|the \w+( one)?))\b")
RANK_RE = re.compile(r"\b((which|what) (one )?(would you|do you|should i) (pick|choose|recommend|go for|take)|(your|the) (top )?(pick|recommendation)|which is (the )?best( one)?|which one is best)\b")
COMPARE_RE = re.compile(r"\b(compare|comparison|difference|differ|versus|vs\.?|side by side|stack up)\b|\bwhich (one )?(is|has|'s|would be) (the )?"
                        r"(cheaper|cheapest|closer|closest|bigger|biggest|nicer|quieter|newer|nearest|nearer)\b|\b(cheaper|closer|bigger|nicer|quieter|nearer) than\b")
REJECT_RE = re.compile(r"\b(too (far|expensive|pricey|dear|small|tiny|big|noisy|old|much|cramped|dark)|(don'?t|do not|didn'?t) (like|want|love) (it|that|this|that one|this one|the \w+ one|that place|this place)|"
                       r"not (that|this) one|not for me|(rule|cross|strike|knock) (it|that|this)( one)? (out|off)|drop (it|that|this)( one)?|(get rid of|remove) (it|that|this)( one)?|"
                       r"no to (that|this)|hate (it|that|this)|not interested)\b")
JUMP_RE = re.compile(r"\b(go back( to)?|back to (the )?(first|second|third|last|previous|top)|(the )?(first|second|third|previous|last|top) one again|previous (one|place)|"
                     r"tell me about (the )?(first|second|third|last|next|top)( one| place)?|what about (the )?(first|second|third|last|other|top)( one| place)?|"
                     r"(skip|jump) to (the )?(first|second|third|last)( one)?)\b")
AGENT_RE = re.compile(r"\b(agent|landlord|they|owner)\b.*\b(said|says|replied|confirmed|wrote|told)\b|living room only|pets? (are|is) (fine|ok|okay|allowed)")
QUESTION_START = re.compile(r"^(is|are|does|do|did|can|could|how|what|which|where|when|why|who|will|would|was|were|has|have|tell me|show me)\b")
ABOUT_PLACE = re.compile(r"^(is|are|does|do|has|have|was|will|did|can i|could i)\s+(it|this|that|they|there|the\s+\w+|this one|that one)\b")
UPDATE_CUE = re.compile(r"\b(make it|make that|can we|could we|can you (also )?(look|search|find|filter)|could you (also )?(look|search|find|filter)|let'?s|change|instead|"
                        r"what about|how about|also|as well|too|actually|i (also )?(need|want|have|'ve got|got|own|prefer)|i'?d (like|prefer|rather))\b")


def _strip_markers(t: str) -> str:
    """开头的语气词剥掉（"wait, does it…" → "does it…"；"oh and it needs…" → "it needs…"）。"""
    t = t.strip()
    while True:
        m = re.match(r"^" + MARKERS + r"\b[\s,.!?;:-]*", t)
        if not m or not m.end():
            return t
        t = t[m.end():].strip()


def intent(text: str) -> str:
    """一句插话 / 追问是什么意思：resume / stop / next / repeat / questions / shorter / detail / rank / compare / agent_reply / reject / jump /
    update / question / decline / unclear。"question?" = 规则只是猜它是个问题（没有问句形式），模型可用时 Session 再问一次模型。"""
    t = text.lower().strip()
    words = re.findall(r"[a-z0-9']+", t)
    if not words or all(w in FILLERS for w in words):
        return "resume"
    if re.fullmatch(r"\W*(no|nah|nope)(,? (thanks|thank you|that'?s (all|it|fine)|i'?m (good|fine|okay|ok)|all good|need))?\W*", t):
        return "decline"
    core = _strip_markers(t)
    bare = re.sub(r"[\s,.!?]*\b(please|thanks|thank you|now|then|mate|for a sec(ond)?)\b[\s,.!?]*$", "", core).strip(" ,.!?;:")
    if not bare:
        if re.search(r"\b(wait|hang on|hold on)\b", t):
            return "stop"
        if re.search(r"\b(sorry|pardon)\b", t):
            return "repeat"
        return "resume"
    if re.fullmatch(STOP_BARE, bare):
        return "stop"
    if re.fullmatch(NEXT_BARE, bare):
        return "next"
    if re.fullmatch(RESUME_BARE, bare):
        return "resume"
    if REPEAT_RE.search(t) or bare in ("what", "sorry", "pardon", "huh", "again", "say again", "what was that"):
        return "repeat"
    if QUESTIONS_RE.search(t):
        return "questions"
    if SHORTER_RE.search(t):
        return "shorter"
    if DETAIL_RE.search(t):
        return "detail"
    if RANK_RE.search(t):
        return "rank"
    if COMPARE_RE.search(t):
        return "compare"
    if AGENT_RE.search(t):
        return "agent_reply"
    if REJECT_RE.search(t):
        return "reject"
    if JUMP_RE.search(t):
        return "jump"
    fields = parse_into(new_profile(), t)
    qform = bool(QUESTION_START.search(core)) or "?" in t
    if fields and (not qform or (UPDATE_CUE.search(t) and not ABOUT_PLACE.search(core))):
        return "update"
    if qform:
        return "question"
    return "question?" if len(words) > 2 else "unclear"


def classify(text: str) -> str:
    """旧名字（Pipecat 版、README 里叫它）：intent 的简化版，猜的问题也算问题。"""
    k = intent(text)
    return "question" if k == "question?" else k


INTENT_PROMPT = """HOMETRUTH_INTENT_V1
A renter is talking to a voice assistant that walks them through a shortlist of rental listings (first, second, third). Say what the renter means.
Intents: question (asks about a listing), update (changes or adds a need: budget, bedrooms, commute place, move-in date, pets, furnished, air con, bills, quiet, sunlight), next (skip to the next listing), stop (pause), resume (carry on), repeat (say the last thing again), shorter (wants less detail), detail (wants more detail on one listing), jump (go to a specific listing), reject (doesn't want a listing), compare (compare listings), questions (wants the list of questions for the agents), rank (which one to pick), agent_reply (passing on what an agent said), decline (no thanks), unclear.
Reply with one JSON object and nothing else: {"intent": "<one intent>", "place": "first|second|third|current|next|none"}"""
INTENTS = {"question", "update", "next", "stop", "resume", "repeat", "shorter", "detail", "jump", "reject", "compare", "questions", "rank", "agent_reply", "decline", "unclear"}


def intent_llm(text: str, context: str = "") -> Tuple[Optional[str], Optional[str]]:
    """规则没把握时问模型（2 s 内）：返回 (intent, place)；没模型、超时、答得不对 → (None, None)。"""
    if llm is None or not needs_llm_ready():
        return None, None
    try:
        res = llm.chat([{"role": "system", "content": INTENT_PROMPT}, {"role": "user", "content": f"Context: {context[:300]}\nRenter: {text[:300]}"}],
                       task="intent", temperature=0, max_tokens=40, retries=0, timeout=float(os.environ.get("INTENT_LLM_TIMEOUT", "2")))
    except Exception:  # noqa: BLE001
        return None, None
    obj = _json_object(res.text) or {}
    k = str(obj.get("intent") or "").strip().lower()
    place = str(obj.get("place") or "").strip().lower()
    return (k if k in INTENTS else None), (place if place in ("first", "second", "third", "current", "next") else None)


def find_listing(text: str, ranked: List[dict], current: Optional[str]) -> Optional[dict]:
    """话里说的是哪套：街名 > 第几套（first / second / third / last）> 下一套 / 上一套 > 这套（this / that / it）> 正在讲的那套 > 第一套。"""
    t = text.lower()
    for item in ranked:
        street = item["listing"]["street"].lower()
        name = re.sub(r"^\d+[a-z]?\s+", "", street)
        if name.split() and re.search(r"\b" + re.escape(name.split()[0]) + r"\b", t):
            return item
    shown = ranked[:TOP_N]
    for word, i in ORDINALS.items():
        if re.search(r"\b" + word + r"\b", t):
            if shown:
                return shown[i if i >= 0 else len(shown) - 1] if (i < len(shown)) else None
    cur = next((k for k, it in enumerate(shown) if it["listing"]["id"] == current), None)
    if re.search(r"\b(next|following) (one|place)\b|\bthe next\b", t) and cur is not None and cur + 1 < len(shown):
        return shown[cur + 1]
    if re.search(r"\b(previous|last) (one|place)\b|\bthe one before\b", t) and cur is not None and cur > 0 and not re.search(r"\bthe last one\b", t):
        return shown[cur - 1]
    for item in ranked:
        if item["listing"]["id"] == current:
            return item
    return ranked[0] if ranked else None


def listings_in(text: str, shown: List[dict]) -> List[dict]:
    """话里点名的几套（比较用），按说的顺序。"""
    t = text.lower()
    hits: List[Tuple[int, dict]] = []
    for item in shown:
        name = re.sub(r"^\d+[a-z]?\s+", "", item["listing"]["street"].lower())
        m = re.search(r"\b" + re.escape(name.split()[0]) + r"\b", t) if name.split() else None
        if m:
            hits.append((m.start(), item))
    for word, i in ORDINALS.items():
        for m in re.finditer(r"\b" + word + r"\b", t):
            j = i if i >= 0 else len(shown) - 1
            if 0 <= j < len(shown):
                hits.append((m.start(), shown[j]))
    out: List[dict] = []
    for _, it in sorted(hits, key=lambda h: h[0]):
        if all(o is not it for o in out):
            out.append(it)
    return out


COMPARATIVE_DIM = [("A1", r"cheap|pric|dear|expensive|rent|cost"), ("G1", r"close|near|far|commute|walk|bus|train|minutes"), ("B1", r"big|small|bedroom|size|space"),
                   ("E4", r"quiet|noise|noisy"), ("E2", r"sun|light|bright"), ("D1", r"new|modern|old|condition|renovat")]


def compare_dim_for(text: str) -> Optional[str]:
    t = text.lower()
    for d, pat in COMPARATIVE_DIM:
        if re.search(pat, t):
            return d
    return dim_for(text)


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
        self.declined: Set[str] = set()  # 反问时说了不知道的必填项（"I don't know when yet"）：不再问，开查时假设
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
        self.mode = tour_mode()  # brief（默认）/ full；说 "shorter" 之后是 headlines
        self.rejected: Set[str] = set()  # 租客说不要的房（"too far" / "not that one"），排名里跳过；有租客编号就记进 memory，下次也不推
        self.idx_seq = 0  # 句子编号一个会话里一直往上数：新计划的编号不会和客户端报回来的旧编号撞上
        self.emit_from = 0  # 最近一次 _emit_plan 从哪开始：客户端报的编号不在当前计划里（还没听完新计划的第一句）就从这里重讲
        self.extra_questions: List[str] = []  # 租客问了、我们答不上的（押金、车位…）：列问题清单时带上
        self.lock = threading.Lock()

    # ---- 欢迎回来（memory.py）----
    def attach_renter(self, renter_id: Any, prefill: bool = True) -> Optional[dict]:
        """认下这位租客：有记忆、还没开始说需求就把上次的需求预填进来；信念日志里翻过的格子（中介回复过的）也一并恢复。返回记忆（没有就 None）。"""
        self.renter = memory.clean_id(renter_id)
        self.memory = memory.load(self.renter) if self.renter else None
        if self.renter and not self.overrides:
            self.overrides = beliefs.overrides(self.renter)  # 上次中介说了的，这次还算数（beliefs.py 重放）
        if self.memory and self.memory.get("rejected"):
            self.rejected |= {str(x) for x in self.memory["rejected"]}
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
        extra, streets = self._welcome_extra(with_open=self.mode == "full")  # 简短播报：还在等的问题到那套房时会问，开场不念
        fact = phraser.welcome_question(self._welcome_summary(), extra)
        text = fact
        if self._nar() and self.mode == "full":
            must = [r"welcome|back|last time"] + [re.escape(street_word(s)) for s in streets]  # 离开时到的回复 / 还在等的问题得点到那套房
            text = narrator.line("welcome", fact, context=self._ctx(), required=narrator.nums(fact), question=True, must=must) or fact
        yield {"type": "ask", "fields": [], "text": text}
        yield self._said(text, fact, expects_answer=True, step="welcome")
        yield {"type": "done"}

    def _needs_memory(self) -> dict:
        return {"remembered": list(self.remembered)} if self.remembered else {}

    def _welcome_summary(self) -> str:
        if self.mode != "full":  # 简短播报：只点卧室、通勤、预算（10-28 前整段复述要念 20 秒）
            return phraser.short_summary(self.profile)
        return self.memory.get("summary") or phraser.summary(self.profile)

    def _welcome_extra(self, with_open: bool = True) -> Tuple[str, List[str]]:
        """开场多说的那句：离开时收件箱到了中介回复（先），不然就是上次还在等中介回答的问题。返回 (句子, 要点名的街名)。"""
        if self.renter:
            streets: List[str] = []
            for it in inbox.unread(self.renter):
                L = listing_by_id(it["listing_id"])
                if L and L["street"] not in streets:
                    streets.append(L["street"])
            if streets:
                return phraser.away_line(streets), streets
        open_items = [o for o in ((self.memory or {}).get("open") or []) if o.get("street")][:2] if with_open else []
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
        self.last_awaiting = self.awaiting  # 上一句问的是什么（收尾问了 "details on one, or the questions?" 时 "yes" / "the second one" 照它理解）
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
        if self.plan and not self.pending:  # 讲完了 / 停着的时候的追问：和打断同一套处理，只是不用接着讲
            kind = self._intent(text)
            yield from self._dispatch(kind, text, live=self.pos < len(self.plan))
            return
        pending, self.pending = self.pending, []
        if pending and intent(text) == "repeat":  # 反问时 "sorry?"：把问题再问一遍
            self.pending = pending
            q = phraser.ask_sentence(pending, vague=self._vague())
            yield {"type": "ask", "fields": list(pending), "text": q}
            yield self._said(q, q, expects_answer=True, step="repeat")
            yield {"type": "done"}
            return
        kind = "update"
        thinking_shown = False
        if kind == "update":  # 说需求、答反问：过渡句先出声，模型在线程里解析，规则校验兜底
            yield {"type": "state", "phase": "thinking", "label": "Analysing your request"}
            thinking_shown = True
            started = start_needs_llm(text, self.profile, pending) if needs_llm_ready() else None
            yield self._say(phraser.bridge(pending, variety=not self.deterministic), step="bridge")  # "Got it." / "Thanks."：不依赖解析结果，所以能先说
            if started is not None:
                changed, self.parse_meta = parse_needs_llm(text, self.profile, pending, started=started)
            else:
                changed, self.parse_meta = parse_into(self.profile, text, pending), rules_meta()
        self._restated(changed)
        self.declined |= set(declined_fields(text, [m for m in missing_required(self.profile) if m not in changed]))
        yield from self._search(changed, thinking_shown=thinking_shown)  # 没开查过时 changed 只给欢迎回来那句用（"this time budget 800"）

    # 开查：缺必填就问，否则搜 + 导览
    def _search(self, changed: Dict[str, str], thinking_shown: bool = False) -> Iterator[dict]:
        missing = missing_required(self.profile)
        if not thinking_shown:  # 模型解析那条路刚亮过同一个状态，不重复发
            yield {"type": "state", "phase": "thinking", "label": "Analysing your request"}
        to_ask = [m for m in missing if m not in self.declined]
        if to_ask and self.asked_rounds < MAX_ASK_ROUNDS:
            ask = to_ask[:ASK_PER_ROUND]
            self.asked_rounds += 1
            self.pending = ask
            q0 = polish_llm(phraser.ask_sentence(ask, vague=self._vague()), ask)
            q = q0
            yield {"type": "needs", "profile": self._profile_view(), "missing": missing, "asking": ask, **self._parse_view(), **self._needs_memory()}
            if self._nar() and self.mode == "full":  # 先复述听懂的部分（模板，立刻能说），模型同时把反问写得自然；写坏了就用模板
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
            brief = self.mode != "full"
            extra, streets = ("", []) if self.greeted else self._welcome_extra(with_open=not brief)  # 租客先开口的：离开时到的回复 / 还在等的问题也在这句里提
            fact = phraser.welcome_search(self.memory.get("summary") or "", changed, greeted=self.greeted, extra=extra, brief=brief)
            text = fact
            if self._nar() and not brief:
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
        elif self.mode != "full":  # 简短播报：需求已经在芯片上，不再复述；有假设就说出口，再说"在查"
            self.heard_said = False
            for x in sentences(phraser.brief_opening(missing, len(SOURCES), vague=self._vague() if "G1" in missing else None)):
                yield self._say(x, step="opening")
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
        self.ranked, self.excluded = self._rank()
        n_pass = len(self.ranked)
        if self.renter:  # 记住这次的需求、前几套和还在等中介答的问题（memory.py）：下次开场 "Welcome back…"
            self.memory = memory.save(self.renter, self.profile, [r["listing"]["id"] for r in self.ranked[:TOP_N]], self.request_text, self.id,
                                      open=open_loops(self.ranked, self.profile)) or self.memory
        nar = None
        if self._nar() and self.ranked and self.mode == "full":  # 三套房的台词请求现在就发出去，查来源、说开场的这几秒刚好够模型写（简短播报用模板，不调模型）
            shown = self.ranked[:TOP_N]
            legal_pending = any(it["cells"]["H1"]["status"] == "unknown" for it in shown)
            nar = narrator.start_tour(shown, self.profile, self.heard, TOUR_ORDER, best_question,
                                      phraser.wrap(len(shown), self.excluded, legal_pending), legal_pending, self.excluded, viewing_check=viewing_check)
        yield from self._sources(n_pass)
        self.quick = True
        self.plan = self._build(narration=nar)
        self.pos = 0
        yield {"type": "state", "phase": "touring", "label": "Walking you through"}
        yield from self._emit_plan()

    def _shortlist_line(self, n_pass: int) -> dict:
        if self.mode != "full":
            return self._say(phraser.brief_found(n_pass, min(TOP_N, n_pass)), step="shortlist")
        return self._say(phraser.found(n_pass, min(TOP_N, n_pass), variety=True) if self._nar() else phraser.shortlist(n_pass, min(TOP_N, n_pass)),
                         step="shortlist")

    def _sources(self, n_pass: int, announce: bool = True) -> Iterator[dict]:
        """查来源（页面左栏逐行打钩）。announce = 查到第二个来源时说"68 fit"那句（改需求重排时不说）。"""
        if zetaris_live.ENABLED:
            yield from self._sources_zetaris(n_pass, announce)
            return
        for i, src in enumerate(SOURCES):  # 没接 Zetaris（单测、没 key 的机器）：模拟查询，事件带 mock，页面照实标
            rid = _mock_id()
            stage = stage_of({"table": src["table"]})  # 来源面板按五段分组（listing / public / agent；viewing、signing 两段永远是空的）
            yield {"type": "source", "name": src["name"], "label": src["label"], "table": src["table"], "stage": stage, "status": "running", "request_id": rid}
            time.sleep(random.uniform(0.15, 0.35) if self.quick else random.uniform(0.4, 1.0))
            yield {"type": "source", "name": src["name"], "label": src["label"], "table": src["table"], "stage": stage, "status": "done", "request_id": rid,
                   "rows": src["rows"], "ms": random.randint(180, 2400), "mock": True}
            if i == 1 and announce:
                yield self._shortlist_line(n_pass)

    def _sources_zetaris(self, n_pass: int, announce: bool = True) -> Iterator[dict]:
        """真查：每个来源一条 SELECT 经 Zetaris（zetaris_live），只查这次的候选房，一起发出去，哪条先答哪行先亮。答完把排名里每条证据
        重新标上返回它的那条查询。超时的来源用它上一次成功的查询（页面标 earlier query），从没查成过的标 failed，证据留 local。"""
        ids = [r["listing"]["id"] for r in self.ranked] or [L["id"] for L in LISTINGS]
        by_name = {s["name"]: s for s in SOURCES}
        base = {n: {"type": "source", "name": n, "label": s["label"], "table": s["table"], "stage": stage_of({"table": s["table"]}), "via": "zetaris"}
                for n, s in by_name.items()}
        for n in by_name:
            yield dict(base[n], status="running", sql=zetaris_live.source_sql(n, ids))
        for i, r in enumerate(zetaris_live.run_sources(list(by_name), ids)):
            ev = dict(base[r["source"]], sql=r.get("sql"), mock=False)
            if r.get("ok"):
                ev.update(status="done", request_id=r["request_id"], rows=r["rows"], ms=r["ms"], queried_at=r["ts"])
            elif r.get("earlier"):
                e = r["earlier"]
                ev.update(status="done", cached=True, request_id=e["request_id"], rows=e["rows"], ms=e["ms"], sql=e["sql"], queried_at=e["ts"])
            else:
                ev.update(status="failed", error=str(r.get("error") or "")[:160])
            yield ev
            if i == 1 and announce:
                yield self._shortlist_line(n_pass)
        for item in self.ranked:
            for c in item["cells"].values():
                for e in c.get("evidence", []):
                    e.update(zetaris_live.stamp(e))

    def _emit_plan(self) -> Iterator[dict]:
        self.emit_from = self.pos
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
        if self.plan and self.plan[-1].get("step") == "wrap":
            self.awaiting = "wrap"  # 收尾问了 "details on one, or the questions?"："yes" / "the second one" 照这句理解
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
            q = cut_sentence or phraser.welcome_question(self._welcome_summary())
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
        """客户端报告最后一句完整说完的 idx；从它后面接着播（被切断的那句重播）。编号不在当前计划里（新计划还一句没听完）或没有编号：
        从最近一次开始讲的地方重来（emit_from）。"""
        if spoken_idx is not None:
            for i, ev in enumerate(self.plan):
                if ev["type"] == "say" and ev.get("idx") == spoken_idx:
                    self.pos = i + 1
                    return
        self.pos = min(self.emit_from, len(self.plan))

    def _interrupted(self, text: str, inter: dict) -> Iterator[dict]:
        self._rewind_to(inter.get("spoken_idx"))
        if inter.get("listing_id"):
            self.current = inter["listing_id"]
        kind = self._intent(text)
        yield {"type": "state", "phase": "thinking", "label": "One sec"}
        yield from self._dispatch(kind, text, live=self.pos < len(self.plan), cut=True)

    # ---- 插话 / 追问（10-28，docs/12）：每种意思一个处理；live = 导览还没讲完，处理完接着讲
    def _intent(self, text: str) -> str:
        k = intent(text)
        if k == "question?":  # 规则只是猜：问一次模型（2 s 内），不行就当问题
            k2, place = intent_llm(text, self._intent_context()) if not self.deterministic else (None, None)
            if k2:
                self._llm_place = place
                return k2
            k = "question"
        wrap = getattr(self, "last_awaiting", None) == "wrap"
        if k == "resume" and wrap and re.search(r"\b(yes|yeah|yep|sure|please|ok(ay)?)\b", text.lower()):
            return "questions"  # 收尾问的 "details on one, or the questions?" 答 "yes please"：给问题清单
        if k in ("question", "unclear") and len(re.findall(r"[a-z']+", text.lower())) <= 5 and listings_in(text, self.ranked[:TOP_N]) \
                and not dim_for(text) and not QUESTION_START.search(_strip_markers(text.lower())):
            return "detail" if wrap else "jump"  # 只说了是哪套（"the second one"）：讲完了 = 要细节，讲着 = 跳过去
        return k

    def _intent_context(self) -> str:
        shown = [phraser.street_name(it["listing"]["street"]) for it in self.ranked[:TOP_N]]
        cur = listing_by_id(self.current)
        return f"shortlist: {', '.join(shown)}; now talking about: {phraser.street_name(cur['street']) if cur else 'none'}"

    def _dispatch(self, kind: str, text: str, live: bool, cut: bool = False) -> Iterator[dict]:
        """cut = 这句是打断了正在说的话（客户端带了 interrupted）；不是打断的 "go on"（停着 / 中介回复后）直接接着讲，不先说 "Sure."。"""
        place = getattr(self, "_llm_place", None)
        self._llm_place = None
        if place and place not in ("current", "none") and not re.search(r"\b(first|second|third|next|last)\b", text.lower()):
            text = f"{text} (the {place} one)"  # 模型听出是哪套：补进话里，下面的 find_listing 照常认
        if kind == "resume":
            if live:
                if cut:
                    yield self._say("Sure.", step="resume")
                yield {"type": "state", "phase": "touring", "label": "Continuing"}
                yield from self._emit_plan()
            else:
                yield from self._idle(self._say("That was all of them. Want details on one, or the questions for the agents?", step="resume", expects_answer=True))
            return
        if kind == "next":
            nxt = next((i for i in range(self.pos, len(self.plan)) if self.plan[i]["type"] == "card"), None) if live else None
            if nxt is None:
                wrap = next((i for i in range(self.pos, len(self.plan)) if self.plan[i].get("step") == "wrap"), None) if live else None
                if wrap is None:
                    yield from self._idle(self._say("That was the last one. Want details on one, or the questions for the agents?", step="next", expects_answer=True))
                    return
                self.pos = wrap
                yield self._say("That was the last one.", step="next")
            else:
                self.pos = nxt
                yield self._say(phraser.pick("next", not self.deterministic), step="next")
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
            return
        if kind == "stop":
            yield self._say("Okay, I'll pause here. Say continue when you're ready.", step="stop")
            yield {"type": "state", "phase": "idle", "label": "Paused"}
            yield {"type": "done"}
            return
        if kind == "decline":
            yield from self._idle(self._say("No problem. I'm here if you need anything else.", step="decline"))
            return
        if kind == "repeat":
            yield from self._repeat()
            return
        if kind == "shorter":
            yield from self._shorter(live)
            return
        if kind == "detail":
            yield from self._detail(text, live)
            return
        if kind == "jump":
            yield from self._jump(text, live)
            return
        if kind == "reject":
            yield from self._reject(text)
            return
        if kind == "agent_reply":
            yield from self._agent_reply(text)
            return
        if kind == "update":
            yield from self._update(text, live)
            return
        if kind == "questions":
            yield from self._after(self._questions(), live)
            return
        if kind == "rank":
            yield from self._after(iter([self._say(phraser.ranking_plain(self.ranked[:TOP_N]), step="answer")]), live)
            return
        if kind == "compare":
            yield from self._after(self._compare(text), live)
            return
        if kind == "question":
            yield from self._after(self._answer(text), live)
            return
        yield self._say("Sorry, I didn't catch that." + (" I'll carry on; interrupt me any time." if live else " Say it another way?"), step="unclear")
        if live:
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
        else:
            yield {"type": "state", "phase": "idle", "label": "Ready"}
            yield {"type": "done"}

    def _idle(self, *events: dict) -> Iterator[dict]:
        for ev in events:
            yield ev
        self._mark_finished()
        yield {"type": "state", "phase": "idle", "label": "Ready"}
        yield {"type": "done"}

    def _after(self, answer: Iterator[dict], live: bool) -> Iterator[dict]:
        """答完：导览还没讲完就说一句 "back to …" 接着讲（下一句本来就是新一套的开头就不用说），讲完了就停。"""
        yield from answer
        if live and self.pos < len(self.plan):
            nxt = next((ev for ev in self.plan[self.pos:] if ev["type"] == "say"), None)
            cur = next((i for i, it in enumerate(self.ranked[:TOP_N]) if it["listing"]["id"] == self.current), None)
            if cur is not None and nxt is not None and not re.fullmatch(r"L\d+", nxt.get("step") or "") and nxt.get("step") != "wrap":
                yield self._say(phraser.back(cur, variety=not self.deterministic), step="back")
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
            return
        self._mark_finished()
        yield {"type": "state", "phase": "idle", "label": "Ready"}
        yield {"type": "done"}

    def _mark_finished(self) -> None:
        """导览讲完以后的每一轮都以同一个问题收尾（details on one, or the questions?）："yes" / "the second one" 照它理解。"""
        if self.plan and self.pos >= len(self.plan):
            self.awaiting = "wrap"

    def _build(self, narration: Optional[Dict[int, Future]] = None, only: Optional[Set[str]] = None, mode: Optional[str] = None) -> List[dict]:
        plan = build_tour(self.ranked, self.profile, self.excluded, narration=narration, mode=mode or self.mode, start_idx=self.idx_seq, only=only,
                          variety=not self.deterministic)
        self.idx_seq = max([ev["idx"] for ev in plan if ev["type"] == "say" and ev.get("idx") is not None] + [self.idx_seq - 1]) + 1
        return plan

    def _segment(self, item: dict, mode: str) -> List[dict]:
        """一套房的事件（brief / full），编号接着会话往上数：插进计划里讲（tell me more / go back to）。"""
        i = next((k for k, it in enumerate(self.ranked[:TOP_N]) if it["listing"]["id"] == item["listing"]["id"]), 0)
        plan: List[dict] = []
        idx = [self.idx_seq]

        def say(text: str, step: str, fut: Optional[Future] = None, key: Optional[str] = None) -> None:
            if text:
                plan.append({"type": "say", "idx": idx[0], "text": text, "step": step})
                idx[0] += 1
        if mode == "full":
            _full_events(plan, say, i, len(self.ranked[:TOP_N]), item, self.profile)
        else:
            _brief_events(plan, say, i, item, self.profile, {}, variety=not self.deterministic)
        self.idx_seq = idx[0]
        return plan

    def _say_n(self, text: str, step: str) -> dict:
        """插进计划里的句子也带编号（被打断时客户端报得回来）。"""
        ev = {"type": "say", "idx": self.idx_seq, "text": text, "step": step}
        self.idx_seq += 1
        return ev

    def _segment_end(self, k: int) -> int:
        """计划里从 k 开始这一套房的事件到哪结束（下一张卡、beat 或收尾那句之前）。"""
        j = k + 1
        while j < len(self.plan) and self.plan[j]["type"] not in ("card", "beat") and self.plan[j].get("step") != "wrap":
            j += 1
        return j

    def _says_of(self) -> Dict[str, List[int]]:
        says_of: Dict[str, List[int]] = {}
        card = None
        for k, ev in enumerate(self.plan):
            if ev["type"] == "card":
                card = ev["listing"]["id"]
                says_of.setdefault(card, [])
            elif ev["type"] == "say" and card and ev.get("step") != "wrap":
                says_of[card].append(k)
        return says_of

    def _heard_ids(self) -> Set[str]:
        """这几套的三句（或逐格）已经全部讲完、客户端也播完了：改需求后不再重讲。"""
        return {lid for lid, ks in self._says_of().items() if ks and max(ks) < self.pos}

    def _started_ids(self) -> Set[str]:
        """这几套至少开头那句已经播过了（被打断时正在讲的那套）。"""
        return {lid for lid, ks in self._says_of().items() if ks and min(ks) < self.pos}

    def _rank(self) -> Tuple[List[dict], int]:
        ranked, excluded = rank(self.profile, self.overrides)
        if self.rejected:
            ranked = [r for r in ranked if r["listing"]["id"] not in self.rejected]
        return ranked, excluded

    def _vague(self) -> Optional[str]:
        """租客说了个量不了通勤的地方（the beach / the uni / work）：反问时直接给能量的几个地方。"""
        if self.profile.get("anchor"):
            return None
        for t in reversed(self.heard):
            m = re.search(VAGUE_PLACE, t.lower())
            if m:
                return m.group(1)
        return None

    def _repeat(self) -> Iterator[dict]:
        """"Sorry, what was that?"：从最后一句完整说完的那句重说（被切断的那句跟着）。"""
        k = next((j for j in range(min(self.pos, len(self.plan)) - 1, -1, -1) if self.plan[j]["type"] == "say"), None)
        if k is None:
            yield from self._idle(self._say("Sorry, I haven't said anything about the places yet.", step="repeat"))
            return
        self.pos = k
        yield {"type": "state", "phase": "touring", "label": "Continuing"}
        yield from self._emit_plan()

    def _shorter(self, live: bool) -> Iterator[dict]:
        """"Short version" / "too long"：逐格 → 三句，三句 → 每套一句；剩下没讲的照新讲法重排。"""
        self.mode = {"full": "brief", "brief": "headlines"}.get(self.mode, "headlines")
        line = "Sure, just the headlines." if self.mode == "headlines" else "Sure, I'll keep it short."
        if not live:
            yield from self._idle(self._say(line + " Want details on one, or the questions for the agents?", step="shorter", expects_answer=True))
            return
        k = next((j for j in range(self.pos, len(self.plan)) if self.plan[j]["type"] == "card"), None)
        later = [ev["listing"]["id"] for ev in self.plan[k:] if ev["type"] == "card"] if k is not None else []
        rest = self._build(only=set(later)) if later else [ev for ev in self.plan[self.pos:] if ev.get("step") == "wrap"]
        self.plan = self.plan[:self.pos] + [self._say_n(line, "shorter")] + rest
        yield {"type": "state", "phase": "touring", "label": "Continuing"}
        yield from self._emit_plan()

    def _detail(self, text: str, live: bool) -> Iterator[dict]:
        """"Tell me more (about the second one)"：那套逐格讲一遍（插在这里），讲完接着原来的。说的是正在讲的这套：这套剩下的三句不再说。"""
        item = find_listing(text, self.ranked, self.current)
        if item is None:
            yield from self._idle(self._say("I don't have a shortlist yet. Tell me what you're after and I'll search.", step="answer"))
            return
        lid = item["listing"]["id"]
        seg = self._segment(item, "full")
        k = next((j for j in range(self.pos, len(self.plan)) if self.plan[j]["type"] == "card" and self.plan[j]["listing"]["id"] == lid), None)
        if k is not None:  # 这套还没讲到（或刚开头就被打断）：后面那三句不用再讲了
            del self.plan[k:self._segment_end(k)]
            if k > self.pos and self.plan[k - 1]["type"] == "beat":
                del self.plan[k - 1]
        elif live and lid == self.current:  # 正讲到一半：这套剩下的那几句不说了
            j = next((j for j in range(self.pos, len(self.plan)) if self.plan[j]["type"] in ("card", "beat") or self.plan[j].get("step") == "wrap"), len(self.plan))
            del self.plan[self.pos:j]
        self.plan[self.pos:self.pos] = seg + ([self.plan_beat()] if live and self.pos < len(self.plan) else [])
        yield {"type": "state", "phase": "touring", "label": "Here's the detail"}
        yield from self._emit_plan()

    @staticmethod
    def plan_beat() -> dict:
        return {"type": "beat", "ms": BEAT_MS}

    def _jump(self, text: str, live: bool) -> Iterator[dict]:
        """"Go back to the first one" / "tell me about the third"：那套的三句挪到这里讲（讲过的就再讲一遍），讲完接着原来的。"""
        item = find_listing(text, self.ranked, self.current)
        if item is None:
            yield from self._idle(self._say("I don't have a shortlist yet. Tell me what you're after and I'll search.", step="answer"))
            return
        lid = item["listing"]["id"]
        k = next((j for j in range(self.pos, len(self.plan)) if self.plan[j]["type"] == "card" and self.plan[j]["listing"]["id"] == lid), None)
        if k is not None:  # 还没讲到：整段挪过来（后面就不会再讲一遍）
            end = self._segment_end(k)
            seg = self.plan[k:end]
            del self.plan[k:end]
            if k > self.pos and self.plan[k - 1]["type"] == "beat":
                del self.plan[k - 1]  # 它前面那个停顿也不要了
        else:
            seg = self._segment(item, "brief" if self.mode != "full" else "full")
        back = []
        if live and self.pos < len(self.plan):
            cur = next((i for i, it in enumerate(self.ranked[:TOP_N]) if it["listing"]["id"] == self.current), None)
            nxt = next((ev for ev in self.plan[self.pos:] if ev["type"] == "say"), None)
            if cur is not None and nxt is not None and not re.fullmatch(r"L\d+", nxt.get("step") or "") and nxt.get("step") != "wrap" and self.current != lid:
                back = [self.plan_beat(), self._say_n(phraser.back(cur, variety=not self.deterministic), "back")]
            else:
                back = [self.plan_beat()]
        self.plan[self.pos:self.pos] = seg + back
        yield {"type": "state", "phase": "touring", "label": "Continuing"}
        yield from self._emit_plan()

    def _reject(self, text: str) -> Iterator[dict]:
        """"Too far" / "not that one"：划掉，记住（有租客编号就跨会话记），重排；补进来的那套和还没讲的照讲。"""
        item = find_listing(text, self.ranked, self.current)
        if item is None:
            yield from self._idle(self._say("Which one should I drop?", step="reject", expects_answer=True))
            return
        L = item["listing"]
        self.rejected.add(L["id"])
        if self.renter:
            memory.add_rejected(self.renter, L["id"])
        yield self._say(phraser.dropped_line(L), step="reject")
        yield from self._retune({}, dropped_by_renter=L["id"])

    def _update(self, text: str, live: bool) -> Iterator[dict]:
        """导览中 / 讲完后改需求：先 "Okay."（模型同时解析），改到了就 _retune（不从头念）；没改到但说的和现在一样就确认；都不是就当问题答。"""
        started = start_needs_llm(text, self.profile) if needs_llm_ready() else None
        yield self._say(phraser.bridge([], interrupted=True, variety=not self.deterministic), step="bridge")  # "Okay."：先出声，模型同时解析
        if started is not None:
            changed, self.parse_meta = parse_needs_llm(text, self.profile, started=started)
        else:
            changed, self.parse_meta = parse_into(self.profile, text), rules_meta()
        self._restated(changed)
        if changed:
            yield from self._retune(changed)
            return
        same = {k: v for k, v in rules_fields(text).items() if v not in (None, [], {}) and k in ("budget", "bedrooms", "anchor", "pets", "move_in")
                and self.profile.get(k) == v}
        if same:
            words = {"budget": lambda v: f"under {v} a week", "bedrooms": lambda v: phraser.beds_phrase(v), "anchor": lambda v: f"near {v}",
                     "pets": lambda v: v.get("text", "pets") if isinstance(v, dict) else str(v), "move_in": lambda v: v.get("text", "") if isinstance(v, dict) else str(v)}
            line = phraser.confirm_same({k: words[k](v) for k, v in same.items()})
        else:
            line = "I didn't catch a change there." + (" I'll carry on; interrupt me any time." if live else "")
        yield self._say(line, step="unclear")
        if live:
            yield {"type": "state", "phase": "touring", "label": "Continuing"}
            yield from self._emit_plan()
        else:
            yield {"type": "state", "phase": "idle", "label": "Ready"}
            yield {"type": "done"}

    def _retune(self, changed: Dict[str, str], dropped_by_renter: Optional[str] = None) -> Iterator[dict]:
        """改需求 / 划掉一套之后：不复述、不报来源、不从头念。说一句"记下了"，再说前三名怎么变、新条件在前三名里的情况，
        然后只讲没听完的（新进来的、还没讲到的、被打断时正在讲的）。"""
        old = [it["listing"]["id"] for it in self.ranked[:TOP_N]]
        heard = self._heard_ids() if self.plan else set()
        started = (self._started_ids() - heard) if self.plan else set()
        yield {"type": "needs", "profile": self._profile_view(), "missing": missing_required(self.profile), **self._parse_view(), **self._needs_memory()}
        if changed:
            yield self._say(phraser.noted(changed), step="update")
        yield {"type": "state", "phase": "searching", "label": "Checking sources"}
        self.ranked, self.excluded = self._rank()
        if self.renter:
            self.memory = memory.save(self.renter, self.profile, [r["listing"]["id"] for r in self.ranked[:TOP_N]], self.request_text, self.id,
                                      open=open_loops(self.ranked, self.profile)) or self.memory
        yield from self._sources(len(self.ranked), announce=False)
        shown = self.ranked[:TOP_N]
        for i, it in enumerate(shown):  # 前台的卡片先按新排名摆好（讲到哪套再点亮哪套）
            yield {"type": "card", "listing": card_payload(it["listing"], it["cells"], i + 1)}
        new = [it["listing"]["id"] for it in shown]
        street = {it["listing"]["id"]: it["listing"]["street"] for it in shown}
        for lid in old:
            if lid not in street:
                L0 = listing_by_id(lid)
                if L0:
                    street[lid] = L0["street"]
        dropped = [street[x] for x in old if x not in new and x != dropped_by_renter]
        added = [street[x] for x in new if x not in old]
        lines = []
        if not shown:
            lines.append("Nothing passes the basics with that. Want to loosen something?")
        else:
            if changed or dropped or added:
                lines.append(phraser.shortlist_diff(dropped, added, same_order=(old == new), new_top=street.get(new[0]) if new and old and new[0] != old[0] else None)
                             if (dropped or added or old != new) else "Same top three.")
            for d in self._new_dims(changed):
                yes = [it["listing"]["street"] for it in shown if (it["cells"].get(d) or {}).get("status") == "supported"]
                no = [it["listing"]["street"] for it in shown if (it["cells"].get(d) or {}).get("status") != "supported"]
                lines.append(phraser.condition_line(d, yes, no))
        for ln in lines:
            yield self._say(ln, step="diff")
        if not shown:
            yield {"type": "state", "phase": "idle", "label": "Ready"}
            yield {"type": "done"}
            return
        todo = {x for x in new if x not in heard}
        self.plan = self._build(only=todo) if todo else [self._say_n("Want details on one, or the questions for the agents?", "wrap")]
        card = None
        for ev in self.plan:  # 被打断时正在讲的那套：开头那句刚听过，换成一句短的（"Fenwick Street is still the top pick."），不原样再念（模拟顾客 P03）
            if ev["type"] == "card":
                card = ev["listing"]["id"]
            elif ev["type"] == "say" and card in started and re.fullmatch(r"L\d+", ev.get("step") or ""):
                ev["text"] = phraser.rank_again(street[card], new.index(card) + 1, old.index(card) + 1 if card in old else None)
                started.discard(card)
        self.pos = 0
        yield {"type": "state", "phase": "touring", "label": "Walking you through"}
        yield from self._emit_plan()

    def _new_dims(self, changed: Dict[str, str]) -> List[str]:
        """这次改动新加的、要在前几套里核的条件（furnished、air con、宠物…）：确认那句说"只有 Alder Lane 有家具"。"""
        out = []
        if "pets" in changed and (self.profile.get("pets") or {}).get("has"):
            out.append("J1")
        if "extras" in changed:
            out += [e["dim"] for e in self.profile["extras"] if e["label"].lower() == changed["extras"]]
        return out[:2]

    def _note_question(self, topic: str) -> None:
        if topic and topic not in self.extra_questions:
            self.extra_questions.append(topic)

    def _questions(self) -> Iterator[dict]:
        """"Draft the questions"：每套最该问中介的一句 + 租客问过、我们答不上的 + 法定必问（犯罪披露）。页面也收到一份（questions 事件）。"""
        shown = self.ranked[:TOP_N]
        items, rows = [], []
        for it in shown:
            bq = best_question(it["cells"])
            if bq:
                q = phraser.q_short(bq[0], bq[1], self.profile, it["listing"])
                items.append((phraser.street_name(it["listing"]["street"]), q))
                rows.append({"listing_id": it["listing"]["id"], "street": it["listing"]["street"], "dim": bq[0], "question": q})
        legal = any(it["cells"]["H1"]["status"] == "unknown" for it in shown)
        yield {"type": "questions", "items": rows, "extra": list(self.extra_questions), "legal": legal}
        for x in sentences(phraser.questions_text(items, legal, self.extra_questions)):
            yield self._say(x, step="questions")

    def _compare(self, text: str) -> Iterator[dict]:
        shown = self.ranked[:TOP_N]
        if not shown:
            yield self._say("I don't have a shortlist yet. Tell me what you're after and I'll search.", step="answer")
            return
        targets = listings_in(text, shown)
        if len(targets) < 2 and re.search(r"\b(this|that|it)\b", text.lower()):
            cur = next((it for it in shown if it["listing"]["id"] == self.current), None)
            if cur is not None and all(t is not cur for t in targets):
                targets = [cur] + targets
        d = compare_dim_for(text)
        if len(targets) >= 2 and not d:
            line = phraser.compare_pair(targets[0], targets[1], self.profile)
        elif d:
            line = phraser.compare_dim(d, targets if len(targets) >= 2 else shown, self.profile)
        else:
            line = phraser.ranking_plain(shown)
        for x in sentences(line):
            yield self._say(x, step="answer")

    def _answer(self, text: str) -> Iterator[dict]:
        """答问：先说结论再给一句依据（answer_plain）。押金：挂牌没写就说 NSW 上限。"下一套便宜吗"：和正在讲的这套比。答不上的记进问题清单。"""
        t = text.lower()
        item = find_listing(text, self.ranked, self.current)
        if item is None:
            yield self._say("I don't have a shortlist yet. Tell me what you're after and I'll search.", step="answer")
            return
        L, cells = item["listing"], item["cells"]
        if re.search(r"\b(bond|deposit)\b", t):
            self._note_question("the bond")
            for x in sentences(phraser.bond_line(L)):
                yield self._say(x, step="answer")
            return
        d = dim_for(text)
        cur = next((it for it in self.ranked[:TOP_N] if it["listing"]["id"] == self.current), None)
        if re.search(r"\b(cheaper|dearer|pricier|more expensive|closer|nearer|further|farther|bigger|smaller)\b", t) and cur is not None and cur is not item:
            for x in sentences(phraser.comparative(cur, item, compare_dim_for(text) or "", self.profile) or phraser.compare_pair(cur, item, self.profile)):
                yield self._say(x, step="answer")
            return
        if d and d in cells:
            c = cells[d]
            yield {"type": "highlight", "listing_id": L["id"], "dim": d, "status": c["status"]}
            yield {"type": "evidence", "listing_id": L["id"], "dim": d, "label": c["label"], "status": c["status"], "items": c["evidence"]}
            for x in sentences(phraser.answer_plain(d, c, L, self.profile)):
                yield self._say(x, step="answer")
            return
        topic = phraser.LABEL_PLAIN.get(d) if d else None
        if topic is None:
            m = re.search(r"\b(parking|car space|garage|storage|gym|pool|lift|elevator|balcony|laundry|dishwasher|internet|nbn|lease|inspection|viewing|heating|"
                          r"washing machine|dryer|security|intercom)\b", t)
            topic = m.group(1) if m else None
        if topic:
            self._note_question(f"{topic} at {phraser.street_name(L['street'])}")
            yield self._say(phraser.no_fact_plain(L, topic), step="answer")
            return
        yield self._say(f"I don't have an answer to that for {phraser.street_name(L['street'])}. Try asking about rent, the commute, pets or what's included.", step="answer")

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
        before = [it["listing"]["id"] for it in rank(self.profile, prev)[0] if it["listing"]["id"] not in self.rejected][:TOP_N]
        self.overrides.setdefault(L["id"], {})[dim] = override
        self.ranked, self.excluded = self._rank()
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
            street_of = lambda lid: next(it for it in self.ranked if it["listing"]["id"] == lid)["listing"]["street"]
            new_in = [lid for lid in after if lid not in before]
            if after[0] != before[0]:
                consequence = f"That moves {street_of(after[0])} to the top."
            elif L["id"] in before and L["id"] not in after and new_in:  # 掉出前三，有一套补进来（以前这里说 "The order stays the same."，不对）
                consequence = f"That drops it out of the top {len(after)}; {street_of(new_in[0])} comes in."
            elif L["id"] in after:
                consequence = f"It is now number {after.index(L['id']) + 1}."
            else:
                consequence = "The order changes."
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
            self.plan = self._build()
            self.emit_from = 0
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
        self.plan = self._build()
        if tour_done:
            self.pos = self.emit_from = len(self.plan)
            return
        card_pos = next((k for k, ev in enumerate(self.plan) if ev["type"] == "card" and ev["listing"]["id"] == cur_id), None)
        if card_pos is None:  # 这套房重排后掉出前三：当作讲完
            self.pos = self.emit_from = len(self.plan)
            return
        k = next((k for k in range(card_pos + 1, len(self.plan))
                  if self.plan[k]["type"] == "card"
                  or (self.plan[k]["type"] == "say" and (self.plan[k]["step"].split(".", 1)[1] if "." in self.plan[k]["step"] else "intro") not in spoken)),
                 len(self.plan))
        while k - 1 > card_pos and self.plan[k - 1]["type"] in ("highlight", "evidence"):
            k -= 1  # 把下一格前面的高亮 / 证据事件也带上
        self.pos = self.emit_from = k

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
