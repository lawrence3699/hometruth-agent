"""Zetaris as the query layer for the evidence (10-27; docs/06 §4E, the P0 "no more mock" item).

How the data gets into Zetaris, with no bucket: server.py publishes every evidence table as JSON at /api/zetaris/<source>
(one row per evidence item, built by policy.zetaris_rows from the same code that builds the evidence). Zetaris registers each
endpoint as a Lightning REST table in database HOMETRUTH_SRC and flattens it into the SchemaStore view hometruth.<source>
(scripts/zetaris/10_register_hometruth.sql). A REST table fetches its endpoint again on every query, so the data stays on our
server and Zetaris queries it where it lives.

At search time policy runs one SELECT per source through Zetaris's SQL API, all in parallel, restricted to the candidate listings.
Every evidence item a query returned is stamped with that query's request id and SQL (via "zetaris"). An item Zetaris did not
return keeps via "local", and an agent reply that arrived during the tour keeps via "agent_reply": the page never claims Zetaris
for them. Each query is logged to runs/zetaris_log.jsonl (same format as scripts/zetaris_sql.py).

Off until enable() is called (server.py and pipecat_app.py main), so unit tests never touch the network. HOMETRUTH_ZETARIS=0 turns
it off on a machine that has the keys.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "runs" / "zetaris_log.jsonl"
CONTAINER = "hometruth"          # SchemaStore container: the views policy queries
DATABASE = "HOMETRUTH_SRC"       # Lightning database: the raw REST tables
# a source (policy.SOURCES name) can carry evidence from more than one evidence table: commute rows for real listings are
# distance estimates (table geo_estimate) and are published with the transit table
SOURCE_TABLES: Dict[str, tuple] = {"public_transit": ("public_transit", "geo_estimate")}
COLUMNS = ("evidence_id", "listing_id", "dim", "source_table", "row_ref", "material_id", "fact")
_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

ENABLED = False
REG: Dict[str, dict] = {}        # evidence_id -> {request_id, sql, ts, source}: the latest Zetaris query that returned it
LAST: Dict[str, dict] = {}       # source -> the latest successful query for it {request_id, sql, ts, rows, ms}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="zetaris")
STATS = {"queries": 0, "ok": 0, "failed": 0, "last_ok": None, "last_error": None}


def tables_of(source: str) -> tuple:
    return SOURCE_TABLES.get(source, (source,))


def evidence_id(item: dict) -> str:
    """Stable id of one evidence item: the same on our endpoint, in Zetaris and in policy's cells."""
    key = "|".join(str(item.get(k) or "") for k in ("table", "row", "material_id", "text"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def configured() -> bool:
    return all(os.environ.get(k) for k in ("ZETARIS_BASE_URL", "ZETARIS_ORG_ID", "ZETARIS_API_KEY"))


def enable() -> bool:
    """Turn live queries on if the keys are there (called by the servers' main, after .env is loaded)."""
    global ENABLED
    ENABLED = configured() and os.environ.get("HOMETRUTH_ZETARIS", "1") != "0"
    return ENABLED


def _log(entry: dict) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run_sql(sql: str, limit: int = 2000, timeout: float = 20.0) -> dict:
    """One statement through the SQL API (POST /api/proxy/sql-editor/sqls/run-query). The API returns no queryId, so the
    X-Request-ID we send is the id of this query (it is also what Zetaris's own logs carry)."""
    base = os.environ.get("ZETARIS_BASE_URL", "").rstrip("/")
    request_id = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {os.environ.get('ZETARIS_API_KEY', '')}", "X-Org-ID": os.environ.get("ZETARIS_ORG_ID", ""),
               "X-Request-ID": request_id, "Content-Type": "application/json"}
    if os.environ.get("ZETARIS_USER_AGENT"):
        headers["User-Agent"] = os.environ["ZETARIS_USER_AGENT"]
    req = Request(f"{base}/api/proxy/sql-editor/sqls/run-query", data=json.dumps({"sql": sql, "limit": limit}).encode("utf-8"),
                  headers=headers, method="POST")
    t0 = time.time()
    entry = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "request_id": request_id, "sql": sql, "limit": limit,
             "caller": "voice"}
    try:
        with urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        entry.update(ok=True, time_used_ms=out.get("timeUsed"), rows=len(out.get("data") or []), wall_ms=round((time.time() - t0) * 1000))
        return {"request_id": request_id, "wall_ms": entry["wall_ms"], **out}
    except HTTPError as e:
        entry.update(ok=False, error=f"HTTP {e.code} {e.read(400).decode('utf-8', errors='replace')}")
        raise RuntimeError(entry["error"]) from e
    except (OSError, TimeoutError, URLError, ValueError) as e:
        entry.update(ok=False, error=str(e)[:300])
        raise RuntimeError(entry["error"]) from e
    finally:
        _log(entry)


def source_sql(source: str, listing_ids: Iterable[str]) -> str:
    ids = [i for i in dict.fromkeys(listing_ids) if _ID_OK.match(str(i))]
    where = f" WHERE listing_id IN ({', '.join(repr(str(i)) for i in ids)})" if ids else ""
    return f"SELECT evidence_id, listing_id, dim, fact FROM {CONTAINER}.{source}{where}"


def query(source: str, listing_ids: Iterable[str], timeout: float = 20.0) -> dict:
    """SELECT the evidence rows of one source; remember which evidence ids this query returned."""
    sql = source_sql(source, listing_ids)
    with _lock:
        STATS["queries"] += 1
    try:
        out = run_sql(sql, timeout=timeout)
    except RuntimeError as e:
        with _lock:
            STATS["failed"] += 1
            STATS["last_error"] = f"{source}: {str(e)[:160]}"
        return {"source": source, "ok": False, "sql": sql, "error": str(e)[:300]}
    hdr = [str(h).lower() for h in (out.get("headers") or [])]
    col = hdr.index("evidence_id") if "evidence_id" in hdr else 0
    ids = [str(r[col]) for r in (out.get("data") or []) if r]
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ms = out.get("timeUsed") if isinstance(out.get("timeUsed"), (int, float)) else out.get("wall_ms")
    rec = {"request_id": out["request_id"], "sql": sql, "ts": ts, "source": source}
    with _lock:
        for i in ids:
            REG[i] = rec
        LAST[source] = dict(rec, rows=len(ids), ms=ms)
        STATS["ok"] += 1
        STATS["last_ok"] = ts
    return {"source": source, "ok": True, "request_id": out["request_id"], "sql": sql, "rows": len(ids), "ms": ms, "ts": ts}


def run_sources(sources: List[str], listing_ids: List[str], budget_s: float = 9.0) -> Iterator[dict]:
    """All sources in parallel; yields each result as it lands. Anything still running after budget_s is reported as timed out
    (with the latest earlier query for that source, if there is one); its thread keeps going and still updates REG when done."""
    futs = {_pool.submit(query, s, listing_ids, budget_s + 15): s for s in sources}
    pending, deadline = set(futs), time.time() + budget_s
    while pending:
        done, pending = wait(pending, timeout=max(0.0, deadline - time.time()), return_when=FIRST_COMPLETED)
        if not done:
            break
        for f in done:
            try:
                yield f.result()
            except Exception as e:  # noqa: BLE001
                yield {"source": futs[f], "ok": False, "error": str(e)[:300]}
    for f in pending:
        s = futs[f]
        yield {"source": s, "ok": False, "timeout": True, "error": f"no answer within {budget_s:.0f} s", "earlier": LAST.get(s)}


def stamp(item: dict) -> dict:
    """Where this evidence item came from, for the page: via zetaris (with the query's id and SQL), agent_reply or local."""
    eid = evidence_id(item)
    rec = REG.get(eid) if ENABLED else None
    if rec:
        return {"evidence_id": eid, "via": "zetaris", "mock": False, "request_id": rec["request_id"], "sql": rec["sql"], "queried_at": rec["ts"]}
    row = str(item.get("row") or "")
    if row.startswith("agent_replies/") or item.get("live"):
        return {"evidence_id": eid, "via": "agent_reply", "mock": False, "request_id": "reply-" + eid[:8], "sql": None}
    return {"evidence_id": eid, "via": "local", "mock": False, "request_id": "local-" + eid[:8], "sql": None}


def warm(sources: List[str], listing_ids: List[str], delay: float = 6.0) -> None:
    """Fill REG once in the background (the server has to be up first: Zetaris fetches our own endpoint)."""
    def go() -> None:
        time.sleep(delay)
        for r in run_sources(sources, listing_ids, budget_s=60):
            print(f"zetaris warm-up {r['source']}: " + (f"{r['rows']} rows in {r['ms']} ms ({r['request_id'][:8]})" if r.get("ok") else f"failed: {r.get('error')}"), flush=True)
    threading.Thread(target=go, name="zetaris-warm", daemon=True).start()


def status() -> dict:
    with _lock:
        return {"enabled": ENABLED, "evidence_ids": len(REG), "sources": sorted(LAST), **STATS}
