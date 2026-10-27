#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""照片事实（src/photo/facts.py 的规则层 + policy 里照片行的核对）：模型的 JSON 读图结果 → 矩阵格子；盖章的家具不管问没问都亮、
要家具的人看到的是冲突；炉灶按想要什么判；卡片和 /api/listings 带照片；台词和审稿词表。不碰网络、不改矩阵文件。
跑：.venv/bin/python -m unittest tests/test_photo_facts.py -v"""
from __future__ import annotations

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
from photo import facts  # noqa: E402

LISTING = {"id": "L-0099", "street": "1 Test Street", "suburb": "Zetland"}
PHOTO = {"url": "/static/qi/assets/photos/L-0099-01.jpg", "caption": "Living room"}
MODEL = "private/nvidia/nemotron-3.5-super-120b-a12b"


def profile(**over):
    p = policy.new_profile()
    p.update(budget=900, bedrooms=2, anchor="Central Station", move_in={"month": 11, "day": 15, "text": "mid-November"}, pets={"has": True, "kind": "cat", "text": "a cat"})
    p.update(over)
    return p


_TOUR = os.environ.get("VOICE_TOUR")


def setUpModule():  # 逐格讲法（简短播报见 test_voice_brief.py）；开跑时设、跑完放回，不串到别的测试模块
    os.environ["VOICE_TOUR"] = "full"


def tearDownModule():
    if _TOUR is None:
        os.environ.pop("VOICE_TOUR", None)
    else:
        os.environ["VOICE_TOUR"] = _TOUR


class ReadingToFacts(unittest.TestCase):
    def test_stamped_photo_means_staged_furniture_that_is_shown_to_everyone(self):
        reading = {"room": "living room", "watermark_text": "VIRTUALLY STAGED", "virtual_staging": True, "furniture": ["sofa", "coffee table"], "cooktop": "none_visible"}
        out = facts.facts_from_reading(LISTING, PHOTO, reading, MODEL)
        c2 = out["C2"]
        self.assertEqual((c2["status"], c2["if_wanted"], c2["notable"], c2["short"]), ("inferred", "conflict", True, "staged"))
        self.assertIn("stamped 'VIRTUALLY STAGED'", c2["why"])
        self.assertIn("sofa and coffee table", c2["why"])
        ev = c2["evidence"][0]
        self.assertEqual((ev["table"], ev["row"], ev["read_by"], ev["image"]), ("photo_facts", "L-0099-photo-01", MODEL, PHOTO["url"]))
        self.assertEqual(ev["text"], "Living room photo; stamped 'VIRTUALLY STAGED'; furniture in view: sofa, coffee table.")
        self.assertNotIn("C3", out)

    def test_plain_photo_with_furniture_is_unknown_and_not_notable(self):
        out = facts.facts_from_reading(LISTING, PHOTO, {"room": "kitchen", "furniture": ["dining table", "chairs"], "cooktop": "gas"}, MODEL)
        self.assertEqual((out["C2"]["status"], out["C2"]["notable"]), ("unknown", False))
        self.assertIn("may be the previous tenant's", out["C2"]["why"])
        self.assertEqual((out["C3"]["status"], out["C3"]["want"], out["C3"]["short"]), ("inferred", "gas", "gas"))
        self.assertIn("gas burners", out["C3"]["evidence"][0]["text"])

    def test_flat_cooktop_reads_electric_but_not_induction(self):
        out = facts.facts_from_reading(LISTING, PHOTO, {"room": "kitchen", "furniture": [], "cooktop": "flat_electric"}, MODEL)
        self.assertEqual(out["C3"]["want"], "electric")
        self.assertIn("ceramic and induction look the same", out["C3"]["why"])
        self.assertEqual(out["C2"]["status"], "unknown")

    def test_model_answer_parsing(self):
        self.assertEqual(facts._json_object('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(facts._json_object('Sure: {"room": "kitchen"} done'), {"room": "kitchen"})
        self.assertIsNone(facts._json_object("no json here"))


class MatrixRows(unittest.TestCase):
    """矩阵里已经写进去的照片事实（src/photo/facts.py write）：L-0002 盖章，其余四套合成房源没盖章；10-26 起真房源（scripts/domain_sample.py）里
    有几套挂牌照片真的印着 "Virtual Furniture" / "digitally furnished"，Nemotron 读出来了，它们的 Furniture 行也不问就亮。"""

    def test_staged_row_appears_without_being_asked(self):
        ranked, _ = policy.rank(profile(), {})
        by_id = {r["listing"]["id"]: r["cells"] for r in ranked}
        self.assertIn("C2", by_id["L-0002"])
        self.assertEqual(by_id["L-0002"]["C2"]["status"], "inferred")
        self.assertTrue(by_id["L-0002"]["C2"]["photo"])
        self.assertTrue(by_id["L-0002"]["C2"]["notable"], "said without being asked, and (rank) not scored")
        self.assertEqual(by_id["L-0002"]["C2"]["evidence"][0]["table"], "photo_facts")
        staged = {L["id"] for L in policy.LISTINGS if (L["facts"].get("C2") or {}).get("notable")}
        self.assertEqual({lid for lid, cells in by_id.items() if "C2" in cells}, staged & set(by_id), "exactly the stamped ones light up unasked")
        self.assertTrue(all(lid == "L-0002" for lid in staged if lid.startswith("L-0")), "of the synthetic five only L-0002 is stamped")  # 真房源 L-D* / L-R*（10-27 起有 REA）可以有虚拟家具

    def test_asking_for_furniture_turns_the_staged_row_into_a_conflict(self):
        ranked, _ = policy.rank(profile(extras=[{"dim": "C2", "label": "Furnished"}]), {})
        by_id = {r["listing"]["id"]: r["cells"] for r in ranked}
        self.assertEqual(by_id["L-0002"]["C2"]["status"], "conflict")
        self.assertEqual(by_id["L-0001"]["C2"]["status"], "unknown")

    def test_stove_wants(self):
        f = {"status": "inferred", "want": "electric", "why": "", "evidence": []}
        self.assertEqual(policy._wanted_status("C3", f, {"dim": "C3", "want": "gas"}), "conflict")
        self.assertEqual(policy._wanted_status("C3", f, {"dim": "C3", "want": "induction"}), "unknown")
        self.assertEqual(policy._wanted_status("C3", f, {"dim": "C3", "want": "electric"}), "inferred")
        self.assertEqual(policy._wanted_status("C3", f, {"dim": "C3", "want": None}), "inferred")
        self.assertEqual(policy.parse_extras("i need a gas stove"), [{"dim": "C3", "label": "Gas stove", "want": "gas"}])
        self.assertEqual(policy.parse_extras("induction cooktop please")[0]["want"], "induction")
        self.assertEqual(policy.parse_extras("does it have a stove")[0]["label"], "Stove")
        self.assertEqual(policy.dim_for("are the photos staged?"), "C2")
        self.assertEqual(policy.dim_for("is the cooktop gas?"), "C3")

    def test_card_and_listing_summary_carry_the_photo(self):
        s = policy.Session("photo-tour")
        s.quick = True
        ev = list(s.handle_turn({"text": "Two bedrooms near Central, under 900 a week, I have a cat, moving mid November"}))
        card = next(e["listing"] for e in ev if e["type"] == "card" and e["listing"]["id"] == "L-0002")
        self.assertEqual(card["image"], "/static/qi/assets/photos/L-0002-01.jpg")
        row = next(c for c in card["cells"] if c["dim"] == "C2")
        self.assertEqual((row["short"], row["photo"], row["status"]), ("staged", True, "inferred"))
        line = next(e["text"] for e in ev if e["type"] == "say" and e.get("step") == "L0.C2")
        self.assertTrue(line.startswith("Furniture: probably, but not confirmed. The listing photo is stamped 'VIRTUALLY STAGED'"), line)
        evid = next(e for e in ev if e["type"] == "evidence" and e["dim"] == "C2")
        self.assertEqual(evid["items"][0]["read_by"], MODEL)
        self.assertTrue(evid["items"][0]["image"].endswith("L-0002-01.jpg"))
        L = next(x for x in policy.LISTINGS if x["id"] == "L-0002")
        summary = policy.listing_summary(L)
        self.assertEqual((summary["image"], summary["photo_set"], summary["photo_stamp"]), (card["image"], "room-1.jpg", "VIRTUALLY STAGED"))
        c2 = next(f for f in summary["facts"] if f["dim"] == "C2")
        self.assertEqual(c2["evidence"][0]["read_by"], MODEL)

    def test_narrator_keeps_the_photo_and_the_staging_words(self):
        L = next(x for x in policy.LISTINGS if x["id"] == "L-0002")
        cells = policy.evaluate(L, profile(), {})
        spec = narrator.cell_spec("C2", cells["C2"], L, profile())
        good = "Reading between the lines on furniture: that photo is stamped virtually staged, so the sofa won't be there, and the listing never says furnished."
        self.assertEqual(narrator.check_line(good, **spec)[0], good)
        self.assertEqual(narrator.check_line("The furniture probably stays, the listing says so.", **spec)[0], None)  # drops the photo, wrong meaning
        self.assertIn("C3", narrator.DIM_WORDS)
        self.assertTrue(phraser.best_question("C3", {"status": "inferred"}, profile()).endswith("?"))


if __name__ == "__main__":
    unittest.main()
