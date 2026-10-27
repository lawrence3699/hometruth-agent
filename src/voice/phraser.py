"""措辞模板（英文）。每句话都从一个格子和它的证据生成；程序决定说什么，这里只决定怎么说。
拿到 Nemotron key 后可以让模型润色，但输入仍然是这些格子，模型不能自由发挥。"""
from __future__ import annotations

import os
import random
import re
from typing import Dict, List, Optional, Tuple

ORD_WORDS = ["first", "second", "third", "fourth", "fifth"]
ORD_LEAD = ["First up", "Second", "Third", "Fourth", "Fifth"]
NUM_WORDS = {0: "studio", 1: "one", 2: "two", 3: "three", 4: "four"}

QUESTIONS = {
    "A1": "what's your weekly budget",
    "B1": "how many bedrooms do you need",
    "G1": "where do you commute to",
    "A4": "when do you need to move in",
    "J1": "do you have any pets",
}

ASSUME = {
    "A1": "no budget cap, so I'll sort by rent",
    "B1": "any number of bedrooms",
    "G1": "commute measured to Central Station",
    "A4": "any move-in date",
    "J1": "no pets",
}


def beds_phrase(n: int) -> str:
    if n == 0:
        return "a studio"
    if n == 1:
        return "one bedroom"
    return f"{NUM_WORDS.get(n, str(n))} bedrooms"


def join(parts: List[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def summary(profile: dict) -> str:
    parts: List[str] = []
    if profile.get("bedrooms") is not None:
        parts.append(beds_phrase(profile["bedrooms"]))
    if profile.get("budget") is not None:
        parts.append(f"under {profile['budget']} a week")
    if profile.get("anchor"):
        parts.append(f"commuting to {profile['anchor']}")
    if profile.get("move_in"):
        parts.append(f"moving {profile['move_in']['text']}")
    pets = profile.get("pets")
    if pets:
        parts.append(f"with {pets['text']}" if pets.get("has") else "no pets")
    for ex in profile.get("extras", []):
        parts.append(ex["label"][0].lower() + ex["label"][1:])
    return join(parts)


def cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


BRIDGES = {
    "first": ["Got it.", "Okay.", "Sure.", "Alright."],  # 听完第一句需求
    "answered": ["Thanks.", "Great, thanks.", "Perfect, thanks."],  # 用户答了反问
    "interrupted": ["Okay.", "Sure.", "Right."],  # 讲到一半被改需求
    "answer": ["Let me check.", "Good question.", "Let me see."],  # 被问了问题（模型写答案时先出声）
    "agent": ["Thanks, noted.", "Good to know.", "Noted."],  # 中介回复到了
    "next": ["Sure, next one.", "Okay, moving on.", "Next one then."],  # 用户说 skip
}


def _choose(opts: List[str], variety: bool) -> str:
    """variety=False（回归、基线）或 VOICE_VARIETY=0 永远取第一个；平时随机换着说。"""
    if variety and os.environ.get("VOICE_VARIETY", "1").strip().lower() not in ("0", "off", "false", "no"):
        return random.choice(opts)
    return opts[0]


def pick(kind: str, variety: bool = True) -> str:
    """过渡句：免得每次都是 "Got it."。"""
    return _choose(BRIDGES[kind], variety)


def all_bridges() -> List[str]:
    return [x for v in BRIDGES.values() for x in v]


# 口语化的接话（10-25 18:50，用户："和真人对话得有点语气：让我看看…找到了，这三套挺符合你的…"）。只在台词模型开着时用，回归 / 基线仍是老句子。
HEARD = ["So: {s}.", "Okay, so {s}.", "Let me make sure I've got it: {s}."]
THINKING = ["Okay, let me see what fits that{near}.", "Alright, let me look at what's out there{near}.",
            "Hmm, let me see what matches that{near}.", "Let me pull up what fits{near}."]
BACK = ["Back to the {o} place.", "Okay, where was I. The {o} place.", "Right, back to the {o} one."]


def heard_sentence(summary_text: str, variety: bool = True) -> str:
    """复述听懂的需求，带一点语气（"So: two bedrooms, …"）。"""
    return _choose([t.format(s=summary_text) for t in HEARD], variety)


def thinking(anchor: Optional[str] = None, variety: bool = True) -> str:
    """开查前的"让我看看"：知道通勤地点就说 near <地点>，不知道就 around Sydney。"""
    near = f" near {anchor}" if anchor else " around Sydney"
    return _choose([t.format(near=near) for t in THINKING], variety)


def found(n_pass: int, n_show: int, variety: bool = True) -> str:
    """查完的"找到了"：说清几套过了硬条件、接下来讲几套（数字来自排序结果，不是模型说的）。"""
    if n_pass == 0:
        opts = ["Hmm, nothing passes the basics yet. I'll show you the closest misses.",
                "Nothing ticks all the basics yet, so I'll show you the closest misses."]
    elif n_pass == 1:
        opts = ["Found one that passes the basics. Here it is.", "Just one place ticks the basics. Let me show you."]
    else:
        n, k = NUM_WORDS.get(n_pass, str(n_pass)), NUM_WORDS.get(n_show, str(n_show))
        if n_show >= n_pass:
            opts = [f"Found some. {n.capitalize()} places tick the basics, and they all look like a good fit for you. Let me take you through them.",
                    f"Okay, here we go: {n} places pass the basics. Let me walk you through them.",
                    f"Right, got {n} that fit. I'll take you through them one by one."]
        else:
            opts = [f"Found some. {n.capitalize()} places tick the basics; these top {k} look like the best fit for you.",
                    f"Okay, here we go: {n} places pass the basics. Let me walk you through the top {k}.",
                    f"Right, got {n} that fit. I'll take you through the top {k}."]
    return _choose(opts, variety)


def all_glue() -> List[str]:
    """给 Magpie 按句缓存预热用：口语化接话里不依赖需求内容的句子。"""
    out: List[str] = [t.format(near=" around Sydney") for t in THINKING] + [t.format(near=" near Central Station") for t in THINKING]
    for n in range(0, 6):
        out += [found(n, min(3, n), variety=False)]
        if n >= 2:
            k = NUM_WORDS.get(n, str(n)); kk = NUM_WORDS.get(min(3, n), str(min(3, n)))
            out += [f"Okay, here we go: {k} places pass the basics. Let me walk you through them.", f"Right, got {k} that fit. I'll take you through them one by one.",
                    f"Okay, here we go: {k} places pass the basics. Let me walk you through the top {kk}.", f"Right, got {k} that fit. I'll take you through the top {kk}."]
    out += [t.format(o=ORD_WORDS[i]) for i in range(3) for t in BACK]
    return list(dict.fromkeys(out))


def bridge(pending: List[str], interrupted: bool = False, variety: bool = False) -> str:
    """过渡句：听完一句需求立刻先说的那两个字。它不依赖解析结果，所以模型还在解析时就能出声（首声从 1.5 s 降到 0.5 s 上下）；
    后面的反问 / 开场 / 重排句子不再自带 "Got it." 这种开头，由它统一提供。"""
    if interrupted:
        return pick("interrupted", variety)
    return pick("answered" if pending else "first", variety)


VAGUE_G1 = "where should I measure the commute to: UNSW, the CBD or Central Station"


def ask_sentence(fields: List[str], vague: Optional[str] = None) -> str:
    """反问句本体，不带开头（开头是 bridge）。vague = 租客说了个量不了通勤的地方（the beach / the uni）：直接给能量的几个地方。"""
    qs = [VAGUE_G1 if (f == "G1" and vague) else QUESTIONS[f] for f in fields]
    if len(qs) >= 2:
        return f"Two quick things: {qs[0]}, and {qs[1]}?"
    return f"One quick thing: {qs[0]}?"


def assumptions(missing: List[str]) -> str:
    if not missing:
        return ""
    return "I'll assume " + join([ASSUME[m] for m in missing]) + "; tell me if that's wrong."


def opening_parts(profile: dict, missing: List[str], n_sources: int) -> List[str]:
    """开场，拆成两句（第一句是需求复述，第二句是假设 + 开查）。"Got it." 已经由 bridge 说过，这里不再重复。"""
    s = summary(profile)
    a = assumptions(missing)
    first = f"{cap(s)}." if s else ""
    second = " ".join(x for x in [a, f"Checking {n_sources} sources now."] if x)
    return [x for x in (first, second) if x]


def opening(profile: dict, missing: List[str], n_sources: int) -> str:
    return " ".join(opening_parts(profile, missing, n_sources))


def shortlist(n_pass: int, n_show: int) -> str:
    if n_pass == 0:
        return "Nothing passes the basics yet. I'll show you the closest misses."
    if n_pass == 1:
        return "One place passes the basics. Here it is."
    return f"{NUM_WORDS.get(n_pass, str(n_pass)).capitalize()} places pass the basics. I'll walk you through the top {NUM_WORDS.get(n_show, str(n_show))}."


def intro(i: int, L: dict) -> str:
    beds = beds_phrase(L["bedrooms"])
    what = "a studio" if L["bedrooms"] == 0 else f"a {beds.replace('one bedroom', 'one-bedroom').replace(' bedrooms', '-bedroom')}"
    return f"{ORD_LEAD[i]}: {what} on {L['street']}, {L['suburb']}, {L['rent']} a week."


STATUS_WORD = {"supported": "supported", "inferred": "I can only infer", "conflict": "a conflict", "unknown": "unknown"}


def cell_sentence(dim: str, c: dict, L: dict, profile: dict) -> str:
    st = c["status"]
    if dim == "A1":
        med = c.get("median") or {}
        tail = ""
        if med.get("rent"):  # 真房源：Domain 的本区中位租金，或（10-27 起，没有 Domain 中位数时）NSW Fair Trading 押金登记里这个邮编同类房的新租约中位数
            pct = med.get("pct") or 0
            rel = 'about the' if abs(pct) < 2 else f'{abs(pct)} percent ' + ('above' if pct > 0 else 'below')
            beds = med.get("beds") if med.get("beds") is not None else 2
            if med.get("source") == "nsw-bonds":
                kind = "studio" if beds == 0 else f"{beds}-bedroom"
                tail = f" That's {rel} the median of {med['rent']} for new {kind} leases in postcode {L.get('postcode') or ''}, from NSW Fair Trading bond records."
            else:
                tail = f" That's {rel} {med['suburb']}'s median of {med['rent']} for {beds} bedroom{'' if beds == 1 else 's'}."
        if st == "supported":
            return f"Rent is {L['rent']} a week, inside your {profile['budget']} budget.{tail}"
        return f"Rent is {L['rent']} a week, over your {profile['budget']} budget.{tail}"
    if dim == "B1":
        if st == "supported":
            return f"{beds_phrase(L['bedrooms']).capitalize()}, as asked."
        return f"Only {beds_phrase(L['bedrooms'])}, so it misses your {beds_phrase(profile['bedrooms'])}."
    if dim == "G1":
        if st == "unknown":
            return f"I don't have the commute time to {profile['anchor']} yet."
        v = c["value"]
        if st == "supported":
            if str(v.get("mode") or "").lower() in ("walk", "walking"):
                return f"A {v['min']}-minute walk to {profile['anchor']}, from the timetable."
            return f"{v['min']} minutes to {profile['anchor']} by {v['mode']}, from the timetable."
        if st == "inferred":  # 真房源：直线距离估的
            return f"About {v['min']} minutes to {profile['anchor']} by {v['mode']}, estimated from the distance, not a timetable."
        return f"{v['min']} minutes to {profile['anchor']}, over your {profile.get('max_commute', 40)} minute limit" + (", and that's only an estimate from the distance." if v.get("estimate") else ".")
    if dim == "A4":
        if st == "unknown":  # 搜索卡片没有可入住日（scripts/domain_sample.py 记成 None）：硬条件待确认，不是冲突，也没有日期可念
            return f"Move-in date: unknown. {c.get('why', '')}".strip()
        if st == "supported":
            return f"Available from {c['value']}, which works for {profile['move_in']['text']}."
        return f"Available from {c['value']}, about {c.get('gap_days', 0)} days after {profile['move_in']['text']}, so that's a conflict unless the date moves."
    label = {"J1": "Pets", "C1": "Bedroom air con", "A6": "Bills", "C2": "Furniture", "C3": "Stove", "E4": "Quiet", "E2": "Sunlight", "D1": "Condition",
             "K1": "Numbers", "K2": "Through-line", "K3": "Doors", "K4": "Outline"}.get(dim, dim)
    if not c.get("evidence") and st == "unknown" and dim in ("C2", "E4", "E2", "D1", "K1", "K2", "K3", "K4"):
        return f"{label}: nothing I have covers it yet."
    lead = {"supported": f"{label}: checks out.", "inferred": f"{label}: probably, but not confirmed.", "conflict": f"{label}: doesn't match what you asked.", "unknown": f"{label}: not confirmed."}[st]
    return f"{lead} {c.get('why', '')}".strip()


def special(L: dict) -> str:
    return f"What's special here: {L['special']}." if L.get("special") else ""


BEST_Q = {
    "J1": "Best question for this agent: are pets allowed, in writing?",
    "C1": "Best question for this agent: is there air con in the bedrooms, not just the living room?",
    "G1": "Best thing to check: how long does it really take to {anchor}?",
    "A4": "Best question for this agent: can the move-in date come forward?",
    "A6": "Best question for this agent: which bills are included?",
    "C2": "Best question for this agent: what furniture stays, per the inventory?",
    "C3": "Best question for this agent: what's the cooktop model, gas, ceramic or induction?",
    "E4": "Best thing to check: what are the noise sources around the block?",
    "E2": "Best thing to check: which way does it face on the floor plan, and what stands in front?",
    "D1": "Best question for this agent: when were the kitchen and bathroom last renovated?",
    "K1": "Best thing to check: what level is it on the building directory? Some blocks skip a floor.",
    "K2": "Best question for this agent: can you send the floor plan, with the entry and balcony marked?",
    "K3": "Best question for this agent: can you send the floor plan showing the bathroom door and the cooktop?",
    "K4": "Best question for this agent: can you send a floor plan with the outer dimensions?",
}


def best_question(dim: str, c: dict, profile: dict) -> str:
    if dim == "G1" and c.get("estimate"):  # 真房源：通勤是直线距离估的，该查的是真实时刻表
        return f"Best thing to check with the agent: what's the real door-to-door time to {profile.get('anchor') or 'your anchor'}? Mine is only an estimate from the distance."
    if dim == "A4" and c.get("status") == "unknown":  # 没有日期时问最早哪天能入住，不问"能不能提前"
        return "Best question for this agent: what's the earliest move-in date?"
    t = BEST_Q.get(dim, "Best question for this agent: can you confirm that in writing?")
    return t.format(status=c["status"], anchor=profile.get("anchor") or "your anchor")


def viewing_check(dim: str, c: dict) -> str:
    """没有可问中介的格子时说的那句：最值得去看房核的那格（policy.viewing_check），hint 来自 policy.next_for。
    e.g. Worth checking at the viewing: look at the cooktop: flame rings or a flat top."""
    hint = str((c.get("next") or {}).get("hint") or "take a close look at it").strip().rstrip(".")
    return f"Worth checking at the viewing: {hint}."


def transition(next_i: int, total: int) -> str:
    if next_i == total - 1:
        return "And the last one."
    return "Next one."


def wrap(n: int, excluded: int, legal_pending: bool) -> str:
    parts = [f"That's the top {NUM_WORDS.get(n, str(n))}."]
    if excluded:
        parts.append(f"{NUM_WORDS.get(excluded, str(excluded)).capitalize()} other{'s' if excluded > 1 else ''} dropped out on rent or size.")
    if legal_pending:
        parts.append("Before you sign any of them, ask about the five-year crime disclosure; it's a legal must-ask.")
    parts.append("Want me to draft the questions, or compare them on anything?")
    return " ".join(parts)


def back(i: int, variety: bool = False) -> str:
    return _choose([t.format(o=ORD_WORDS[i]) for t in BACK], variety)


def answer(dim: str, c: dict, L: dict, profile: dict) -> str:
    return f"For the {L['street']} place: {cell_sentence(dim, c, L, profile)}"


def no_fact(L: dict, topic: str) -> str:
    return f"I don't have a checked fact on {topic} for the {L['street']} place, so it's unknown. I can add it to the questions for the agent."


def ranking(ranked: List[dict]) -> str:
    if not ranked:
        return "Nothing passes the basics yet."
    top = ranked[0]
    cheapest = min(ranked, key=lambda r: r["listing"]["rent"])
    counts = top["counts"]
    s = (f"The {top['listing']['street']} place scores highest right now: {counts['supported']} supported, "
         f"{counts['inferred']} inferred, {counts['open']} open questions.")
    if cheapest is not top:
        s += f" The cheapest is {cheapest['listing']['street']} at {cheapest['listing']['rent']} a week."
    return s


def change_bits(changes: Dict[str, str]) -> List[str]:
    bits = []
    for k, v in changes.items():
        bits.append({"budget": f"budget {v}", "bedrooms": f"{v} bedrooms", "anchor": f"commute to {v}", "move_in": f"move-in {v}", "pets": v, "extras": v, "max_commute": f"{v} minutes max"}.get(k, f"{k} {v}"))
    return bits


def updated(changes: Dict[str, str]) -> str:
    return cap(join(change_bits(changes))) + ". Let me re-rank."  # 开头的 "Got it." / "Okay." 由 bridge 说


# 欢迎回来（memory.py）：机器先开口问的那句，和开查时代替需求复述的那句
def short_summary(profile: dict) -> str:
    """简短播报（docs/12）的欢迎回来只点卧室、通勤和预算，其余的在页面的需求 chip 里：two bedrooms near UNSW, under 900 a week"""
    head = " ".join(x for x in [beds_phrase(profile["bedrooms"]) if profile.get("bedrooms") is not None else "",
                                f"near {profile['anchor']}" if profile.get("anchor") else ""] if x)
    tail = f"under {profile['budget']} a week" if profile.get("budget") is not None else ""
    return ", ".join(x for x in [head, tail] if x) or summary(profile)


def welcome_question(summary_text: str, extra: str = "") -> str:
    """extra = 离开时到的回复 / 还在等的问题那一句（away_line / open_line），放在问句前面。"""
    mid = f" {extra}" if extra else ""
    return f"Welcome back. Last time it was {summary_text}.{mid} Same again, or has anything changed?"


def away_line(streets: List[str]) -> str:
    """开场那句的一部分：While you were away, the agent for 2 Harrow Crescent replied."""
    if not streets:
        return ""
    who = "the agents for" if len(streets) > 1 else "the agent for"
    return f"While you were away, {who} {join(list(streets))} replied."


def open_line(open_items: List[dict]) -> str:
    """e.g. You were still waiting on the agent about pets at 3/2 Harrow Crescent. （最多两项）"""
    bits = [f"{str(o.get('label') or o.get('dim')).lower()} at {o.get('street')}" for o in open_items[:2] if o.get("street")]
    if not bits:
        return ""
    return f"You were still waiting on the agent about {join(bits)}."


def channel_words(channel: Optional[str]) -> str:
    return {"email": " by email", "sms": " by text", "phone": " by phone", "portal": " through the portal"}.get(str(channel or "").lower(), "")


def inbox_change(L: dict, dim_label: str, old: str, new: str, channel: Optional[str], live: bool, consequence: str = "") -> str:
    """收件箱里那条回复落下来的那句。导览中途：Just in, by email: the agent for 2 Harrow Crescent says pets goes from inferred to supported. That moves…
    开查前：By email, the agent for 2 Harrow Crescent says pets goes from inferred to supported; I've folded that in before ranking."""
    by = channel_words(channel).strip()
    core = f"the agent for {L['street']} says {dim_label.lower()} {now_phrase(new)}"
    if live:
        s = f"Just in{', ' + by if by else ''}: {core}."
        return s + (" " + consequence if consequence else "")
    if by:
        return f"{cap(by)}, {core}; I've folded that in before ranking."
    return f"{cap(core)}; I've folded that in before ranking."


def inbox_unmapped(L: dict, channel: Optional[str]) -> str:
    return f"The agent for {L['street']} also replied{channel_words(channel)}, but I couldn't tell which condition it answers, so I've left it alone."


def same_as_sources(L: dict, dim_label: str, status: str) -> str:
    return f"That matches what I already had: {dim_label.lower()} at {L['street']} {plain_status(status)}."


def already_noted(L: dict, dim_label: str, status: str) -> str:
    return f"I already have that reply noted: {dim_label.lower()} at {L['street']} {plain_status(status)}."


def folded_in() -> str:
    return "I've folded that in before ranking."


NOW_PHRASE = {"supported": "is now confirmed", "conflict": "now clashes with what you asked", "inferred": "is now likely, but not confirmed",
              "unknown": "is open again"}


def now_phrase(status: str) -> str:
    """中介回复翻格后的说法（不说 goes from inferred to conflict 这种内部词）。"""
    return NOW_PHRASE.get(status, f"is now {status}")


def welcome_search(summary_text: str, changes: Dict[str, str], greeted: bool = False, extra: str = "", brief: bool = False) -> str:
    """开查前的那句。greeted = 机器已经先问过 "same again?"，就不再说 Welcome back（也不再重复 extra，那句开场已经说过）。
    brief（简短播报）：需求在页面上（欢迎框和需求 chip），不再整段复述，只说变了什么。"""
    tail = f" {extra}" if (extra and not greeted) else ""
    if changes:
        bits = join(change_bits(changes))
        if greeted:
            return f"Got it: {bits}, and the rest as last time."
        if brief:
            return f"Welcome back. This time {bits}, and the rest as before.{tail}"
        return f"Welcome back. Last time it was {summary_text}; this time {bits}, and the rest as before.{tail}"
    if greeted:
        return "Same as last time, then."
    if brief:
        return f"Welcome back. Same as last time.{tail}"
    return f"Welcome back. Same as last time: {summary_text}.{tail}"


def change_sentence(L: dict, dim_label: str, old: str, new: str, consequence: str) -> str:
    s = f"Noted. At {L['street']}, {dim_label.lower()} {now_phrase(new)}."
    if consequence:
        s += " " + consequence
    return s


# ---------------------------------------------------------------- 简短播报（10-28，docs/12）
# 每套房三句：地址 + 租金 + 通勤；和需求不一样或还没确认的最多两件（全对就一句 checks out）；最该问中介的一句。
# 和需求一样的事不念（卡片上都打着勾）；不说 supported / inferred / cell 这类内部词。说 "tell me more" 再逐格展开（policy._detail）。
BRIEF_LEAD = [["Top pick", "First up", "Best match"], ["Second", "Number two", "Second up"], ["Third", "And third", "Number three"], ["Fourth"], ["Fifth"]]
CAVEAT = {  # 维度 → 状态 → 短语（小写开头，拼进 "Two things to check: …"）
    "A1": {"conflict": "it's over your budget"},
    "B1": {"conflict": "it has fewer bedrooms than you asked"},
    "G1": {"conflict": "the commute is over your limit", "inferred": "the commute is only an estimate", "unknown": "I don't have the commute time"},
    "A4": {"conflict": "it's free {gap} days after you need it", "unknown": "there's no move-in date", "inferred": "the move-in date isn't confirmed"},
    "J1": {"inferred": "pets aren't confirmed", "unknown": "pets aren't confirmed", "conflict": "pets aren't allowed"},
    "C1": {"inferred": "bedroom air con isn't confirmed", "unknown": "bedroom air con isn't confirmed", "conflict": "there's no air con in the bedroom"},
    "A6": {"inferred": "bills aren't confirmed", "unknown": "it doesn't say which bills are included", "conflict": "bills aren't included"},
    "C2": {"inferred": "it may not come furnished", "unknown": "furniture isn't mentioned", "conflict": "it's unfurnished"},
    "C3": {"inferred": "the cooktop type isn't confirmed", "unknown": "the cooktop type isn't confirmed", "conflict": "the cooktop isn't the kind you want"},
    "D1": {"inferred": "its condition isn't confirmed", "unknown": "its condition isn't covered", "conflict": "it looks dated"},
    "E4": {"inferred": "quiet isn't confirmed", "unknown": "noise isn't covered", "conflict": "it may be noisy"},
    "E2": {"inferred": "sunlight isn't confirmed", "unknown": "sunlight isn't covered", "conflict": "it may not get much sun"},
}
Q_SHORT = {  # 问中介的那句（问句本体）
    "A1": "is the rent still {rent} a week?", "B1": "how many rooms count as bedrooms?", "A4": "can the move-in date come forward?",
    "J1": "are pets okay, in writing?", "C1": "is there air con in the bedrooms?", "A6": "which bills are included?", "C2": "what furniture stays?",
    "C3": "what kind of cooktop is it?", "D1": "when were the kitchen and bathroom last done?", "E4": "is it quiet at night?",
    "E2": "which way does the living room face?", "G1": "how long is the real trip to {anchor}?", "H1": "the five-year crime disclosure",
    "K1": "which level is it on?", "K2": "can you send the floor plan?", "K3": "can you send the floor plan?", "K4": "can you send the floor plan?",
}
Q_TOPIC = {"A1": "the rent", "B1": "the bedrooms", "A4": "the move-in date", "J1": "pets in writing", "C1": "bedroom air con", "A6": "the bills",
           "C2": "what furniture stays", "C3": "the cooktop", "D1": "the condition", "E4": "noise", "E2": "which way it faces", "G1": "the real trip time",
           "K1": "the level", "K2": "the floor plan", "K3": "the floor plan", "K4": "the floor plan"}
LABEL_PLAIN = {"A1": "rent", "B1": "bedrooms", "G1": "commute", "A4": "move-in", "J1": "pets", "C1": "bedroom air con", "A6": "bills", "C2": "furniture",
               "C3": "cooktop", "D1": "condition", "E4": "quiet", "E2": "sunlight", "H1": "the crime disclosure", "K1": "the number check",
               "K2": "the through-line check", "K3": "the door check", "K4": "the outline check"}


def join_and(parts: List[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def street_name(street: str) -> str:
    """"31 Fenwick Street" → "Fenwick Street"：比较、清单里说短名。"""
    return re.sub(r"^\d+[a-z]?(?:\s*[/-]\s*\d+)?\s+", "", str(street or "")).strip() or str(street or "")


def commute_bit(c: Optional[dict], profile: dict) -> str:
    if not c or c["status"] == "unknown" or not c.get("value"):
        return ""
    v, a = c["value"], profile.get("anchor") or "your anchor"
    if c.get("estimate") or c["status"] == "inferred":
        return f"about {v['min']} minutes to {a}"
    if str(v.get("mode") or "").lower() in ("walk", "walking", "on foot"):
        return f"a {v['min']}-minute walk to {a}"
    return f"{v['min']} minutes to {a} by {v['mode']}"


def brief_intro(i: int, L: dict, cells: Dict[str, dict], profile: dict, variety: bool = False) -> str:
    """Top pick: 31 Fenwick Street in Zetland, 890 a week, 16 minutes to UNSW by bus."""
    lead = _choose(BRIEF_LEAD[min(i, len(BRIEF_LEAD) - 1)], variety)
    bits = [f"{L['street']} in {L['suburb']}", f"{L['rent']} a week"]
    cb = commute_bit(cells.get("G1"), profile)
    if cb:
        bits.append(cb)
    return f"{lead}: " + ", ".join(bits) + "."


def caveat(dim: str, c: dict) -> str:
    st, why = c["status"], str(c.get("why") or "").lower()
    if dim == "C2" and "staged" in why:
        return "the photos are virtually staged"
    if dim == "C1" and st != "supported" and "living room" in why:
        return "the air con looks living-room only"
    if dim == "D1" and c.get("notable"):
        return "the photos show it's dated"
    if dim in ("K1", "K2", "K3", "K4"):
        return f"{LABEL_PLAIN[dim]} isn't confirmed" if st != "conflict" else f"it fails {LABEL_PLAIN[dim]}"
    t = (CAVEAT.get(dim) or {}).get(st) or f"{LABEL_PLAIN.get(dim, dim)} isn't confirmed"
    return t.format(gap=c.get("gap_days", 0))


def short_special(L: dict) -> str:
    """挂牌的"特别之处"够短（≤ 14 个词、不是引号里的原话）才说："It's the closest of the three to UNSW, nine minutes on foot."。"""
    sp = str(L.get("special") or "").strip().rstrip(".")
    if not sp or "'" in sp or '"' in sp or len(sp.split()) > 14:
        return ""
    sp = re.sub(r"^it is\b", "it's", sp, flags=re.I)
    return cap(sp) + "."


def brief_verdict(asked: List[str], notable: List[str], special: str = "", variety: bool = False) -> str:
    """asked = 租客要的、还没落实的（最多两件进这句）；notable = 没问但照片说了的坏消息（盖章家具、看着旧）。"""
    lead = f"{special} " if special else ""
    if not asked:
        ok = _choose(["Everything you asked for checks out", "It ticks everything you asked for"], variety)
        return lead + (f"{ok}, but {notable[0]}." if notable else f"{ok}.")
    if len(asked) == 1:
        return lead + _choose(["One thing to check: {a}.", "One catch: {a}."], variety).format(a=asked[0])
    return lead + _choose(["Two things to check: {a}, and {b}.", "Two things aren't settled: {a}, and {b}."], variety).format(a=asked[0], b=asked[1])


def rank_again(street: str, n_now: int, n_before: Optional[int]) -> str:
    """改需求后，被打断时正在讲的那套，代替刚听过的开头那句：Fenwick Street is still the top pick. / Alder Lane is now number two."""
    where = "the top pick" if n_now == 1 else f"number {NUM_WORDS.get(n_now, str(n_now))}"
    return f"{street_name(street)} is {'still' if n_before == n_now else 'now'} {where}."


def verdict_again(dims: List[str]) -> str:
    """和前面某套的那句一字不差时换的说法（10-28 模拟顾客 P04：两套都是宠物、卧室空调没落实，同一句说了两遍）。"""
    labels = [LABEL_PLAIN.get(d, d) for d in dims]
    if not labels:
        return "This one checks out too."
    if len(labels) == 1:
        return f"Same open point here: {labels[0]}."
    return f"Same {NUM_WORDS.get(len(labels), str(len(labels)))} open points here: {join_and(labels)}."


def q_short(dim: str, c: dict, profile: dict, L: Optional[dict] = None) -> str:
    if dim == "A4" and c.get("status") == "unknown":
        return "what's the earliest move-in date?"
    return Q_SHORT.get(dim, "can you confirm that in writing?").format(rent=(L or {}).get("rent", ""), anchor=profile.get("anchor") or "your anchor")


def brief_question(dim: str, c: dict, profile: dict, L: dict, asked_before: int, variety: bool = False) -> str:
    """asked_before = 前面几套问过同一个问题几次：第二次 "Same question for this agent: …"，第三次 "Same pets question here too."（不一字不差说两遍）"""
    if asked_before >= 2:
        return f"Same {LABEL_PLAIN.get(dim, 'question').removeprefix('the ')} question here too."
    if asked_before:
        return f"Same question for this agent: {Q_TOPIC.get(dim, 'the same thing')}."
    return _choose(["Ask the agent: {q}", "Worth asking the agent: {q}"], variety).format(q=q_short(dim, c, profile, L))


VIEW_VERBS = r"(?:check|look|ask|see|test|open|run|try|take|make|measure|note|bring|count|listen|feel|turn|flush|stand|walk|compare|photograph)\b"


def brief_viewing(dim: str, c: dict) -> str:
    """At the viewing, check the benchtops, tiles and carpet.（提示是名词清单时补上动词，以前念成 "At the viewing, benchtops, tiles, carpet."）"""
    hint = str((c.get("next") or {}).get("hint") or "take a close look at it").strip().rstrip(".")
    if not re.match(VIEW_VERBS, hint, re.I):
        parts = [x.strip() for x in hint.split(",") if x.strip()]
        hint = "check the " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else hint)
    return f"At the viewing, {hint[0].lower() + hint[1:]}."


def brief_opening(missing: List[str], n_sources: int, vague: Optional[str] = None) -> str:
    """开场只说"在查"（需求已经在左边的芯片上，不再复述）；缺必填就把假设说出口；说了量不了的地方（the beach）就明说量不了。"""
    a = assumptions(missing)
    v = f"I can't measure trips to {vague} yet." if vague else ""
    return " ".join(x for x in [a, v, f"Checking {n_sources} sources now."] if x)


def brief_found(n_pass: int, n_show: int) -> str:
    if n_pass == 0:
        return "Nothing passes the basics yet. Here are the closest misses."
    if n_pass == 1:
        return "One place fits:"
    if n_show >= n_pass:
        return f"{n_pass} fit:"
    return f"{n_pass} fit. The top {NUM_WORDS.get(n_show, str(n_show))}:"


def brief_wrap(n: int, legal_pending: bool) -> str:
    what = {1: "That's the one.", 2: "That's the two."}.get(n, f"That's the {NUM_WORDS.get(n, str(n))}.")
    tail = ", including a legal must-ask?" if legal_pending else "?"
    return f"{what} Want details on one, or the questions for the agents{tail}"


def headline(i: int, L: dict, cells: Dict[str, dict], profile: dict) -> str:
    """"just the headlines" 之后：每套只剩这一句。"""
    lead = ["First", "Second", "Third", "Fourth", "Fifth"][min(i, 4)]
    cb = commute_bit(cells.get("G1"), profile)
    return f"{lead}, {street_name(L['street'])}: {L['rent']} a week" + (f", {cb}" if cb else "") + "."


def noted(changes: Dict[str, str]) -> str:
    """改需求后的确认：Furnished, noted. / Under 800 a week, noted."""
    bits = []
    for k, v in changes.items():
        bits.append({"budget": v, "bedrooms": f"{v} bedrooms", "anchor": f"commute to {v}", "move_in": f"move-in {v}", "pets": v, "extras": v,
                     "max_commute": f"{v} minutes max"}.get(k, str(v)))
    return cap(join(bits)) + ", noted."


def shortlist_diff(dropped: List[str], added: List[str], same_order: bool, new_top: Optional[str]) -> str:
    if not dropped and not added:
        if same_order:
            return "Same top three."
        return f"Same three, but {new_top} moves to the top." if new_top else "Same three, in a new order."
    d = join_and([street_name(s) for s in dropped])
    a = join_and([street_name(s) for s in added])
    if dropped and added:
        return f"{d} drop{'s' if len(dropped) == 1 else ''} out; {a} come{'s' if len(added) == 1 else ''} in."
    if dropped:
        return f"{d} drop{'s' if len(dropped) == 1 else ''} out."
    return f"{a} come{'s' if len(added) == 1 else ''} in."


def condition_line(dim: str, yes: List[str], no: List[str]) -> str:
    """新加的条件在前几套里的情况：On furniture, only Botany Road checks out. / On furniture, none of them is confirmed yet; it's on your agent questions."""
    lab = LABEL_PLAIN.get(dim, dim)
    if not yes:
        return f"On {lab}, none of them is confirmed yet, so it's on your agent questions."
    if not no:
        return f"On {lab}, all of them check out."
    return f"On {lab}, only {join_and([street_name(s) for s in yes])} check{'s' if len(yes) == 1 else ''} out."


def dropped_line(L: dict) -> str:
    return f"Okay, {street_name(L['street'])} is off the list."


def plain_status(st: str) -> str:
    return {"supported": "checks out", "inferred": "isn't confirmed", "conflict": "doesn't match what you asked", "unknown": "isn't confirmed"}.get(st, st)


def first_sentence(s: str, max_words: int = 26) -> str:
    s = str(s or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    out = m.group(1) if m else s
    w = out.split()
    return " ".join(w[:max_words]).rstrip(",;:") + ("." if len(w) > max_words else "")


def answer_plain(dim: str, c: dict, L: dict, profile: dict) -> str:
    """答问：先说结论（是 / 不是 / 没确认），再给一句依据；不说内部词。"""
    st, name = c["status"], street_name(L["street"])
    if dim == "A1":
        b = profile.get("budget")
        tail = f", {'inside' if st == 'supported' else 'over'} your {b} budget" if b else ""
        return f"{name} is {L['rent']} a week{tail}."
    if dim == "B1":
        return f"{name} has {beds_phrase(L['bedrooms'])}."
    if dim == "G1":
        cb = commute_bit(c, profile)
        if not cb:
            return f"I don't have the commute time from {name} yet; it's on your agent questions."
        return f"From {name}, it's {cb}" + (", estimated from the distance." if c.get("estimate") else ".")
    if dim == "A4":
        if not c.get("value"):
            return f"{name} doesn't list a move-in date; ask the agent for the earliest one."
        return f"{name} is available from {c['value']}" + ("." if st == "supported" else f", {c.get('gap_days', 0)} days after you need it.")
    lead = {"supported": "Yes", "conflict": "No", "inferred": "Probably, but it's not confirmed", "unknown": "Not confirmed"}[st]
    why = first_sentence(c.get("why") or "")
    return f"{lead}, at {name}." + (f" {why}" if why else "")


def no_fact_plain(L: dict, topic: str) -> str:
    return f"I don't know about {topic} at {street_name(L['street'])} yet. I've added it to your agent questions."


def bond_line(L: dict) -> str:
    """NSW 押金上限四周房租（Residential Tenancies Act 2010 s 159）：挂牌没写押金时给的上限，不是实际押金。"""
    return (f"The listing doesn't say. In NSW the bond can't be more than four weeks' rent, so at most {4 * int(L['rent'])} "
            f"for {street_name(L['street'])}. I've added it to your agent questions.")


def compare_dim(dim: str, items: List[dict], profile: dict) -> str:
    """一项比几套：On commute: Alder Lane, 9 minutes walking; Fenwick Street, 16 by bus; …"""
    if dim == "A1":
        xs = sorted(items, key=lambda it: it["listing"]["rent"])
        return "Cheapest first: " + "; ".join(f"{street_name(it['listing']['street'])}, {it['listing']['rent']}" for it in xs) + "."
    if dim == "G1":
        def mins(it):
            v = (it["cells"].get("G1") or {}).get("value") or {}
            return v.get("min", 999)
        xs = sorted(items, key=mins)
        bits = []
        for it in xs:
            cb = commute_bit(it["cells"].get("G1"), profile)
            bits.append(f"{street_name(it['listing']['street'])}, {cb or 'no time yet'}")
        return "Closest first: " + "; ".join(bits) + "."
    if dim == "B1":
        return "; ".join(f"{street_name(it['listing']['street'])} has {beds_phrase(it['listing']['bedrooms'])}" for it in items) + "."
    lab = LABEL_PLAIN.get(dim, dim)
    good = [street_name(it["listing"]["street"]) for it in items if (it["cells"].get(dim) or {}).get("status") == "supported"]
    bad = [street_name(it["listing"]["street"]) for it in items if (it["cells"].get(dim) or {}).get("status") != "supported"]
    if not good:
        return f"On {lab}, none of them is confirmed yet; it's on your agent questions."
    if not bad:
        return f"On {lab}, all of them check out."
    return f"On {lab}, {join_and(good)} check{'s' if len(good) == 1 else ''} out; {join_and(bad)} {'isn' if len(bad) == 1 else 'aren'}'t confirmed."


def _open_bits(it: dict) -> List[str]:
    return [caveat(d, c) for d, c in it["cells"].items() if d != "H1" and not c.get("notable") and c["status"] != "supported"]


def compare_pair(a: dict, b: dict, profile: dict) -> str:
    """两套比：Fenwick Street is 890 a week, 16 minutes to UNSW by bus, and everything checks out. Alder Lane is 130 cheaper, …"""
    out = []
    for k, it in enumerate((a, b)):
        L = it["listing"]
        bits = []
        if k == 1 and L["rent"] != a["listing"]["rent"]:
            diff = L["rent"] - a["listing"]["rent"]
            bits.append(f"{abs(diff)} {'cheaper' if diff < 0 else 'dearer'}")
        else:
            bits.append(f"{L['rent']} a week")
        cb = commute_bit(it["cells"].get("G1"), profile)
        if cb:
            bits.append(cb)
        ob = _open_bits(it)
        tail = "and everything checks out" if not ob else f"but {ob[0]}" + (f" and {ob[1]}" if len(ob) > 1 else "")
        out.append(f"{street_name(L['street'])} is " + ", ".join(bits) + f", {tail}.")
    return " ".join(out)


def comparative(cur: dict, other: dict, dim: str, profile: dict) -> Optional[str]:
    """"Is the next one cheaper?" / "Is the third one closer?"：一句话答（和正在讲的那套比）。只管租金和通勤，别的返回 None。"""
    a, b = cur["listing"], other["listing"]
    if dim == "A1":
        diff = b["rent"] - a["rent"]
        if diff == 0:
            return f"Same rent: {street_name(b['street'])} is also {b['rent']} a week."
        return (f"{'Yes' if diff < 0 else 'No'}, {street_name(b['street'])} is {b['rent']} a week, "
                f"{abs(diff)} {'less' if diff < 0 else 'more'} than {street_name(a['street'])}.")
    if dim == "G1":
        va, vb = (cur["cells"].get("G1") or {}).get("value") or {}, (other["cells"].get("G1") or {}).get("value") or {}
        if not va.get("min") or not vb.get("min"):
            return None
        cb = commute_bit(other["cells"].get("G1"), profile)
        closer = vb["min"] < va["min"]
        return f"{'Yes' if closer else 'No'}, {street_name(b['street'])} is {cb}, against {va['min']} from {street_name(a['street'])}."
    return None


def ranking_plain(ranked: List[dict]) -> str:
    if not ranked:
        return "Nothing passes the basics yet."
    top = ranked[0]
    ob = _open_bits(top)
    s = f"I'd start with {street_name(top['listing']['street'])}: " + ("everything you asked for checks out." if not ob else f"most of it checks out, but {ob[0]}.")
    cheapest = min(ranked, key=lambda r: r["listing"]["rent"])
    if cheapest is not top:
        s += f" {street_name(cheapest['listing']['street'])} is the cheapest at {cheapest['listing']['rent']}."
    return s


def questions_text(items: List[Tuple[str, str]], legal_pending: bool, extra: List[str]) -> str:
    """把问题清单念出来：Fenwick Street: what furniture stays? Alder Lane: are pets okay, in writing? … And for all of them: the crime disclosure."""
    parts, seen = [], {}
    for name, q in items:
        if q in seen:
            parts.append(f"{name}: same as {seen[q]}.")
        else:
            seen[q] = name
            parts.append(f"{name}: {q}")
    if extra:
        parts.append("You also asked about " + join_and(extra) + ".")
    if legal_pending:
        parts.append("And for all of them: the five-year crime disclosure. It's a legal must-ask before you sign.")
    return "Here's what to ask. " + " ".join(parts) if parts else "There's nothing left to ask the agents."


def confirm_same(fields: Dict[str, str]) -> str:
    return "Yes, " + join_and(list(fields.values())) + ". That's what I'm searching for."
