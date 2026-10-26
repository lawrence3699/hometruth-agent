# -*- coding: utf-8 -*-
"""台词交给模型写（10-25）。每句话仍然来自一个格子：phraser 的模板句就是"事实"，Nemotron 只负责把它说得像人。

规矩（和需求解析一样"模型写、规则审"）：
  - 输入是一列事实（键 + 状态 + 模板句）+ 房源/需求里的数字 + 租客原话；模型按"自然口语、短句、不加事实、数字照抄"逐条重写，
    回一个 JSON：键就是 reply_keys 里的键，值是一行台词。
  - 每行校验：数字只能来自事实（一个不能多），关键数字一个不能少；状态词必须在（推断 / 冲突 / 未知各有一组词，
    有支持的不许出现"unknown / conflict / likely"这类词）；维度关键词必须在；不许 markdown、换行、太长；
    不许以 "Supported:" 这种标签开头；不许把租客的话原样复述；原样照抄模板算"没写"（用模板，不记 by: llm）。
  - 校验不过、模型没回、超时 → 用模板句。模型不可用 → 全模板（事件流和原来逐字一样）。
  - 导览的三套房各一次调用，开查时就在线程里发出去，讲到那句话时才取结果（取不到就模板），所以几乎不等。
  - 模型回的 JSON 结构不听话（格子平铺在顶层、套一层 cells、值是 {fact: …}）都认（_flatten）。
环境变量：NARRATION_LLM=auto|0（默认 auto：有模型就用）、NARRATION_LLM_TIMEOUT（秒，默认 6；单句的小调用 2.5）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import phraser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.append(str(ROOT / "src"))
try:
    from llm import provider as llm
except Exception:  # noqa: BLE001
    llm = None

log = logging.getLogger("hometruth.narrator")
if not log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s narrator %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)

POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="narrate")
STATS = {"calls": 0, "accepted": 0, "rejected": 0, "copied": 0, "failed": 0, "timeouts": 0}

SYSTEM = """HOMETRUTH_NARRATE_V1
You are HomeTruth, a rental check-up assistant talking out loud to a renter in Sydney. You get FACTS: template sentences, each one a checked fact about one listing, some with a status: supported, inferred, conflict or unknown. Say each one again as natural spoken English, the way a sharp, friendly agent walks someone through a place.
Rules:
- One line per key, same meaning, same status, same evidence. Keep the things the fact names (the listing, the by-laws, the agent's reply, the floor plan, the transit table, the agent) and never add facts, places, prices, dates, sources, objects or reasons that are not in the fact. Keep every number as digits exactly as given (write 14, not fourteen; 1 Nov, not November first), and add no other numbers.
- Rewrite the whole sentence in your own words: keep the meaning, change the structure. A line that repeats the fact word for word, or just tacks a word onto it, doesn't count. Use a different sentence shape for each line; don't start two lines the same way.
- Never use the bare words supported, inferred, conflict or unknown as a tag, and never start a line with a label like "Supported:" or "Pets:". Say what the status means, in your own words each time: supported means it checks out and the materials back it up; inferred means you're reading between the lines and it's not confirmed; conflict means it clashes with what the renter asked; unknown means you can't confirm it from the materials, so it's one to ask the agent. Each fact comes with a status_hint.
- Bad: "Two bedrooms, as asked, supported." Bad: "Rent is 890 a week, inside your 900 budget, supported." Bad: "Pets: supported. The by-laws allow pets."
- One or two short sentences per line, up to about 25 words, contractions, no lists, no emojis, no headings, no quotes. Now and then refer briefly to what the renter said, but never repeat their words back as a question.
- Keys: "intro" keeps the position (first, second...), street, suburb and weekly rent. "special" says what sets this place apart. "question" says this is the best thing to ask the agent, then the question itself, ending with "?". "viewing" says there is nothing to ask the agent on this one, but names what to look at or listen for at the viewing. "next" is a hand-over of at most 8 words. "wrap" closes the tour and still offers to draft the questions or compare. "ask" asks every item listed in one friendly question. "ack" confirms the changed need and says you'll re-rank; it is not a question. "answer" answers the renter's question using the fact. "change" names the place and says what the agent's reply changed and what follows from it. "welcome" greets a renter who has been here before, repeats what they asked for last time and asks whether anything has changed, ending with "?". "back" greets a renter who has been here before and repeats what they asked for this time (same as last time, or what changed, from the fact), then says you are checking the sources now. Two statements, no question mark at all: they already told you whether anything changed, so do not ask. Never say re-rank or re-check, because nothing has been ranked yet.
- Reply with ONE JSON object: every key in "reply_keys", each value one line of text. Nothing before or after the JSON."""

STATUS_RE = {
    "inferred": r"\b(infer|inferr?ed|inferring|likely|probably|seems?|looks? like|suggests?|appears?|reading between|not confirmed|unconfirmed|"
                r"my guess|guess(ing)?|lean(ing)?|assum\w*|i'?d say|i think|can'?t be sure|nobody'?s confirmed|no one'?s confirmed|hasn'?t (been )?confirmed|"
                r"haven'?t confirmed|only infer|best guess|reading (it|that) as|i reckon|chances are)\b",
    "conflict": r"\b(conflict|doesn'?t match|mismatch|clash|contradicts?|over your|above your|misses|short of|outside|beyond|not what you asked|doesn'?t fit|"
                r"unless|falls short|later than|too (late|far|small|expensive)|says no|rules? (it|that) out|snag|catch|doesn'?t work|won'?t work|after your|"
                r"past your|over budget|above budget|more than your|exceeds|doesn'?t line up|at odds|but you (asked|wanted|need)|not (quite )?what you|"
                r"problem|issue|against|doesn'?t (meet|suit)|not (a )?(match|fit)|out of|only \w+ bedroom)\b",
    "unknown": r"\b(unknown|can'?t confirm|cannot confirm|not confirmed|unconfirmed|no record|nothing (in|on|about)|doesn'?t say|don'?t have|haven'?t got|"
               r"no (row|data|info|information)|need to ask|to confirm|not covered|unclear|can'?t tell|yet to|still open|open question|haven'?t (seen|found|got)|"
               r"can'?t say|no mention|not mentioned|doesn'?t mention|nothing (mentions|covers|says)|silent on|no word|not (yet )?known|one to ask|"
               r"ask the agent|worth asking|need to check|check with|not sure|unsure|nothing on|no way to (tell|know)|up in the air|still unknown|"
               r"no checked fact|no fact|not (been )?checked|haven'?t checked|hasn'?t been checked|no answer (yet|on)|nothing checked)\b",
}
NOT_SUPPORTED_RE = r"\b(unknown|can'?t confirm|cannot confirm|not confirmed|unconfirmed|conflict|mismatch|clash|unclear|infer|inferred|inferring|likely|probably|doesn'?t match|my guess|guessing)\b"
MONTH_RE = r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DIM_WORDS = {
    "A1": r"rent|budget|week|\$", "B1": r"bedroom|studio|\bbeds?\b|room", "G1": r"minute|\bmins?\b|commute|bus|train|walk|station|get(s)? (you )?to|trip|ride|transit|light rail",
    "A4": r"available|move|from|date|" + MONTH_RE, "J1": r"\bpets?\b|\bcats?\b|\bdogs?\b|animal", "C1": r"air[- ]?con|cooling|split|a\.?c\b|conditioning",
    "A6": r"bill|utilit|includ", "C2": r"furnish|furniture|staged|staging|sofa|couch|photo", "C3": r"stove|cooktop|hob|gas|induction|electric|ceramic",
    "E4": r"quiet|noise|noisy|traffic|main road", "E2": r"sun|light|bright|orientation|north|east|west|south|aspect|facing|june|december|winter|summer",
    "H1": r"disclosure|crime|violent|legal|must-ask|sign",
    "D1": r"condition|dated|renovat|modern|new|old|worn|tired|finish|benchtop|tiles|carpet|kitchen|bathroom|photo",
    "K1": r"number|four|\b4\b|level|unit|digit", "K2": r"through|entry|door|balcony|window|line|straight", "K3": r"door|bathroom|toilet|kitchen|stove|cooktop|entry",
    "K4": r"outline|corner|square|shape|rectang|notch",
}
GENERIC_BAD = re.compile(r"[*#`\n\r\[\]{}<>]|as an ai|language model|here'?s what|here is what|json", re.I)
LABEL_PREFIX = re.compile(r"^(supported|inferred|conflict|unknown|status|fact|note)\s*[:\-–]", re.I)
TAG_RE = re.compile(r"(,|;|\band\b)\s*(supported|inferred|conflict|unknown)\s*([,.;!]|$)", re.I)  # "…, supported." 这种把状态词当标签贴在句尾的写法
STATUS_HINT = {"supported": "it checks out, the materials back it up", "inferred": "you're inferring this, it's not confirmed",
               "conflict": "it clashes with what the renter asked", "unknown": "you can't confirm it from the materials; one to ask the agent"}
DIM_KEY = re.compile(r"^[A-K]\d$")
QUESTION_WORDS = r"agent|ask|question|check|confirm|worth|find out|in writing|get (it|that) in writing"
STOP = set("""a an the and but or so that this it its is are was were be been being your you yours from for with which what who whom when where there here
have has had not only just also into onto than then them they their about after before under over out one two three four five six seven eight nine ten
all any each every some such very will would can could should may might must shall do does did done get got gets going go goes come comes came make makes
made say says said still yet already like well much many more most less least own same other another both either neither now right okay let lets place
i'm i've i'd it's that's there's here's you're we'll we've don't doesn't didn't can't won't isn't aren't wasn't weren't thing things""".split())

# 数字写成了英文词（fourteen、seven hundred、the twenty-fourth of November）：校验前先换回数字；个位数（one…nine）太常见（one of the grounds），只在月份旁边换
_U = dict(zip("one two three four five six seven eight nine".split(), range(1, 10)))
_T = dict(zip("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(10, 20)))
_D = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_OU = dict(zip("first second third fourth fifth sixth seventh eighth ninth".split(), range(1, 10)))
_OT = dict(zip("tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split(), range(10, 20)))
_OD = {"twentieth": 20, "thirtieth": 30}
_UW, _TW, _DW = "|".join(_U), "|".join(_T), "|".join(_D)
_SMALL = rf"(?:(?:{_DW})[-\s](?:{_UW})|{_TW}|{_DW}|{_UW})"
_ORD = rf"(?:(?:{_DW})[-\s](?:{'|'.join(_OU)})|{'|'.join(_OT)}|{'|'.join(_OD)}|{'|'.join(_OU)})"
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _wordval(w: str) -> int:
    return sum(_U.get(x, 0) + _T.get(x, 0) + _D.get(x, 0) + _OU.get(x, 0) + _OT.get(x, 0) + _OD.get(x, 0) for x in re.split(r"[-\s]+", w.lower()))


def words_to_digits(t: str) -> str:
    t = re.sub(rf"\b({_MONTH})\s+(?:the\s+)?({_ORD})\b", lambda m: f"{m.group(1)} {_wordval(m.group(2))}", t, flags=re.I)
    t = re.sub(rf"\b(?:the\s+)?({_ORD})\s+(?:of\s+)?({_MONTH})\b", lambda m: f"{_wordval(m.group(1))} {m.group(2)}", t, flags=re.I)

    def hundred(m):
        base = (1 if m.group(1).lower() in ("a", "an") else _U[m.group(1).lower()]) * 100
        return str(base + (_wordval(m.group(2)) if m.group(2) else 0))

    t = re.sub(rf"\b({_UW}|an?)\s+hundred(?:\s+(?:and\s+)?({_SMALL}))?\b", hundred, t, flags=re.I)
    return re.sub(rf"\b((?:{_DW})[-\s](?:{_UW})|{_TW}|{_DW})\b", lambda m: str(_wordval(m.group(1))), t, flags=re.I)


def _content(s: str) -> Set[str]:
    return {w[:5] for w in re.findall(r"[a-z']+", (s or "").lower().replace("-", " ")) if len(w) >= 4 and w not in STOP}


KEEP_PHRASES = [  # 事实句点名的证据来源，台词必须保留（"owners corporation" 改成 "owner" 就不是一回事了）
    (r"owners?\s+corporation", "owners corporation"), (r"by-?\s?laws?", "by-laws"),
    # 中介回复（10-27 起代替看房报告：agent reply / agent's email / the agent said … 都归一成同一个出处名）
    (r"agent(?:'s|s')?\s+(?:reply|replies|email|e-mail|answer|message|text)|agent\s+(?:said|says|wrote|replied|confirm(?:ed|s)?|told|answered)", "agent reply"),
    (r"floor ?plan", "floor plan"), (r"transit table", "transit table"), (r"condition report", "condition report"), (r"\bstrata\b", "strata"),
    (r"\blisting\b", "listing"), (r"\bagent\b", "agent"), (r"\bnsw\b", "NSW"), (r"\blease\b", "lease"), (r"\binventory\b", "inventory"),
    (r"\bphotos?\b", "photos"), (r"\bdisclosure\b", "disclosure"),
]


ADDED_SOURCE_SKIP = {"listing", "agent"}  # 这两个词太泛（"second listing" 指房子、"ask the agent" 哪句都能说），不算安出处


def added_sources(line_: str, fact: str) -> List[str]:
    """台词里提到、事实里却没有的出处（by-laws、agent reply、floor plan…）：模型把结论安到了别的材料头上。
    "agent reply" 认 agent's reply / agent's email / the agent said / the agent confirmed 这些说法（KEEP_PHRASES 同一条正则）。"""
    out = []
    for rx, name in KEEP_PHRASES:
        if name in ADDED_SOURCE_SKIP:
            continue
        if re.search(rx, line_ or "", re.I) and not re.search(rx, fact or "", re.I):
            out.append(name)
    return out


def dropped_sources(line_: str, fact: str) -> List[str]:
    low_f, low_l = (fact or "").lower(), (line_ or "").lower()
    return [name for rx, name in KEEP_PHRASES if re.search(rx, low_f) and not re.search(rx, low_l)]


def overlap_ratio(line_: str, fact: str) -> float:
    """模板句的实词（去停用词、取前 5 个字母当词干）有多少还在台词里：太少说明模型跑题、换了证据（例子里的沙发跑进了宠物那行）。"""
    f = _content(fact)
    return 1.0 if not f else len(f & _content(line_)) / len(f)


def enabled() -> bool:
    """模型路可用吗：NARRATION_LLM=0 关；否则看模型层能不能选到 provider（和需求解析同一条路）。"""
    v = os.environ.get("NARRATION_LLM", "auto").strip().lower()
    if v in ("0", "off", "false", "no", "rules", "template"):
        return False
    if llm is None:
        return False
    try:
        return llm.select().name != "none"
    except Exception:  # noqa: BLE001
        return False


def timeout() -> float:
    try:
        return float(os.environ.get("NARRATION_LLM_TIMEOUT", "6"))
    except ValueError:
        return 6.0


# ---------------------------------------------------------------- 校验
def nums(s: str) -> Set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", (s or "").replace(",", "")))


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _clean(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return None
    t = " ".join(text.split()).strip().strip('"').strip("'").strip()
    if not t or len(t) > 340 or GENERIC_BAD.search(t):
        return None
    return t[0].upper() + t[1:]


def check_line(text: Any, *, required: Iterable[str] = (), allowed: Iterable[str] = (), status: Optional[str] = None,
               words: Optional[str] = None, must: Any = None, max_words: Optional[int] = None,
               question: bool = False, fact: Optional[str] = None, avoid: Iterable[str] = (), overlap: float = 0.0,
               statement: bool = False) -> Tuple[Optional[str], str]:
    """一行台词过审：返回 (干净的句子, "") 或 (None, 原因)。fact 给了就查"是不是原样照抄"和"实词还剩多少"（overlap 是最低比例），
    avoid 是不许整句复述的话（租客原话），must 是必须出现的词（一个正则，或一列正则都要命中）。"""
    t = _clean(text)
    if t is None:
        return None, "empty or markdown or too long"
    if LABEL_PREFIX.match(t):
        return None, "starts with a status label"
    if TAG_RE.search(t):
        return None, "status word used as a tag"
    if fact is not None and _norm(t) == _norm(fact):
        return None, "copied the fact"
    for a in avoid:
        na = _norm(a)
        if len(na.split()) >= 4 and na in _norm(t):
            return None, "repeats the renter's words"
    if overlap and fact is not None:
        if overlap_ratio(t, fact) < overlap:
            return None, f"drifts from the fact (keeps {round(overlap_ratio(t, fact) * 100)}% of its words)"
        gone = dropped_sources(t, fact)
        if gone:
            return None, f"drops the source ({', '.join(gone)})"
    low = t.lower()
    n = nums(words_to_digits(t))
    extra = n - set(allowed) - set(required)
    if extra:
        return None, f"invented number {sorted(extra)}"
    missing = set(required) - n
    if missing:
        return None, f"missing number {sorted(missing)}"
    if status in STATUS_RE and not re.search(STATUS_RE[status], low):
        return None, f"no {status} wording"
    if status == "supported" and re.search(NOT_SUPPORTED_RE, low):
        return None, "supported line hedges"
    if words and not re.search(words, low):
        return None, "topic words missing"
    for m in ([must] if isinstance(must, str) else list(must or [])):
        if m and not re.search(m, low):
            return None, "required wording missing"
    if fact is not None:
        extra = added_sources(t, fact)
        if extra:
            return None, f"adds a source ({', '.join(extra)})"  # 事实没提 by-laws / 中介 / 验房报告，台词不能自己安上
    if statement and "?" in t:
        return None, "asks a question"  # 确认改需求之类的句子不该反问（模型爱在结尾加 "What's next?"）
    if question and "?" not in t:
        return None, "not a question"
    if max_words and len(t.split()) > max_words:
        return None, f"longer than {max_words} words"
    return t, ""


def _profile_nums(profile: dict) -> Set[str]:
    out: Set[str] = set()
    for k in ("budget", "bedrooms"):  # max_commute 不在这里：事实句没提的上限不许模型顺手加上（"under your 40-minute limit"）
        if profile.get(k) is not None:
            out.add(str(profile[k]))
    mi = profile.get("move_in") or {}
    if mi.get("day"):
        out.add(str(mi["day"]))
    return out


def _listing_nums(L: dict) -> Set[str]:
    out = {str(L.get("rent")), str(L.get("bedrooms")), str(L.get("bathrooms"))}
    out |= nums(str(L.get("street", ""))) | nums(str(L.get("unit", "") or ""))
    try:
        out.add(str(int(str(L.get("available_from", ""))[8:10])))
    except ValueError:
        pass
    return {x for x in out if x and x != "None"}


def cell_spec(dim: str, c: dict, L: dict, profile: dict) -> dict:
    """某一格的校验要求：模板句（事实）、关键数字、允许的数字、状态、维度词。可以直接 **spec 传给 check_line。"""
    fact = phraser.cell_sentence(dim, c, L, profile)
    allowed = nums(fact) | _profile_nums(profile) | _listing_nums(L)
    required: Set[str] = set()
    if dim == "A1":
        required = {str(L["rent"]), str(profile["budget"])}
    elif dim == "G1" and c.get("value"):
        required = {str(c["value"]["min"])}
    elif dim == "A4" and c.get("value"):
        required = nums(str(c["value"]))
    return {"fact": fact, "required": required, "allowed": allowed, "status": c["status"], "words": DIM_WORDS.get(dim), "overlap": 0.3}


# ---------------------------------------------------------------- 模型调用
def _chat(system: str, user: Any, *, max_tokens: int, timeout_s: float, temperature: float = 0.7):
    STATS["calls"] += 1
    body = user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)
    return llm.chat([{"role": "system", "content": system}, {"role": "user", "content": body}], task="narrate",
                    temperature=temperature, max_tokens=max_tokens, retries=0, timeout=timeout_s)  # 走和需求解析一样的钉死路由


def _fail(e: Exception, where: str) -> None:
    if getattr(e, "kind", "") == "timeout":
        STATS["timeouts"] += 1
    else:
        STATS["failed"] += 1
    log.info(f"{where}: model failed ({getattr(e, 'kind', type(e).__name__)}: {str(e)[:120]}) → templates")


def _json_object(text: str) -> Optional[dict]:
    t = (text or "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _put(out: Dict[str, str], key: str, value: str) -> None:
    name = key.strip().split(".")[-1]
    out.setdefault(name, value)
    if DIM_KEY.match(name):
        out.setdefault(f"cells.{name}", value)


def _flatten(obj: Any, out: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """模型回的结构不听话也认：顶层平铺、套一层 cells / lines、值是 {line: …} / {fact: …}、或 [{key, line}] 列表。"""
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                _put(out, str(k), v)
            elif isinstance(v, dict):
                s = next((v[x] for x in ("line", "text", "say", "rewrite", "spoken", "fact") if isinstance(v.get(x), str)), None)
                if s is not None and not any(isinstance(x, (dict, list)) for x in v.values()):
                    _put(out, str(k), s)
                else:
                    _flatten(v, out)
            elif isinstance(v, list):
                if len(v) == 1 and isinstance(v[0], str):
                    _put(out, str(k), v[0])
                _flatten(v, out)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                s = next((item[x] for x in ("line", "text", "say", "rewrite", "spoken", "fact") if isinstance(item.get(x), str)), None)
                if s is not None:
                    _put(out, item["key"], s)
            else:
                _flatten(item, out)
    return out


def _judge(flat: Dict[str, str], specs: Dict[str, dict], avoid: Iterable[str] = ()) -> Tuple[Dict[str, str], List[str], int]:
    """按 specs 逐行过审：返回 (过审的行, 被拒的说明, 原样照抄的行数)。"""
    out: Dict[str, str] = {}
    rejected: List[str] = []
    copied = 0
    for key, spec in specs.items():
        try:
            line_, why = check_line(flat.get(key), avoid=avoid, **spec)
        except Exception as e:  # noqa: BLE001  校验自己出错也不能让导览没声音
            line_, why = None, f"check error {type(e).__name__}: {e}"
        if line_:
            out[key] = line_
        elif why == "copied the fact":
            copied += 1
        else:
            rejected.append(f"{key}: {why} ({str(flat.get(key))[:80]!r})")
    return out, rejected, copied


def _tour_call(i: int, n: int, L: dict, cells: Dict[str, dict], profile: dict, request_text: Any, tour_order: List[str],
               bq: Optional[Tuple[str, dict]], wrap_fact: Optional[str], legal_pending: bool, excluded: int,
               vc: Optional[Tuple[str, dict]] = None) -> Dict[str, str]:
    """一套房一次调用：intro + 每格 + special + question（或 viewing）+ next (+ wrap)。返回过审的行（键同模板的 step：intro / cells.A1 / special / question / viewing / next / wrap）。
    request_text：租客最近说的几句（列表）或一句（字串）。vc：没有可问中介的格子时，最值得去看房核的那格（policy.viewing_check）。"""
    t0 = time.time()
    heard = [request_text] if isinstance(request_text, str) else [str(x) for x in (request_text or [])]
    specs: Dict[str, dict] = {}
    facts: List[Dict[str, str]] = []
    intro = phraser.intro(i, L)
    facts.append({"key": "intro", "fact": intro})
    specs["intro"] = {"fact": intro, "required": {str(L["rent"])}, "allowed": _listing_nums(L) | _profile_nums(profile),
                      "must": re.escape(re.sub(r"^\d+\s+", "", L["street"]).split()[0].lower())}
    for d in tour_order:
        if d in cells:
            s = cell_spec(d, cells[d], L, profile)
            specs[f"cells.{d}"] = s
            facts.append({"key": d, "status": cells[d]["status"], "status_hint": STATUS_HINT[cells[d]["status"]], "fact": s["fact"]})
    sp = phraser.special(L)
    if sp:
        facts.append({"key": "special", "fact": sp})
        specs["special"] = {"fact": sp, "allowed": nums(sp) | _listing_nums(L), "overlap": 0.3}
    if bq:
        q = phraser.best_question(bq[0], bq[1], profile)
        facts.append({"key": "question", "fact": q})
        specs["question"] = {"fact": q, "allowed": nums(q) | _profile_nums(profile), "words": DIM_WORDS.get(bq[0]), "question": True, "must": QUESTION_WORDS}
    elif vc:
        v = phraser.viewing_check(vc[0], vc[1])
        facts.append({"key": "viewing", "fact": v})
        specs["viewing"] = {"fact": v, "allowed": nums(v) | _profile_nums(profile), "words": DIM_WORDS.get(vc[0]), "overlap": 0.3,
                            "must": r"viewing|visit|look|check|see|inspect|listen|walk|when you(?:'re| are) there"}
    if i < n - 1:
        nx = phraser.transition(i + 1, n)
        facts.append({"key": "next", "fact": nx})
        specs["next"] = {"fact": nx, "max_words": 8}
    if wrap_fact:
        facts.append({"key": "wrap", "fact": wrap_fact})
        specs["wrap"] = {"fact": wrap_fact, "allowed": nums(wrap_fact) | {str(n), str(excluded)}, "must": r"question|compare|draft|anything else|what next",
                         **({"words": r"disclosure|crime|violent"} if legal_pending else {})}
    user = {"renter_said": " / ".join(heard)[:400], "needs": {k: v for k, v in profile.items() if k in ("budget", "bedrooms", "anchor", "max_commute")},
            "position": f"{phraser.ORD_WORDS[i]} of {n}",
            "listing": {"street": L["street"], "suburb": L["suburb"], "rent_per_week": L["rent"], "bedrooms": L["bedrooms"], "bathrooms": L["bathrooms"]},
            "facts": facts, "reply_keys": [f["key"] for f in facts]}
    try:
        res = _chat(SYSTEM, user, max_tokens=900, timeout_s=timeout())
    except Exception as e:  # noqa: BLE001  没 provider、超时、401 …
        _fail(e, f"L{i}")
        return {}
    obj = _json_object(res.text)
    if obj is None:
        STATS["failed"] += 1
        log.info(f"L{i}: answer was not JSON → templates ({res.ms} ms)")
        return {}
    out, rejected, copied = _judge(_flatten(obj), specs, avoid=heard)
    STATS["accepted"] += len(out)
    STATS["rejected"] += len(rejected)
    STATS["copied"] += copied
    log.info(f"L{i}: {len(out)}/{len(specs)} lines accepted in {round(time.time() - t0, 2)} s via {res.provider}/{res.served_model or res.model}"
             + (f"; {copied} copied the template" if copied else "") + (f"; rejected {rejected}" if rejected else ""))
    return out


def start_tour(shown: List[dict], profile: dict, request_text: Any, tour_order: List[str], best_question, wrap_fact: str,
               legal_pending: bool, excluded: int, viewing_check=None) -> Dict[int, Future]:
    """开查时就把三套房的台词请求发出去（线程池），讲到时再取。返回 {第几套: Future}。
    viewing_check（policy.viewing_check）：没有可问中介的格子时改写 "worth checking at the viewing" 那句；不给就只用模板。"""
    futs: Dict[int, Future] = {}
    n = len(shown)
    for i, item in enumerate(shown):
        L, cells = item["listing"], item["cells"]
        bq = best_question(cells)
        vc = viewing_check(cells) if (viewing_check is not None and bq is None) else None
        f = POOL.submit(_tour_call, i, n, L, cells, profile, request_text, tour_order, bq,
                        wrap_fact if i == n - 1 else None, legal_pending, excluded, vc)
        f.t0 = time.time()  # type: ignore[attr-defined]
        futs[i] = f
    return futs


def take(fut: Optional[Future], key: str) -> Optional[str]:
    """讲到这句时取模型写的那行：在预算内等（预算 = 发出时间 + 超时 − 现在），等不到就 None（用模板）。"""
    if fut is None:
        return None
    wait = max(0.0, getattr(fut, "t0", time.time()) + timeout() - time.time())
    try:
        lines = fut.result(timeout=wait)
    except FutureTimeout:
        STATS["timeouts"] += 1
        return None
    except Exception:  # noqa: BLE001
        return None
    return (lines or {}).get(key)


def line(kind: str, fact: str, *, context: dict, required: Iterable[str] = (), allowed: Iterable[str] = (),
         status: Optional[str] = None, words: Optional[str] = None, must: Any = None, question: bool = False,
         timeout_s: float = 2.5, max_words: Optional[int] = None, overlap: float = 0.0, statement: bool = False) -> Optional[str]:
    """单句（反问、改需求的确认、答问、中介回复的变化）：同步调一次，超时或没过审或原样照抄就 None（用模板）。"""
    if not enabled():
        return None
    t0 = time.time()
    heard = [str(x) for x in (context.get("heard") or [context.get("renter_said", "")])]
    item = {"key": kind, "fact": fact}
    if status in STATUS_HINT:
        item.update(status=status, status_hint=STATUS_HINT[status])
    user = dict({k: v for k, v in context.items() if k != "heard"}, facts=[item], reply_keys=[kind])
    try:
        res = _chat(SYSTEM, user, max_tokens=160, timeout_s=timeout_s)
    except Exception as e:  # noqa: BLE001
        _fail(e, kind)
        return None
    flat = _flatten(_json_object(res.text) or {})
    if kind not in flat and len(set(flat.values())) == 1:  # 键写错了（把句子放在 reply_keys 下面之类），但只有一句：就是它
        flat[kind] = next(iter(flat.values()))
    spec = {"fact": fact, "required": required, "allowed": set(allowed) | nums(fact), "status": status, "words": words, "must": must,
            "question": question, "max_words": max_words, "overlap": overlap, "statement": statement}
    out, rejected, copied = _judge(flat, {kind: spec}, avoid=heard)
    if out:
        STATS["accepted"] += 1
        log.info(f"{kind}: accepted in {round(time.time() - t0, 2)} s: {out[kind][:100]!r}")
        return out[kind]
    if copied:
        STATS["copied"] += 1
        log.info(f"{kind}: copied the template → template ({round(time.time() - t0, 2)} s)")
    else:
        STATS["rejected"] += 1
        log.info(f"{kind}: rejected → template ({round(time.time() - t0, 2)} s): {rejected}" + (f"; answer was {res.text[:160]!r}" if kind not in flat else ""))
    return None
