#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往某位租客的收件箱里放一条中介回复（演示里替代邮件 / 短信的 webhook）。

  python3 scripts/agent_reply.py --renter r-xxxx --listing L-0003 --text "Pets are fine with the owners corporation's consent" [--channel email] [--port 8630]
  python3 scripts/agent_reply.py --renter r-xxxx --list           # 看这位租客有几条没读

租客编号在浏览器的 localStorage（键 ht_renter），页面右下角 Forget me 旁边也看得到；8630 和 8631 都有 /api/inbox，放一次两边都认（同一个文件）。
租客下次回来：开场 "While you were away, the agent for … replied"，Same again 之后那一格翻转、排名重排、信念日志 v1 → v2。"""
import argparse
import json
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--renter", required=True, help="浏览器 localStorage 里的 ht_renter")
    ap.add_argument("--listing", help="房源编号，如 L-0003")
    ap.add_argument("--text", help="中介回复原文（英文）")
    ap.add_argument("--channel", default="email", help="email / sms / phone / portal（只是记录，默认 email）")
    ap.add_argument("--port", type=int, default=8630)
    ap.add_argument("--list", action="store_true", help="只看未读")
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.port}"
    if a.list:
        with urllib.request.urlopen(f"{base}/api/hello?renter={a.renter}", timeout=5) as r:
            h = json.loads(r.read().decode("utf-8"))
        away = ((h.get("memory") or {}).get("away")) or {"unread": 0, "items": []}
        print(json.dumps(away, ensure_ascii=False, indent=1))
        return 0
    if not a.listing or not a.text:
        ap.error("--listing and --text are required unless --list")
    body = json.dumps({"renter": a.renter, "listing_id": a.listing, "text": a.text, "channel": a.channel}).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/inbox", data=body, headers={"Content-Type": "application/json", "User-Agent": "HomeTruth-client/1"}, method="POST")  # 公网经 Cloudflare：Python-urllib 的默认 UA 会被浏览器完整性检查拦（1010）
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            print(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
