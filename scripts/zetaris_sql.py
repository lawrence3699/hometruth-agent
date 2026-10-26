#!/usr/bin/env python3
"""HomeTruth · Zetaris SQL 小工具（只依赖标准库，不需要装包）。

用法：
  python3 scripts/zetaris_sql.py "SELECT 1"
  python3 scripts/zetaris_sql.py --file scripts/zetaris/02_query_smoke.sql     # 文件里多条语句按 ; 顺序执行
  python3 scripts/zetaris_sql.py --limit 5 --json "SELECT * FROM hometruth_smoke.weather_cottage_point"

配置：读项目根目录的 .env（ZETARIS_BASE_URL / ZETARIS_ORG_ID / ZETARIS_API_KEY / ZETARIS_USER_AGENT）。
接口：POST {ZETARIS_BASE_URL}/api/proxy/sql-editor/sqls/run-query，body {"sql", "limit"}，
      头 Authorization: Bearer <API key>、X-Org-ID、X-Request-ID（每次一个新 UUID）。
日志：每次调用追加一行到 runs/zetaris_log.jsonl（request_id、sql、耗时、行数、是否成功）。
      Zetaris 这个接口不返回 queryId，所以"这条证据来自哪次查询"以我们自己的 request_id 为准。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "runs" / "zetaris_log.jsonl"


def load_env(path: Path = ROOT / ".env") -> None:
    """把 .env 里的 KEY=VALUE 放进环境变量（已存在的不覆盖）。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def split_statements(text: str) -> list[str]:
    """按引号外的 ; 切分多条语句，去掉 -- 注释行。"""
    lines = [l for l in text.splitlines() if not l.strip().startswith("--")]
    text = "\n".join(lines)
    out, buf, quote = [], [], None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ";":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def run(sql: str, limit: int) -> dict:
    base = os.environ.get("ZETARIS_BASE_URL", "").rstrip("/")
    org = os.environ.get("ZETARIS_ORG_ID", "")
    key = os.environ.get("ZETARIS_API_KEY", "")
    if not (base and org and key):
        raise RuntimeError("缺 ZETARIS_BASE_URL / ZETARIS_ORG_ID / ZETARIS_API_KEY，请检查项目根目录 .env")
    request_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {key}",
        "X-Org-ID": org,
        "X-Request-ID": request_id,
        "Content-Type": "application/json",
    }
    if os.environ.get("ZETARIS_USER_AGENT"):
        headers["User-Agent"] = os.environ["ZETARIS_USER_AGENT"]
    body = json.dumps({"sql": sql, "limit": limit}, ensure_ascii=False).encode("utf-8")
    req = Request(f"{base}/api/proxy/sql-editor/sqls/run-query", data=body, headers=headers, method="POST")
    entry = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "request_id": request_id, "sql": sql, "limit": limit}
    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        entry.update(ok=True, time_used_ms=result.get("timeUsed"), rows=len(result.get("data") or []))
        return {"request_id": request_id, **result}
    except HTTPError as e:
        detail = e.read(800).decode("utf-8", errors="replace")
        entry.update(ok=False, error=f"HTTP {e.code} {detail}")
        raise RuntimeError(f"Zetaris 返回 HTTP {e.code}: {detail}") from e
    except (OSError, TimeoutError, URLError) as e:
        entry.update(ok=False, error=str(e))
        raise RuntimeError(f"连不上 {base}: {e}") from e
    finally:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def print_table(result: dict) -> None:
    headers = result.get("headers") or []
    rows = result.get("data") or []
    cell = lambda v: ("" if v is None else str(v))[:40]
    widths = [max([len(cell(h))] + [len(cell(r[i])) for r in rows if i < len(r)]) for i, h in enumerate(headers)]
    fmt = lambda r: " | ".join(cell(v).ljust(widths[i]) for i, v in enumerate(r))
    if headers:
        print(fmt(headers))
        print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt(r))
    print(f"[{len(rows)} 行 · 服务端耗时 {result.get('timeUsed')} ms · request_id {result['request_id']}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?", help="一条 SQL")
    ap.add_argument("--file", help="SQL 文件，多条语句用 ; 分隔")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("ZETARIS_QUERY_LIMIT", "1000")))
    ap.add_argument("--json", action="store_true", help="原样输出 JSON")
    args = ap.parse_args()
    load_env()
    if args.file:
        statements = split_statements(Path(args.file).read_text(encoding="utf-8"))
    elif args.sql:
        statements = [args.sql]
    else:
        ap.print_help()
        return 2
    for i, sql in enumerate(statements, 1):
        if len(statements) > 1:
            print(f"\n== 语句 {i}/{len(statements)} ==\n{sql}\n")
        try:
            result = run(sql, args.limit)
        except RuntimeError as e:
            print(f"失败: {e}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False)) if args.json else print_table(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
