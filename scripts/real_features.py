#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性：把 9 套 Domain 真房源的设施清单（data/real/domain/<DomainId>.json 的 features 数组）抄进 src/voice/mock_matrix.json
对应 listing（id = L-D<DomainId>）的 `features` 字段。只加 / 覆盖这一个字段，别的不动；Domain 页上没有设施的留空数组。
文件按原来的格式写回（indent=1、不转义中文、末尾换行），所以 diff 只有加的那几行。

跑：python3 scripts/real_features.py        （--dry 只打印，不写）
之后 /api/listings 的 listing_summary 会带 features（src/voice/policy.py），详情页画成 Domain 式的三列网格（static/qi/property-detail.js）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / "data" / "real" / "domain"
MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"


def main() -> int:
    dry = "--dry" in sys.argv
    feats: dict[str, list[str]] = {}
    for f in sorted(DOMAIN.glob("*.json")):
        o = json.loads(f.read_text(encoding="utf-8"))
        items = [str(x).strip() for x in (o.get("features") or []) if str(x).strip()]
        feats[f"L-D{o['id']}"] = list(dict.fromkeys(items))  # 去重、保持顺序，文字照 Domain 原样
    raw = MATRIX.read_text(encoding="utf-8")
    m = json.loads(raw)
    n = 0
    for L in m["listings"]:
        if L["id"] in feats:
            L["features"] = feats[L["id"]]
            n += 1
            print(f"{L['id']}: {len(feats[L['id']])} features {feats[L['id']]}")
    missing = sorted(set(feats) - {L["id"] for L in m["listings"]})
    if missing:
        print("not in the matrix (skipped):", missing)
    out = json.dumps(m, indent=1, ensure_ascii=False) + "\n"
    if dry:
        print(f"dry run: {n} listings would get a features field")
        return 0
    MATRIX.write_text(out, encoding="utf-8")
    print(f"wrote {MATRIX.relative_to(ROOT)}: {n} listings got a features field")
    return 0


if __name__ == "__main__":
    sys.exit(main())
