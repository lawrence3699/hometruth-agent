#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取证经 Zetaris（src/voice/zetaris_live.py）：开查时每个来源一条 SELECT，证据标上返回它的那条查询；没返回的、查失败的标 local，
不冒充 Zetaris。这里把 SQL 接口换成假的（按 SQL 从 policy.zetaris_rows 里筛行），不联网。
跑：.venv/bin/python -m unittest tests/test_zetaris_live.py -v"""
from __future__ import annotations

import os
import re
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))

ENV = {"NARRATION_LLM": "0", "NEEDS_PARSER": "rules", "HOMETRUTH_ENV_FILE": "", "VOICE_VARIETY": "0"}
NEED = "Two bedrooms under 900 a week near Central Station, moving mid-November, and I have a cat."


class ZetarisLiveCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        import policy  # noqa: WPS433
        import zetaris_live  # noqa: WPS433
        self.policy, self.z = policy, zetaris_live
        self._run_sql = zetaris_live.run_sql
        self.issued, self.fail = [], set()
        zetaris_live.run_sql = self.fake_sql
        zetaris_live.REG.clear()
        zetaris_live.LAST.clear()
        zetaris_live.ENABLED = True

    def tearDown(self):
        self.z.run_sql = self._run_sql
        self.z.ENABLED = False
        self.z.REG.clear()
        self.z.LAST.clear()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def fake_sql(self, sql, limit=2000, timeout=20.0):
        source = re.search(r"FROM hometruth\.(\w+)", sql).group(1)
        if source in self.fail:
            raise RuntimeError("HTTP 500 fake")
        ids = set(re.findall(r"'([^']+)'", sql))
        rows = [r for r in self.policy.zetaris_rows(source) if not ids or r["listing_id"] in ids]
        rid = str(uuid.uuid4())
        self.issued.append(rid)
        return {"request_id": rid, "headers": ["evidence_id", "listing_id", "dim", "fact"],
                "data": [[r["evidence_id"], r["listing_id"], r["dim"], r["fact"]] for r in rows], "timeUsed": 7}

    def search(self, name):
        s = self.policy.Session(name)
        return s, list(s.handle_turn({"text": NEED, "deterministic": True}))

    def published(self, e):
        return e.get("text") != "No row yet" and e.get("table") in {t for src in self.policy.SOURCES for t in self.z.tables_of(src["name"])}

    def test_every_source_is_a_real_query(self):
        s, events = self.search("t-zet-live")
        done = [e for e in events if e.get("type") == "source" and e.get("status") == "done"]
        self.assertEqual(sorted(e["name"] for e in done), sorted(src["name"] for src in self.policy.SOURCES))
        for e in done:
            self.assertEqual(e["via"], "zetaris")
            self.assertIn(e["request_id"], self.issued)
            self.assertFalse(e["mock"])
            self.assertTrue(e["sql"].startswith(f"SELECT evidence_id, listing_id, dim, fact FROM hometruth.{e['name']} WHERE listing_id IN ("))
        self.assertTrue(any(e.get("type") == "say" and e.get("step") == "shortlist" for e in events))

    def test_evidence_carries_the_query_that_returned_it(self):
        s, events = self.search("t-zet-stamp")
        items = [it for e in events if e.get("type") == "evidence" for it in e["items"]]
        self.assertTrue(items)
        for it in items:
            if self.published(it):
                self.assertEqual(it["via"], "zetaris", it)
                self.assertIn(it["request_id"], self.issued)
                self.assertIn("FROM hometruth.", it["sql"])
            else:
                self.assertIn(it["via"], ("local", "agent_reply"))
            self.assertFalse(it["mock"])

    def test_failed_source_stays_local(self):
        self.fail = {"documents"}
        s, events = self.search("t-zet-fail")
        doc = [e for e in events if e.get("type") == "source" and e.get("name") == "documents"]
        self.assertEqual(doc[-1]["status"], "failed")
        items = [it for e in events if e.get("type") == "evidence" for it in e["items"] if it.get("table") == "documents"]
        self.assertTrue(items)
        self.assertTrue(all(it["via"] != "zetaris" for it in items))

    def test_off_means_simulated_sources_and_local_evidence(self):
        self.z.ENABLED = False
        s, events = self.search("t-zet-off")
        self.assertFalse(self.issued)
        self.assertTrue(all(e["mock"] for e in events if e.get("type") == "source" and e.get("status") == "done"))
        items = [it for e in events if e.get("type") == "evidence" for it in e["items"]]
        self.assertTrue(all(it["via"] in ("local", "agent_reply") and not it["mock"] for it in items))

    def test_endpoint_rows_and_ids(self):
        self.assertIsNone(self.policy.zetaris_rows("nope"))
        rows = self.policy.zetaris_rows("public_transit")
        self.assertTrue(rows)
        self.assertEqual(set(rows[0]), set(self.z.COLUMNS))
        self.assertTrue(all(isinstance(v, str) for r in rows for v in r.values()))
        self.assertEqual({r["source_table"] for r in rows} - {"public_transit", "geo_estimate"}, set())
        self.assertNotIn("'x", self.z.source_sql("listings", ["L-0001", "x'; DROP"]))


if __name__ == "__main__":
    unittest.main()
