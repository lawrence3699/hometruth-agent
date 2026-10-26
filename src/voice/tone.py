#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情绪标签：给认标签的合成模型（ElevenLabs v3 / v4 系列）在句首加一个方括号标签，比如 "[happy] Found some. Three places tick the basics."
标签只进嘴（送去合成的文本），不进字幕、事件、日志、回归基线——UI 和 8630 浏览器版看到的台词一个字都不变。
谁来挑标签：规则，按这句话在流程里的位置（step）和它说的那个格子的状态（supported / inferred / conflict / unknown）。
不交给模型挑：事实不受影响、零延迟、可预期；标签词表是 ElevenLabs 文档里 v3 认的那种情绪 / 语气描述词。
用法：mood = Mood(enabled)；每个事件按顺序过一遍 mood.tag(ev)（它要看 highlight 事件记住格子状态）；对 say 事件返回标签或 None。"""
from __future__ import annotations

import re
from typing import Optional

TAG_RE = re.compile(r"^\s*\[[a-z][a-z ,'-]{1,30}\]\s*", re.I)
TOUR_RE = re.compile(r"^L\d+(?:\.(.+))?$")
WORD_RE = re.compile(r"[A-Za-z0-9']+")

MIN_WORDS = 3  # 一两个词的过渡句（"Okay." / "Great, thanks."）不加：标签比句子长，念出来反而怪

STEP_TAGS = {
    "heard": "[thoughtful]",     # "So: two bedrooms, under 900 a week…"
    "ask": "[curious]",          # 反问预算 / 入住时间
    "opening": "[thoughtful]",   # "Let me pull up what fits near Central."
    "shortlist": "[happy]",      # "Found some. Three places tick the basics…"
    "update": "[reassuring]",    # 改了条件后的确认
    "resume": "[cheerful]",
    "next": "[cheerful]",        # "Okay, moving on."
    "stop": "[calm]",
    "back": "[thoughtful]",      # "Okay, where was I. The first place."
    "unclear": "[gentle]",       # 没听清
    "agent": "[curious]",
    "change": "[thoughtful]",    # 中介回复后"什么变了"
    "wrap": "[warmly]",
    "welcome": "[warmly]",       # "Welcome back. Last time it was…"
}
STATUS_TAGS = {"inferred": "[thoughtful]", "conflict": "[concerned]", "unknown": "[curious]"}  # supported 的格子不加，平实地说
THINKING_RE = re.compile(r"\b(let me|hmm|one sec|checking|hang on)\b", re.I)
OPEN_RE = re.compile(r"no checked fact|can't confirm|cannot confirm|not (been )?checked|ask the agent|no fact|unknown|not sure", re.I)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def tag_for(step: str, text: str, status: Optional[str] = None) -> Optional[str]:
    """这句话（step、文本、所讲格子的状态）配哪个标签；None = 不加。"""
    if word_count(text) < MIN_WORDS:
        return None
    m = TOUR_RE.match(step or "")
    if m:
        part = m.group(1)
        if part is None:
            return "[upbeat]"            # "First up: a two-bedroom on 31 Fenwick Street…"
        if part == "special":
            return "[cheerful]"
        if part == "question":
            return "[thoughtful]"        # 最值得问中介的那一句
        if part == "next":
            return "[cheerful]"
        return STATUS_TAGS.get(status or "")
    if step == "answer":
        return "[thoughtful]" if OPEN_RE.search(text) else "[reassuring]"
    if step == "bridge":
        return "[thoughtful]" if THINKING_RE.search(text) else "[warmly]"
    return STEP_TAGS.get(step or "")


def strip_tags(text: str) -> str:
    """把句首标签去掉（字幕、日志、测试用）。"""
    return TAG_RE.sub("", text or "", count=1)


class Mood:
    """按顺序喂事件：highlight 事件告诉它接下来那句讲的格子是什么状态；say 事件返回标签。enabled=False 时永远 None。"""

    def __init__(self, enabled: bool):
        self.enabled = bool(enabled)
        self.status: Optional[str] = None
        self.tagged = 0

    def tag(self, ev: dict) -> Optional[str]:
        kind = ev.get("type")
        if kind == "highlight":
            self.status = ev.get("status")
            return None
        if kind != "say" or not self.enabled:
            return None
        t = tag_for(ev.get("step") or "", ev.get("text") or "", self.status)
        if t:
            self.tagged += 1
        return t

    def speak(self, ev: dict) -> str:
        """送去合成的文本：有标签就加在句首，没有就是原句。每个事件只能喂一次。"""
        t = self.tag(ev)
        text = ev.get("text") or ""
        return f"{t} {text}" if t else text
