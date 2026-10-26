"""措辞模板（英文）。每句话都从一个格子和它的证据生成；程序决定说什么，这里只决定怎么说。
拿到 Nemotron key 后可以让模型润色，但输入仍然是这些格子，模型不能自由发挥。"""
from __future__ import annotations

import os
import random
from typing import Dict, List, Optional

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


def ask_sentence(fields: List[str]) -> str:
    """反问句本体，不带开头（开头是 bridge）。"""
    qs = [QUESTIONS[f] for f in fields]
    if len(qs) >= 2:
        return f"Two quick things before I search: {qs[0]}, and {qs[1]}?"
    return f"One quick thing before I search: {qs[0]}?"


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
        if med.get("rent"):  # 真房源：Domain 的本区中位租金（广告说 vs 来源说）
            pct = med.get("pct") or 0
            tail = f" That's {'about the' if abs(pct) < 2 else f'{abs(pct)} percent ' + ('above' if pct > 0 else 'below')} {med['suburb']}'s median of {med['rent']} for {med.get('beds') or 2} bedrooms."
        if st == "supported":
            return f"Rent is {L['rent']} a week, inside your {profile['budget']} budget.{tail}"
        return f"Rent is {L['rent']} a week, over your {profile['budget']} budget.{tail}"
    if dim == "B1":
        if st == "supported":
            return f"{beds_phrase(L['bedrooms']).capitalize()}, as asked."
        return f"Only {beds_phrase(L['bedrooms'])}, so it misses your {beds_phrase(profile['bedrooms'])}."
    if dim == "G1":
        if st == "unknown":
            return f"I don't have a transit row for {profile['anchor']} yet, so the commute is unknown until I add it."
        v = c["value"]
        if st == "supported":
            return f"{v['min']} minutes to {profile['anchor']} by {v['mode']}, from the transit table, so that's supported."
        if st == "inferred":  # 真房源：直线距离估的
            return f"About {v['min']} minutes to {profile['anchor']} by {v['mode']}, estimated from the distance, not a timetable, so I can only infer."
        return f"{v['min']} minutes to {profile['anchor']}, over your {profile.get('max_commute', 40)} minute limit" + (", and that's only an estimate from the distance." if v.get("estimate") else ".")
    if dim == "A4":
        if st == "supported":
            return f"Available from {c['value']}, which works for {profile['move_in']['text']}."
        return f"Available from {c['value']}, about {c.get('gap_days', 0)} days after {profile['move_in']['text']}, so that's a conflict unless the date moves."
    label = {"J1": "Pets", "C1": "Bedroom air con", "A6": "Bills", "C2": "Furniture", "C3": "Stove", "E4": "Quiet", "E2": "Sunlight", "D1": "Condition",
             "K1": "Numbers", "K2": "Through-line", "K3": "Doors", "K4": "Outline"}.get(dim, dim)
    if not c.get("evidence") and st == "unknown" and dim in ("C2", "E4", "E2", "D1", "K1", "K2", "K3", "K4"):
        return f"{label}: nothing in the materials covers it, so unknown."
    lead = {"supported": f"{label}: supported.", "inferred": f"{label}: I can only infer.", "conflict": f"{label}: a conflict.", "unknown": f"{label}: unknown."}[st]
    return f"{lead} {c.get('why', '')}".strip()


def special(L: dict) -> str:
    return f"What's special here: {L['special']}." if L.get("special") else ""


BEST_Q = {
    "J1": "Best question for this agent: are pets allowed, in writing? A yes turns that cell from {status} to supported.",
    "C1": "Best question for this agent: is there air con in the bedrooms, not just the living room?",
    "G1": "Best thing to check: how long does it really take to {anchor}? I don't have a transit row yet.",
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
        parts.append("One more thing for all of them: the five-year violent-crime disclosure hasn't been asked yet. It's a legal must-ask before you sign, so it stays unknown until the agents answer.")
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
    core = f"the agent for {L['street']} says {dim_label.lower()} goes from {old} to {new}"
    if live:
        s = f"Just in{', ' + by if by else ''}: {core}."
        return s + (" " + consequence if consequence else "")
    if by:
        return f"{cap(by)}, {core}; I've folded that in before ranking."
    return f"{cap(core)}; I've folded that in before ranking."


def inbox_unmapped(L: dict, channel: Optional[str]) -> str:
    return f"The agent for {L['street']} also replied{channel_words(channel)}, but I couldn't tell which condition it answers, so I've left it alone."


def same_as_sources(L: dict, dim_label: str, status: str) -> str:
    return f"That matches what the sources already say: {dim_label.lower()} at {L['street']} stays {status}."


def already_noted(L: dict, dim_label: str, status: str) -> str:
    return f"I already have that reply noted: {dim_label.lower()} at {L['street']} is {status}."


def folded_in() -> str:
    return "I've folded that in before ranking."


def welcome_search(summary_text: str, changes: Dict[str, str], greeted: bool = False, extra: str = "") -> str:
    """开查前的那句。greeted = 机器已经先问过 "same again?"，就不再说 Welcome back（也不再重复 extra，那句开场已经说过）。"""
    tail = f" {extra}" if (extra and not greeted) else ""
    if changes:
        bits = join(change_bits(changes))
        if greeted:
            return f"Got it: {bits}, and the rest as last time."
        return f"Welcome back. Last time it was {summary_text}; this time {bits}, and the rest as before.{tail}"
    if greeted:
        return "Same as last time, then."
    return f"Welcome back. Same as last time: {summary_text}.{tail}"


def change_sentence(L: dict, dim_label: str, old: str, new: str, consequence: str) -> str:
    s = f"Noted. For the {L['street']} place, {dim_label.lower()} goes from {old} to {new}."
    if consequence:
        s += " " + consequence
    return s
