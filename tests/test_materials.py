#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""材料分段 + 每格一个下一步（10-27，src/voice/README.md「材料分段」）：全部离线。
(a) /api/listings 里每条证据的 stage 都在五段内；(b) mock_matrix.json 全文没有 inspection；(c) 跑 evaluate()：非 supported 的格子 next.kind 在三种之内、
supported 没有 next；(d) 来源 label 没有 Inspection；(e) card_payload 行带 next。另加 stage_of / next_for / best_question / viewing_check 的用例。
跑：.venv/bin/python -m unittest tests/test_materials.py -v"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "voice"))
os.environ["HOMETRUTH_ENV_FILE"] = ""
os.environ["NEEDS_PARSER"] = "rules"
os.environ["NARRATION_LLM"] = "0"
os.environ["VOICE_VARIETY"] = "0"

import narrator  # noqa: E402
import phraser  # noqa: E402
import policy  # noqa: E402

MATRIX = ROOT / "src" / "voice" / "mock_matrix.json"
STAGES = {"listing", "public", "agent", "viewing", "signing"}
KINDS = {"ask_agent", "see_at_viewing", "check_at_signing"}
TEXTS = {"ask_agent": "Ask the agent", "see_at_viewing": "See at the viewing", "check_at_signing": "Check at signing"}


def profile(**kw) -> dict:
    p = policy.new_profile()
    p.update({"budget": 900, "bedrooms": 2, "anchor": "Central Station", "move_in": {"month": 11, "day": 15, "text": "mid-November"},
              "pets": {"has": True, "kind": "cat", "text": "a cat"}})
    p.update(kw)
    return p


class Stages(unittest.TestCase):
    def test_every_listing_summary_evidence_has_a_stage(self):  # (a)
        n = 0
        for L in policy.LISTINGS:
            for f in policy.listing_summary(L)["facts"]:
                self.assertIn("next", f)  # null when supported or not registered, otherwise {kind, text, hint}
                for e in f["evidence"]:
                    self.assertIn(e["stage"], STAGES, (L["id"], f["dim"], e))
                    self.assertNotEqual(e["stage"], "viewing", "first-version data has no renter photos")
                    self.assertNotEqual(e["stage"], "signing", "signing material is never evidence")
                    n += 1
        self.assertGreater(n, 50)

    def test_stage_of_by_table_and_document_row(self):
        self.assertEqual(policy.stage_of({"table": "listings"}), "listing")
        self.assertEqual(policy.stage_of({"table": "photo_facts"}), "listing")
        self.assertEqual(policy.stage_of({"table": "floorplan_facts"}), "listing")
        self.assertEqual(policy.stage_of({"table": "public_transit"}), "public")
        self.assertEqual(policy.stage_of({"table": "sun_geometry"}), "public")
        self.assertEqual(policy.stage_of({"table": "geo_estimate"}), "public")
        self.assertEqual(policy.stage_of({"table": "documents", "row": "M-0002-reply-01", "material_id": "M-0002-reply-01"}), "agent")
        self.assertEqual(policy.stage_of({"table": "documents", "row": "M-0002-bylaws", "material_id": "M-0002-bylaws"}), "agent")
        self.assertEqual(policy.stage_of({"table": "documents", "row": "agent_replies/L-0001", "material_id": None}), "agent")
        self.assertEqual(policy.stage_of({"table": "documents", "row": "M-0001-condition-report", "material_id": None}), "signing")
        self.assertEqual(policy.stage_of({"table": "documents", "row": "x", "stage": "agent"}), "agent")
        self.assertEqual(policy.stage_of({"table": "something_new"}), "public")
        for src in policy.SOURCES:
            self.assertIn(policy.stage_of({"table": src["table"]}), ("listing", "public", "agent"))

    def test_matrix_has_no_inspection_report_and_sources_are_relabelled(self):  # (b) (d)
        raw = MATRIX.read_text(encoding="utf-8")
        self.assertNotIn("inspection", raw.lower())
        for src in policy.SOURCES:
            self.assertNotIn("inspection", src["label"].lower())
        docs = next(s for s in policy.SOURCES if s["name"] == "documents")
        self.assertEqual(docs["label"], "Agent replies and by-laws")
        m = json.loads(raw)
        replies = [(L["id"], e) for L in m["listings"] for f in L["facts"].values() for e in f.get("evidence", []) if "reply-" in str(e.get("material_id") or "")]
        self.assertEqual(sorted(lid for lid, _ in replies), ["L-0001", "L-0002", "L-0003", "L-0005"])
        for lid, e in replies:
            self.assertEqual(e["table"], "documents")
            self.assertEqual(e["row"], e["material_id"])
            self.assertTrue(e["text"].startswith("Agent reply ("), e)
            self.assertFalse(lid.startswith("L-D"), "real listings keep only real facts")
        fenwick = next(L for L in m["listings"] if L["id"] == "L-0002")
        self.assertIn("the agent has confirmed in writing", fenwick["special"])

    def test_source_events_carry_a_stage(self):
        s = policy.Session("t-mat-src")
        s.quick = True
        ev = list(s.handle_turn({"text": "Two bedrooms under 900 near Central, moving mid-November, no pets.", "deterministic": True}))
        sources = [e for e in ev if e["type"] == "source"]
        self.assertEqual(len(sources), 2 * len(policy.SOURCES))
        for e in sources:
            self.assertIn(e["stage"], ("listing", "public", "agent"), e)
        self.assertEqual(next(e["stage"] for e in sources if e["name"] == "documents"), "agent")
        self.assertEqual(next(e["label"] for e in sources if e["name"] == "documents"), "Agent replies and by-laws")
        for e in ev:
            if e["type"] == "evidence":
                for it in e["items"]:
                    self.assertIn(it["stage"], STAGES)


class NextSteps(unittest.TestCase):
    def test_every_open_cell_has_a_next_and_supported_has_none(self):  # (c)
        p = profile(extras=[{"dim": "C1", "label": "Air con in the bedroom"}, {"dim": "C2", "label": "Furnished"}, {"dim": "A6", "label": "Bills included"},
                           {"dim": "E4", "label": "Quiet"}, {"dim": "E2", "label": "Sunlight"}, {"dim": "D1", "label": "Condition"},
                           {"dim": "C3", "label": "Gas stove", "want": "gas"}] + [{"dim": d, "label": policy.PACK_LABELS[d], "pack": "fengshui"} for d in policy.FENGSHUI])
        seen_kinds, seen_dims = set(), set()
        for L in policy.LISTINGS:
            for d, c in policy.evaluate(L, p, {}).items():
                seen_dims.add(d)
                if c["status"] == "supported":
                    self.assertNotIn("next", c, (L["id"], d))
                elif d == "G1":
                    self.assertNotIn("next", c, "no next for the commute: no timetable means unknown")
                else:
                    self.assertIn("next", c, (L["id"], d, c["status"]))
                    self.assertIn(c["next"]["kind"], KINDS)
                    self.assertEqual(c["next"]["text"], TEXTS[c["next"]["kind"]])
                    self.assertLessEqual(len(c["next"]["hint"].split()), 12, c["next"]["hint"])
                    seen_kinds.add(c["next"]["kind"])
                for e in c["evidence"]:
                    self.assertIn(e["stage"], STAGES)
        self.assertTrue(seen_kinds <= KINDS)
        self.assertTrue({"ask_agent", "see_at_viewing"} <= seen_kinds, seen_kinds)  # check_at_signing only once an agent reply left A6 / C2 open: not in the first-version data
        self.assertTrue({"C1", "C2", "A6", "E4", "E2", "D1", "C3", "K2", "H1", "J1"} <= seen_dims)

    def test_primary_then_secondary_once_the_agent_has_replied(self):
        unknown = {"evidence": [{"table": "listings", "row": "L-0001", "material_id": "M-0001-listing", "text": "no mention"}]}
        self.assertEqual(policy.next_for("C1", "unknown", unknown), {"kind": "ask_agent", "text": "Ask the agent", "hint": "air con in the bedrooms, not just the living room"})
        self.assertEqual(policy.next_for("C1", "conflict", unknown)["kind"], "ask_agent")
        self.assertEqual(policy.next_for("C1", "inferred", unknown)["kind"], "ask_agent")
        replied = {"evidence": unknown["evidence"] + [{"table": "documents", "row": "M-0001-reply-01", "material_id": "M-0001-reply-01", "text": "Agent reply (email, 20 Oct): 'living room'"}]}
        self.assertEqual(policy.next_for("C1", "inferred", replied), {"kind": "see_at_viewing", "text": "See at the viewing", "hint": "look for a unit or vent in each bedroom"})
        self.assertEqual(policy.next_for("A6", "unknown", replied)["kind"], "check_at_signing")
        self.assertEqual(policy.next_for("J1", "conflict", replied)["kind"], "ask_agent", "only one step for pets: still the agent, in writing")
        placeholder = {"evidence": [{"table": "documents", "row": "agent_replies/L-0001", "material_id": None, "text": "No agent reply about pets on file"}]}
        self.assertEqual(policy.next_for("J1", "inferred", placeholder)["kind"], "ask_agent")
        self.assertFalse(policy._agent_replied(placeholder), "a 'not asked yet' placeholder is not a reply")
        self.assertIsNone(policy.next_for("C1", "supported", unknown))
        self.assertIsNone(policy.next_for("C1", None, unknown), "a fact with no fixed status (rent, bedrooms, move-in) has no next")
        self.assertIsNone(policy.next_for("G1", "unknown", unknown))
        self.assertIsNone(policy.next_for("A7", "unknown", unknown))
        self.assertEqual(policy.next_for("H1", "unknown", {"evidence": []})["hint"], "the agent must answer: deaths, flood, fire, drug lab, asbestos, cladding, sale")
        self.assertEqual(policy.next_for("D1", "unknown", {"evidence": []})["kind"], "see_at_viewing")
        self.assertEqual(policy.next_for("C3", "conflict", {"evidence": []})["hint"], "look at the cooktop: flame rings or a flat top")

    def test_sunlight_next_depends_on_whether_the_aspect_is_known(self):
        no_aspect = {"value": None, "evidence": [{"table": "listings", "row": "L-0001", "material_id": None, "text": "no facing stated"}]}
        self.assertEqual(policy.next_for("E2", "unknown", no_aspect), {"kind": "ask_agent", "text": "Ask the agent", "hint": "which way the living room faces"})
        east = {"value": "E-facing", "evidence": [{"table": "sun_geometry", "row": "x 21 Jun / 21 Dec", "material_id": None,
                                                   "text": "Facing E at -33.924, 151.234: direct sun on the main window 07:05–11:40 (4.6 h) on 21 June and 05:45–12:50 (7.1 h) on 21 December"}]}
        self.assertEqual(policy.next_for("E2", "inferred", east), {"kind": "see_at_viewing", "text": "See at the viewing", "hint": "visit around 9 am; the main window should be in sun"})
        north = dict(east, evidence=[dict(east["evidence"][0], text="direct sun on the main window 07:05–16:50 (9.8 h) on 21 June")])
        self.assertEqual(policy.next_for("E2", "inferred", north)["hint"], "visit around midday; the main window should be in sun")
        west = dict(east, evidence=[dict(east["evidence"][0], text="direct sun on the main window 12:10–16:50 on 21 June")])
        self.assertEqual(policy.next_for("E2", "inferred", west)["hint"], "visit around 3 pm; the main window should be in sun")
        self.assertEqual(policy.next_for("E2", "inferred", {"value": "N-facing", "evidence": []})["hint"], "visit in daylight and look at the main window")
        for L in policy.LISTINGS:  # the real listings with a facing: geometry only, so the viewing settles it
            f = next(x for x in policy.listing_summary(L)["facts"] if x["dim"] == "E2")
            if f["status"] == "inferred":
                self.assertEqual(f["next"]["kind"], "see_at_viewing", L["id"])
            elif f["status"] == "unknown":
                self.assertEqual(f["next"]["hint"], "which way the living room faces", L["id"])

    def test_card_rows_and_listing_summary_carry_next(self):  # (e)
        p = profile(extras=[{"dim": "C1", "label": "Air con in the bedroom"}])
        ranked, _ = policy.rank(p, {})
        self.assertTrue(ranked)
        rows_with_next = 0
        for it in ranked:
            card = policy.card_payload(it["listing"], it["cells"], 1)
            for row in card["cells"]:
                c = it["cells"][row["dim"]]
                if c["status"] == "supported" or row["dim"] == "G1":
                    self.assertNotIn("next", row)
                else:
                    self.assertEqual(row["next"], c["next"]["kind"])
                    self.assertIn(row["next"], KINDS)
                    rows_with_next += 1
        self.assertGreater(rows_with_next, 0)
        summ = policy.listing_summary(policy.listing_by_id("L-0001"))
        c1 = next(f for f in summ["facts"] if f["dim"] == "C1")
        self.assertEqual(c1["next"], {"kind": "see_at_viewing", "text": "See at the viewing", "hint": "look for a unit or vent in each bedroom"})
        self.assertEqual([e["stage"] for e in c1["evidence"]], ["listing", "listing", "agent"])
        a1 = next(f for f in summ["facts"] if f["dim"] == "A1")
        self.assertIsNone(a1["next"])
        staged = next(f for f in policy.listing_summary(policy.listing_by_id("L-0002"))["facts"] if f["dim"] == "C2")
        self.assertEqual((staged["value"], staged["short"]), ("Staged photos", "staged"))

    def test_best_question_only_asks_what_the_agent_can_answer(self):
        p = profile(extras=[{"dim": "C1", "label": "Air con in the bedroom"}])
        cells = policy.evaluate(policy.listing_by_id("L-0001"), p, {})
        self.assertEqual(policy.best_question(cells)[0], "J1")  # pets (inferred, hard): ask the agent; C1 already has a reply, so it's for the viewing
        self.assertEqual(policy.viewing_check(cells)[0], "C1")
        real = policy.evaluate(policy.listing_by_id("L-D18339937"), p, {})
        self.assertEqual(real["G1"]["status"], "inferred")
        self.assertEqual(policy.best_question(real)[0], "J1", "the estimated commute has no next step, so pets is the question")
        quiet = policy.evaluate(policy.listing_by_id("L-0001"), profile(pets={"has": False, "text": "no pets"}, extras=[{"dim": "D1", "label": "Condition"}]), {})
        self.assertIsNone(policy.best_question(quiet))
        self.assertEqual(policy.viewing_check(quiet)[0], "D1")
        line = phraser.viewing_check("D1", quiet["D1"])
        self.assertEqual(line, "Worth checking at the viewing: benchtops, tiles, carpet.")
        staged = policy.evaluate(policy.listing_by_id("L-0002"), profile(pets={"has": False, "text": "no pets"}), {})
        self.assertEqual(policy.best_question(staged)[0], "C2", "the notable staged-photos row is open and the agent can say what stays")
        self.assertIsNone(policy.viewing_check(staged))
        nothing = policy.evaluate(policy.listing_by_id("L-0005"), profile(budget=1000, pets={"has": False, "text": "no pets"}), {})
        self.assertEqual([d for d, c in nothing.items() if c["status"] != "supported"], ["H1"], "only the legal disclosure is open, and that has its own line in the wrap")
        self.assertIsNone(policy.best_question(nothing))
        self.assertIsNone(policy.viewing_check(nothing))

    def test_tour_says_the_viewing_line_when_there_is_nothing_to_ask(self):
        s = policy.Session("t-mat-tour")
        s.quick = True
        ev = list(s.handle_turn({"text": "Two bedrooms under 900 near Central, moving mid-November, no pets, renovated please.", "deterministic": True}))
        says = [e for e in ev if e["type"] == "say"]
        viewing = [e for e in says if str(e.get("step", "")).endswith(".viewing")]
        self.assertTrue(viewing, [e["step"] for e in says])
        self.assertTrue(all(e["text"].startswith("Worth checking at the viewing: ") for e in viewing))
        hl = [e for e in ev if e["type"] == "highlight" and e.get("viewing")]
        self.assertEqual(len(hl), len(viewing))
        for e in says:
            self.assertNotIn("inspection report", e["text"].lower())
            self.assertFalse(str(e.get("step", "")).endswith(".question") and str(e.get("step", "")).endswith(".viewing"))
        cards = [e for e in ev if e["type"] == "card"]
        for c in cards:  # a card either gets a question or a viewing line, never both
            prefix = f"L{c['listing']['rank'] - 1}."
            kinds = {e["step"].split(".")[-1] for e in says if str(e.get("step", "")).startswith(prefix) and e["step"].split(".")[-1] in ("question", "viewing")}
            self.assertLessEqual(len(kinds), 1, kinds)


class Wording(unittest.TestCase):
    def test_narrator_knows_the_agent_reply_as_a_source(self):
        self.assertNotIn("inspection", narrator.SYSTEM.lower())
        self.assertIn("agent's reply", narrator.SYSTEM)
        fact = "Bedroom air con: supported. The agent confirmed in writing: ducted air con with vents in the living room and both bedrooms."
        self.assertEqual(narrator.dropped_sources("Both bedrooms have ducted vents, the agent's email confirms it.", fact), [])
        self.assertEqual(narrator.dropped_sources("Both bedrooms have ducted vents, the agent said so.", fact), [])
        self.assertIn("agent reply", narrator.dropped_sources("Both bedrooms have ducted vents, the floor plan shows them.", fact))
        self.assertEqual(narrator.added_sources("The agent's reply confirms vents in both bedrooms.", fact), [])
        self.assertIn("agent reply", narrator.added_sources("The agent replied that there are vents in both bedrooms.", "The floor plan shows vents in both bedrooms."))
        ok, why = narrator.check_line("Both bedrooms have ducted air con vents and the agent confirmed it in writing, so that checks out.", fact=fact, status="supported",
                                      words=narrator.DIM_WORDS["C1"], overlap=0.3)
        self.assertTrue(ok, why)
        bad, why = narrator.check_line("Both bedrooms have ducted air con vents, so that checks out.", fact=fact, status="supported", words=narrator.DIM_WORDS["C1"], overlap=0.3)
        self.assertIsNone(bad)
        self.assertIn("agent reply", why)

    def test_phraser_cell_sentences_use_the_agent_reply(self):
        p = profile(extras=[{"dim": "C1", "label": "Air con in the bedroom"}])
        for lid, want in (("L-0002", "The agent confirmed in writing"), ("L-0001", "the agent's reply only mentions the living room"), ("L-0005", "The agent replied")):
            L = policy.listing_by_id(lid)
            line = phraser.cell_sentence("C1", policy.evaluate(L, p, {})["C1"], L, p)
            self.assertIn(want, line, line)
            self.assertNotIn("inspection", line.lower())
        self.assertIn("the agent has confirmed in writing", phraser.special(policy.listing_by_id("L-0002")))


if __name__ == "__main__":
    unittest.main()
