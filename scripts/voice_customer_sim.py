"""Simulated renters talking to /api/turn: what they would hear, how long, and what happens when they cut in.
Speech time is estimated at 2.3 words/s, measured from the ElevenLabs Sarah takes in runs/video (take3, v4take1).
usage: .venv/bin/python scripts/voice_customer_sim.py [base_url] [out.json]   (ONLY=P01,P05 runs just those renters)
Reports from 2026-10-28 (before the upgrade, docs/12): runs/voice_sim/2026-10-28_local_8661.json, 2026-10-28_public.json"""
import json, re, sys, time, urllib.request, uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8661"
OUT = sys.argv[2] if len(sys.argv) > 2 else "sim_report.json"
WPS = 2.3
FULL = "Two bedrooms near UNSW, under 900 a week, moving mid-November. I've got a cat, and I want air con in the bedroom."
JARGON = re.compile(r"\b(supported|inferred|cell|transit table|conflict|unknown|materials?|by-laws excerpt)\b", re.I)


def words(t):
    return len(re.findall(r"[A-Za-z0-9']+", t or ""))


def secs(t):
    return words(t) / WPS


class Renter:
    def __init__(self, name):
        self.name, self.sid, self.rid = name, "sim-" + uuid.uuid4().hex[:10], "sim-r-" + uuid.uuid4().hex[:10]
        self.turns = []

    def turn(self, text, interrupted=None, listing_id=None):
        body = {"session": self.sid, "renter": self.rid, "text": text, "source": "voice", "listing_id": listing_id,
                "interrupted": interrupted or {"active": False}}
        req = urllib.request.Request(BASE + "/api/turn", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "HomeTruth-customer-sim/1.0"})
        evs, t0 = [], time.time()
        with urllib.request.urlopen(req, timeout=180) as r:
            for raw in r:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    ev["_t"] = round(time.time() - t0, 3)
                    evs.append(ev)
        self.turns.append({"user": text, "interrupted": bool(interrupted), "events": evs})
        return evs

    def cut_at(self, evs, at):
        """The renter talks while sentence `off` (0-based) of place `n` (0-based) is playing, at = (n, off). Counted by the say's step
        (L0, L0.brief, L0.A1 …), so the same cut means the same moment in the brief tour and the full one."""
        n_want, off_want = at
        cur, last_idx, seen = None, None, {}
        for pos, ev in enumerate(evs):
            if ev["type"] == "card":
                cur = ev["listing"]["id"]
            elif ev["type"] == "highlight":
                cur = ev["listing_id"]
            elif ev["type"] == "say" and ev.get("idx") is not None:
                m = re.match(r"L(\d+)", ev.get("step") or "")
                if m:
                    n = int(m.group(1))
                    k = seen.get(n, 0)
                    seen[n] = k + 1
                    if (n, k) == (n_want, off_want):
                        heard = {e["text"] for e in evs[:pos] if e["type"] == "say"}  # what the renter actually heard before cutting in
                        return {"active": True, "spoken_idx": last_idx, "listing_id": cur, "cut_sentence": ev["text"]}, cur, ev["text"], heard
                last_idx = ev["idx"]
        raise ValueError("no sentence %d of place %d (sentences per place: %s)" % (off_want, n_want, seen))


def says(evs):
    return [e for e in evs if e["type"] == "say"]


def summarize_tour(evs):
    s = says(evs)
    out = {"sentences": len(s), "words": sum(words(e["text"]) for e in s), "seconds": round(sum(secs(e["text"]) for e in s), 1)}
    # time until the first listing is named (first L*-step sentence)
    t = 0.0
    first = None
    per = {}
    for e in s:
        step = e.get("step") or ""
        m = re.match(r"L(\d+)", step)
        if m and first is None:
            first = round(t, 1)
        if m:
            per.setdefault(int(m.group(1)), [0, 0.0])
            per[int(m.group(1))][0] += 1
            per[int(m.group(1))][1] += secs(e["text"])
        t += secs(e["text"])
    out["first_listing_at_s"] = first
    out["per_listing"] = {k: {"sentences": v[0], "seconds": round(v[1], 1)} for k, v in sorted(per.items())}
    longest = max(s, key=lambda e: words(e["text"])) if s else None
    out["longest"] = {"words": words(longest["text"]), "seconds": round(secs(longest["text"]), 1), "text": longest["text"]} if longest else None
    texts = [e["text"] for e in s]
    out["repeated"] = sorted({x for x in texts if texts.count(x) > 1})
    out["jargon_hits"] = sum(len(JARGON.findall(x)) for x in texts)
    out["over_20_words"] = sum(1 for x in texts if words(x) > 20)
    return out


def show(r, label, evs, heard_before=None):
    s = says(evs)
    kinds = [e.get("step") for e in s]
    restarted = any(e["type"] == "state" and e.get("phase") == "searching" for e in evs)
    first_cards = [e["listing"]["id"] for e in evs if e["type"] == "card"]
    rep = None
    if heard_before is not None:
        rep_s = [e["text"] for e in s if e["text"] in heard_before]
        rep = {"sentences": len(rep_s), "seconds": round(sum(secs(x) for x in rep_s), 1)}
    return {"label": label, "first_reply": [e["text"] for e in s[:3]], "steps_head": kinds[:6], "restarted_search": restarted,
            "cards": first_cards, "repeat_of_already_heard": rep, "summary": summarize_tour(evs)}


report = {"base": BASE, "wps": WPS, "personas": []}


ONLY = [x for x in __import__("os").environ.get("ONLY", "").split(",") if x]


def persona(name, fn):
    if ONLY and not any(name.startswith(o) for o in ONLY):
        return
    r = Renter(name)
    try:
        res = fn(r)
    except Exception as e:  # keep going: one broken persona must not hide the others
        res = {"error": repr(e)}
    report["personas"].append({"name": name, "session": r.sid, "result": res,
                               "transcript": [{"user": t["user"], "interrupted": t["interrupted"],
                                               "said": [e["text"] for e in says(t["events"])]} for t in r.turns]})
    print("done:", name, flush=True)


def p_one_shot(r):
    evs = r.turn(FULL)
    return show(r, "one shot", evs)


def p_two_step(r):
    a = r.turn("Hi, I'm looking for a two bedroom near UNSW. I have a cat.")
    b = r.turn("Under 900, mid-November.")
    return {"ask": [e["text"] for e in says(a)], "tour": show(r, "after answering", b)}


def cut_persona(at, line):
    def fn(r):
        evs = r.turn(FULL)
        inter, cur, cut, heard = r.cut_at(evs, at)
        after = r.turn(line, interrupted=inter, listing_id=cur)
        res = show(r, line, after, heard_before=heard)
        res["cut_while_saying"] = cut
        return res
    return fn


def p_stop_continue(r):
    evs = r.turn(FULL)
    inter, cur, cut, heard = r.cut_at(evs, (0, 2))
    a = r.turn("Stop.", interrupted=inter, listing_id=cur)
    b = r.turn("Okay, continue.", listing_id=cur)
    res = show(r, "continue", b, heard_before=heard | {e["text"] for e in says(a)})
    res["cut_while_saying"], res["on_stop"] = cut, [e["text"] for e in says(a)]
    return res


def p_after_tour(line):
    def fn(r):
        r.turn(FULL)
        after = r.turn(line)
        return show(r, line, after)
    return fn


def p_misheard_place(r):
    a = r.turn("Two bedrooms near you and SW, under 900 a week, mid-November, I've got a cat.")
    return {"said": [e["text"] for e in says(a)], "needs": [e for e in a if e["type"] == "needs"][:1]}


def p_vague(r):
    a = r.turn("Somewhere cheap near the beach, it's just me.")
    b = r.turn("Not sure, maybe 600? I don't know when yet.")
    c = r.turn("No pets.")
    return {"turn1": [e["text"] for e in says(a)], "turn2": [e["text"] for e in says(b)][:4], "turn3": [e["text"] for e in says(c)][:4],
            "tour": summarize_tour(c)}


# at = (place, sentence): which sentence of which place (both 0-based) is playing when the renter cuts in. Before 10-28 this was a
# running count over the full tour (P04 k=14, P11 k=13, P12 k=15 fell in place 2); the brief tour has 3 sentences a place.
persona("P01 one shot, listens to the end", p_one_shot)
persona("P02 says it in two goes", p_two_step)
persona("P03 adds a need during place 1", cut_persona((0, 1), "Oh, and it needs to be furnished."))
persona("P04 lowers the budget during place 2", cut_persona((1, 1), "Actually, can we make it 800 max?"))
persona("P05 'wait' + question", cut_persona((0, 2), "Wait, does that one allow cats?"))
persona("P06 'hang on' + question", cut_persona((0, 1), "Hang on, is that per week?"))
persona("P07 asks about the next one", cut_persona((0, 2), "Is the next one cheaper?"))
persona("P08 doesn't like this place", cut_persona((0, 1), "That one's too far for me."))
persona("P09 missed what was said", cut_persona((0, 2), "Sorry, what was that?"))
persona("P10 wants it shorter", cut_persona((0, 2), "Can you just give me the short version?"))
persona("P11 compares two places", cut_persona((1, 1), "What's the difference between the first and the second one?"))
persona("P12 goes back to place 1", cut_persona((1, 2), "Go back to the first one."))
persona("P13 asks about the bond", cut_persona((0, 2), "How much is the bond?"))
persona("P14 corrects a mishearing", cut_persona((0, 1), "No, I said two bedrooms, not three."))
persona("P15 takes the wrap-up offer", p_after_tour("Yes please, draft the questions."))
persona("P16 asks to compare after the tour", p_after_tour("Compare them on the commute."))
persona("P17 place name misheard by speech recognition", p_misheard_place)
persona("P18 vague first-timer", p_vague)
persona("P19 'stop' mid-place then continue", p_stop_continue)
persona("P20 one-word 'next' (the Next button)", cut_persona((0, 1), "Next."))
persona("P21 'tell me more about this one' (the More button)", cut_persona((0, 1), "Tell me more about this one."))

json.dump(report, open(OUT, "w"), indent=1, ensure_ascii=False)
print("wrote", OUT)
